from __future__ import annotations

import asyncio
from pathlib import Path

import botpy
from qqbot_app.client import QQBotClient
from qqbot_app.config import Settings
from qqbot_app.plugin import PluginManager


def main() -> None:
    settings = Settings.load()
    plugin_manager = PluginManager(Path(__file__).parent / "plugins")
    plugin_manager.load()
    # qq-botpy 1.2.1 expects a current loop, which Python 3.14 no longer creates.
    asyncio.set_event_loop(asyncio.new_event_loop())
    intents = botpy.Intents(
        public_messages=True,
        public_guild_messages=True,
    )
    client = QQBotClient(
        settings=settings,
        plugin_manager=plugin_manager,
        intents=intents,
    )
    client.run(
        appid=settings.app_id,
        secret=settings.app_secret,
    )


if __name__ == "__main__":
    main()
