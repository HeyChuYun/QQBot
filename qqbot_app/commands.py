from __future__ import annotations

import re
from typing import Any


COMMON_PANEL_COMMANDS: list[dict[str, Any]] = [
    {"type": "command", "name": "帮助", "desc": "查看机器人指令", "only_admin": False},
]


def panel_commands(
    scope: str, plugin_commands: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    items = [dict(item) for item in COMMON_PANEL_COMMANDS]
    if scope == "c2c":
        items.append({"type": "command", "name": "我的ID", "desc": "查看自己的user_openid", "only_admin": False})
    if scope == "group":
        items.append({"type": "command", "name": "本群ID", "desc": "查看当前群的group_openid", "only_admin": False})
    items.extend(plugin_commands or [])
    return items


def normalize_content(content: str) -> str:
    """Remove a possible channel mention before matching commands."""
    return re.sub(r"^<@!?\d+>\s*", "", content).strip()


def is_command(content: str, name: str) -> bool:
    return normalize_content(content) in {name, f"/{name}"}


def build_text_reply(content: str, plugin_help: tuple[str, ...] = ()) -> str:
    command = normalize_content(content)

    if command in {"/帮助", "/help", "帮助", "help"}:
        help_text = (
            "可用指令：\n"
            "/帮助 - 查看指令\n"
            "/本群ID - 在群聊中查看 group_openid\n"
            "/我的ID - 在单聊中查看 user_openid"
        )
        if plugin_help:
            help_text += "\n" + "\n".join(plugin_help)
        return help_text

    if not command:
        return "我在线。发送 /帮助 查看可用指令。"
    return f"收到：{command}"
