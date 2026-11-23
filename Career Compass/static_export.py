import argparse
import html
import json
import os
import re
import shutil
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = PROJECT_ROOT / "static-site"
PAGE_FILES = {
    "/": "index.html",
    "/login": "login.html",
    "/register": "register.html",
    "/assessment": "assessment.html",
    "/results": "results.html",
    "/tests": "tests.html",
    "/career-feedback": "career-feedback.html",
    "/careers": "careers.html",
    "/roadmap": "roadmap.html",
    "/tasks": "tasks.html",
    "/progress": "progress.html",
    "/profile": "profile.html",
    "/insights": "insights.html",
    "/mentor": "mentor.html",
}


def static_page_for_path(path):
    if path in PAGE_FILES:
        return PAGE_FILES[path]
    if re.fullmatch(r"/tests/\d+/analysis", path):
        return "test-analysis.html"
    if re.fullmatch(r"/tests/\d+", path):
        return "test.html"
    return None


class StaticHTMLRewriter(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.output = []
        self.script_depth = 0

    def _render_attrs(self, attrs):
        rendered = []
        for name, value in attrs:
            if name == "name" and value == "csrf_token":
                return None
            if value is None:
                rendered.append(name)
                continue
            if name in {"href", "src"}:
                value = self._rewrite_url(value)
            elif name == "action":
                value = "#static-preview"
            rendered.append(f'{name}="{html.escape(value, quote=True)}"')
        return " " + " ".join(rendered) if rendered else ""

    @staticmethod
    def _rewrite_url(value):
        if value.startswith("/static/"):
            return value.lstrip("/")
        if not value.startswith("/") or value.startswith("//"):
            return value
        path = urlsplit(value).path
        return static_page_for_path(path) or "index.html"

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.script_depth += 1
            return
        if self.script_depth:
            return
        if tag == "input" and any(
            name == "name" and value == "csrf_token" for name, value in attrs
        ):
            return
        attrs = list(attrs)
        if tag == "form":
            attrs = [
                (name, value)
                for name, value in attrs
                if name not in {"method", "action", "data-static-form"}
            ]
            attrs.extend(
                [
                    ("method", "get"),
                    ("action", "#static-preview"),
                    ("data-static-form", "true"),
                ]
            )
        self.output.append(f"<{tag}{self._render_attrs(attrs)}>")
        if tag == "main":
            self.output.append(
                '<aside class="static-preview-banner" role="status">'
                "<strong>Static preview</strong> — this exported site is read-only. "
                "Accounts, saved progress, test submissions, mentor replies, and live "
                "career research require the Python backend."
                "</aside>"
            )

    def handle_startendtag(self, tag, attrs):
        if self.script_depth:
            if tag == "script":
                self.script_depth -= 1
            return
        self.output.append(f"<{tag}{self._render_attrs(attrs)}/>")

    def handle_endtag(self, tag):
        if tag == "script" and self.script_depth:
            self.script_depth -= 1
            return
        if self.script_depth:
            return
        if tag == "body":
            self.output.append('<script src="static/static-preview.js" defer></script>')
        self.output.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.script_depth:
            self.output.append(data)

    def handle_entityref(self, name):
        if not self.script_depth:
            self.output.append(f"&{name};")

    def handle_charref(self, name):
        if not self.script_depth:
            self.output.append(f"&#{name};")

    def handle_comment(self, data):
        if not self.script_depth:
            self.output.append(f"<!--{data}-->")

    def handle_decl(self, decl):
        if not self.script_depth:
            self.output.append(f"<!{decl}>")

    def rewrite(self, source):
        self.feed(source)
        self.close()
        return "".join(self.output)


def _csrf_token(client):
    with client.session_transaction() as state:
        return state["csrf_token"]


def _require_success(response, expected_status=200):
    if response.status_code != expected_status:
        raise RuntimeError(
            f"Static export setup request failed: HTTP {response.status_code} "
            f"for {response.request.path}."
        )
    return response


def _render_preview_pages():
    with tempfile.TemporaryDirectory(prefix="career-compass-static-") as workdir:
        database_path = Path(workdir) / "preview.db"
        os.environ["DATABASE_PATH"] = str(database_path)
        os.environ["SECRET_KEY"] = "static-export-preview-secret-not-for-deployment"

        from app import app

        import app as app_module

        app.config.update(TESTING=True, SECRET_KEY=os.environ["SECRET_KEY"])
        rendered = {}
        with app.test_client() as client:
            _require_success(client.get("/register"))
            response = client.post(
                "/register",
                data={
                    "csrf_token": _csrf_token(client),
                    "name": "Career Compass Preview",
                    "email": "preview@example.invalid",
                    "password": "static-preview-password",
                    "confirm_password": "static-preview-password",
                },
                follow_redirects=True,
            )
            _require_success(response)

            _require_success(client.get("/assessment"))
            answers = {"csrf_token": _csrf_token(client)}
            answers.update(
                {question["id"]: "4" for question in app_module.QUESTIONS}
            )
            _require_success(
                client.post("/assessment", data=answers, follow_redirects=True)
            )

            _require_success(client.get("/careers"))
            _require_success(client.get("/career-feedback"))
            _require_success(client.get("/roadmap"))
            _require_success(client.get("/tasks"))
            _require_success(client.get("/progress"))
            _require_success(client.get("/profile"))
            _require_success(client.get("/insights"))
            _require_success(client.get("/mentor"))
            _require_success(client.get("/"))
            _require_success(client.get("/tests"))

            response = client.post(
                "/tests/start",
                data={"csrf_token": _csrf_token(client)},
                follow_redirects=False,
            )
            if response.status_code != 302:
                raise RuntimeError(
                    f"Could not create static test preview: HTTP {response.status_code}."
                )
            take_path = urlsplit(response.headers["Location"]).path
            take_response = _require_success(client.get(take_path))
            rendered["test.html"] = take_response.get_data(as_text=True)
            test_id = int(re.search(r"/tests/(\d+)$", take_path).group(1))
            with app.app_context():
                attempt = app_module.get_db().execute(
                    "SELECT questions_json FROM learning_tests WHERE id = ?",
                    (test_id,),
                ).fetchone()
            questions = json.loads(attempt["questions_json"])
            test_answers = {"csrf_token": _csrf_token(client)}
            test_answers.update(
                {
                    f"question_{index}": str(question["answer"])
                    for index, question in enumerate(questions)
                }
            )
            _require_success(
                client.post(
                    f"/tests/{test_id}/submit",
                    data=test_answers,
                    follow_redirects=True,
                )
            )
            _require_success(client.get("/tests"))

            page_routes = {
                "/": "index.html",
                "/login": "login.html",
                "/register": "register.html",
                "/assessment": "assessment.html",
                "/results": "results.html",
                "/tests": "tests.html",
                f"/tests/{test_id}/analysis": "test-analysis.html",
                "/career-feedback": "career-feedback.html",
                "/careers": "careers.html",
                "/roadmap": "roadmap.html",
                "/tasks": "tasks.html",
                "/progress": "progress.html",
                "/profile": "profile.html",
                "/insights": "insights.html",
                "/mentor": "mentor.html",
            }
            for route, filename in page_routes.items():
                if filename in {"login.html", "register.html"}:
                    continue
                response = client.get(route)
                _require_success(response)
                rendered[filename] = response.get_data(as_text=True)

            response = client.post(
                "/logout",
                data={"csrf_token": _csrf_token(client)},
                follow_redirects=True,
            )
            _require_success(response)
            rendered["login.html"] = client.get("/login").get_data(as_text=True)
            rendered["register.html"] = client.get("/register").get_data(
                as_text=True
            )
        return rendered


def build_static_site(output_dir=DEFAULT_OUTPUT):
    output_dir = Path(output_dir).resolve()
    if output_dir == PROJECT_ROOT or PROJECT_ROOT in output_dir.parents:
        if output_dir == PROJECT_ROOT:
            raise ValueError("Choose an output directory below the project root.")
    if output_dir == PROJECT_ROOT / "static":
        raise ValueError("The export cannot overwrite the application's static assets.")

    output_dir.mkdir(parents=True, exist_ok=True)
    pages = _render_preview_pages()
    for filename, source in pages.items():
        rewriter = StaticHTMLRewriter()
        (output_dir / filename).write_text(
            rewriter.rewrite(source), encoding="utf-8"
        )

    assets = output_dir / "static"
    assets.mkdir(exist_ok=True)
    shutil.copy2(PROJECT_ROOT / "static" / "style.css", assets / "style.css")
    shutil.copy2(PROJECT_ROOT / "static" / "favicon.svg", assets / "favicon.svg")
    (assets / "static-preview.js").write_text(
        """document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("form[data-static-form]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const notice = document.createElement("p");
      notice.className = "static-form-notice";
      notice.setAttribute("role", "status");
      notice.textContent =
        "This is a static preview. This action needs the Python backend.";
      form.append(notice);
    });
  });
});
""",
        encoding="utf-8",
    )
    (output_dir / "README.txt").write_text(
        "Career Compass static preview\n"
        "=============================\n\n"
        "Open index.html or serve this folder with any static web server.\n"
        "This export is a read-only snapshot made with demonstration data. "
        "Account sign-in, progress saving, tests, mentor responses, and live "
        "career research require the Python/Flask application.\n\n"
        "Regenerate from the project root with:\n"
        "  python static_export.py\n",
        encoding="utf-8",
    )
    return sorted(path.name for path in output_dir.glob("*.html"))


def main():
    parser = argparse.ArgumentParser(
        description="Export Career Compass pages as a static HTML preview."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output directory (default: static-site)",
    )
    args = parser.parse_args()
    pages = build_static_site(args.output)
    print(f"Exported {len(pages)} HTML pages to {args.output.resolve()}")
    for page in pages:
        print(f"  {page}")


if __name__ == "__main__":
    main()
