from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path


APP_DIR = Path(__file__).parent
PLUGINS_DIR = APP_DIR / "plugins"
DEPENDENCIES_DIR = Path(
    os.getenv("PLUGIN_DEPENDENCIES_DIR", APP_DIR / ".plugin-deps")
)


def requirements_digest(files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(PLUGINS_DIR)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def install_plugin_dependencies() -> None:
    if os.getenv("PLUGIN_AUTO_INSTALL", "true").lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        print("Plugin dependency auto-install is disabled.", flush=True)
        return

    requirement_files = sorted(PLUGINS_DIR.glob("*/requirements.txt"))
    digest = requirements_digest(requirement_files)
    stamp = DEPENDENCIES_DIR / ".requirements.sha256"
    if stamp.is_file() and stamp.read_text(encoding="ascii").strip() == digest:
        print("Plugin dependencies are up to date.", flush=True)
        return

    DEPENDENCIES_DIR.mkdir(parents=True, exist_ok=True)
    for requirements in requirement_files:
        print(
            f"Installing dependencies for plugin {requirements.parent.name}...",
            flush=True,
        )
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-cache-dir",
                "--upgrade",
                "--target",
                str(DEPENDENCIES_DIR),
                "-r",
                str(requirements),
            ]
        )
    stamp.write_text(digest, encoding="ascii")


def main() -> None:
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    install_plugin_dependencies()
    command = sys.argv[1:] or [sys.executable, "bot.py"]
    os.execvpe(command[0], command, os.environ)


if __name__ == "__main__":
    main()
