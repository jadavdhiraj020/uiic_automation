"""
build.py — Build the UIIC Surveyor Automation into a standalone Windows .exe

Usage:
    uv run build.py

This script:
  1. Collects all data files (configs, QSS, icon)
  2. Locates PaddleOCR models + Playwright Chromium
  3. Runs PyInstaller with the correct options
"""

import os
import sys
import subprocess
import shutil
import glob

# ── Paths ──────────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
MAIN_SCRIPT = os.path.join(ROOT, "main.py")
DIST_DIR = os.path.join(ROOT, "dist")
BUILD_DIR = os.path.join(ROOT, "build")
ICON_PATH = os.path.join(ROOT, "assets", "icon.ico")

APP_NAME = "UIIC_Surveyor_Automation"


def find_playwright_chromium() -> str | None:
    """Find the Playwright Chromium browser directory."""
    # Playwright stores browsers in a well-known location
    import playwright
    pw_dir = os.path.dirname(playwright.__file__)
    driver_dir = os.path.join(pw_dir, "driver", "package", ".local-browsers")

    if os.path.isdir(driver_dir):
        # Look for chromium-* directory
        for entry in os.listdir(driver_dir):
            if entry.startswith("chromium"):
                full = os.path.join(driver_dir, entry)
                if os.path.isdir(full):
                    print(f"  [OK] Found Playwright Chromium: {full}")
                    return full

    # Fallback: check LOCALAPPDATA
    local_app = os.environ.get("LOCALAPPDATA", "")
    ms_pw = os.path.join(local_app, "ms-playwright")
    if os.path.isdir(ms_pw):
        for entry in os.listdir(ms_pw):
            if entry.startswith("chromium"):
                full = os.path.join(ms_pw, entry)
                if os.path.isdir(full):
                    print(f"  [OK] Found Playwright Chromium (ms-playwright): {full}")
                    return full

    return None


def find_paddleocr_models() -> str | None:
    """Find PaddleOCR model directory (~/.paddleocr)."""
    home = os.path.expanduser("~")
    model_dir = os.path.join(home, ".paddleocr")
    if os.path.isdir(model_dir):
        print(f"  [OK] Found PaddleOCR models: {model_dir}")
        return model_dir
    return None


def build():
    print("=" * 60)
    print(f"  Building {APP_NAME}")
    print("=" * 60)

    # ── Collect data files as --add-data pairs ─────────────────────────────
    datas = []

    # Config JSON files
    config_dir = os.path.join(ROOT, "app", "config")
    if os.path.isdir(config_dir):
        datas.append(f"{config_dir}{os.pathsep}app/config")
        print(f"  [OK] Config dir: {config_dir}")

    # QSS stylesheet
    qss_path = os.path.join(ROOT, "app", "ui", "styles.qss")
    if os.path.isfile(qss_path):
        datas.append(f"{qss_path}{os.pathsep}app/ui")
        print(f"  [OK] QSS stylesheet: {qss_path}")

    # App icon
    if os.path.isfile(ICON_PATH):
        datas.append(f"{ICON_PATH}{os.pathsep}assets")
        print(f"  [OK] App icon: {ICON_PATH}")

    # Playwright Chromium browser
    chromium_dir = find_playwright_chromium()
    if chromium_dir:
        # Bundle as playwright_browsers/chromium-XXXX
        dest_name = os.path.basename(chromium_dir)
        datas.append(f"{chromium_dir}{os.pathsep}playwright_browsers/{dest_name}")
    else:
        print("  ⚠️  Playwright Chromium not found! Users will need to install it separately.")

    # PaddleOCR models
    paddle_models = find_paddleocr_models()
    if paddle_models:
        datas.append(f"{paddle_models}{os.pathsep}.paddleocr")
    else:
        print("  ⚠️  PaddleOCR models not found. They'll download on first launch.")

    # ── Hidden imports ─────────────────────────────────────────────────────
    hidden_imports = [
        "PyQt6",
        "PyQt6.QtWidgets",
        "PyQt6.QtGui",
        "PyQt6.QtCore",
        "PyQt6.sip",
        "playwright",
        "playwright.async_api",
        "paddleocr",
        "paddlepaddle",
        "paddle",
        "paddle.fluid",
        "xlrd",
        "openpyxl",
        "pdfplumber",
        "PIL",
        "numpy",
        "setuptools",
        "asyncio",
        "logging",
        "json",
        "re",
        "dataclasses",
        "pathlib",
        "app",
        "app.ui",
        "app.ui.main_window",
        "app.ui.components",
        "app.ui.components.widgets",
        "app.automation",
        "app.automation.engine",
        "app.automation.login_module",
        "app.automation.navigation_module",
        "app.automation.captcha_solver",
        "app.automation.claim_assessment",
        "app.automation.claim_documents",
        "app.automation.interim_report",
        "app.automation.form_helpers",
        "app.automation.selectors",
        "app.automation.tab_utils",
        "app.data",
        "app.data.data_model",
        "app.data.excel_reader",
        "app.data.folder_scanner",
    ]

    # ── Build via spec for maximum reproducibility ─────────────────────────
    # The spec file contains the full data/binaries/hidden-import story.
    spec_path = os.path.join(ROOT, "uiic_automation.spec")
    if os.path.isfile(spec_path):
        cmd = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            f"--distpath={DIST_DIR}",
            f"--workpath={BUILD_DIR}",
            spec_path,
        ]
    else:
        # Fallback: legacy CLI build (kept for compatibility)
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm",
            "--onedir",                       # onedir = faster startup than onefile
            "--windowed",                     # no console window (GUI app)
            f"--name={APP_NAME}",
            f"--distpath={DIST_DIR}",
            f"--workpath={BUILD_DIR}",
        ]

    if not os.path.isfile(spec_path):
        # Icon
        if os.path.isfile(ICON_PATH):
            cmd.append(f"--icon={ICON_PATH}")

        # Data files
        for d in datas:
            cmd.extend(["--add-data", d])

        # Hidden imports
        for h in hidden_imports:
            cmd.extend(["--hidden-import", h])

        # Add PaddleOCR internal dir to pathex so it finds 'ppocr' and 'tools'
        import paddleocr
        paddleocr_dir = os.path.dirname(paddleocr.__file__)
        cmd.extend(["--paths", paddleocr_dir])

        # Runtime hook to set deterministic env vars in frozen mode
        hook_path = os.path.join(ROOT, "pyinstaller_hooks", "runtime_hook.py")
        if os.path.isfile(hook_path):
            cmd.extend(["--runtime-hook", hook_path])

        # Exclude unnecessary heavy packages
        excludes = [
            "matplotlib",
            "scipy",
            "pandas",
            "tkinter",
            "unittest",
            "test",
            "IPython",
            "jupyter",
            "notebook",
            "sphinx",
        ]
        for e in excludes:
            cmd.extend(["--exclude-module", e])

        cmd.append(MAIN_SCRIPT)

    print()
    print("  Running PyInstaller...")
    print(f"  Command: {' '.join(cmd[:10])}...")
    print()

    result = subprocess.run(cmd, cwd=ROOT)

    if result.returncode != 0:
        print("\n  [FAIL] Build FAILED!")
        sys.exit(1)

    exe_dir = os.path.join(DIST_DIR, APP_NAME)
    print()
    print("=" * 60)
    print(f"  [OK] Build SUCCESSFUL!")
    print(f"  Output: {exe_dir}")
    print(f"  EXE:    {os.path.join(exe_dir, APP_NAME + '.exe')}")
    print()
    print("  To distribute:")
    print(f"    1. Zip the '{APP_NAME}' folder in dist/")
    print(f"    2. Share the zip — users just run {APP_NAME}.exe")
    print("=" * 60)


if __name__ == "__main__":
    build()
