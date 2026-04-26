"""
PyInstaller runtime hook.

Runs before app imports execute and keeps the frozen app deterministic.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _user_data_base() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    return os.path.join(base, "UIIC_Surveyor_Automation")


def _set_if_dir(env_key: str, path: str) -> None:
    if path and os.path.isdir(path):
        os.environ[env_key] = path


if _is_frozen():
    base = getattr(sys, "_MEIPASS", "")

    bundled_browsers = os.path.join(base, "playwright_browsers")
    _set_if_dir("PLAYWRIGHT_BROWSERS_PATH", bundled_browsers)
    if os.path.isdir(bundled_browsers):
        os.environ.setdefault("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", "1")

    user_base = _user_data_base()
    os.makedirs(os.path.join(user_base, "config"), exist_ok=True)
    os.makedirs(os.path.join(user_base, "logs"), exist_ok=True)
    os.makedirs(os.path.join(user_base, "cache"), exist_ok=True)

    os.environ.setdefault("PADDLE_HOME", os.path.join(user_base, ".paddle"))
    os.environ.setdefault("PADDLEOCR_HOME", os.path.join(user_base, ".paddleocr"))
    os.environ.setdefault("XDG_CACHE_HOME", os.path.join(user_base, "cache"))
