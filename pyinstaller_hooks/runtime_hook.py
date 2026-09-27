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

    # Register ONNX Runtime C++ DLL directory
    ort_capi = os.path.join(base, "onnxruntime", "capi")
    if os.path.isdir(ort_capi):
        os.environ["PATH"] = ort_capi + os.pathsep + os.environ.get("PATH", "")
        try:
            os.add_dll_directory(ort_capi)
        except (OSError, AttributeError):
            pass

    os.environ.setdefault("PADDLE_HOME", os.path.join(user_base, ".paddle"))

    # Bundled RapidOCR or legacy PaddleOCR models handling
    bundled_paddleocr = os.path.join(base, ".paddleocr")
    bundled_rapidocr = os.path.join(base, "rapidocr_onnxruntime")
    if os.path.isdir(bundled_paddleocr):
        os.environ["PADDLEOCR_HOME"] = bundled_paddleocr
    elif not os.path.isdir(bundled_rapidocr):
        os.environ.setdefault("PADDLEOCR_HOME", os.path.join(user_base, ".paddleocr"))
    os.environ.setdefault("XDG_CACHE_HOME", os.path.join(user_base, "cache"))



    pywin32_gen = os.path.join(user_base, "cache", "win32com_gen_py")
    os.makedirs(pywin32_gen, exist_ok=True)
    # GEN_PY_DIR is the env var that win32com.client.gencache reads to locate
    # its writable generated-type cache directory.  Without this the cache
    # defaults to a path inside _MEIPASS (read-only in a frozen EXE), which
    # causes COM dispatch to fall back to slow late-binding and may raise
    # PermissionError on some machines.
    # PYWIN32_CACHE_DIR is kept for forward-compatibility with future pywin32 versions.
    os.environ["GEN_PY_DIR"] = pywin32_gen
    os.environ.setdefault("PYWIN32_CACHE_DIR", pywin32_gen)
