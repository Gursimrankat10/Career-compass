import json
import os
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from cloudflare_d1 import D1Database
from app import load_secret_key


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeStatement:
    def __init__(self, database, sql):
        self.database = database
        self.sql = sql
        self.parameters = ()

    def bind(self, *parameters):
        self.parameters = parameters
        return self

    def all(self):
        return {"results": self.database.rows}

    def run(self):
        if self.database.error:
            raise RuntimeError(self.database.error)
        return {"meta": {"last_row_id": 41, "changes": 1}}


class FakeD1Binding:
    def __init__(self):
        self.rows = [{"id": 7, "name": "Ada"}]
        self.error = None
        self.batches = []

    def prepare(self, sql):
        return FakeStatement(self, sql)

    def batch(self, statements):
        if self.error:
            raise RuntimeError(self.error)
        self.batches.append(statements)
        return [{"meta": {"changes": 1}} for _ in statements]


class CloudflareDeploymentTests(unittest.TestCase):
    def test_d1_select_rows_support_sqlite_row_access_patterns(self):
        database = D1Database(FakeD1Binding(), run_sync=lambda result: result)

        cursor = database.execute("SELECT id, name FROM users WHERE id = ?", (7,))

        row = cursor.fetchone()
        self.assertEqual(row["name"], "Ada")
        self.assertEqual(row[0], 7)
        self.assertIsNone(cursor.fetchone())

    def test_d1_write_exposes_insert_metadata_and_batch(self):
        binding = FakeD1Binding()
        database = D1Database(binding, run_sync=lambda result: result)

        cursor = database.execute("INSERT INTO users (name) VALUES (?)", ("Ada",))
        batch_cursor = database.executemany(
            "INSERT INTO users (name) VALUES (?)", [("Ada",), ("Grace",)]
        )

        self.assertEqual(cursor.lastrowid, 41)
        self.assertEqual(cursor.rowcount, 1)
        self.assertEqual(batch_cursor.rowcount, 2)
        self.assertEqual(len(binding.batches), 1)

    def test_d1_account_creation_is_batched_and_returns_the_created_id(self):
        binding = FakeD1Binding()
        database = D1Database(binding, run_sync=lambda result: result)

        user_id = database.create_user("ada@example.test", "Ada", "hash", "today")

        self.assertEqual(user_id, 7)
        self.assertEqual(len(binding.batches[0]), 2)

    def test_d1_unique_constraint_uses_existing_registration_error_handling(self):
        binding = FakeD1Binding()
        binding.error = "UNIQUE constraint failed: users.email"
        database = D1Database(binding, run_sync=lambda result: result)

        with self.assertRaises(sqlite3.IntegrityError):
            database.create_user("ada@example.test", "Ada", "hash", "today")

    def test_d1_rejects_sql_transaction_statements_instead_of_ignoring_them(self):
        database = D1Database(FakeD1Binding(), run_sync=lambda result: result)

        with self.assertRaisesRegex(RuntimeError, "D1 batch"):
            database.execute("BEGIN IMMEDIATE")

    def test_worker_secret_does_not_read_or_create_local_secret_file(self):
        secret_file = PROJECT_ROOT / ".worker-secret-test"
        secret_file.unlink(missing_ok=True)
        with patch.dict(os.environ, {"CLOUDFLARE_WORKERS": "1"}, clear=True):
            secret = load_secret_key(secret_file)
        self.assertEqual(secret, "cloudflare-secret-is-set-per-request")
        self.assertFalse(secret_file.exists())

    def test_d1_migration_creates_the_app_tables(self):
        database = sqlite3.connect(":memory:")
        for migration_path in sorted((PROJECT_ROOT / "migrations").glob("*.sql")):
            database.executescript(migration_path.read_text(encoding="utf-8"))

        tables = {
            row[0]
            for row in database.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertTrue(
            {
                "users",
                "user_progress",
                "assessments",
                "task_completions",
                "daily_task_plans",
                "mentor_messages",
                "learning_tests",
                "career_feedback",
                "career_insights",
            }.issubset(tables)
        )
        columns = {
            row[1] for row in database.execute("PRAGMA table_info(users)")
        }
        self.assertTrue({"accent_color", "market_country"}.issubset(columns))
        self.assertNotIn("meta_ai_enabled", columns)

    def test_wrangler_config_declares_worker_entrypoint_d1_and_daily_refresh(self):
        config = json.loads((PROJECT_ROOT / "wrangler.jsonc").read_text(encoding="utf-8"))

        self.assertEqual(config["main"], "cloudflare_worker.py")
        self.assertIn("python_workers", config["compatibility_flags"])
        self.assertEqual(config["d1_databases"][0]["binding"], "DB")
        self.assertEqual(config["triggers"]["crons"], ["17 0 * * *"])
        assets_directory = (PROJECT_ROOT / config["assets"]["directory"]).resolve()
        self.assertEqual(assets_directory, PROJECT_ROOT.resolve())
        self.assertTrue((assets_directory / "static" / "style.css").is_file())
        self.assertTrue((assets_directory / "templates" / "auth.html").is_file())

    def test_assets_ignore_only_allows_static_and_template_directories(self):
        ignore_rules = (PROJECT_ROOT / ".assetsignore").read_text(
            encoding="utf-8"
        ).splitlines()

        self.assertEqual(
            ignore_rules,
            ["*", "!static/", "!static/**", "!templates/", "!templates/**"],
        )


if __name__ == "__main__":
    unittest.main()
