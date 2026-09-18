from __future__ import annotations

import asyncio
import json
import re
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from botpy import logging
from dotenv import dotenv_values

from qqbot_app.plugin import BotPlugin, MessageContext, PluginCommand

from .fnos_client import FnosGateway
from .monitor import (
    UpsPowerState,
    UpsStateStore,
    classify_ups_state,
    format_snapshot,
    ups_transition_message,
)


logger = logging.get_logger()
ENV_REFERENCE_PATTERN = re.compile(r"\$\{[^}]+\}")
OPENID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,128}$")


def parse_bool(value: str, default: bool = False) -> bool:
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Administrator:
    name: str
    openid: str


@dataclass(frozen=True)
class FnosPluginSettings:
    enabled: bool
    endpoint: str
    username: str
    password: str
    token: str
    long_token: str
    secret: str
    use_ssl: bool
    skip_ssl_verify: bool
    connect_timeout: int
    request_timeout: int
    poll_interval: int
    ups_monitor_enabled: bool
    notify_on_recovery: bool
    state_file: Path
    administrators: tuple[Administrator, ...]

    @classmethod
    def load(cls, plugin_dir: Path) -> "FnosPluginSettings":
        config_path = plugin_dir / "config.env"
        if not config_path.is_file():
            raise ValueError(f"插件配置不存在：{config_path}")
        config = dotenv_values(config_path, interpolate=False)

        def value(name: str, default: str = "") -> str:
            configured = str(config.get(name) or "").strip()
            if ENV_REFERENCE_PATTERN.search(configured):
                raise ValueError(
                    f"{config_path} 的 {name} 不允许引用环境变量，请直接填写配置值"
                )
            return configured or default

        def integer(name: str, default: int, minimum: int) -> int:
            try:
                result = int(value(name, str(default)))
            except ValueError as error:
                raise ValueError(f"{name} 必须是整数") from error
            if result < minimum:
                raise ValueError(f"{name} 不能小于 {minimum}")
            return result

        endpoint = value("FNOS_ENDPOINT")
        username = value("FNOS_USERNAME")
        password = value("FNOS_PASSWORD")
        token = value("FNOS_TOKEN")
        long_token = value("FNOS_LONG_TOKEN")
        secret = value("FNOS_SECRET")
        if not endpoint:
            raise ValueError("FNOS_ENDPOINT 不能为空")
        uses_password = bool(username and password)
        uses_token = bool(token and long_token and secret)
        if not uses_password and not uses_token:
            raise ValueError(
                "必须填写 FNOS_USERNAME/FNOS_PASSWORD，或完整填写 "
                "FNOS_TOKEN/FNOS_LONG_TOKEN/FNOS_SECRET"
            )
        if any((token, long_token, secret)) and not uses_token:
            raise ValueError("FNOS_TOKEN、FNOS_LONG_TOKEN、FNOS_SECRET 必须同时填写")

        state_file = Path(value("FNOS_STATE_FILE", "data/state.json"))
        if not state_file.is_absolute():
            state_file = plugin_dir / state_file
        return cls(
            enabled=parse_bool(value("ENABLED", "true"), True),
            endpoint=endpoint,
            username=username,
            password=password,
            token=token,
            long_token=long_token,
            secret=secret,
            use_ssl=parse_bool(value("FNOS_USE_SSL")),
            skip_ssl_verify=parse_bool(value("FNOS_SKIP_SSL_VERIFY", "true"), True),
            connect_timeout=integer("FNOS_CONNECT_TIMEOUT_SECONDS", 10, 1),
            request_timeout=integer("FNOS_REQUEST_TIMEOUT_SECONDS", 15, 1),
            poll_interval=integer("FNOS_POLL_INTERVAL_SECONDS", 60, 15),
            ups_monitor_enabled=parse_bool(value("UPS_MONITOR_ENABLED", "true"), True),
            notify_on_recovery=parse_bool(value("NOTIFY_ON_RECOVERY", "true"), True),
            state_file=state_file,
            administrators=load_administrators(plugin_dir / "admins.json"),
        )


def load_administrators(path: Path) -> tuple[Administrator, ...]:
    if not path.is_file():
        raise ValueError(f"管理员配置不存在：{path}")
    raw_text = path.read_text(encoding="utf-8")
    if ENV_REFERENCE_PATTERN.search(raw_text):
        raise ValueError(f"{path} 不允许引用环境变量，请直接填写 user_openid")
    data = json.loads(raw_text)
    records = data.get("admins", [])
    if not isinstance(records, list):
        raise ValueError("admins.json 的 admins 必须是列表")
    administrators: list[Administrator] = []
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ValueError(f"admins 第 {index} 项必须是对象")
        openid = str(record.get("openid") or "").strip()
        if not OPENID_PATTERN.fullmatch(openid):
            logger.warning("已跳过 admins 第 %s 项：openid 无效", index)
            continue
        administrators.append(
            Administrator(str(record.get("name") or f"管理员-{index}"), openid)
        )
    return tuple(administrators)


class FnosMonitorPlugin(BotPlugin):
    commands = (
        PluginCommand(
            name="飞牛状态",
            description="查看飞牛系统、CPU、内存、硬盘和 UPS 状态",
            scopes=("c2c",),
            only_admin=True,
        ),
    )

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self.settings = FnosPluginSettings.load(self.plugin_dir)
        self.gateway = FnosGateway(
            endpoint=self.settings.endpoint,
            username=self.settings.username,
            password=self.settings.password,
            token=self.settings.token,
            long_token=self.settings.long_token,
            secret=self.settings.secret,
            use_ssl=self.settings.use_ssl,
            skip_ssl_verify=self.settings.skip_ssl_verify,
            connect_timeout=self.settings.connect_timeout,
            request_timeout=self.settings.request_timeout,
        )
        self.state = UpsStateStore(self.settings.state_file)
        self.client: Any = None
        self.task: Optional[asyncio.Task] = None
        self.host_name = "飞牛 NAS"

    async def start(self, client: Any) -> None:
        self.client = client
        if not self.settings.enabled:
            logger.info("飞牛系统监控插件已在 config.env 中停用")
            return
        if not self.settings.administrators:
            logger.warning("飞牛系统监控未启动：admins.json 中没有有效管理员")
            return
        if self.settings.ups_monitor_enabled:
            self.task = asyncio.create_task(self._monitor_ups(), name="plugin-fnos-ups")
        logger.info("飞牛系统监控插件已启动")

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None
        await self.gateway.close()

    async def handle_command(
        self, context: MessageContext, command: PluginCommand
    ) -> Optional[str]:
        author = getattr(context.message, "author", None)
        openid = str(getattr(author, "user_openid", "") or "")
        allowed = {administrator.openid for administrator in self.settings.administrators}
        if openid not in allowed:
            return "你没有查看飞牛系统状态的权限。"
        if not self.settings.enabled:
            return "飞牛系统监控插件当前已停用。"
        try:
            snapshot = await self.gateway.collect_snapshot(
                include_ups=self.settings.ups_monitor_enabled
            )
            return format_snapshot(snapshot)
        except Exception as error:
            logger.exception("读取飞牛系统状态失败")
            return f"读取飞牛系统状态失败：{error}"

    async def _monitor_ups(self) -> None:
        while True:
            try:
                await self._check_ups()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("读取飞牛 UPS 状态失败，将在下次检查重试")
            await asyncio.sleep(self.settings.poll_interval)

    async def _check_ups(self) -> None:
        payload = await self.gateway.get_ups_status()
        self.host_name = self.gateway.host_name or self.host_name
        current = classify_ups_state(payload)
        if current == UpsPowerState.UNKNOWN:
            logger.warning("无法识别飞牛 UPS 状态：%s", payload)
            return

        for administrator in self.settings.administrators:
            previous = self.state.get(administrator.openid)
            message = ups_transition_message(
                previous,
                current,
                self.settings.notify_on_recovery,
                self.host_name,
            )
            if message:
                await self.client.api.post_c2c_message(
                    openid=administrator.openid,
                    msg_type=0,
                    content=message,
                )
                logger.info("已向管理员 %s 发送 UPS 状态提醒", administrator.name)
            self.state.set(administrator.openid, current)


Plugin = FnosMonitorPlugin
