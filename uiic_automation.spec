# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the UIIC Surveyor Automation Windows EXE.

Key stability choices:
- onedir build for fast startup and easier native dependency handling
- repo-local bundled runtime dependencies for Playwright, PaddleOCR, and LibreOffice
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
        if path and path.exists() and (not path.is_dir() or any(path.iterdir())):
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
        # win32com ships demos and test fixtures — exclude both to avoid
        # pulling ~30 MB of non-runtime code into the EXE bundle.
        "win32com.demos",
        "win32com.test",
        "win32com.servers",
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
        "demos",
        "servers",
    }


datas: list[tuple] = []
binaries: list[tuple] = []
hiddenimports: list[str] = []


# Application resources.
add_directory(datas, PROJECT_ROOT / "app" / "config", "app/config")
for portal_config in sorted((PROJECT_ROOT / "app" / "portals").glob("*/config")):
    portal_id = portal_config.parent.name
    add_directory(datas, portal_config, f"app/portals/{portal_id}/config")
for required_portal in ("uiic", "newindia", "oic"):
    required_config = PROJECT_ROOT / "app" / "portals" / required_portal / "config"
    if not required_config.is_dir():
        raise FileNotFoundError(f"Required portal config directory missing: {required_config}")
if (PROJECT_ROOT / "app" / "ui" / "styles.qss").exists():
    datas.append((str(PROJECT_ROOT / "app" / "ui" / "styles.qss"), "app/ui"))
else:
    raise FileNotFoundError(PROJECT_ROOT / "app" / "ui" / "styles.qss")
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

libreoffice_bundle = first_existing(
    BUILD_ASSETS / "LibreOffice",
    BUILD_ASSETS / "libreoffice",
    Path(os.environ.get("PROGRAMFILES", "")) / "LibreOffice",
    Path(os.environ.get("PROGRAMFILES(X86)", "")) / "LibreOffice",
)
if libreoffice_bundle:
    add_directory(datas, libreoffice_bundle, "LibreOffice")
    print(f"[spec] LibreOffice bundled from: {libreoffice_bundle}")
else:
    # In CI the staging step guarantees LibreOffice is in build_assets/ before
    # PyInstaller runs — if it's missing there, the build must fail hard.
    # On local developer machines LibreOffice is optional: the EXE falls back
    # gracefully to Excel COM, and devs can still iterate without it installed.
    _in_ci = os.environ.get("CI", "").lower() in ("true", "1", "yes")
    if _in_ci:
        raise FileNotFoundError(
            "LibreOffice runtime not found in CI. The 'Stage bundled LibreOffice "
            "runtime' workflow step must run before PyInstaller. "
            "Expected path: build_assets/LibreOffice/program/soffice.exe"
        )
    else:
        print(
            "[spec] WARNING: LibreOffice not found locally — bundling skipped. "
            "PDF generation will fall back to Excel COM only in the local EXE. "
            "Install LibreOffice or set build_assets/LibreOffice to bundle it."
        )


# Native paddle DLLs collected explicitly into paddle/libs.
paddle_libs_dir = SITE_PACKAGES / "paddle" / "libs"
if paddle_libs_dir.exists():
    for dll_path in paddle_libs_dir.glob("*.dll"):
        binaries.append((str(dll_path), "paddle/libs"))

# PyInstaller's pywin32 hooks usually collect these DLLs, but we keep an
# explicit pass because printable PDF export depends on COM in production.
pywin32_system32 = SITE_PACKAGES / "pywin32_system32"
if pywin32_system32.exists():
    for dll_path in pywin32_system32.glob("*.dll"):
        binaries.append((str(dll_path), "."))


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
    "pypdfium2",
    "pandas",
    "openpyxl",
    "docx",
    "win32com",
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
        "pypdfium2",
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
        "pythoncom",
        "pywintypes",
        "win32api",
        "win32com",
        "win32com.client",
        "win32com.client.dynamic",
        "win32con",
        "win32print",
        # ── New India Assurance portal — automation package ─────────────────
        # engine.py imports these lazily inside if-blocks; static analysis
        # cannot find them. List explicitly so they are always compiled in.
        "app.portals.newindia.automation",
        "app.portals.newindia.automation.login_module",
        "app.portals.newindia.automation.navigation_module",
        "app.portals.newindia.automation.quick_update_module",
        "app.portals.newindia.automation.vehicle_photo_module",
        "app.portals.newindia.automation.registration_cert_module",
        "app.portals.newindia.automation.driver_details_module",
        "app.portals.newindia.automation.fir_details_module",
        "app.portals.newindia.automation.neft_module",
        "app.portals.newindia.automation.work_approval_module",
        "app.portals.newindia.automation.claim_assessment_module",
        "app.portals.newindia.automation.document_upload_module",
        "app.portals.newindia.automation.popup_service",
        "app.portals.newindia.automation.ui_utils",
        "app.portals.newindia.automation.ocr_helper",
        "app.portals.newindia.automation.survey_fee_bill_module",
        # ── Oriental Insurance Company portal — automation package ───────────
        # engine.py imports these lazily inside if-blocks; static analysis
        # cannot find them. List explicitly so they are always compiled in.
        "app.portals.oic.automation",
        "app.portals.oic.automation.login_module",
        "app.portals.oic.automation.navigation_module",
        # NOTE: 'claim_assessment_module' kept for back-compat but the real
        # assessment module is 'assessment_of_loss_module' — both listed.
        "app.portals.oic.automation.claim_assessment_module",
        "app.portals.oic.automation.assessment_of_loss_module",
        "app.portals.oic.automation.interim_report_module",
        "app.portals.oic.automation.date_formatter",
        "app.portals.oic.automation.document_upload_module",
        "app.portals.oic.automation.popup_service",
        "app.portals.oic.automation.ui_utils",
        "app.portals.oic.automation.workflow_module",
        "app.portals.oic.automation.basic_details_module",
        "app.portals.oic.automation.claim_search_module",
        "app.portals.oic.automation.selectors",
        # ── app.data — Excel extraction and OIC assessment generation ─────────
        # These are imported at runtime by the OIC portal engine but PyInstaller
        # cannot detect them through dynamic import chains.
        "app.data",
        "app.data.oic_assessment_generator",
        "app.data.excel_parts_extractor",
        "app.data.excel_reader",
        "app.data.assessment_generator",
        "app.data.data_model",
        "app.data.folder_scanner",
        # Explicitly listed even though collect_submodules("app") should find it:
        # guards against dynamic-import-chain misses for the PDF generation path.
        "app.data.printable_excel_service",
        # ── UI service layer (lazy-imported inside main_window event handlers)
        "app.ui.services",
        # ── Automation service layer (if it contains dynamically loaded code)
        "app.automation.services",
        "app.automation.services.cheque_ocr_adapter",
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
