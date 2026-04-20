"""
utils.py — Shared utilities for frozen (PyInstaller) and normal execution.

Primary goals for production reliability:
  - Resolve packaged resources correctly (read-only inside the bundle)
  - Provide a guaranteed writable per-user directory (config/logs/cache)
  - Keep runtime behavior consistent across machines and install locations
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

APP_SLUG = "UIIC_Surveyor_Automation"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_base_dir() -> str:
    """
    Return the bundle root used for reading packaged resources.

    - Frozen exe: sys._MEIPASS (PyInstaller extraction dir; read-only semantics)
    - Source run: project root (directory containing `main.py`)
    """
    if is_frozen():
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_exe_dir() -> str:
    """Directory containing the executable (or project root in source mode)."""
    if is_frozen():
        return os.path.dirname(sys.executable)
    return get_base_dir()


def resource_path(*parts: str) -> str:
    """Absolute path to a packaged (read-only) resource."""
    return os.path.join(get_base_dir(), *parts)


def user_data_dir(*parts: str) -> str:
    """
    Guaranteed writable per-user directory.

    Frozen exe should never write into sys._MEIPASS.
    We default to LOCALAPPDATA\\<APP_SLUG> (portable, no admin needed).
    """
    base = (
        os.environ.get("LOCALAPPDATA")
        or os.environ.get("APPDATA")
        or str(Path.home())
    )
    return os.path.join(base, APP_SLUG, *parts)


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def settings_paths() -> dict[str, str]:
    """
    Canonical settings locations.

    - `default`: bundled default settings shipped with the app
    - `user`: writable user-specific settings (preferred at runtime)
    """
    return {
        "default": resource_path("app", "config", "settings.json"),
        "user": os.path.join(user_data_dir("config"), "settings.json"),
    }


def read_json_file(path: str) -> Optional[dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            import json

            return json.load(f)
    except Exception:
        return None


def write_json_file(path: str, data: dict[str, Any]) -> None:
    ensure_dir(os.path.dirname(path))
    import json

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_settings() -> dict[str, Any]:
    """
    Load settings with a stable precedence:
      user settings override bundled defaults.
    """
    paths = settings_paths()
    base = read_json_file(paths["default"]) or {}
    override = read_json_file(paths["user"]) or {}
    base.update(override)
    return base


def save_settings(overrides: dict[str, Any]) -> str:
    """Merge and save settings into the writable user settings file."""
    paths = settings_paths()
    current = load_settings()
    current.update(overrides or {})
    write_json_file(paths["user"], current)
    return paths["user"]
