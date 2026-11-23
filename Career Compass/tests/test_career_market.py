import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from career_market import (
    MetaAPIError,
    _extract_answer,
    _safe_source,
    cached_insight_is_stale,
    career_market_prompt,
    mentor_prompt,
    read_cached_insight,
    refresh_insights,
    refresh_stale_insights,
)
from careers import CAREERS


class CareerMarketTests(unittest.TestCase):
    def setUp(self):
        self.database = sqlite3.connect(":memory:")
        self.database.row_factory = sqlite3.Row
        self.database.execute(
            """CREATE TABLE career_insights (
               career_id TEXT NOT NULL, country_code TEXT NOT NULL,
               report TEXT NOT NULL, sources_json TEXT NOT NULL,
               updated_at TEXT NOT NULL, PRIMARY KEY (career_id, country_code)
            )"""
        )

    def tearDown(self):
        self.database.close()

    def test_market_prompt_requests_region_and_cited_statistical_context(self):
        career = next(item for item in CAREERS if item["id"] == "data-analyst")
        prompt = career_market_prompt(career, "IN")
        self.assertIn("Prioritize India", prompt)
        self.assertIn("CAREER SCOPE", prompt)
        self.assertIn("EARNINGS", prompt)
        self.assertIn("WHAT THE WORK IS LIKE", prompt)
        self.assertIn("ENTRY ROUTES AND PROGRESSION", prompt)
        self.assertIn(career["description"], prompt)
        self.assertIn("never estimate or convert unsupported pay", prompt)

    def test_mentor_prompt_uses_market_report_and_task_details(self):
        career = next(item for item in CAREERS if item["id"] == "data-analyst")
        task = {"title": "Compare two datasets", "deliverable": "A short, sourced comparison"}
        prompt = mentor_prompt(
            "What if the data disagree?",
            career,
            "GB",
            "Cached report from 2026",
            task_context=task,
        )
        self.assertIn("United Kingdom", prompt)
        self.assertIn("Cached report from 2026", prompt)
        self.assertIn("A short, sourced comparison", prompt)
        self.assertIn("What if the data disagree?", prompt)
        general_prompt = mentor_prompt("What could I explore?", None, "IN")
        self.assertIn("No career has been selected yet", general_prompt)

    def test_answer_parser_keeps_only_safe_deduplicated_https_citations(self):
        result = {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Use current official information.",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "title": "Official source",
                                    "url": "https://example.test/report",
                                },
                                {
                                    "type": "url_citation",
                                    "title": "Unsafe source",
                                    "url": "javascript:alert(1)",
                                },
                            ],
                        }
                    ],
                },
                {
                    "type": "web_search_call",
                    "results": [
                        {
                            "title": "Official source",
                            "url": "https://example.test/report",
                        }
                    ],
                },
            ],
        }
        answer, sources = _extract_answer(result)
        self.assertEqual(answer, "Use current official information.")
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["type"], "url_citation")
        self.assertIsNone(_safe_source("HTTP source", "http://example.test"))

    def test_incomplete_or_uncited_response_is_not_saved(self):
        with self.assertRaises(MetaAPIError):
            _extract_answer({"status": "in_progress", "output": []})
        with patch("career_market._request_payload", return_value=("Uncited report.", [])):
            with self.assertRaises(MetaAPIError):
                refresh_insights(
                    self.database,
                    CAREERS[0],
                    "IN",
                    "test-key",
                )

    def test_refresh_saves_cited_report_and_marks_it_fresh(self):
        sources = [
            {
                "type": "url_citation",
                "title": "Official source",
                "url": "https://example.test/report",
            }
        ]
        with patch(
            "career_market._request_payload",
            return_value=("A current, sourced report.", sources),
        ) as request:
            saved = refresh_insights(self.database, CAREERS[0], "IN", "test-key")
        self.assertEqual(request.call_args.kwargs["max_output_tokens"], 2600)
        cached = read_cached_insight(self.database, CAREERS[0]["id"], "IN")
        self.assertEqual(saved["report"], "A current, sourced report.")
        self.assertEqual(cached["sources"], sources)
        self.assertFalse(cached["stale"])

    def test_scheduled_refresh_is_bounded_to_three_expired_reports(self):
        old = "2020-01-01T00:00:00+00:00"
        self.database.executemany(
            """INSERT INTO career_insights
               (career_id, country_code, report, sources_json, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (CAREERS[0]["id"], country, "Old report", "[]", old)
                for country in ("IN", "US", "GB", "CA")
            ],
        )
        self.database.commit()
        with patch("career_market.refresh_insights") as refresh:
            count = refresh_stale_insights(
                self.database,
                "test-key",
                lambda career_id: CAREERS[0] if career_id == CAREERS[0]["id"] else None,
            )
        self.assertEqual(count, 3)
        self.assertEqual(refresh.call_count, 3)

    def test_cache_expiry_is_seven_days_and_invalid_dates_are_stale(self):
        now = datetime(2026, 11, 22, tzinfo=timezone.utc)
        six_days_old = (now - timedelta(days=6)).isoformat()
        eight_days_old = (now - timedelta(days=8)).isoformat()
        self.assertFalse(cached_insight_is_stale(six_days_old, now))
        self.assertTrue(cached_insight_is_stale(eight_days_old, now))
        self.assertTrue(cached_insight_is_stale("not a date", now))
        self.assertTrue(cached_insight_is_stale(None, now))


if __name__ == "__main__":
    unittest.main()
