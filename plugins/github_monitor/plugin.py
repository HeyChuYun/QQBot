from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any, Optional

from botpy import logging
from botpy.http import Route
from dotenv import dotenv_values

from qqbot_app.plugin import BotPlugin, MessageContext, PluginCommand

from .monitor import (
    Commit,
    GitHubCommitMonitor,
    Subscription,
    format_notification,
)
from .renderer import CommitCardRenderer


logger = logging.get_logger()
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
OPENID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,128}$")


def parse_bool(value: str, default: bool = False) -> bool:
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class GitHubPluginSettings:
    enabled: bool
    subscriptions: tuple[Subscription, ...]
    token: str
    interval_seconds: int
    include_link: bool
    state_file: Path
    browser_channel: str
    browser_executable: str
    fallback_to_text: bool

    @classmethod
    def load(cls, plugin_dir: Path) -> "GitHubPluginSettings":
        config = dotenv_values(plugin_dir / "config.env")

        def value(name: str, default: str = "") -> str:
            configured = str(config.get(name) or "").strip()
            return configured or os.getenv(name, default).strip()

        subscriptions = load_subscriptions(plugin_dir / "subscriptions.json")

        try:
            interval_seconds = int(value("GITHUB_POLL_INTERVAL_SECONDS", "300"))
        except ValueError as error:
            raise ValueError("GITHUB_POLL_INTERVAL_SECONDS 必须是整数") from error
        if interval_seconds < 60:
            raise ValueError("GITHUB_POLL_INTERVAL_SECONDS 不能小于 60")

        state_file = Path(value("GITHUB_STATE_FILE", "data/state.json"))
        if not state_file.is_absolute():
            state_file = plugin_dir / state_file

        return cls(
            enabled=parse_bool(value("ENABLED", "true"), True),
            subscriptions=subscriptions,
            token=value("GITHUB_TOKEN"),
            interval_seconds=interval_seconds,
            include_link=parse_bool(value("GITHUB_INCLUDE_LINK")),
            state_file=state_file,
            browser_channel=value("BROWSER_CHANNEL", "msedge"),
            browser_executable=value("BROWSER_EXECUTABLE"),
            fallback_to_text=parse_bool(value("FALLBACK_TO_TEXT", "true"), True),
        )


def load_subscriptions(path: Path) -> tuple[Subscription, ...]:
    if not path.is_file():
        raise ValueError(f"订阅配置不存在：{path}")
    raw_text = Template(path.read_text(encoding="utf-8")).safe_substitute(os.environ)
    data = json.loads(raw_text)
    subscriptions: list[Subscription] = []
    for config_key, target_type in (("personal", "personal"), ("groups", "group")):
        records = data.get(config_key, [])
        if not isinstance(records, list):
            raise ValueError(f"subscriptions.json 的 {config_key} 必须是列表")
        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                raise ValueError(f"{config_key} 第 {index} 项必须是对象")
            openid = str(record.get("openid") or "").strip()
            repositories = tuple(
                dict.fromkeys(
                    str(repository).strip()
                    for repository in record.get("repositories", [])
                    if str(repository).strip()
                )
            )
            invalid = [
                repository
                for repository in repositories
                if not REPOSITORY_PATTERN.fullmatch(repository)
            ]
            if invalid:
                raise ValueError(
                    f"{config_key} 第 {index} 项仓库格式错误：" + ", ".join(invalid)
                )
            if not OPENID_PATTERN.fullmatch(openid) or not repositories:
                logger.warning(
                    "已跳过订阅 %s 第 %s 项：openid 无效或仓库列表为空",
                    config_key,
                    index,
                )
                continue
            subscriptions.append(
                Subscription(
                    target_type=target_type,
                    name=str(record.get("name") or f"{config_key}-{index}"),
                    openid=openid,
                    repositories=repositories,
                )
            )
    return tuple(subscriptions)


class GitHubMonitorPlugin(BotPlugin):
    commands = (
        PluginCommand(
            name="仓库状态",
            description="查看GitHub监听状态",
        ),
    )

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self.settings = GitHubPluginSettings.load(self.plugin_dir)
        self.monitor: Optional[GitHubCommitMonitor] = None
        self.task: Optional[asyncio.Task] = None
        self.client: Any = None
        self.renderer = CommitCardRenderer(
            self.settings.browser_channel,
            self.settings.browser_executable,
        )
        self.renderer_available = False

    async def start(self, client: Any) -> None:
        self.client = client
        if not self.settings.enabled:
            logger.info("GitHub 提交监听插件已在 config.env 中停用")
            return
        if not self.settings.subscriptions:
            logger.info(
                "GitHub 提交监听未启动，请检查插件 subscriptions.json"
            )
            return

        try:
            await self.renderer.start()
            self.renderer_available = True
        except Exception:
            logger.exception("GitHub 通知卡片渲染器启动失败")
            if not self.settings.fallback_to_text:
                raise
        self.monitor = GitHubCommitMonitor(
            subscriptions=self.settings.subscriptions,
            token=self.settings.token,
            interval_seconds=self.settings.interval_seconds,
            state_file=self.settings.state_file,
            include_link=self.settings.include_link,
            send_notification=self._send_notification,
        )
        self.task = asyncio.create_task(
            self.monitor.run(), name="plugin-github-monitor"
        )
        logger.info("GitHub 提交监听插件已启动")

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None
        await self.renderer.stop()
        self.renderer_available = False

    async def _send_notification(
        self, subscription: Subscription, commit: Commit
    ) -> None:
        try:
            if not self.renderer_available:
                raise RuntimeError("图片渲染器不可用")
            image_data = await self.renderer.render(commit)
            media = await self._upload_image(subscription, image_data)
            await self._post_media(subscription, media)
        except Exception:
            logger.exception("向订阅 %s 发送图片通知失败", subscription.name)
            if not self.settings.fallback_to_text:
                raise
            await self._post_text(
                subscription,
                format_notification(commit, self.settings.include_link),
            )

    async def _upload_image(
        self, subscription: Subscription, image_data: bytes
    ) -> dict[str, Any]:
        encoded = base64.b64encode(image_data).decode("ascii")
        if subscription.target_type == "group":
            route = Route(
                "POST",
                "/v2/groups/{openid}/files",
                openid=subscription.openid,
            )
        else:
            route = Route(
                "POST",
                "/v2/users/{openid}/files",
                openid=subscription.openid,
            )
        result = await self.client.api._http.request(
            route,
            json={"file_type": 1, "file_data": encoded, "srv_send_msg": False},
        )
        if not isinstance(result, dict):
            raise RuntimeError("QQ 图片上传接口未返回媒体信息")
        return result

    async def _post_media(
        self, subscription: Subscription, media: dict[str, Any]
    ) -> None:
        if subscription.target_type == "group":
            await self.client.api.post_group_message(
                group_openid=subscription.openid,
                msg_type=7,
                media=media,
            )
        else:
            await self.client.api.post_c2c_message(
                openid=subscription.openid,
                msg_type=7,
                media=media,
            )

    async def _post_text(
        self, subscription: Subscription, content: str
    ) -> None:
        if subscription.target_type == "group":
            await self.client.api.post_group_message(
                group_openid=subscription.openid,
                msg_type=0,
                content=content,
            )
        else:
            await self.client.api.post_c2c_message(
                openid=subscription.openid,
                msg_type=0,
                content=content,
            )

    async def handle_command(
        self, context: MessageContext, command: PluginCommand
    ) -> Optional[str]:
        if not self.settings.enabled:
            return "GitHub 监听插件：已停用"
        if self.monitor:
            return self.monitor.status_text()
        repositories = tuple(
            dict.fromkeys(
                repository
                for subscription in self.settings.subscriptions
                for repository in subscription.repositories
            )
        )
        return f"GitHub 监听：未启动\n仓库：{'、'.join(repositories) or '未配置'}"
