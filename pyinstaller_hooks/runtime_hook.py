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


def _prepend_path(path: str) -> None:
    if not path or not os.path.isdir(path):
        return
    parts = os.environ.get("PATH", "").split(os.pathsep)
    norm_path = os.path.normcase(os.path.normpath(path))
    if norm_path not in {os.path.normcase(os.path.normpath(p)) for p in parts if p}:
        os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")


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

    # Prefer bundled models shipped in _internal/.paddleocr (offline-first).
    # Only fall back to user's AppData if bundled models are absent.
    bundled_paddleocr = os.path.join(base, ".paddleocr")
    _required_model_trees = ("whl/det", "whl/rec", "whl/cls")
    if os.path.isdir(bundled_paddleocr):
        _missing = [t for t in _required_model_trees
                    if not os.path.isdir(os.path.join(bundled_paddleocr, t.replace("/", os.sep)))]
        if _missing:
            import sys as _sys
            print(
                f"[runtime_hook] WARNING: Bundled .paddleocr is incomplete — "
                f"missing: {', '.join(_missing)}. CAPTCHA OCR may fail.",
                file=_sys.stderr,
            )
        os.environ["PADDLEOCR_HOME"] = bundled_paddleocr
    else:
        import sys as _sys
        print(
            "[runtime_hook] WARNING: Bundled .paddleocr not found. "
            "Falling back to user cache. CAPTCHA OCR will fail if models "
            "are not pre-cached in AppData.",
            file=_sys.stderr,
        )
        os.environ.setdefault("PADDLEOCR_HOME", os.path.join(user_base, ".paddleocr"))
    os.environ.setdefault("XDG_CACHE_HOME", os.path.join(user_base, "cache"))

    bundled_libreoffice = os.path.join(base, "LibreOffice")
    bundled_soffice = os.path.join(bundled_libreoffice, "program", "soffice.exe")
    if os.path.isfile(bundled_soffice):
        os.environ["UIIC_BUNDLED_LIBREOFFICE"] = bundled_libreoffice
        os.environ["UIIC_BUNDLED_SOFFICE"] = bundled_soffice
        _prepend_path(os.path.dirname(bundled_soffice))

    pywin32_gen = os.path.join(user_base, "cache", "win32com_gen_py")
    os.makedirs(pywin32_gen, exist_ok=True)
    os.environ.setdefault("PYWIN32_CACHE_DIR", pywin32_gen)
