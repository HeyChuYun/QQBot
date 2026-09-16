from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import quote

import aiohttp
from botpy import logging


logger = logging.get_logger()
GITHUB_API_URL = "https://api.github.com"
MAX_COMMITS_PER_POLL = 20


@dataclass(frozen=True)
class Commit:
    repository: str
    sha: str
    title: str
    author: str
    committed_at: str
    url: str


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


def parse_commit(repository: str, data: dict[str, Any]) -> Commit:
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

    def status_text(self) -> str:
        repositories = "、".join(self.repositories) or "未配置"
        personal_count = sum(
            subscription.target_type == "personal"
            for subscription in self.subscriptions
        )
        group_count = sum(
            subscription.target_type == "group"
            for subscription in self.subscriptions
        )
        return (
            f"GitHub 监听：{'运行中' if self.repositories else '未配置'}\n"
            f"仓库：{repositories}\n"
            f"个人订阅：{personal_count} 个\n"
            f"群组订阅：{group_count} 个\n"
            f"检查间隔：{self.interval_seconds} 秒"
        )

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
        return [parse_commit(repository, item) for item in data]
