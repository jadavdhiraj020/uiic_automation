# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the UIIC Surveyor Automation Windows EXE.

Key stability choices:
- onedir build for fast startup and easier native dependency handling
- repo-local bundled runtime dependencies for Playwright and PaddleOCR
- explicit native DLL search paths via runtime hooks
- broad runtime coverage for PaddleOCR and related native/scientific packages
"""

from __future__ import annotations

import os
import site
import warnings
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


APP_NAME = "UIIC_Surveyor_Automation"
PROJECT_ROOT = Path.cwd()
HOOKS_DIR = PROJECT_ROOT / "pyinstaller_hooks"
SITE_PACKAGES = Path(site.getsitepackages()[-1])
BUILD_ASSETS = PROJECT_ROOT / "build_assets"
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", ""))

warnings.filterwarnings(
    "ignore",
    message=r"The numpy\.array_api submodule is still experimental\..*",
    category=UserWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"invalid escape sequence.*",
    category=SyntaxWarning,
)


def first_existing(*paths: Path) -> Path | None:
    for path in paths:
        if path and path.exists():
            return path
    return None


def add_package(name: str, datas: list, binaries: list, hiddenimports: list) -> None:
    try:
        package_datas, package_binaries, package_hidden = collect_all(
            name,
            filter_submodules=is_runtime_submodule,
            exclude_datas=PACKAGE_DATA_EXCLUDES,
        )
        datas.extend(package_datas)
        binaries.extend(package_binaries)
        hiddenimports.extend(package_hidden)
    except Exception as exc:
        print(f"[spec] collect_all skipped for {name}: {exc}")


def add_directory(datas: list, source: Path, destination: str) -> None:
    if source.exists():
        datas.append((str(source), destination))


def dedupe_pairs(items: list[tuple]) -> list[tuple]:
    deduped: list[tuple] = []
    seen: set[tuple] = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


PACKAGE_DATA_EXCLUDES = [
    "**/tests/**",
    "**/test/**",
    "**/testing/**",
    "**/bench/**",
    "**/benchmarks/**",
    "**/examples/**",
    "**/docs/**",
]


def is_runtime_submodule(name: str) -> bool:
    lowered = name.lower()
    excluded_parts = (
        ".tests",
        ".test",
        ".testing",
        ".bench",
        ".benchmarks",
        ".examples",
        ".docs",
        ".conftest",
        "paddleocr.ppstructure",
        "paddleocr.ppocr.postprocess.pse_postprocess",
        "scipy._lib.array_api_compat.torch",
        "scipy._lib.array_api_compat.dask",
        "scipy._lib.array_api_compat.cupy",
        "pandas.core._numba",
    )
    if any(part in lowered for part in excluded_parts):
        return False

    tail = lowered.rsplit(".", 1)[-1]
    return tail not in {
        "tests",
        "test",
        "testing",
        "bench",
        "benchmarks",
        "examples",
        "docs",
        "conftest",
    }


datas: list[tuple] = []
binaries: list[tuple] = []
hiddenimports: list[str] = []


# Application resources.
add_directory(datas, PROJECT_ROOT / "app" / "config", "app/config")
if (PROJECT_ROOT / "app" / "ui" / "styles.qss").exists():
    datas.append((str(PROJECT_ROOT / "app" / "ui" / "styles.qss"), "app/ui"))
if (PROJECT_ROOT / "assets" / "icon.ico").exists():
    datas.append((str(PROJECT_ROOT / "assets" / "icon.ico"), "assets"))


# Build-time bundled runtime dependencies.
playwright_cache = first_existing(
    BUILD_ASSETS / "ms-playwright",
    LOCALAPPDATA / "ms-playwright",
)
if playwright_cache:
    add_directory(datas, playwright_cache, "playwright_browsers")
else:
    print("[spec] Playwright browser cache not found; the EXE will need first-run download.")

paddleocr_cache = first_existing(
    BUILD_ASSETS / "paddleocr",
    Path.home() / ".paddleocr",
)
if paddleocr_cache:
    add_directory(datas, paddleocr_cache, ".paddleocr")
else:
    print("[spec] PaddleOCR model cache not found; the EXE will need first-run download.")


# Native paddle DLLs collected explicitly into paddle/libs.
paddle_libs_dir = SITE_PACKAGES / "paddle" / "libs"
if paddle_libs_dir.exists():
    for dll_path in paddle_libs_dir.glob("*.dll"):
        binaries.append((str(dll_path), "paddle/libs"))


# Community-proven collect-all coverage for tricky packages.
for package_name in (
    "paddle",
    "paddleocr",
    "Cython",
    "numpy",
    "PIL",
    "lmdb",
    "scipy",
    "scipy.io",
    "skimage",
    "pyclipper",
    "imgaug",
    "cv2",
    "shapely",
    "playwright",
    "pdfplumber",
    "pandas",
    "openpyxl",
    "docx",
):
    add_package(package_name, datas, binaries, hiddenimports)


# Explicit hidden imports for dynamic modules and lazy imports used by the app.
hiddenimports.extend(
    collect_submodules("app")
    + [
        "PyQt6",
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "PyQt6.sip",
        "playwright.async_api",
        "playwright.sync_api",
        "pyee",
        "greenlet",
        "openpyxl",
        "xlrd",
        "pdfplumber",
        "pandas",
        "numpy",
        "PIL",
        "cv2",
        "paddle",
        "paddle.base",
        "paddle.dataset",
        "paddle.distributed",
        "paddle.framework",
        "paddle.io",
        "paddle.nn",
        "paddle.optimizer",
        "paddle.utils",
        "paddle.vision",
        "paddleocr",
        "paddleocr.paddleocr",
        "paddleocr.ppocr",
        "paddleocr.ppocr.data",
        "paddleocr.ppocr.modeling",
        "paddleocr.ppocr.postprocess",
        "paddleocr.ppocr.utils",
        "lmdb",
        "scipy",
        "scipy.io",
        "skimage",
        "skimage.morphology",
        "imgaug",
        "pyclipper",
        "shapely",
        "requests",
        "sniffio",
        "six",
        "Cython",
        "setuptools",
        "docx",
    ]
)


datas = dedupe_pairs(datas)
binaries = dedupe_pairs(binaries)
hiddenimports = sorted(set(hiddenimports))


runtime_hooks = [
    str(PROJECT_ROOT / "pyinstaller_hooks" / "runtime_hook.py"),
    str(PROJECT_ROOT / "runtime_hook_paddle.py"),
]


a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(HOOKS_DIR)],
    hooksconfig={},
    runtime_hooks=runtime_hooks,
    excludes=[
        "IPython",
        "jupyter",
        "matplotlib",
        "notebook",
        "pytest",
        "sphinx",
        "tkinter",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(PROJECT_ROOT / "assets" / "icon.ico") if (PROJECT_ROOT / "assets" / "icon.ico").exists() else None,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
