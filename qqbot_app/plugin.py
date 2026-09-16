from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import re
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from botpy import logging

from .commands import normalize_content


logger = logging.get_logger()
PLUGIN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
VALID_SCOPES = frozenset({"c2c", "group", "channel"})


@dataclass(frozen=True)
class PluginMetadata:
    plugin_id: str
    name: str
    version: str
    description: str
    entrypoint: str


@dataclass(frozen=True)
class PluginCommand:
    name: str
    description: str
    scopes: tuple[str, ...] = ("c2c", "group", "channel")
    aliases: tuple[str, ...] = ()
    only_admin: bool = False

    def __post_init__(self) -> None:
        if not self.name or any(scope not in VALID_SCOPES for scope in self.scopes):
            raise ValueError(f"无效的插件指令：{self.name}")

    def matches(self, content: str) -> bool:
        value = normalize_content(content).removeprefix("/")
        return value in (self.name, *self.aliases)

    def panel_item(self) -> dict[str, Any]:
        return {
            "type": "command",
            "name": self.name,
            "desc": self.description,
            "only_admin": self.only_admin,
        }


@dataclass(frozen=True)
class MessageContext:
    client: Any
    message: Any
    scope: str
    content: str


class BotPlugin:
    """All plugins inherit this class and live entirely inside their plugin directory."""

    commands: tuple[PluginCommand, ...] = ()

    def __init__(self, plugin_dir: Path, metadata: PluginMetadata):
        self.plugin_dir = plugin_dir
        self.metadata = metadata

    async def start(self, client: Any) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def handle_command(
        self, context: MessageContext, command: PluginCommand
    ) -> Optional[str]:
        return None

    async def on_message(self, context: MessageContext) -> Optional[str]:
        return None

    def help_lines(self, scope: str) -> tuple[str, ...]:
        return tuple(
            f"/{command.name} - {command.description}"
            for command in self.commands
            if scope in command.scopes
        )


class PluginManager:
    def __init__(self, plugins_dir: Path):
        self.plugins_dir = plugins_dir.resolve()
        self.plugins: list[BotPlugin] = []
        self._command_owners: dict[tuple[str, str], BotPlugin] = {}
        self._started = False

    def load(self) -> None:
        self.plugins.clear()
        self._command_owners.clear()
        if not self.plugins_dir.exists():
            logger.info("插件目录不存在：%s", self.plugins_dir)
            return

        for directory in sorted(self.plugins_dir.iterdir()):
            manifest_path = directory / "plugin.json"
            if not directory.is_dir() or not manifest_path.is_file():
                continue
            try:
                manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest_data.get("enabled", True) is False:
                    logger.info("插件已停用：%s", directory.name)
                    continue
                plugin = self._load_one(directory, manifest_path)
                self._register_commands(plugin)
                self.plugins.append(plugin)
                logger.info(
                    "已加载插件 %s v%s", plugin.metadata.name, plugin.metadata.version
                )
            except Exception:
                logger.exception("插件加载失败：%s", directory.name)

    def _load_one(self, directory: Path, manifest_path: Path) -> BotPlugin:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        plugin_id = str(data.get("id", "")).strip()
        if not PLUGIN_ID_PATTERN.fullmatch(plugin_id):
            raise ValueError("plugin.json 的 id 只能包含小写字母、数字、下划线和连字符")

        entrypoint = str(data.get("entrypoint", "plugin.py:Plugin"))
        module_file, separator, class_name = entrypoint.partition(":")
        if not separator or not class_name:
            raise ValueError("entrypoint 格式应为 文件.py:类名")

        entry_path = (directory / module_file).resolve()
        if directory.resolve() not in entry_path.parents or not entry_path.is_file():
            raise ValueError("插件入口文件不存在或超出插件目录")

        metadata = PluginMetadata(
            plugin_id=plugin_id,
            name=str(data.get("name") or plugin_id),
            version=str(data.get("version") or "0.0.0"),
            description=str(data.get("description") or ""),
            entrypoint=entrypoint,
        )
        module = self._load_module(directory, entry_path, plugin_id)
        plugin_class = getattr(module, class_name)
        if not isinstance(plugin_class, type) or not issubclass(plugin_class, BotPlugin):
            raise TypeError(f"{class_name} 必须继承 BotPlugin")
        return plugin_class(plugin_dir=directory, metadata=metadata)

    @staticmethod
    def _load_module(directory: Path, entry_path: Path, plugin_id: str) -> types.ModuleType:
        digest = hashlib.sha1(str(directory).encode("utf-8")).hexdigest()[:10]
        package_name = f"_qqbot_plugin_{plugin_id.replace('-', '_')}_{digest}"
        package = types.ModuleType(package_name)
        package.__path__ = [str(directory)]
        package.__package__ = package_name
        sys.modules[package_name] = package

        module_name = f"{package_name}.{entry_path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, entry_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法读取插件入口：{entry_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def _register_commands(self, plugin: BotPlugin) -> None:
        for command in plugin.commands:
            for scope in command.scopes:
                for name in (command.name, *command.aliases):
                    key = (scope, name)
                    owner = self._command_owners.get(key)
                    if owner:
                        raise ValueError(
                            f"指令 /{name} 与插件 {owner.metadata.plugin_id} 冲突"
                        )
                    self._command_owners[key] = plugin

    async def start(self, client: Any) -> None:
        if self._started:
            return
        self._started = True
        for plugin in self.plugins:
            try:
                await plugin.start(client)
            except Exception:
                logger.exception("插件启动失败：%s", plugin.metadata.plugin_id)

    async def stop(self) -> None:
        if not self._started:
            return
        for plugin in reversed(self.plugins):
            try:
                await plugin.stop()
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("插件停止失败：%s", plugin.metadata.plugin_id)
        self._started = False

    async def dispatch(self, context: MessageContext) -> Optional[str]:
        normalized = normalize_content(context.content).removeprefix("/")
        owner = self._command_owners.get((context.scope, normalized))
        if owner:
            command = next(
                item for item in owner.commands if item.matches(context.content)
            )
            try:
                return await owner.handle_command(context, command)
            except Exception:
                logger.exception("插件指令执行失败：%s", owner.metadata.plugin_id)
                return f"插件 {owner.metadata.name} 执行失败，请查看服务日志。"

        for plugin in self.plugins:
            try:
                response = await plugin.on_message(context)
            except Exception:
                logger.exception("插件消息事件执行失败：%s", plugin.metadata.plugin_id)
                continue
            if response is not None:
                return response
        return None

    def panel_commands(self, scope: str) -> list[dict[str, Any]]:
        return [
            command.panel_item()
            for plugin in self.plugins
            for command in plugin.commands
            if scope in command.scopes
        ]

    def help_lines(self, scope: str) -> tuple[str, ...]:
        return tuple(
            line
            for plugin in self.plugins
            for line in plugin.help_lines(scope)
        )

    def summary(self) -> str:
        if not self.plugins:
            return "未加载插件"
        return "、".join(
            f"{plugin.metadata.name} v{plugin.metadata.version}"
            for plugin in self.plugins
        )
