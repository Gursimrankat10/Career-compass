import json
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from careers import (
    CAREERS,
    DIMENSION_LABELS,
    QUESTIONS,
    daily_tasks_for_career,
    tasks_for_career,
    video_recommendations,
)
from career_market import (
    COUNTRIES,
    PALETTES,
    RESEARCH_SOURCES,
    MetaAPIError,
    current_model_api_key,
    meta_mentor_reply,
    read_cached_insight,
    refresh_insights,
    refresh_stale_insights,
)
from learning_engine import build_learning_test, grade_learning_test
from mentor_engine import (
    classify_intent,
    mentor_reply,
    task_mentor_reply,
    test_review_reply,
)


BASE_DIR = Path(__file__).resolve().parent
DATABASE = Path(os.environ.get("DATABASE_PATH", str(BASE_DIR / "career_compass.db")))
SECRET_KEY_FILE = BASE_DIR / ".career_compass_secret"
LEGACY_TABLES = ("progress", "assessments", "task_completions", "mentor_messages")
CLOUDFLARE_WORKER = os.environ.get("CLOUDFLARE_WORKERS") == "1"


def load_secret_key(path=SECRET_KEY_FILE):
    configured_secret = os.environ.get("SECRET_KEY")
    if configured_secret:
        return configured_secret
    if os.environ.get("CLOUDFLARE_WORKERS") == "1":
        return "cloudflare-secret-is-set-per-request"
    try:
        secret = path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        secret = secrets.token_hex(32)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            secret = path.read_text(encoding="ascii").strip()
        else:
            with os.fdopen(descriptor, "w", encoding="ascii") as secret_file:
                secret_file.write(secret)
                secret_file.write("\n")
    if len(secret) < 64:
        raise RuntimeError(f"The Flask session secret in {path} is invalid.")
    return secret


app = Flask(__name__)
app.config.update(
    SECRET_KEY=load_secret_key(),
    MAX_CONTENT_LENGTH=16 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(
        CLOUDFLARE_WORKER or os.environ.get("COOKIE_SECURE") == "1"
    ),
    PERMANENT_SESSION_LIFETIME=timedelta(days=365),
)


def get_db():
    if "db" not in g:
        if CLOUDFLARE_WORKER:
            from cloudflare_d1 import D1Database

            environment = request.environ.get("workers.env")
            if environment is None:
                raise RuntimeError("The Cloudflare Worker environment is unavailable.")
            g.db = D1Database(environment.DB)
        else:
            g.db = sqlite3.connect(DATABASE)
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    database = g.pop("db", None)
    if database is not None and not CLOUDFLARE_WORKER:
        database.close()


def table_exists(database, table_name):
    return database.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone() is not None


def init_db():
    database = get_db()
    for table in LEGACY_TABLES:
        if not table_exists(database, table):
            continue
        columns = {
            row["name"] for row in database.execute(f"PRAGMA table_info({table})")
        }
        legacy_name = f"legacy_{table}"
        if table == "progress" or "user_id" not in columns:
            if table_exists(database, legacy_name):
                raise RuntimeError(f"Both {table} and {legacy_name} exist; resolve the database migration manually.")
            database.execute(f"ALTER TABLE {table} RENAME TO {legacy_name}")

    database.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            theme TEXT NOT NULL DEFAULT 'dark' CHECK (theme IN ('dark', 'light')),
            accent_color TEXT NOT NULL DEFAULT 'green',
            market_country TEXT NOT NULL DEFAULT 'IN',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_progress (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            xp INTEGER NOT NULL DEFAULT 0,
            streak INTEGER NOT NULL DEFAULT 0,
            last_active TEXT,
            selected_career TEXT
        );
        CREATE TABLE IF NOT EXISTS assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            scores TEXT NOT NULL,
            answered_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS assessments_user_created
            ON assessments(user_id, created_at);
        CREATE TABLE IF NOT EXISTS task_completions (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            task_id TEXT NOT NULL,
            completed_on TEXT NOT NULL,
            PRIMARY KEY (user_id, task_id, completed_on)
        );
        CREATE TABLE IF NOT EXISTS daily_task_plans (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            plan_date TEXT NOT NULL,
            task_ids TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id, plan_date)
        );
        CREATE TABLE IF NOT EXISTS mentor_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK (role IN ('user', 'mentor')),
            message TEXT NOT NULL,
            sources TEXT NOT NULL DEFAULT '[]',
            intent TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS mentor_messages_user_id ON mentor_messages(user_id, id);
        CREATE TABLE IF NOT EXISTS learning_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            career_id TEXT,
            level INTEGER NOT NULL,
            questions_json TEXT NOT NULL,
            answers_json TEXT NOT NULL DEFAULT '{}',
            score INTEGER,
            correct_count INTEGER,
            total_count INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            submitted_at TEXT,
            timed_out INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS learning_tests_user_submitted
            ON learning_tests(user_id, submitted_at);
        CREATE TABLE IF NOT EXISTS career_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            career_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            performance_json TEXT NOT NULL,
            recommendations_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS career_insights (
            career_id TEXT NOT NULL,
            country_code TEXT NOT NULL,
            report TEXT NOT NULL,
            sources_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (career_id, country_code)
        );
        """
    )
    user_columns = {
        row["name"] for row in database.execute("PRAGMA table_info(users)")
    }
    if "accent_color" not in user_columns:
        database.execute(
            "ALTER TABLE users ADD COLUMN accent_color TEXT NOT NULL DEFAULT 'green'"
        )
    if "market_country" not in user_columns:
        database.execute(
            "ALTER TABLE users ADD COLUMN market_country TEXT NOT NULL DEFAULT 'IN'"
        )
    if "meta_ai_enabled" in user_columns:
        database.execute("ALTER TABLE users DROP COLUMN meta_ai_enabled")
    assessment_columns = {
        row["name"] for row in database.execute("PRAGMA table_info(assessments)")
    }
    if "answered_count" not in assessment_columns:
        database.execute(
            "ALTER TABLE assessments ADD COLUMN answered_count INTEGER NOT NULL DEFAULT 0"
        )
    learning_test_columns = {
        row["name"] for row in database.execute("PRAGMA table_info(learning_tests)")
    }
    if "timed_out" not in learning_test_columns:
        database.execute(
            "ALTER TABLE learning_tests ADD COLUMN timed_out INTEGER NOT NULL DEFAULT 0"
        )
    database.execute(
        "INSERT OR IGNORE INTO user_progress (user_id) SELECT id FROM users"
    )
    database.commit()


def migrate_legacy_data(database, user_id):
    if table_exists(database, "legacy_progress"):
        columns = {
            row["name"] for row in database.execute("PRAGMA table_info(legacy_progress)")
        }
        rows = (
            database.execute("SELECT * FROM legacy_progress").fetchall()
            if "user_id" in columns
            else [database.execute("SELECT * FROM legacy_progress LIMIT 1").fetchone()]
        )
        for row in rows:
            if row:
                target_user_id = row["user_id"] if "user_id" in columns else user_id
                database.execute(
                    """UPDATE user_progress SET xp = ?, streak = ?, last_active = ?,
                       selected_career = ? WHERE user_id = ?""",
                    (
                        row["xp"],
                        row["streak"],
                        row["last_active"],
                        row["selected_career"],
                        target_user_id,
                    ),
                )
    if table_exists(database, "legacy_assessments"):
        for row in database.execute("SELECT scores, created_at FROM legacy_assessments"):
            database.execute(
                "INSERT INTO assessments (user_id, scores, created_at) VALUES (?, ?, ?)",
                (user_id, row["scores"], row["created_at"]),
            )
    if table_exists(database, "legacy_task_completions"):
        for row in database.execute("SELECT task_id, completed_on FROM legacy_task_completions"):
            database.execute(
                "INSERT OR IGNORE INTO task_completions (user_id, task_id, completed_on) VALUES (?, ?, ?)",
                (user_id, row["task_id"], row["completed_on"]),
            )
    if table_exists(database, "legacy_mentor_messages"):
        for row in database.execute(
            "SELECT role, message, created_at FROM legacy_mentor_messages ORDER BY id"
        ):
            database.execute(
                """INSERT INTO mentor_messages
                   (user_id, role, message, sources, created_at)
                   VALUES (?, ?, ?, '[]', ?)""",
                (user_id, row["role"], row["message"], row["created_at"]),
            )
    for table in LEGACY_TABLES:
        legacy_name = f"legacy_{table}"
        if table_exists(database, legacy_name):
            database.execute(f"DROP TABLE {legacy_name}")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Sign in to save and view your career progress.", "info")
            return redirect(url_for("login"))
        user = get_db().execute(
            "SELECT id FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()
        if user is None:
            session.clear()
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def current_progress():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute(
        "SELECT * FROM user_progress WHERE user_id = ?", (user_id,)
    ).fetchone()


def selected_career_id(progress):
    if progress is None:
        return None
    try:
        return progress["selected_career"]
    except (TypeError, KeyError):
        return None


def daily_task_plan(user_id, career, plan_date=None):
    database = get_db()
    plan_date = plan_date or date.today()
    day_key = plan_date.isoformat()
    saved_plan = database.execute(
        "SELECT task_ids FROM daily_task_plans WHERE user_id = ? AND plan_date = ?",
        (user_id, day_key),
    ).fetchone()
    if saved_plan:
        task_ids = json.loads(saved_plan["task_ids"])
        available = {task["id"]: task for task in tasks_for_career(career)}
        if all(task_id in available for task_id in task_ids):
            return [available[task_id] for task_id in task_ids]

    assessment = latest_assessment(user_id)
    recent_task_ids = [
        row["task_id"]
        for row in database.execute(
            """SELECT task_id FROM task_completions
               WHERE user_id = ? AND completed_on >= ? AND completed_on < ?
               ORDER BY completed_on DESC""",
            (user_id, (plan_date - timedelta(days=7)).isoformat(), day_key),
        ).fetchall()
    ]
    selected_tasks = daily_tasks_for_career(
        career,
        user_id,
        plan_date,
        assessment["scores"] if assessment else None,
        recent_task_ids,
    )
    database.execute(
        """INSERT OR REPLACE INTO daily_task_plans
           (user_id, plan_date, task_ids, created_at) VALUES (?, ?, ?, ?)""",
        (
            user_id,
            day_key,
            json.dumps([task["id"] for task in selected_tasks]),
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    database.commit()
    return selected_tasks


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


@app.context_processor
def inject_template_helpers():
    browser_theme = request.cookies.get("career_compass_theme", "")
    browser_accent = request.cookies.get("career_compass_accent", "")
    return {
        "csrf_token": csrf_token,
        "today": date.today().isoformat(),
        "motivation_quote": [
            "Small steps still move you forward.",
            "Curiosity is a good place to begin.",
            "Practice makes progress visible.",
            "You can learn one thing at a time.",
            "A first draft is a real start.",
            "Rest, reflect, then try again.",
            "Your path can change as you learn.",
        ][date.today().toordinal() % 7],
        "current_progress": current_progress,
        "current_user": current_user,
        "accent_palettes": PALETTES,
        "browser_theme": browser_theme if browser_theme in {"dark", "light"} else "dark",
        "browser_accent_color": browser_accent if browser_accent in PALETTES else "green",
    }


def remember_ui_preferences(response, theme, accent_color):
    if theme not in {"dark", "light"}:
        theme = "dark"
    if accent_color not in PALETTES:
        accent_color = "green"
    cookie_options = {
        "max_age": 60 * 60 * 24 * 365,
        "httponly": True,
        "secure": app.config["SESSION_COOKIE_SECURE"],
        "samesite": "Lax",
    }
    response.set_cookie("career_compass_theme", theme, **cookie_options)
    response.set_cookie("career_compass_accent", accent_color, **cookie_options)
    return response


def verify_csrf():
    if not secrets.compare_digest(
        str(request.form.get("csrf_token", "")), str(session.get("csrf_token", ""))
    ):
        abort(400, description="Your form session expired. Refresh the page and try again.")


def career_by_id(career_id):
    if isinstance(career_id, dict):
        career_id = career_id.get("id")
    if not career_id:
        return None
    return next((career for career in CAREERS if career["id"] == career_id), None)


def latest_assessment(user_id):
    row = get_db().execute(
        """SELECT scores, answered_count, created_at FROM assessments
           WHERE user_id = ? ORDER BY id DESC LIMIT 1""",
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "scores": json.loads(row["scores"]),
        "answered_count": row["answered_count"],
        "created_at": row["created_at"],
    }


def ranked_careers(scores, test_profile=None, reference_career=None):
    ranked = []
    for career in CAREERS:
        dimensions = career["dimensions"]
        total_weight = sum(dimensions.values())
        questionnaire_score = sum(
            ((scores.get(key, 3) - 1) / 4) * weight
            for key, weight in dimensions.items()
        ) / max(total_weight, 0.001)
        components = [(questionnaire_score, 0.7)]
        if test_profile:
            test_total_weight = sum(
                weight for key, weight in dimensions.items() if key in test_profile
            )
            if test_total_weight:
                test_score = sum(
                    (test_profile[key] / 100) * weight
                    for key, weight in dimensions.items()
                    if key in test_profile
                ) / test_total_weight
                components.append((test_score, 0.3))
        if reference_career and reference_career["id"] != career["id"]:
            previous_dimensions = reference_career["dimensions"]
            shared = set(dimensions) | set(previous_dimensions)
            dot_product = sum(
                dimensions.get(key, 0) * previous_dimensions.get(key, 0)
                for key in shared
            )
            norm = (
                sum(value**2 for value in dimensions.values())
                * sum(value**2 for value in previous_dimensions.values())
            ) ** 0.5
            similarity = dot_product / norm if norm else 0
            components.append((similarity, 0.2))
        score = sum(value * weight for value, weight in components) / sum(
            weight for _, weight in components
        )
        reasons = sorted(
            (key for key in dimensions if key in scores),
            key=lambda key: ((scores.get(key, 3) - 1) / 4) * dimensions[key],
            reverse=True,
        )
        ranked_careers = {
            **career,
            "fit_score": score,
            "compatibility": round(score * 100),
            "fit_reasons": [
                DIMENSION_LABELS[key] for key in reasons[:3] if key in DIMENSION_LABELS
            ],
        }
        ranked.append((score, ranked_careers))
    return [career for _, career in sorted(ranked, key=lambda item: item[0], reverse=True)]


def test_performance(user_id):
    rows = get_db().execute(
        """SELECT questions_json, answers_json, score FROM learning_tests
           WHERE user_id = ? AND submitted_at IS NOT NULL ORDER BY id""",
        (user_id,),
    ).fetchall()
    totals = {}
    correct_by_dimension = {}
    for row in rows:
        questions = json.loads(row["questions_json"])
        answers = json.loads(row["answers_json"])
        for index, question in enumerate(questions):
            dimension = question["dimension"]
            totals[dimension] = totals.get(dimension, 0) + 1
            if answers.get(str(index)) == question["answer"]:
                correct_by_dimension[dimension] = (
                    correct_by_dimension.get(dimension, 0) + 1
                )
    dimensions = {
        dimension: round(correct_by_dimension.get(dimension, 0) / count * 100)
        for dimension, count in totals.items()
    }
    scores = [row["score"] for row in rows if row["score"] is not None]
    return {
        "dimensions": dimensions,
        "attempts": len(scores),
        "average": round(sum(scores) / len(scores)) if scores else None,
    }


def learning_skill_summary(user_id, scores=None):
    scores = scores or {}
    tested = test_performance(user_id)["dimensions"]
    dimensions = set(scores) | set(tested)
    if not dimensions:
        return {"strengths": [], "practice_areas": [], "basis": None}
    ranked = []
    for dimension in dimensions:
        evidence = []
        if dimension in scores:
            evidence.append(((scores[dimension] - 1) / 4 * 100, 0.35 if dimension in tested else 1))
        if dimension in tested:
            evidence.append((tested[dimension], 0.65 if dimension in scores else 1))
        value = sum(score * weight for score, weight in evidence) / sum(
            weight for _, weight in evidence
        )
        ranked.append(
            {
                "dimension": dimension,
                "label": DIMENSION_LABELS.get(dimension, dimension.replace("_", " ")),
                "score": round(value),
                "tested": dimension in tested,
                "interest": dimension in scores,
            }
        )
    ranked.sort(key=lambda item: (item["score"], item["label"]))
    midpoint = (len(ranked) + 1) // 2
    return {
        "strengths": list(reversed(ranked[midpoint:]))[:3],
        "practice_areas": ranked[:midpoint][:3],
        "basis": "questionnaire interests and test answers" if tested and scores else (
            "test answers" if tested else "questionnaire interests"
        ),
    }


def task_reward(task_id):
    return next(
        (task["xp"] for task in tasks_for_career(None) if task["id"] == task_id),
        0,
    )


def _session_for_user(user_id):
    session.clear()
    session["user_id"] = user_id
    session["csrf_token"] = secrets.token_urlsafe(32)
    session.permanent = True


def _valid_email(value):
    return bool(
        len(value) <= 254
        and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value)
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("home"))
    if request.method == "POST":
        verify_csrf()
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirmation = request.form.get("confirm_password", "")
        if len(name) < 2 or len(name) > 60:
            flash("Your name must be between 2 and 60 characters.", "error")
        elif not _valid_email(email):
            flash("Enter a valid email address.", "error")
        elif len(password) < 10 or len(password) > 128:
            flash("Choose a password between 10 and 128 characters.", "error")
        elif password != confirmation:
            flash("The passwords do not match.", "error")
        else:
            database = get_db()
            try:
                password_hash = generate_password_hash(password)
                created_at = datetime.now().isoformat(timespec="seconds")
                if CLOUDFLARE_WORKER:
                    user_id = database.create_user(
                        email, name, password_hash, created_at
                    )
                else:
                    database.execute("BEGIN IMMEDIATE")
                    existing_user_count = database.execute(
                        "SELECT COUNT(*) AS count FROM users"
                    ).fetchone()["count"]
                    cursor = database.execute(
                        """INSERT INTO users
                           (email, display_name, password_hash, theme, created_at)
                           VALUES (?, ?, ?, 'dark', ?)""",
                        (email, name, password_hash, created_at),
                    )
                    user_id = cursor.lastrowid
                    database.execute(
                        "INSERT INTO user_progress (user_id) VALUES (?)", (user_id,)
                    )
                    if existing_user_count == 0:
                        migrate_legacy_data(database, user_id)
                    database.commit()
            except sqlite3.IntegrityError:
                database.rollback()
                flash("An account with that email already exists. Try signing in instead.", "error")
            else:
                _session_for_user(user_id)
                flash(f"Welcome, {name}. Your private career journey is ready.", "success")
                return remember_ui_preferences(
                    redirect(url_for("home")), "dark", "green"
                )
    return render_template("auth.html", mode="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("home"))
    if request.method == "POST":
        verify_csrf()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute(
            "SELECT id, password_hash, theme, accent_color FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        if (
            user is None
            or len(password) > 128
            or not check_password_hash(user["password_hash"], password)
        ):
            flash("Email or password is incorrect.", "error")
        else:
            _session_for_user(user["id"])
            return remember_ui_preferences(
                redirect(url_for("home")), user["theme"], user["accent_color"]
            )
    return render_template("auth.html", mode="login")


@app.post("/logout")
@login_required
def logout():
    verify_csrf()
    session.clear()
    flash("You are signed out. Your progress is saved to your account.", "info")
    return redirect(url_for("login"))


@app.get("/")
@login_required
def home():
    user_id = session["user_id"]
    progress = current_progress() or {}
    career = career_by_id(selected_career_id(progress))
    tasks = daily_task_plan(user_id, career)
    completions = get_db().execute(
        "SELECT COUNT(*) AS count FROM task_completions WHERE user_id = ? AND completed_on = ?",
        (user_id, date.today().isoformat()),
    ).fetchone()["count"]
    completed = {
        row["task_id"]
        for row in get_db()
        .execute(
            "SELECT task_id FROM task_completions WHERE user_id = ? AND completed_on = ?",
            (user_id, date.today().isoformat()),
        )
        .fetchall()
    }
    return render_template(
        "home.html",
        progress=progress,
        career=career,
        completions=completions,
        assessment=latest_assessment(user_id),
        tasks=tasks,
        completed=completed,
        videos=video_recommendations(career),
    )


@app.route("/assessment", methods=["GET", "POST"])
@login_required
def assessment():
    if request.method == "POST":
        verify_csrf()
        totals = {}
        counts = {}
        for question in QUESTIONS:
            value = request.form.get(question["id"], type=int)
            if value is not None and value not in range(1, 6):
                abort(400, description="Choose a response from the available scale.")
            if value is None:
                continue
            dimension = question["dimension"]
            totals[dimension] = totals.get(dimension, 0) + value
            counts[dimension] = counts.get(dimension, 0) + 1
        answered_count = sum(counts.values())
        if answered_count < 10:
            flash("Answer at least 10 questions to receive a useful rough estimate.", "error")
            return render_template(
                "assessment.html",
                questions=QUESTIONS,
                minimum_answers=10,
                answered_count=answered_count,
            ), 400
        scores = {
            dimension: round(total / counts[dimension], 3)
            for dimension, total in totals.items()
        }
        matches = ranked_careers(scores)
        user_id = session["user_id"]
        database = get_db()
        database.execute(
            """INSERT INTO assessments (user_id, scores, answered_count, created_at)
               VALUES (?, ?, ?, ?)""",
            (
                user_id,
                json.dumps(scores),
                answered_count,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        database.execute(
            "UPDATE user_progress SET selected_career = ? WHERE user_id = ?",
            (matches[0]["id"], user_id),
        )
        database.commit()
        return redirect(url_for("results"))
    return render_template(
        "assessment.html",
        questions=QUESTIONS,
        minimum_answers=10,
        answered_count=0,
    )


@app.get("/results")
@login_required
def results():
    user_id = session["user_id"]
    assessment_result = latest_assessment(user_id)
    if assessment_result is None:
        flash("Complete the assessment to see your career matches.", "info")
        return redirect(url_for("assessment"))
    return render_template(
        "results.html",
        matches=ranked_careers(assessment_result["scores"])[:6],
        assessment=assessment_result,
    )


def _finish_learning_test(attempt, submitted_answers, timed_out=False):
    questions = json.loads(attempt["questions_json"])
    result = grade_learning_test(questions, submitted_answers)
    get_db().execute(
        """UPDATE learning_tests SET answers_json = ?, score = ?, correct_count = ?,
           submitted_at = ?, timed_out = ?
           WHERE id = ? AND user_id = ? AND submitted_at IS NULL""",
        (
            json.dumps(result["answers"]),
            result["score"],
            result["correct"],
            datetime.now().isoformat(timespec="seconds"),
            int(timed_out),
            attempt["id"],
            session["user_id"],
        ),
    )
    get_db().commit()
    return result


def _expire_learning_tests(user_id):
    now = datetime.now()
    attempts = get_db().execute(
        """SELECT * FROM learning_tests
           WHERE user_id = ? AND submitted_at IS NULL""",
        (user_id,),
    ).fetchall()
    for attempt in attempts:
        started = datetime.fromisoformat(attempt["started_at"])
        if now - started >= timedelta(minutes=20):
            _finish_learning_test(attempt, {}, timed_out=True)


@app.get("/tests")
@login_required
def learning_tests():
    user_id = session["user_id"]
    _expire_learning_tests(user_id)
    progress = current_progress() or {}
    career = career_by_id(selected_career_id(progress))
    attempts = get_db().execute(
        """SELECT id, career_id, level, score, correct_count, total_count,
           started_at, submitted_at FROM learning_tests
           WHERE user_id = ? ORDER BY id DESC""",
        (user_id,),
    ).fetchall()
    performance = test_performance(user_id)
    last_score = attempts[0]["score"] if attempts else None
    completed_tasks = get_db().execute(
        "SELECT COUNT(DISTINCT task_id) AS count FROM task_completions WHERE user_id = ?",
        (user_id,),
    ).fetchone()["count"]
    test_level = 3 if completed_tasks >= 8 or (
        performance["average"] is not None and performance["average"] >= 80
    ) else (
        2 if completed_tasks >= 3 or (
            performance["average"] is not None and performance["average"] >= 60
        ) else 1
    )
    return render_template(
        "tests.html",
        career=career,
        attempts=attempts,
        average=performance["average"],
        last_score=last_score,
        test_level=test_level,
    )


@app.post("/tests/start")
@login_required
def start_learning_test():
    verify_csrf()
    user_id = session["user_id"]
    progress = current_progress() or {}
    career = career_by_id(selected_career_id(progress))
    if career is None:
        flash("Choose a career direction before starting a tailored learning test.", "info")
        return redirect(url_for("assessment"))
    completed_tasks = get_db().execute(
        "SELECT COUNT(DISTINCT task_id) AS count FROM task_completions WHERE user_id = ?",
        (user_id,),
    ).fetchone()["count"]
    performance = test_performance(user_id)
    previous_average = performance["average"] or 0
    database = get_db()
    started_at = datetime.now().isoformat(timespec="seconds")
    cursor = database.execute(
        """INSERT INTO learning_tests
           (user_id, career_id, level, questions_json, total_count, started_at)
           VALUES (?, ?, 1, '[]', 10, ?)""",
        (user_id, career["id"], started_at),
    )
    attempt_id = cursor.lastrowid
    learning_test = build_learning_test(
        career,
        completed_tasks,
        previous_average,
        attempt_id,
        skill_profile=performance["dimensions"],
        completed_task_ids=[
            row["task_id"]
            for row in database.execute(
                """SELECT DISTINCT task_id FROM task_completions
                   WHERE user_id = ?""",
                (user_id,),
            ).fetchall()
        ],
    )
    database.execute(
        "UPDATE learning_tests SET level = ?, questions_json = ? WHERE id = ?",
        (learning_test["level"], json.dumps(learning_test["questions"]), attempt_id),
    )
    database.commit()
    return redirect(url_for("take_learning_test", test_id=attempt_id))


@app.get("/tests/<int:test_id>")
@login_required
def take_learning_test(test_id):
    attempt = get_db().execute(
        "SELECT * FROM learning_tests WHERE id = ? AND user_id = ?",
        (test_id, session["user_id"]),
    ).fetchone()
    if attempt is None:
        abort(404)
    if attempt["submitted_at"]:
        return redirect(url_for("learning_test_analysis", test_id=test_id))
    started = datetime.fromisoformat(attempt["started_at"])
    deadline = started + timedelta(minutes=20)
    if datetime.now() >= deadline:
        _finish_learning_test(attempt, {}, timed_out=True)
        flash("Time is up. You can review your answers and try again whenever you are ready.", "info")
        return redirect(url_for("learning_test_analysis", test_id=test_id))
    career = career_by_id(attempt["career_id"])
    questions = json.loads(attempt["questions_json"])
    public_questions = [
        {key: value for key, value in question.items() if key != "answer"}
        for question in questions
    ]
    return render_template(
        "test_take.html",
        attempt=attempt,
        career=career,
        questions=public_questions,
        deadline=int(deadline.timestamp() * 1000),
    )


@app.post("/tests/<int:test_id>/submit")
@login_required
def submit_learning_test(test_id):
    verify_csrf()
    attempt = get_db().execute(
        "SELECT * FROM learning_tests WHERE id = ? AND user_id = ?",
        (test_id, session["user_id"]),
    ).fetchone()
    if attempt is None:
        abort(404)
    if attempt["submitted_at"]:
        return redirect(url_for("learning_test_analysis", test_id=test_id))
    submitted_answers = {
        str(index): request.form.get(f"question_{index}", "")
        for index in range(attempt["total_count"])
    }
    timed_out = datetime.now() >= (
        datetime.fromisoformat(attempt["started_at"]) + timedelta(minutes=20)
    )
    browser_submitted_on_timeout = request.form.get("timed_out") == "1"
    if timed_out and not browser_submitted_on_timeout:
        _finish_learning_test(attempt, {}, timed_out=True)
        flash("The 20-minute limit passed before submission. Review your result and start a fresh test when ready.", "info")
        return redirect(url_for("learning_test_analysis", test_id=test_id))
    _finish_learning_test(attempt, submitted_answers, timed_out=timed_out)
    flash("Test saved. Your answer-by-answer feedback is ready.", "success")
    return redirect(url_for("learning_test_analysis", test_id=test_id))


@app.get("/tests/<int:test_id>/analysis")
@login_required
def learning_test_analysis(test_id):
    attempt = get_db().execute(
        "SELECT * FROM learning_tests WHERE id = ? AND user_id = ?",
        (test_id, session["user_id"]),
    ).fetchone()
    if attempt is None:
        abort(404)
    if not attempt["submitted_at"]:
        return redirect(url_for("take_learning_test", test_id=test_id))
    questions = json.loads(attempt["questions_json"])
    result = grade_learning_test(questions, json.loads(attempt["answers_json"]))
    career = career_by_id(attempt["career_id"])
    return render_template(
        "test_analysis.html",
        attempt=attempt,
        result=result,
        career=career,
        mentor_feedback=test_review_reply(result["mistakes"], career),
    )


@app.route("/career-feedback", methods=["GET", "POST"])
@login_required
def career_feedback():
    user_id = session["user_id"]
    progress = current_progress() or {}
    career = career_by_id(selected_career_id(progress))
    if career is None:
        flash("Choose a career direction before asking for alternatives.", "info")
        return redirect(url_for("assessment"))
    if request.method == "POST":
        verify_csrf()
        reason = request.form.get("reason", "").strip()
        if len(reason) < 10 or len(reason) > 1000:
            flash("Share at least 10 characters so the recommendations have useful context.", "error")
            return render_template("career_feedback.html", career=career), 400
        assessment_result = latest_assessment(user_id)
        performance = test_performance(user_id)
        matches = ranked_careers(
            assessment_result["scores"] if assessment_result else {},
            test_profile=performance["dimensions"],
            reference_career=career,
        )
        recommendations = [
            match for match in matches if match["id"] != career["id"]
        ][:4]
        cursor = get_db().execute(
            """INSERT INTO career_feedback
               (user_id, career_id, reason, performance_json, recommendations_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                career["id"],
                reason,
                json.dumps(performance),
                json.dumps([match["id"] for match in recommendations]),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        get_db().commit()
        return redirect(url_for("career_feedback", feedback_id=cursor.lastrowid))
    feedback_id = request.args.get("feedback_id", type=int)
    feedback = None
    recommendations = []
    if feedback_id:
        feedback = get_db().execute(
            "SELECT * FROM career_feedback WHERE id = ? AND user_id = ?",
            (feedback_id, user_id),
        ).fetchone()
        if feedback is None:
            abort(404)
        recommendations = [
            career_by_id(career_id)
            for career_id in json.loads(feedback["recommendations_json"])
        ]
    return render_template(
        "career_feedback.html",
        career=career,
        feedback=feedback,
        recommendations=recommendations,
    )


@app.get("/careers")
@login_required
def careers():
    query = request.args.get("q", "").strip()[:100]
    category = request.args.get("category", "").strip()[:80]
    categories = sorted({career["category"] for career in CAREERS})
    filtered = CAREERS
    if category in categories:
        filtered = [career for career in filtered if career["category"] == category]
    else:
        category = ""
    if query:
        terms = query.casefold().split()
        filtered = [
            career
            for career in filtered
            if all(
                term in " ".join(
                    (career["title"], career["category"], career["description"])
                ).casefold()
                for term in terms
            )
        ]
    return render_template(
        "careers.html", careers=filtered, query=query, categories=categories, category=category
    )


@app.post("/careers/<career_id>/select")
@login_required
def select_career(career_id):
    verify_csrf()
    career = career_by_id(career_id)
    if career is None:
        abort(404)
    get_db().execute(
        "UPDATE user_progress SET selected_career = ? WHERE user_id = ?",
        (career_id, session["user_id"]),
    )
    get_db().commit()
    flash(f"{career['title']} is now your career direction to explore.", "success")
    return redirect(url_for("roadmap"))


@app.get("/roadmap")
@login_required
def roadmap():
    progress = current_progress() or {}
    career = career_by_id(selected_career_id(progress))
    if career is None:
        flash("Take the assessment to build your personalized roadmap.", "info")
        return redirect(url_for("assessment"))
    user_id = session["user_id"]
    completed_task_ids = {
        row["task_id"]
        for row in get_db().execute(
            "SELECT DISTINCT task_id FROM task_completions WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    }
    task_progress = round(
        len(completed_task_ids) / max(1, len(tasks_for_career(None))) * 100
    )
    test_average = test_performance(user_id)["average"]
    overall_progress = round(
        task_progress * 0.6 + (test_average or 0) * 0.4
    )
    phases = career["roadmap"]
    roadmap_flow = [
        {
            "title": "Explore the role",
            "description": career["first_step"],
            "done": bool(completed_task_ids & {"career-snapshot", "workday-map"}),
        },
        {
            "title": "Build foundations",
            "description": phases[1]["items"][0],
            "done": len(completed_task_ids) >= 3,
        },
        {
            "title": "Practice a core skill",
            "description": phases[1]["items"][1],
            "done": len(completed_task_ids) >= 6,
        },
        {
            "title": "Make a small project",
            "description": career["project"],
            "done": "starter-project" in completed_task_ids,
        },
        {
            "title": "Review and choose a next step",
            "description": phases[2]["items"][2],
            "done": "portfolio-reflection" in completed_task_ids and test_average is not None,
        },
    ]
    return render_template(
        "roadmap.html",
        career=career,
        roadmap_flow=roadmap_flow,
        overall_progress=overall_progress,
    )


@app.get("/tasks")
@login_required
def tasks():
    user_id = session["user_id"]
    progress = current_progress() or {}
    career = career_by_id(selected_career_id(progress))
    task_list = daily_task_plan(user_id, career)
    completed = {
        row["task_id"]
        for row in get_db()
        .execute(
            "SELECT task_id FROM task_completions WHERE user_id = ? AND completed_on = ?",
            (user_id, date.today().isoformat()),
        )
        .fetchall()
    }
    return render_template(
        "tasks.html",
        tasks=task_list,
        completed=completed,
        progress=progress,
        career=career,
        plan_date=date.today().isoformat(),
        assessment=latest_assessment(user_id),
    )


@app.post("/tasks/<task_id>/complete")
@login_required
def complete_task(task_id):
    verify_csrf()
    progress = current_progress() or {}
    career = career_by_id(selected_career_id(progress))
    available_tasks = daily_task_plan(session["user_id"], career)
    if not any(task["id"] == task_id for task in available_tasks):
        abort(404)
    database = get_db()
    user_id = session["user_id"]
    today = date.today()
    today_key = today.isoformat()
    completion = database.execute(
        "SELECT 1 FROM task_completions WHERE user_id = ? AND task_id = ? AND completed_on = ?",
        (user_id, task_id, today_key),
    ).fetchone()
    if completion is None:
        task = next(item for item in available_tasks if item["id"] == task_id)
        reward = task["xp"]
        progress = current_progress()
        last_active = date.fromisoformat(progress["last_active"]) if progress["last_active"] else None
        if last_active == today:
            streak = progress["streak"]
        elif last_active == today - timedelta(days=1):
            streak = progress["streak"] + 1
        else:
            streak = 1
        database.execute(
            "INSERT INTO task_completions (user_id, task_id, completed_on) VALUES (?, ?, ?)",
            (user_id, task_id, today_key),
        )
        database.execute(
            "UPDATE user_progress SET xp = xp + ?, streak = ?, last_active = ? WHERE user_id = ?",
            (reward, streak, today_key, user_id),
        )
        database.commit()
        flash(f"Task complete! You earned {reward} XP.", "success")
    else:
        flash("You already completed this task today.", "info")
    return redirect(url_for("tasks"))


@app.get("/api/day")
@login_required
def api_day():
    return jsonify({"date": date.today().isoformat()})


@app.get("/progress")
@login_required
def progress_page():
    user_id = session["user_id"]
    today = date.today()
    first_day = today - timedelta(days=6)
    rows = get_db().execute(
        """SELECT completed_on, COUNT(*) AS task_count
           FROM task_completions
           WHERE user_id = ? AND completed_on BETWEEN ? AND ?
           GROUP BY completed_on""",
        (user_id, first_day.isoformat(), today.isoformat()),
    ).fetchall()
    count_by_day = {row["completed_on"]: row["task_count"] for row in rows}
    largest_day = max(count_by_day.values(), default=1)
    week = [
        {
            "date": (first_day + timedelta(days=offset)).isoformat(),
            "label": (first_day + timedelta(days=offset)).strftime("%a"),
            "tasks": count_by_day.get(
                (first_day + timedelta(days=offset)).isoformat(), 0
            ),
            "bar": round(
                count_by_day.get(
                    (first_day + timedelta(days=offset)).isoformat(), 0
                )
                / largest_day
                * 100
            ),
        }
        for offset in range(7)
    ]
    weekly_tasks = sum(day["tasks"] for day in week)
    active_days = sum(day["tasks"] > 0 for day in week)
    total_tasks = get_db().execute(
        "SELECT COUNT(*) AS count FROM task_completions WHERE user_id = ?",
        (user_id,),
    ).fetchone()["count"]
    completed_task_types = get_db().execute(
        "SELECT COUNT(DISTINCT task_id) AS count FROM task_completions WHERE user_id = ?",
        (user_id,),
    ).fetchone()["count"]
    progress = current_progress() or {}
    career = career_by_id(selected_career_id(progress))
    weekly_task_rows = get_db().execute(
        """SELECT task_id FROM task_completions WHERE user_id = ?
           AND completed_on BETWEEN ? AND ?""",
        (user_id, first_day.isoformat(), today.isoformat()),
    ).fetchall()
    performance = test_performance(user_id)
    assessment_result = latest_assessment(user_id)
    test_history = get_db().execute(
        """SELECT id, score, submitted_at FROM learning_tests
           WHERE user_id = ? AND submitted_at IS NOT NULL ORDER BY id DESC""",
        (user_id,),
    ).fetchall()
    task_progress = round(
        completed_task_types / max(1, len(tasks_for_career(None))) * 100
    )
    test_progress = performance["average"]
    overall_progress = round(
        task_progress * 0.6 + (test_progress or 0) * 0.4
    )
    return render_template(
        "progress.html",
        week=week,
        weekly_tasks=weekly_tasks,
        weekly_xp=sum(task_reward(row["task_id"]) for row in weekly_task_rows),
        active_days=active_days,
        weekly_goal=12,
        total_tasks=total_tasks,
        completed_task_types=completed_task_types,
        progress=progress,
        career=career,
        task_progress=task_progress,
        test_progress=test_progress,
        overall_progress=overall_progress,
        test_history=test_history,
        performance=performance,
        skill_summary=learning_skill_summary(
            user_id,
            assessment_result["scores"] if assessment_result else {},
        ),
    )


@app.get("/profile")
@login_required
def profile():
    user_id = session["user_id"]
    progress = current_progress() or {}
    career = career_by_id(selected_career_id(progress))
    assessment_history = get_db().execute(
        "SELECT created_at FROM assessments WHERE user_id = ? ORDER BY id DESC LIMIT 5",
        (user_id,),
    ).fetchall()
    return render_template(
        "profile.html",
        progress=progress,
        career=career,
        assessment_history=assessment_history,
        user=current_user(),
        palettes=PALETTES,
        countries=COUNTRIES,
    )


@app.post("/profile/preferences")
@login_required
def update_preferences():
    verify_csrf()
    theme = request.form.get("theme", "")
    accent_color = request.form.get("accent_color", "")
    market_country = request.form.get("market_country", "")
    name = request.form.get("name", "").strip()
    if theme not in {"dark", "light"}:
        abort(400, description="Choose one of the available color themes.")
    if accent_color not in PALETTES:
        abort(400, description="Choose one of the available accent colors.")
    if market_country not in COUNTRIES:
        abort(400, description="Choose one of the available career research regions.")
    if len(name) < 2 or len(name) > 60:
        flash("Your display name must be between 2 and 60 characters.", "error")
    else:
        get_db().execute(
            """UPDATE users SET display_name = ?, theme = ?, accent_color = ?,
               market_country = ? WHERE id = ?""",
            (
                name,
                theme,
                accent_color,
                market_country,
                session["user_id"],
            ),
        )
        get_db().commit()
        flash("Your profile preferences have been saved.", "success")
        return remember_ui_preferences(
            redirect(url_for("profile")), theme, accent_color
        )
    return redirect(url_for("profile"))


def _worker_environment():
    if not CLOUDFLARE_WORKER:
        return None
    environment = request.environ.get("workers.env")
    if environment is None:
        raise RuntimeError("The Cloudflare Worker environment is unavailable.")
    return environment


def _model_api_key():
    return current_model_api_key(_worker_environment())


@app.get("/insights")
@login_required
def career_insights():
    progress = current_progress() or {}
    career_id = request.args.get("career", "") or selected_career_id(progress)
    career = career_by_id(career_id)
    if career is None:
        flash("Choose a career direction to view its market research.", "info")
        return redirect(url_for("assessment"))
    user = current_user()
    country_code = user["market_country"] if user["market_country"] in COUNTRIES else "IN"
    insight = read_cached_insight(get_db(), career["id"], country_code)
    return render_template(
        "career_insights.html",
        career=career,
        country_code=country_code,
        country_name=COUNTRIES[country_code],
        countries=COUNTRIES,
        insight=insight,
        research_sources=RESEARCH_SOURCES,
        meta_api_available=bool(_model_api_key()),
    )


@app.post("/insights/refresh")
@login_required
def refresh_career_insights():
    verify_csrf()
    career_id = request.form.get("career", "")[:100]
    career = career_by_id(career_id)
    if career is None:
        abort(404)
    api_key = _model_api_key()
    if not api_key:
        flash(
            "Live career research is not configured. Ask the site administrator to set the Meta Model API key.",
            "error",
        )
        return redirect(url_for("career_insights", career=career_id))
    user = current_user()
    country_code = user["market_country"] if user["market_country"] in COUNTRIES else "IN"
    try:
        refresh_insights(
            get_db(), career, country_code, api_key, _worker_environment()
        )
    except MetaAPIError:
        flash(
            "Live research failed, so no new report was saved. Check the API configuration and try again.",
            "error",
        )
    else:
        flash("Career-market research updated with live web citations.", "success")
    return redirect(url_for("career_insights", career=career_id))


@app.route("/mentor", methods=["GET", "POST"])
@login_required
def mentor():
    database = get_db()
    user_id = session["user_id"]
    progress = current_progress() or {}
    has_career = bool(selected_career_id(progress))
    if request.method == "POST":
        verify_csrf()
        message = request.form.get("message", "").strip()
        requested_task_id = request.form.get("task_id", "")[:100]
        if not message or len(message) > 500:
            flash("Enter a message of up to 500 characters.", "error")
        else:
            career = career_by_id(selected_career_id(progress))
            task_context = None
            if requested_task_id:
                task_context = next(
                    (
                        task
                        for task in daily_task_plan(user_id, career)
                        if task["id"] == requested_task_id
                    ),
                    None,
                )
                if task_context is None:
                    abort(404)
            reply = (
                task_mentor_reply(task_context, career)
                if task_context
                else mentor_reply(message, career)
            )
            reply_sources = []
            browser_reply = request.form.get("browser_ai_reply", "").strip()
            if browser_reply:
                if len(browser_reply) > 4000:
                    abort(400, description="The browser mentor response is too long.")
                reply = browser_reply
                reply_sources = [
                    {"type": "browser_ai", "title": "On-device browser AI"}
                ]
            user = current_user()
            api_key = _model_api_key() if not browser_reply else None
            if not browser_reply and api_key:
                cached = (
                    read_cached_insight(
                        database,
                        career["id"],
                        user["market_country"],
                    )
                    if career
                    else None
                )
                try:
                    reply, reply_sources = meta_mentor_reply(
                        message,
                        career,
                        user["market_country"],
                        api_key,
                        cached["report"] if cached else None,
                        _worker_environment(),
                        task_context=task_context,
                    )
                except MetaAPIError:
                    flash(
                        "Meta AI is temporarily unavailable; this reply came from the built-in mentor instead.",
                        "error",
                    )
            intent = classify_intent(message)
            sources = json.dumps(
                reply_sources
                or ([{"type": "career_catalog", "id": career["id"]}] if career else [])
            )
            now = datetime.now().isoformat(timespec="seconds")
            database.executemany(
                """INSERT INTO mentor_messages
                   (user_id, role, message, sources, intent, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (user_id, "user", message, sources, intent, now),
                    (user_id, "mentor", reply, sources, intent, now),
                ],
            )
            database.commit()
        return redirect(url_for("mentor"))
    messages = database.execute(
        "SELECT role, message, sources, created_at FROM mentor_messages WHERE user_id = ? ORDER BY id DESC LIMIT 30",
        (user_id,),
    ).fetchall()
    messages = [
        {**dict(item), "sources": json.loads(item["sources"] or "[]")}
        for item in reversed(messages)
    ]
    career = career_by_id(selected_career_id(progress))
    task_context = None
    requested_task_id = request.args.get("task", "")[:100]
    if requested_task_id:
        task_context = next(
            (
                task
                for task in daily_task_plan(user_id, career)
                if task["id"] == requested_task_id
            ),
            None,
        )
    prefilled_message = request.args.get("message", "")[:500]
    if task_context and not prefilled_message:
        prefilled_message = (
            f"Can you explain how to complete '{task_context['title']}'? "
            f"Here is the finish line: {task_context['deliverable']}"
        )
    user = current_user()
    browser_mentor_context = {
        "career": career["title"] if career else None,
        "career_category": career["category"] if career else None,
        "market_region": COUNTRIES.get(user["market_country"], "Global"),
        "task": (
            {
                "title": task_context["title"],
                "deliverable": task_context["deliverable"],
                "steps": task_context.get("steps", []),
            }
            if task_context
            else None
        ),
        "history": [
            {
                "role": "user" if item["role"] == "user" else "assistant",
                "content": item["message"],
            }
            for item in messages[-8:]
        ],
    }
    return render_template(
        "mentor.html",
        messages=messages,
        has_career=has_career,
        user=user,
        meta_api_available=bool(_model_api_key()),
        browser_mentor_context=browser_mentor_context,
        career=career,
        task_context=task_context,
        prefilled_message=prefilled_message,
        task_id=task_context["id"] if task_context else None,
    )


if not CLOUDFLARE_WORKER:
    with app.app_context():
        init_db()


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5050")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
