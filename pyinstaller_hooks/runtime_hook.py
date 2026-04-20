"""
PyInstaller runtime hook.

Runs BEFORE your app imports execute (critical for Playwright/Paddle/PaddleOCR).
Keeps the frozen app deterministic across machines.
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

    # 1) Playwright: force bundled browsers (so no external install needed)
    _set_if_dir("PLAYWRIGHT_BROWSERS_PATH", os.path.join(base, "playwright_browsers"))

    # 2) Writable locations (avoid writing into _MEIPASS)
    user_base = _user_data_base()
    os.makedirs(os.path.join(user_base, "config"), exist_ok=True)
    os.makedirs(os.path.join(user_base, "logs"), exist_ok=True)

    # 3) PaddleOCR: steer any downloads/cache to user data if the library tries.
    # (Your captcha solver already points directly at bundled models when present.)
    os.environ.setdefault("PADDLEOCR_HOME", os.path.join(user_base, ".paddleocr"))

