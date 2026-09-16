import tempfile
from pathlib import Path
from unittest import TestCase

from plugins.github_monitor.monitor import (
    Commit,
    CommitStateStore,
    Subscription,
    format_notification,
    new_commits,
)


def commit(sha: str) -> Commit:
    return Commit(
        repository="owner/repo",
        sha=sha,
        title=f"commit {sha}",
        author="developer",
        committed_at="2026-09-15T00:00:00Z",
        url=f"https://github.com/owner/repo/commit/{sha}",
    )


class GitHubMonitorTest(TestCase):
    def test_returns_new_commits_oldest_first(self):
        commits = [commit("newest"), commit("middle"), commit("known")]
        self.assertEqual([item.sha for item in new_commits(commits, "known")], ["middle", "newest"])

    def test_first_poll_does_not_return_history(self):
        self.assertEqual(new_commits([commit("head")], None), [])

    def test_state_is_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            CommitStateStore(path).set("owner/repo", "abc")
            self.assertEqual(CommitStateStore(path).get("owner/repo"), "abc")

    def test_link_is_optional(self):
        self.assertNotIn("https://", format_notification(commit("abc"), False))
        self.assertIn("https://", format_notification(commit("abc"), True))

    def test_each_subscriber_has_independent_state(self):
        first = Subscription("group", "开发群", "group-1", ("owner/repo",))
        second = Subscription("group", "测试群", "group-2", ("owner/repo",))
        self.assertNotEqual(
            first.state_key("owner/repo"), second.state_key("owner/repo")
        )
