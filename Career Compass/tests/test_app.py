import json
import os
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import app as app_module

TEST_DATABASE = Path(tempfile.gettempdir()) / f"career-compass-tests-{os.getpid()}.db"
os.environ["DATABASE_PATH"] = str(TEST_DATABASE)

from app import app, daily_task_plan, get_db, init_db, load_secret_key, test_performance
from careers import CAREERS, QUESTIONS, daily_tasks_for_career
from learning_engine import build_learning_test
from mentor_engine import classify_intent


app.config.update(TESTING=True, SECRET_KEY="career-compass-test-secret")
app_module.DATABASE = TEST_DATABASE


def remove_test_database():
    for suffix in ("", "-wal", "-shm"):
        Path(f"{TEST_DATABASE}{suffix}").unlink(missing_ok=True)


class CareerCompassTests(unittest.TestCase):
    def setUp(self):
        remove_test_database()
        with app.app_context():
            init_db()
        self.client = app.test_client()

    def tearDown(self):
        remove_test_database()

    def csrf_token(self):
        with self.client.session_transaction() as state:
            return state.get("csrf_token")

    def register(self, client, name, email):
        client.get("/register")
        with client.session_transaction() as state:
            token = state["csrf_token"]
        response = client.post(
            "/register",
            data={
                "csrf_token": token,
                "name": name,
                "email": email,
                "password": "Correct-Horse-42!",
                "confirm_password": "Correct-Horse-42!",
            },
        )
        self.assertEqual(response.status_code, 302)

    def test_guest_requires_an_account(self):
        self.assertEqual(self.client.get("/").status_code, 302)
        self.assertEqual(self.client.get("/login").status_code, 200)

    def test_new_account_dashboard_and_mentor_work_without_a_selected_career(self):
        self.register(self.client, "Avery Explorer", "avery@example.test")
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/tasks").status_code, 200)
        self.assertEqual(self.client.get("/profile").status_code, 200)
        self.assertEqual(self.client.get("/progress").status_code, 200)

        response = self.client.get("/mentor")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Career Compass", response.data)

        response = self.client.post(
            "/mentor",
            data={
                "csrf_token": self.csrf_token(),
                "message": "I feel overwhelmed about choosing a career",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(b"whole future today", self.client.get("/mentor").data)

    def test_existing_database_drops_the_removed_mentor_preference(self):
        with app.app_context():
            get_db().execute(
                "ALTER TABLE users ADD COLUMN meta_ai_enabled INTEGER NOT NULL DEFAULT 0"
            )
            get_db().commit()
            init_db()
            columns = {
                row["name"] for row in get_db().execute("PRAGMA table_info(users)")
            }
        self.assertNotIn("meta_ai_enabled", columns)

    def test_remembered_login_survives_browser_restart_and_logout_is_available(self):
        self.register(self.client, "Avery Explorer", "avery@example.test")
        self.assertEqual(self.client.get("/login").status_code, 302)
        cookie = self.client.get_cookie("session")
        self.assertIsNotNone(cookie)
        self.assertIsNotNone(cookie.expires)

        reopened_browser = app.test_client()
        reopened_browser.set_cookie("session", cookie.value)
        self.assertEqual(reopened_browser.get("/").status_code, 200)
        self.assertEqual(reopened_browser.get("/profile").status_code, 200)
        with reopened_browser.session_transaction() as state:
            csrf_token = state["csrf_token"]
        response = reopened_browser.post(
            "/logout", data={"csrf_token": csrf_token}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(reopened_browser.get("/").status_code, 302)
        self.assertEqual(reopened_browser.get("/login").status_code, 200)

    def test_session_secret_is_stable_across_application_restarts(self):
        secret_file = TEST_DATABASE.with_suffix(".secret")
        secret_file.unlink(missing_ok=True)
        try:
            with patch.dict(os.environ, {}, clear=True):
                first_secret = load_secret_key(secret_file)
                restarted_secret = load_secret_key(secret_file)
            self.assertEqual(first_secret, restarted_secret)
            self.assertEqual(len(first_secret), 64)
        finally:
            secret_file.unlink(missing_ok=True)

    def test_assessment_and_career_catalog(self):
        self.register(self.client, "Avery Explorer", "avery@example.test")
        self.assertEqual(len(QUESTIONS), 25)
        self.assertGreaterEqual(len(CAREERS), 35)

        data = {"csrf_token": self.csrf_token()}
        data.update({question["id"]: "5" for question in QUESTIONS[:10]})
        response = self.client.post("/assessment", data=data)
        self.assertEqual(response.status_code, 302)
        results = self.client.get("/results")
        self.assertEqual(results.status_code, 200)
        self.assertIn(b"STRONGEST STARTING MATCH", results.data)
        self.assertIn(b"Rough compatibility", results.data)
        self.assertIn(b"rough compatibility estimate", results.data)
        self.assertEqual(self.client.get("/roadmap").status_code, 200)
        self.assertIn(b"Environmental Scientist", self.client.get("/careers?q=environment").data)

    def test_assessment_requires_ten_but_accepts_any_ten_of_twenty_five(self):
        self.register(self.client, "Avery Explorer", "avery@example.test")
        insufficient = {"csrf_token": self.csrf_token()}
        insufficient.update({question["id"]: "4" for question in QUESTIONS[:9]})
        response = self.client.post("/assessment", data=insufficient)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Answer at least 10 questions", response.data)
        with app.app_context():
            saved_count = get_db().execute(
                "SELECT COUNT(*) AS count FROM assessments"
            ).fetchone()["count"]
        self.assertEqual(saved_count, 0)

        sufficient = {"csrf_token": self.csrf_token()}
        sufficient.update({question["id"]: "4" for question in QUESTIONS[5:15]})
        self.assertEqual(self.client.post("/assessment", data=sufficient).status_code, 302)
        with app.app_context():
            assessment = get_db().execute(
                "SELECT answered_count, scores FROM assessments"
            ).fetchone()
        self.assertEqual(assessment["answered_count"], 10)
        self.assertGreaterEqual(len(json.loads(assessment["scores"])), 5)

    def test_learning_test_saves_analysis_and_adapts_to_progress(self):
        self.register(self.client, "Avery Explorer", "avery@example.test")
        answers = {"csrf_token": self.csrf_token()}
        answers.update({question["id"]: "4" for question in QUESTIONS[:10]})
        self.client.post("/assessment", data=answers)

        response = self.client.post(
            "/tests/start", data={"csrf_token": self.csrf_token()}
        )
        test_id = int(response.location.rsplit("/", 1)[1])
        page = self.client.get(response.location)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.data.count(b'type="radio"'), 40)
        self.assertIn(b"20:00", page.data)

        submission = {"csrf_token": self.csrf_token()}
        with app.app_context():
            saved_questions = json.loads(
                get_db().execute(
                    "SELECT questions_json FROM learning_tests WHERE id = ?",
                    (test_id,),
                ).fetchone()["questions_json"]
            )
        submission.update(
            {
                f"question_{index}": str(question["answer"])
                for index, question in enumerate(saved_questions)
            }
        )
        submission["question_0"] = str((saved_questions[0]["answer"] + 1) % 4)
        response = self.client.post(
            f"/tests/{test_id}/submit", data=submission
        )
        self.assertEqual(response.status_code, 302)
        analysis = self.client.get(response.location)
        self.assertEqual(analysis.status_code, 200)
        self.assertIn(b"90%", analysis.data)
        self.assertIn(b"Suggested answer:", analysis.data)
        self.assertIn(b"mentor", analysis.data.lower())
        self.assertEqual(self.client.get("/tests").status_code, 200)
        self.assertEqual(self.client.get("/progress").status_code, 200)
        with app.app_context():
            user_id = get_db().execute(
                "SELECT id FROM users WHERE email = ?", ("avery@example.test",)
            ).fetchone()["id"]
            performance = test_performance(user_id)
        self.assertEqual(performance["average"], 90)
        next_test = build_learning_test(
            CAREERS[0], completed_task_count=0, previous_average=90, attempt_id=912
        )
        self.assertEqual(next_test["level"], 3)
        self.assertIn(3, {question["level"] for question in next_test["questions"]})
        self.assertTrue(
            any(
                question.get("track") == "technology"
                for question in next_test["questions"]
            )
        )

    def test_test_attempt_expires_at_twenty_minutes_and_is_private(self):
        self.register(self.client, "Avery Explorer", "avery@example.test")
        answers = {"csrf_token": self.csrf_token()}
        answers.update({question["id"]: "4" for question in QUESTIONS[:10]})
        self.client.post("/assessment", data=answers)
        response = self.client.post(
            "/tests/start", data={"csrf_token": self.csrf_token()}
        )
        test_id = int(response.location.rsplit("/", 1)[1])
        with app.app_context():
            get_db().execute(
                "UPDATE learning_tests SET started_at = ? WHERE id = ?",
                ((datetime.now() - timedelta(minutes=21)).isoformat(), test_id),
            )
            get_db().commit()
        history = self.client.get("/tests")
        self.assertEqual(history.status_code, 200)
        analysis = self.client.get(f"/tests/{test_id}/analysis")
        self.assertEqual(analysis.status_code, 200)
        self.assertIn(b"TIME LIMIT REACHED", analysis.data)
        self.assertIn(b"0%", analysis.data)

        other_client = app.test_client()
        self.register(other_client, "Blair Explorer", "blair@example.test")
        self.assertEqual(other_client.get(f"/tests/{test_id}").status_code, 404)

    def test_task_rewards_are_variable_and_duplicate_completion_is_idempotent(self):
        self.register(self.client, "Avery Explorer", "avery@example.test")
        self.assertEqual(self.client.get("/tasks").status_code, 200)
        with app.app_context():
            user_id = get_db().execute(
                "SELECT id FROM users WHERE email = ?", ("avery@example.test",)
            ).fetchone()["id"]
            task = daily_task_plan(user_id, None)[0]
        self.assertNotEqual(task["xp"], 20)
        form_data = {"csrf_token": self.csrf_token()}
        self.assertEqual(
            self.client.post(
                f"/tasks/{task['id']}/complete", data=form_data
            ).status_code,
            302,
        )
        self.assertEqual(
            self.client.post(
                f"/tasks/{task['id']}/complete", data=form_data
            ).status_code,
            302,
        )
        with app.app_context():
            progress = get_db().execute("SELECT xp FROM user_progress").fetchone()
            completion_count = get_db().execute(
                "SELECT COUNT(*) AS count FROM task_completions"
            ).fetchone()["count"]
        self.assertEqual(progress["xp"], task["xp"])
        self.assertEqual(completion_count, 1)

    def test_task_mentor_uses_task_details(self):
        self.register(self.client, "Avery Explorer", "avery@example.test")
        answers = {"csrf_token": self.csrf_token()}
        answers.update({question["id"]: "4" for question in QUESTIONS[:10]})
        self.client.post("/assessment", data=answers)
        with app.app_context():
            user_id = get_db().execute(
                "SELECT id FROM users WHERE email = ?", ("avery@example.test",)
            ).fetchone()["id"]
            task = daily_task_plan(user_id, None)[0]
        page = self.client.get(f"/mentor?task={task['id']}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(task["deliverable"].encode(), page.data)
        response = self.client.post(
            "/mentor",
            data={
                "csrf_token": self.csrf_token(),
                "task_id": task["id"],
                "message": "Help me understand the task",
            },
        )
        self.assertEqual(response.status_code, 302)
        mentor_page = self.client.get("/mentor")
        self.assertIn(b"start with the finish line", mentor_page.data)
        self.assertIn(task["deliverable"].encode(), mentor_page.data)

    def test_career_feedback_suggests_alternatives_and_preserves_reason(self):
        self.register(self.client, "Avery Explorer", "avery@example.test")
        answers = {"csrf_token": self.csrf_token()}
        answers.update({question["id"]: "4" for question in QUESTIONS[:10]})
        self.client.post("/assessment", data=answers)
        csrf = self.csrf_token()
        self.client.post(
            "/careers/football-player/select",
            data={"csrf_token": csrf},
        )
        response = self.client.post(
            "/career-feedback",
            data={
                "csrf_token": csrf,
                "reason": "I prefer supporting a team than competing.",
            },
        )
        self.assertEqual(response.status_code, 302)
        page = self.client.get(response.location)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Other directions to explore", page.data)
        with app.app_context():
            saved_feedback = get_db().execute(
                "SELECT career_id, reason, recommendations_json FROM career_feedback"
            ).fetchone()
        self.assertEqual(saved_feedback["career_id"], "football-player")
        self.assertEqual(
            saved_feedback["reason"],
            "I prefer supporting a team than competing.",
        )
        self.assertNotIn(
            "football-player", json.loads(saved_feedback["recommendations_json"])
        )

    def test_account_data_is_isolated(self):
        self.register(self.client, "Avery Explorer", "avery@example.test")
        daily = self.client.get("/tasks")
        self.assertEqual(daily.status_code, 200)
        with app.app_context():
            user_id = get_db().execute(
                "SELECT id FROM users WHERE email = ?", ("avery@example.test",)
            ).fetchone()["id"]
        with self.client.session_transaction() as state:
            state["user_id"] = user_id
        self.client.post(
            f"/tasks/{self.current_daily_task_id(user_id)}/complete",
            data={"csrf_token": self.csrf_token()},
        )

        another_client = app.test_client()
        self.register(another_client, "Blair Explorer", "blair@example.test")
        dashboard = another_client.get("/").data
        self.assertIn(b"Blair Explorer", dashboard)
        self.assertNotIn(b"Avery Explorer", dashboard)
        with app.app_context():
            progress = get_db().execute(
                "SELECT xp FROM user_progress WHERE user_id = (SELECT id FROM users WHERE email = ?)",
                ("blair@example.test",),
            ).fetchone()
        self.assertEqual(progress["xp"], 0)
        self.assertEqual(another_client.get("/results").status_code, 302)

    def current_daily_task_id(self, user_id):
        with app.app_context():
            return daily_task_plan(
                user_id,
                None,
            )[0]["id"]

    def test_daily_plan_is_stable_then_rotates_on_new_date(self):
        career = next(item for item in CAREERS if item["id"] == "software-developer")
        today = date(2026, 11, 8)
        first = daily_tasks_for_career(career, 7, today)
        repeated = daily_tasks_for_career(career, 7, today)
        following_day = daily_tasks_for_career(career, 7, today + timedelta(days=1))
        self.assertEqual([task["id"] for task in first], [task["id"] for task in repeated])
        self.assertEqual(len(first), 3)
        self.assertNotEqual(
            {task["id"] for task in first},
            {task["id"] for task in following_day},
        )

        self.register(self.client, "Avery Explorer", "avery@example.test")
        with app.app_context():
            user_id = get_db().execute(
                "SELECT id FROM users WHERE email = ?", ("avery@example.test",)
            ).fetchone()["id"]
            plan = daily_task_plan(user_id, career, today)
            stored = get_db().execute(
                "SELECT task_ids FROM daily_task_plans WHERE user_id = ? AND plan_date = ?",
                (user_id, today.isoformat()),
            ).fetchone()
        self.assertEqual(json.loads(stored["task_ids"]), [task["id"] for task in plan])
        self.assertEqual(self.client.get("/progress").status_code, 200)
        self.assertIn(b"Practice adds up", self.client.get("/progress").data)
        self.assertEqual(self.client.get("/api/day").json["date"], date.today().isoformat())

    def test_dashboard_has_six_progressive_career_video_searches(self):
        self.register(self.client, "Avery Explorer", "avery@example.test")
        data = {"csrf_token": self.csrf_token()}
        data.update({question["id"]: "5" for question in QUESTIONS})
        self.client.post("/assessment", data=data)
        dashboard = self.client.get("/").data
        self.assertEqual(dashboard.count(b"youtube.com/results?search_query="), 6)
        self.assertIn(b"Beginner", dashboard)
        self.assertIn(b"Intermediate", dashboard)
        self.assertIn(b"Advanced", dashboard)

    def test_theme_and_mentor_are_persisted_per_account(self):
        self.register(self.client, "Avery Explorer", "avery@example.test")
        response = self.client.post(
            "/profile/preferences",
            data={
                "csrf_token": self.csrf_token(),
                "name": "Avery Light",
                "theme": "light",
                "accent_color": "magenta",
                "market_country": "GB",
            },
        )
        self.assertEqual(response.status_code, 302)
        profile = self.client.get("/profile").data
        self.assertIn(b"theme-light", profile)
        self.assertIn(b"Magenta", profile)
        with app.app_context():
            saved_user = get_db().execute(
                "SELECT theme, accent_color, market_country "
                "FROM users WHERE email = ?",
                ("avery@example.test",),
            ).fetchone()
            user_columns = {
                row["name"] for row in get_db().execute("PRAGMA table_info(users)")
            }
        self.assertEqual(
            tuple(saved_user),
            ("light", "magenta", "GB"),
        )
        self.assertNotIn("meta_ai_enabled", user_columns)
        self.assertEqual(self.client.get_cookie("career_compass_theme").value, "light")
        self.assertEqual(
            self.client.get_cookie("career_compass_accent").value, "magenta"
        )

        response = self.client.post(
            "/mentor",
            data={
                "csrf_token": self.csrf_token(),
                "message": "I feel overwhelmed about choosing a career",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(b"whole future today", self.client.get("/mentor").data)
        with app.app_context():
            saved_message = get_db().execute(
                "SELECT intent, sources FROM mentor_messages ORDER BY id DESC LIMIT 1"
            ).fetchone()
        self.assertEqual(saved_message["intent"], "overwhelmed")
        self.assertEqual(saved_message["sources"], "[]")
        self.assertEqual(classify_intent("How do I start learning this skill?"), "learning")
        self.assertEqual(
            self.client.post(
                "/logout", data={"csrf_token": self.csrf_token()}
            ).status_code,
            302,
        )
        signed_out_page = self.client.get("/login").data
        self.assertIn(b"theme-light accent-magenta", signed_out_page)
        self.assertIn(b'data-accent="magenta"', signed_out_page)
        self.client.delete_cookie("career_compass_theme")
        self.client.delete_cookie("career_compass_accent")
        self.client.get("/login")
        response = self.client.post(
            "/login",
            data={
                "csrf_token": self.csrf_token(),
                "email": "avery@example.test",
                "password": "Correct-Horse-42!",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get_cookie("career_compass_theme").value, "light")
        self.assertEqual(
            self.client.get_cookie("career_compass_accent").value, "magenta"
        )

    def test_career_outlook_renders_research_links_without_inventing_a_report(self):
        self.register(self.client, "Avery Explorer", "avery@example.test")
        answers = {"csrf_token": self.csrf_token()}
        answers.update({question["id"]: "4" for question in QUESTIONS[:10]})
        self.client.post("/assessment", data=answers)
        with patch.object(app_module, "_model_api_key", return_value=None):
            page = self.client.get("/insights")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"No live report saved yet", page.data)
        self.assertIn(b"STRENGTHS TO BUILD", page.data)
        self.assertIn(b"WORLDWIDE SCOPE", page.data)
        self.assertIn(b"EARNINGS", page.data)
        self.assertIn(b"TYPICAL WORK", page.data)
        self.assertIn(b"ENTRY &amp; PROGRESSION", page.data)
        self.assertIn(b"Occupational Outlook Handbook", page.data)
        self.assertNotIn(b"Current cached report", page.data)

    def test_configured_meta_mentor_is_used_by_default(self):
        self.register(self.client, "Avery Explorer", "avery@example.test")
        answers = {"csrf_token": self.csrf_token()}
        answers.update({question["id"]: "4" for question in QUESTIONS[:10]})
        self.client.post("/assessment", data=answers)
        profile = self.client.get("/profile").data
        self.assertNotIn(b"Use Meta AI for mentor answers", profile)
        with app.app_context():
            user_id = get_db().execute(
                "SELECT id FROM users WHERE email = ?", ("avery@example.test",)
            ).fetchone()["id"]
            task = daily_task_plan(user_id, None)[0]
        source = {
            "type": "url_citation",
            "title": "Official occupational outlook",
            "url": "https://example.test/outlook",
        }
        with (
            patch.object(app_module, "_model_api_key", return_value="test-key"),
            patch.object(
                app_module,
                "meta_mentor_reply",
                return_value=("A sourced answer about the task.", [source]),
            ) as meta_reply,
        ):
            response = self.client.post(
                "/mentor",
                data={
                    "csrf_token": self.csrf_token(),
                    "task_id": task["id"],
                    "message": "What if I use another approach?",
                },
            )
            page = self.client.get("/mentor")
        self.assertEqual(response.status_code, 302)
        self.assertIn(b"A sourced answer about the task.", page.data)
        self.assertIn(b"Official occupational outlook", page.data)
        self.assertIn(b"server uses Meta AI for your answer", page.data)
        self.assertEqual(
            meta_reply.call_args.kwargs["task_context"]["id"],
            task["id"],
        )

    def test_browser_ai_reply_is_saved_without_calling_meta(self):
        self.register(self.client, "Avery Explorer", "avery@example.test")
        with (
            patch.object(app_module, "_model_api_key", return_value="test-key"),
            patch.object(app_module, "meta_mentor_reply") as meta_reply,
        ):
            response = self.client.post(
                "/mentor",
                data={
                    "csrf_token": self.csrf_token(),
                    "message": "What is one useful next step?",
                    "browser_ai_reply": "Build a small project and review what you learn.",
                },
            )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(meta_reply.called)
        with app.app_context():
            saved_message = get_db().execute(
                "SELECT role, message, sources FROM mentor_messages "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        self.assertEqual(saved_message["role"], "mentor")
        self.assertEqual(
            saved_message["message"],
            "Build a small project and review what you learn.",
        )
        self.assertEqual(
            json.loads(saved_message["sources"]),
            [{"type": "browser_ai", "title": "On-device browser AI"}],
        )

    def test_existing_accounts_do_not_claim_legacy_backups(self):
        self.register(self.client, "Avery Explorer", "avery@example.test")
        with app.app_context():
            user_id = get_db().execute(
                "SELECT id FROM users WHERE email = ?", ("avery@example.test",)
            ).fetchone()["id"]
            get_db().executescript(
                """
                CREATE TABLE legacy_progress (
                    id INTEGER PRIMARY KEY, xp INTEGER, streak INTEGER,
                    last_active TEXT, selected_career TEXT
                );
                INSERT INTO legacy_progress VALUES (1, 900, 12, '2026-11-07', 'teacher');
                """
            )
        another_client = app.test_client()
        self.register(another_client, "Blair Explorer", "blair@example.test")
        with app.app_context():
            progress = get_db().execute(
                "SELECT xp FROM user_progress WHERE user_id = ?", (user_id,)
            ).fetchone()
            new_progress = get_db().execute(
                "SELECT xp FROM user_progress WHERE user_id = "
                "(SELECT id FROM users WHERE email = ?)",
                ("blair@example.test",),
            ).fetchone()
            backup = get_db().execute(
                "SELECT xp FROM legacy_progress"
            ).fetchone()
        self.assertEqual(progress["xp"], 0)
        self.assertEqual(new_progress["xp"], 0)
        self.assertEqual(backup["xp"], 900)

    def test_legacy_profile_moves_to_first_registered_account(self):
        remove_test_database()
        legacy = sqlite3.connect(TEST_DATABASE)
        legacy.executescript(
            """
            CREATE TABLE progress (
                id INTEGER PRIMARY KEY CHECK(id = 1), xp INTEGER NOT NULL,
                streak INTEGER NOT NULL, last_active TEXT, selected_career TEXT
            );
            INSERT INTO progress VALUES (1, 120, 2, '2026-11-07', 'data-analyst');
            CREATE TABLE assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT, scores TEXT NOT NULL, created_at TEXT NOT NULL
            );
            INSERT INTO assessments(scores, created_at)
                VALUES ('{"analytical": 4}', '2026-11-06T12:00:00');
            CREATE TABLE task_completions (
                task_id TEXT NOT NULL, completed_on TEXT NOT NULL,
                PRIMARY KEY(task_id, completed_on)
            );
            INSERT INTO task_completions VALUES ('curiosity-note', '2026-11-07');
            CREATE TABLE mentor_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL CHECK(role IN ('user', 'mentor')),
                message TEXT NOT NULL, created_at TEXT NOT NULL
            );
            INSERT INTO mentor_messages(role, message, created_at)
                VALUES ('user', 'legacy message', '2026-11-06T12:00:00');
            """
        )
        legacy.commit()
        legacy.close()
        with app.app_context():
            init_db()

        self.register(self.client, "Avery Explorer", "avery@example.test")
        with app.app_context():
            progress = get_db().execute("SELECT xp, selected_career FROM user_progress").fetchone()
            old_tables = get_db().execute(
                "SELECT COUNT(*) AS count FROM sqlite_master "
                "WHERE type = 'table' AND name LIKE 'legacy_%'"
            ).fetchone()["count"]
        self.assertEqual(progress["xp"], 120)
        self.assertEqual(progress["selected_career"], "data-analyst")
        self.assertEqual(old_tables, 0)
        self.assertIn(b"legacy message", self.client.get("/mentor").data)


if __name__ == "__main__":
    unittest.main()
