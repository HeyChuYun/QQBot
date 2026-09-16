import tempfile
from pathlib import Path
from unittest import TestCase

from plugins.github_monitor.monitor import (
    Commit,
    CommitStateStore,
    GITHUB_BRANDING,
    RepositoryBranding,
    Subscription,
    format_notification,
    is_custom_social_preview,
    new_commits,
    select_repository_branding,
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

    def test_custom_social_preview_has_highest_priority(self):
        branding = select_repository_branding(
            True,
            "https://repository-images.githubusercontent.com/1/preview.png",
            "Organization",
            "https://avatars.githubusercontent.com/u/1",
        )
        self.assertEqual(branding.image_kind, "social-preview")

    def test_organization_avatar_is_the_second_choice(self):
        branding = select_repository_branding(
            False,
            "",
            "Organization",
            "https://avatars.githubusercontent.com/u/1",
        )
        self.assertEqual(
            branding,
            RepositoryBranding(
                "https://avatars.githubusercontent.com/u/1", "owner-avatar"
            ),
        )

    def test_personal_repository_uses_github_icon(self):
        branding = select_repository_branding(
            False,
            "",
            "User",
            "https://avatars.githubusercontent.com/u/1",
        )
        self.assertEqual(branding, GITHUB_BRANDING)

    def test_only_repository_images_domain_is_custom_preview(self):
        self.assertTrue(
            is_custom_social_preview(
                "https://repository-images.githubusercontent.com/1/image.png"
            )
        )
        self.assertFalse(
            is_custom_social_preview(
                "https://opengraph.githubassets.com/hash/owner/repo"
            )
        )
