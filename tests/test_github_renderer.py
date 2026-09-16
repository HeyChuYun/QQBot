import tempfile
from pathlib import Path
from unittest import TestCase

from plugins.github_monitor.monitor import Commit
from plugins.github_monitor.renderer import DEFAULT_TEMPLATE_PATH, build_commit_html


class GitHubRendererTest(TestCase):
    def test_commit_values_are_escaped_in_html(self):
        commit = Commit(
            repository="owner/<repo>",
            sha="abcdef123456",
            title="fix <script>alert(1)</script>",
            author="dev & team",
            committed_at="2026-09-15T00:00:00Z",
            url="https://example.test",
        )
        html = build_commit_html(commit)

        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("dev &amp; team", html)

    def test_html_is_loaded_from_editable_template_file(self):
        self.assertTrue(DEFAULT_TEMPLATE_PATH.is_file())
        with tempfile.TemporaryDirectory() as temp:
            template = Path(temp) / "template.html"
            template.write_text(
                "<p>{{REPOSITORY}} - {{TITLE}} - {{AUTHOR}} - "
                "{{SHA}} - {{TIMESTAMP}}</p>",
                encoding="utf-8",
            )
            commit = Commit(
                repository="owner/repo",
                sha="abcdef123456",
                title="new commit",
                author="developer",
                committed_at="",
                url="",
            )

            html = build_commit_html(commit, template)
            self.assertEqual(
                html,
                "<p>owner/repo - new commit - developer - abcdef1 - 刚刚</p>",
            )
