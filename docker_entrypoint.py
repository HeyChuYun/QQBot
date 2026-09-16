from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit


APP_DIR = Path(__file__).parent
PLUGINS_DIR = APP_DIR / "plugins"
DEPENDENCIES_DIR = Path(
    os.getenv("PLUGIN_DEPENDENCIES_DIR", APP_DIR / ".plugin-deps")
)
PIP_CACHE_DIR = Path(os.getenv("PLUGIN_PIP_CACHE_DIR", APP_DIR / ".pip-cache"))


def requirements_digest(files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(PLUGINS_DIR)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def positive_integer(name: str, default: int) -> str:
    value = os.getenv(name, str(default)).strip()
    if not value.isdigit() or int(value) <= 0:
        raise SystemExit(f"{name} must be a positive integer.")
    return value


def pip_install_command(requirements: Path) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--prefer-binary",
        "--timeout",
        positive_integer("PLUGIN_PIP_TIMEOUT", 300),
        "--retries",
        positive_integer("PLUGIN_PIP_RETRIES", 10),
        "--cache-dir",
        str(PIP_CACHE_DIR),
        "--target",
        str(DEPENDENCIES_DIR),
    ]

    index_url = os.getenv("PLUGIN_PIP_INDEX_URL", "").strip()
    if index_url:
        command.extend(["--index-url", index_url])
    extra_index_url = os.getenv("PLUGIN_PIP_EXTRA_INDEX_URL", "").strip()
    if extra_index_url:
        command.extend(["--extra-index-url", extra_index_url])
    trusted_host = os.getenv("PLUGIN_PIP_TRUSTED_HOST", "").strip()
    if trusted_host:
        command.extend(["--trusted-host", trusted_host])

    command.extend(["-r", str(requirements)])
    return command


def pip_source_name() -> str:
    index_url = os.getenv("PLUGIN_PIP_INDEX_URL", "").strip()
    if not index_url:
        return "pip default index"
    return urlsplit(index_url).hostname or "configured index"


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
    PIP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for requirements in requirement_files:
        print(
            f"Installing dependencies for plugin {requirements.parent.name} "
            f"from {pip_source_name()}...",
            flush=True,
        )
        subprocess.check_call(pip_install_command(requirements))
    stamp.write_text(digest, encoding="ascii")


def main() -> None:
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    install_plugin_dependencies()
    command = sys.argv[1:] or [sys.executable, "bot.py"]
    os.execvpe(command[0], command, os.environ)


if __name__ == "__main__":
    main()
