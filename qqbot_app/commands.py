from __future__ import annotations

import random
import re
from datetime import datetime
from typing import Any


EMOJIS = ("😊", "😂", "🥳", "😎", "🤖", "✨", "👍", "❤️")

COMMON_PANEL_COMMANDS: list[dict[str, Any]] = [
    {"type": "command", "name": "虚拟", "desc": "给管理者发送你好", "only_admin": False},
    {"type": "command", "name": "帮助", "desc": "查看机器人指令", "only_admin": False},
    {"type": "command", "name": "状态", "desc": "检查机器人状态", "only_admin": False},
    {"type": "command", "name": "你好", "desc": "发送带表情的问候", "only_admin": False},
    {"type": "command", "name": "表情", "desc": "随机发送一个表情", "only_admin": False},
    {"type": "command", "name": "图片", "desc": "发送机器人头像", "only_admin": False},
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
            "/状态 - 检查机器人状态\n"
            "/虚拟 - 给管理者发送你好\n"
            "/你好 - 发送问候\n"
            "/表情 - 随机发送表情\n"
            "/图片 - 发送机器人头像\n"
            "/本群ID - 在群聊中查看 group_openid\n"
            "/我的ID - 在单聊中查看 user_openid"
        )
        if plugin_help:
            help_text += "\n" + "\n".join(plugin_help)
        return help_text

    if command in {"/状态", "/ping", "状态", "ping"}:
        now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        return f"机器人运行正常\n服务器时间：{now}"
    if command in {"/你好", "你好"}:
        return "你好 👋"
    if command in {"/表情", "表情"}:
        return random.choice(EMOJIS)
    if not command:
        return "我在线。发送 /帮助 查看可用指令。"
    return f"收到：{command}"
