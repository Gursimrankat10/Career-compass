import unittest

from static_export import StaticHTMLRewriter, static_page_for_path


class StaticExportTests(unittest.TestCase):
    def test_application_routes_map_to_static_html_pages(self):
        self.assertEqual(static_page_for_path("/"), "index.html")
        self.assertEqual(static_page_for_path("/mentor"), "mentor.html")
        self.assertEqual(static_page_for_path("/tests/17"), "test.html")
        self.assertEqual(
            static_page_for_path("/tests/17/analysis"),
            "test-analysis.html",
        )
        self.assertIsNone(static_page_for_path("/api/day"))

    def test_rewriter_removes_backend_forms_and_rewrites_local_assets(self):
        source = (
            '<!DOCTYPE html><html><body><main>'
            '<a href="/mentor">Mentor</a>'
            '<img src="/static/favicon.svg">'
            '<form method="post" action="/login">'
            '<input type="hidden" name="csrf_token" value="secret">'
            '<button type="submit">Sign in</button></form>'
            '<script>fetch("/api/day")</script>'
            "</main></body></html>"
        )

        result = StaticHTMLRewriter().rewrite(source)

        self.assertTrue(result.startswith("<!DOCTYPE html>"))
        self.assertIn('href="mentor.html"', result)
        self.assertIn('src="static/favicon.svg"', result)
        self.assertIn('data-static-form="true"', result)
        self.assertIn('action="#static-preview"', result)
        self.assertNotIn("name=\"csrf_token\"", result)
        self.assertNotIn('fetch("/api/day")', result)
        self.assertIn('src="static/static-preview.js"', result)
        self.assertIn("Static preview", result)


if __name__ == "__main__":
    unittest.main()
