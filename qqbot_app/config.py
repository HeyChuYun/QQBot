from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"缺少环境变量 {name}，请在 .env 中填写。")
    return value


@dataclass(frozen=True)
class Settings:
    app_id: str
    app_secret: str
    admin_openid: str

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv()
        return cls(
            app_id=required_env("QQ_BOT_APPID"),
            app_secret=required_env("QQ_BOT_SECRET"),
            admin_openid=os.getenv("QQ_BOT_ADMIN_OPENID", "").strip(),
        )
