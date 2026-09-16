from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from .monitor import Commit, display_time


DEFAULT_TEMPLATE_PATH = Path(__file__).with_name("template.html")
TEMPLATE_FIELDS = {
    "{{REPOSITORY}}": lambda commit: commit.repository,
    "{{TITLE}}": lambda commit: commit.title,
    "{{AUTHOR}}": lambda commit: commit.author,
    "{{SHA}}": lambda commit: commit.sha[:7],
    "{{TIMESTAMP}}": lambda commit: display_time(commit.committed_at) or "刚刚",
}


def build_commit_html(
    commit: Commit, template_path: Path = DEFAULT_TEMPLATE_PATH
) -> str:
    html = template_path.read_text(encoding="utf-8")
    for placeholder, get_value in TEMPLATE_FIELDS.items():
        html = html.replace(placeholder, escape(get_value(commit)))
    return html


class CommitCardRenderer:
    def __init__(
        self, browser_channel: str, browser_executable: str = ""
    ):
        self.browser_channel = browser_channel
        self.browser_executable = browser_executable
        self._playwright: Any = None
        self._browser: Any = None

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        launch_options: dict[str, Any] = {"headless": True}
        if self.browser_executable:
            launch_options["executable_path"] = self.browser_executable
            launch_options["args"] = ["--no-sandbox"]
        elif self.browser_channel:
            launch_options["channel"] = self.browser_channel
        self._browser = await self._playwright.chromium.launch(**launch_options)

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def render(self, commit: Commit) -> bytes:
        if not self._browser:
            raise RuntimeError("截图浏览器尚未启动")
        page = await self._browser.new_page(
            viewport={"width": 960, "height": 520},
            device_scale_factor=1,
        )
        try:
            await page.set_content(build_commit_html(commit), wait_until="load")
            return await page.locator(".card").screenshot(type="png")
        finally:
            await page.close()
