from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import quote, urlparse

import aiohttp
from botpy import logging


logger = logging.get_logger()
GITHUB_API_URL = "https://api.github.com"
MAX_COMMITS_PER_POLL = 20
GITHUB_ICON_URL = "https://github.githubassets.com/favicons/favicon.svg"


@dataclass(frozen=True)
class RepositoryBranding:
    image_url: str
    image_kind: str


GITHUB_BRANDING = RepositoryBranding(GITHUB_ICON_URL, "github-icon")


@dataclass(frozen=True)
class Commit:
    repository: str
    sha: str
    title: str
    author: str
    committed_at: str
    url: str
    brand_image_url: str = GITHUB_ICON_URL
    brand_image_kind: str = "github-icon"


@dataclass(frozen=True)
class Subscription:
    target_type: str
    name: str
    openid: str
    repositories: tuple[str, ...]

    def state_key(self, repository: str) -> str:
        return f"{self.target_type}:{self.openid}:{repository}"


class CommitStateStore:
    def __init__(self, path: Path):
        self.path = path
        self._state = self._load()

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("读取 GitHub 状态文件失败，将重新建立基线")
            return {}
        return {str(key): str(value) for key, value in data.items()}

    def get(self, repository: str) -> Optional[str]:
        return self._state.get(repository)

    def set(self, repository: str, sha: str) -> None:
        self._state[repository] = sha
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.path)


def select_repository_branding(
    uses_custom_preview: bool,
    preview_url: str,
    owner_type: str,
    owner_avatar_url: str,
) -> RepositoryBranding:
    if uses_custom_preview and preview_url:
        return RepositoryBranding(preview_url, "social-preview")
    if owner_type.lower() == "organization" and owner_avatar_url:
        return RepositoryBranding(owner_avatar_url, "owner-avatar")
    return GITHUB_BRANDING


class OpenGraphImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.image_url = ""

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, Optional[str]]]
    ) -> None:
        if tag.lower() != "meta" or self.image_url:
            return
        values = dict(attrs)
        if values.get("property") == "og:image":
            self.image_url = values.get("content") or ""


def is_custom_social_preview(image_url: str) -> bool:
    return urlparse(image_url).hostname == "repository-images.githubusercontent.com"


def parse_commit(
    repository: str,
    data: dict[str, Any],
    branding: RepositoryBranding = GITHUB_BRANDING,
) -> Commit:
    commit_data = data.get("commit", {})
    api_author = data.get("author") or {}
    git_author = commit_data.get("author") or {}
    title = str(commit_data.get("message") or "无提交说明").splitlines()[0].strip()
    return Commit(
        repository=repository,
        sha=str(data.get("sha") or ""),
        title=title[:200],
        author=str(api_author.get("login") or git_author.get("name") or "未知"),
        committed_at=str(git_author.get("date") or ""),
        url=str(data.get("html_url") or ""),
        brand_image_url=branding.image_url,
        brand_image_kind=branding.image_kind,
    )


def new_commits(commits: list[Commit], last_sha: Optional[str]) -> list[Commit]:
    if not commits or last_sha is None or commits[0].sha == last_sha:
        return []
    for index, commit in enumerate(commits):
        if commit.sha == last_sha:
            return list(reversed(commits[:index]))
    return [commits[0]]


def display_time(value: str) -> str:
    timestamp = value
    if not timestamp:
        return ""
    try:
        return (
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            .astimezone()
            .strftime("%Y-%m-%d %H:%M:%S")
        )
    except ValueError:
        return timestamp


def format_notification(commit: Commit, include_link: bool) -> str:
    timestamp = display_time(commit.committed_at)

    lines = [
        "[GitHub 提交更新]",
        f"仓库：{commit.repository}",
        f"提交：{commit.sha[:7]}",
        f"作者：{commit.author}",
        f"内容：{commit.title}",
    ]
    if timestamp:
        lines.append(f"时间：{timestamp}")
    if include_link and commit.url:
        lines.append(f"查看：{commit.url}")
    return "\n".join(lines)


class GitHubCommitMonitor:
    def __init__(
        self,
        subscriptions: tuple[Subscription, ...],
        token: str,
        interval_seconds: int,
        state_file: Path,
        include_link: bool,
        send_notification: Callable[[Subscription, Commit], Awaitable[None]],
    ):
        self.subscriptions = subscriptions
        self.repositories = tuple(
            dict.fromkeys(
                repository
                for subscription in subscriptions
                for repository in subscription.repositories
            )
        )
        self.token = token
        self.interval_seconds = interval_seconds
        self.include_link = include_link
        self.send_notification = send_notification
        self.state = CommitStateStore(state_file)
        self._branding_cache: dict[str, RepositoryBranding] = {}

    async def run(self) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "QQBot-GitHub-Monitor",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            while True:
                try:
                    await self.poll(session)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("GitHub 提交检查失败")
                await asyncio.sleep(self.interval_seconds)

    async def poll(self, session: aiohttp.ClientSession) -> None:
        commits_by_repository = {
            repository: await self.fetch_commits(session, repository)
            for repository in self.repositories
        }
        for subscription in self.subscriptions:
            for repository in subscription.repositories:
                commits = commits_by_repository.get(repository, [])
                if not commits:
                    continue

                state_key = subscription.state_key(repository)
                last_sha = self.state.get(state_key) or self.state.get(repository)
                if last_sha is None:
                    self.state.set(state_key, commits[0].sha)
                    logger.info(
                        "订阅 %s 的仓库 %s 已建立基线 %s",
                        subscription.name,
                        repository,
                        commits[0].sha[:7],
                    )
                    continue

                try:
                    for commit in new_commits(commits, last_sha):
                        await self.send_notification(subscription, commit)
                        self.state.set(state_key, commit.sha)
                        logger.info(
                            "已向订阅 %s 推送 %s@%s",
                            subscription.name,
                            repository,
                            commit.sha[:7],
                        )
                except Exception:
                    logger.exception(
                        "订阅 %s 推送失败，将在下次检查重试",
                        subscription.name,
                    )

    async def fetch_commits(
        self, session: aiohttp.ClientSession, repository: str
    ) -> list[Commit]:
        branding = await self.fetch_repository_branding(session, repository)
        owner, name = repository.split("/", 1)
        url = (
            f"{GITHUB_API_URL}/repos/{quote(owner, safe='')}/"
            f"{quote(name, safe='')}/commits"
        )
        async with session.get(
            url, params={"per_page": MAX_COMMITS_PER_POLL}
        ) as response:
            data = await response.json(content_type=None)
            if response.status >= 400:
                message = data.get("message") if isinstance(data, dict) else str(data)
                raise RuntimeError(
                    f"GitHub API 请求失败：{repository}，"
                    f"HTTP {response.status}，{message}"
                )
        return [parse_commit(repository, item, branding) for item in data]

    async def fetch_repository_branding(
        self, session: aiohttp.ClientSession, repository: str
    ) -> RepositoryBranding:
        cached = self._branding_cache.get(repository)
        if cached:
            return cached

        try:
            if self.token:
                branding = await self._fetch_branding_graphql(session, repository)
            else:
                branding = await self._fetch_branding_public(session, repository)
        except Exception:
            logger.exception("读取仓库品牌图片失败，将使用 GitHub 图标：%s", repository)
            branding = GITHUB_BRANDING
        self._branding_cache[repository] = branding
        logger.info("仓库 %s 使用品牌图片类型：%s", repository, branding.image_kind)
        return branding

    async def _fetch_branding_graphql(
        self, session: aiohttp.ClientSession, repository: str
    ) -> RepositoryBranding:
        owner, name = repository.split("/", 1)
        query = """
        query RepositoryBranding($owner: String!, $name: String!) {
          repository(owner: $owner, name: $name) {
            usesCustomOpenGraphImage
            openGraphImageUrl
            owner {
              __typename
              avatarUrl
            }
          }
        }
        """
        async with session.post(
            f"{GITHUB_API_URL}/graphql",
            json={"query": query, "variables": {"owner": owner, "name": name}},
        ) as response:
            data = await response.json(content_type=None)
            if response.status >= 400 or data.get("errors"):
                raise RuntimeError(
                    f"GitHub GraphQL 请求失败：HTTP {response.status}，"
                    f"{data.get('errors') or data}"
                )
        repository_data = (data.get("data") or {}).get("repository") or {}
        owner_data = repository_data.get("owner") or {}
        return select_repository_branding(
            bool(repository_data.get("usesCustomOpenGraphImage")),
            str(repository_data.get("openGraphImageUrl") or ""),
            str(owner_data.get("__typename") or ""),
            str(owner_data.get("avatarUrl") or ""),
        )

    async def _fetch_branding_public(
        self, session: aiohttp.ClientSession, repository: str
    ) -> RepositoryBranding:
        owner, name = repository.split("/", 1)
        api_url = (
            f"{GITHUB_API_URL}/repos/{quote(owner, safe='')}/"
            f"{quote(name, safe='')}"
        )
        async with session.get(api_url) as response:
            repository_data = await response.json(content_type=None)
            if response.status >= 400:
                raise RuntimeError(
                    f"GitHub 仓库信息请求失败：HTTP {response.status}"
                )

        owner_data = repository_data.get("owner") or {}
        parser = OpenGraphImageParser()
        async with session.get(f"https://github.com/{repository}") as response:
            if response.status < 400:
                parser.feed(await response.text())
        return select_repository_branding(
            is_custom_social_preview(parser.image_url),
            parser.image_url,
            str(owner_data.get("type") or ""),
            str(owner_data.get("avatar_url") or ""),
        )
