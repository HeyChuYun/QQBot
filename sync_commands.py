from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import aiohttp

from qqbot_app.commands import panel_commands
from qqbot_app.config import Settings
from qqbot_app.plugin import PluginManager


TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
API_BASE_URL = "https://api.sgroup.qq.com"
PANEL_REMARK_PREFIX = "qqbot-python-managed"

async def response_json(response: aiohttp.ClientResponse) -> dict[str, Any]:
    data = await response.json(content_type=None)
    if response.status >= 400:
        raise RuntimeError(
            f"QQ API 请求失败：HTTP {response.status}，"
            f"code={data.get('code')}，message={data.get('message')}"
        )
    return data


async def get_access_token(
    session: aiohttp.ClientSession, appid: str, secret: str
) -> str:
    async with session.post(
        TOKEN_URL,
        json={"appId": appid, "clientSecret": secret},
    ) as response:
        data = await response_json(response)

    token = data.get("access_token")
    if not token:
        raise RuntimeError("QQ API 未返回 access_token，请检查 AppID 和 AppSecret")
    return str(token)


def panel_config(
    scope: str, plugin_manager: PluginManager
) -> dict[str, Any]:
    return {
        "items": panel_commands(scope, plugin_manager.panel_commands(scope)),
        "remark": f"{PANEL_REMARK_PREFIX}-{scope}",
    }


async def sync_panel(
    session: aiohttp.ClientSession, scope: str, plugin_manager: PluginManager
) -> tuple[str, str]:
    async with session.get(
        f"{API_BASE_URL}/v2/panels",
        params={"scope": scope, "limit": 50},
    ) as response:
        data = await response_json(response)

    remark = f"{PANEL_REMARK_PREFIX}-{scope}"
    existing = next(
        (
            record
            for record in data.get("records", [])
            if record.get("panel", {}).get("remark") == remark
        ),
        None,
    )

    if existing:
        panel_id = str(existing["panel_id"])
        async with session.put(
            f"{API_BASE_URL}/v2/panels/{panel_id}",
            json={"panel": panel_config(scope, plugin_manager)},
        ) as response:
            await response_json(response)
        return "更新", panel_id

    async with session.post(
        f"{API_BASE_URL}/v2/panels",
        json={
            "scope": scope,
            "target_type": "all",
            "panel": panel_config(scope, plugin_manager),
        },
    ) as response:
        created = await response_json(response)
    return "创建", str(created["panel_id"])


async def main() -> None:
    settings = Settings.load()
    plugin_manager = PluginManager(Path(__file__).parent / "plugins")
    plugin_manager.load()

    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as token_session:
        access_token = await get_access_token(token_session, settings.app_id, settings.app_secret)

    headers = {
        "Authorization": f"QQBot {access_token}",
        "X-Union-Appid": settings.app_id,
        "Content-Type": "application/json",
    }
    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        for scope in ("c2c", "group", "channel"):
            action, panel_id = await sync_panel(session, scope, plugin_manager)
            print(f"{scope}: 已{action}指令面板 {panel_id}")


if __name__ == "__main__":
    asyncio.run(main())
