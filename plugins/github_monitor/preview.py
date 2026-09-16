from __future__ import annotations

import asyncio
from pathlib import Path

from .monitor import Commit
from .renderer import CommitCardRenderer


async def render_preview() -> Path:
    output = Path(__file__).parent / "data" / "preview.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    renderer = CommitCardRenderer("msedge")
    await renderer.start()
    try:
        image = await renderer.render(
            Commit(
                repository="JryhDev/FireViewChemdahTheme",
                sha="270679bbb0a5c6c80fb8b89870dc2b9af4a04f25",
                title="1、测试更新",
                author="JryhDev",
                committed_at="2026-09-15T14:41:00Z",
                url="",
            )
        )
        output.write_bytes(image)
        return output
    finally:
        await renderer.stop()


if __name__ == "__main__":
    print(asyncio.run(render_preview()))
