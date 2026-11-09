# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the standalone Owner Edition license key generator
(UIIC_License_Generator.exe).

Key design choices:
- onedir + console=False (zero terminal window, fast startup)
- bundles ONLY GUI + Ed25519 signing/DPAPI/AES-GCM vault modules
- excludes all Playwright, RapidOCR, ONNX, Excel/PDF automation, and dev CLI modules
- built cleanly in CI and shared privately with the software owner (never in public Releases)
"""

from __future__ import annotations

import warnings
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


APP_NAME = "UIIC_License_Generator"
PROJECT_ROOT = Path.cwd()

warnings.filterwarnings(
    "ignore",
    message=r"invalid escape sequence.*",
    category=SyntaxWarning,
)

PACKAGE_DATA_EXCLUDES = [
    "**/tests/**",
    "**/test/**",
    "**/testing/**",
    "**/examples/**",
    "**/docs/**",
]

datas: list[tuple] = []
binaries: list[tuple] = []
hiddenimports: list[str] = []

if (PROJECT_ROOT / "assets" / "icon.ico").exists():
    datas.append((str(PROJECT_ROOT / "assets" / "icon.ico"), "assets"))

try:
    c_datas, c_binaries, c_hidden = collect_all(
        "cryptography",
        exclude_datas=PACKAGE_DATA_EXCLUDES,
    )
    datas.extend(c_datas)
    binaries.extend(c_binaries)
    hiddenimports.extend(c_hidden)
except Exception as exc:
    print(f"[spec] collect_all skipped for cryptography: {exc}")

hiddenimports.extend(
    [
        "PyQt6",
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "PyQt6.sip",
        "cryptography",
        "cryptography.exceptions",
        "cryptography.hazmat.primitives.asymmetric.ed25519",
        "cryptography.hazmat.primitives.ciphers.aead",
        "cryptography.hazmat.primitives.kdf.scrypt",
        "cryptography.hazmat.primitives.serialization",
        "app",
        "app.utils",
        "app.licensing",
        "app.licensing.public_key",
        "app.licensing.fingerprint",
        "app.licensing.codec",
        "app.licensing.verifier",
        "tools",
        "tools.owner_vault",
        "tools.owner_generator_app",
    ]
)

hiddenimports = sorted(set(hiddenimports))

a = Analysis(
    [str(PROJECT_ROOT / "tools" / "owner_generator_app.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "IPython",
        "jupyter",
        "matplotlib",
        "notebook",
        "pytest",
        "sphinx",
        "tkinter",
        "playwright",
        "pyee",
        "greenlet",
        "rapidocr_onnxruntime",
        "onnxruntime",
        "paddle",
        "paddleocr",
        "Cython",
        "numpy",
        "cv2",
        "PIL",
        "pandas",
        "openpyxl",
        "xlrd",
        "pdfplumber",
        "pypdfium2",
        "pdfminer",
        "docx",
        "win32com",
        "rapidfuzz",
        "fonttools",
        "scipy",
        "skimage",
        "albumentations",
        "albucore",
        "imgaug",
        "lmdb",
        "app.automation",
        "app.data",
        "app.portals",
        "app.ui",
        "app.web_sync",
        "tools.license_generator",
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
