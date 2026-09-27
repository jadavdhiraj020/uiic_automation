"""
Verify the PyInstaller onedir bundle has the production runtime resources.

This is intentionally static: it catches missing bundled files before release
without depending on a GUI display or a developer machine cache.

Exits 0 on success, 1 on any missing resource.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


APP_NAME = "UIIC_Surveyor_Automation"
REQUIRED_JSON = ("settings.json", "field_mapping.json", "doc_mapping.json", "automation_defaults.json")
REQUIRED_PORTALS = ("uiic", "newindia", "oic")
MIN_QSS_BYTES = 1024

_PYWIN32_DLL_PATTERNS = ("pythoncom*.dll", "pywintypes*.dll")


def _resource_root(dist_dir: Path) -> Path:
    internal = dist_dir / "_internal"
    return internal if internal.is_dir() else dist_dir


def _require_file(path: Path, errors: list[str]) -> None:
    if not path.is_file():
        errors.append(f"missing file: {path}")


def _require_nonempty_file(path: Path, errors: list[str], *, min_bytes: int = 1) -> bool:
    if not path.is_file():
        errors.append(f"missing file: {path}")
        return False
    size = path.stat().st_size
    if size < min_bytes:
        errors.append(f"file too small: {path} ({size} bytes, expected >= {min_bytes})")
        return False
    return True


def _require_dir(path: Path, errors: list[str]) -> None:
    if not path.is_dir():
        errors.append(f"missing directory: {path}")


def _has_child_matching(path: Path, prefix: str) -> bool:
    return path.is_dir() and any(
        child.name.lower().startswith(prefix) for child in path.iterdir()
    )


def verify(dist_dir: Path) -> list[str]:
    errors: list[str] = []
    root = _resource_root(dist_dir)
    checks: list[tuple[str, bool]] = []   # (description, passed)

    # ── EXE ──────────────────────────────────────────────────────────────────
    exe = dist_dir / f"{APP_NAME}.exe"
    ok = exe.is_file()
    checks.append((f"EXE: {exe.name}", ok))
    if not ok:
        errors.append(f"missing file: {exe}")

    # ── Legacy shared config JSONs ────────────────────────────────────────────
    for name in REQUIRED_JSON:
        path = root / "app" / "config" / name
        ok = _require_nonempty_file(path, errors)
        checks.append((f"shared config: {name}", ok))

    # ── Portal-specific config JSONs (UIIC + New India) ───────────────────────
    for portal_id in REQUIRED_PORTALS:
        for name in REQUIRED_JSON:
            path = root / "app" / "portals" / portal_id / "config" / name
            ok = _require_nonempty_file(path, errors)
            checks.append((f"{portal_id} config: {name}", ok))

    # ── UI stylesheet ─────────────────────────────────────────────────────────
    qss = root / "app" / "ui" / "styles.qss"
    ok = _require_nonempty_file(qss, errors, min_bytes=MIN_QSS_BYTES)
    checks.append((f"UI: styles.qss >= {MIN_QSS_BYTES} bytes", ok))

    # ── App icon (optional warning only) ─────────────────────────────────────
    icon = root / "assets" / "icon.ico"
    if not icon.is_file():
        print(f"  [WARN] optional app icon not bundled: {icon}")

    # ── Playwright Chromium ───────────────────────────────────────────────────
    browsers = root / "playwright_browsers"
    has_browsers = browsers.is_dir()
    checks.append(("Playwright: browsers dir", has_browsers))
    if not has_browsers:
        errors.append(f"missing directory: {browsers}")
    else:
        has_chromium = _has_child_matching(browsers, "chromium")
        checks.append(("Playwright: chromium payload", has_chromium))
        if not has_chromium:
            errors.append(f"missing Playwright Chromium payload under: {browsers}")

    # ── RapidOCR & ONNX Runtime — model and DLL check ────────────────────────
    rapidocr_models = root / "rapidocr_onnxruntime" / "models"
    has_rapidocr = rapidocr_models.is_dir()
    checks.append(("RapidOCR: models dir", has_rapidocr))
    if not has_rapidocr:
        errors.append(f"missing directory: {rapidocr_models}")
    else:
        rec_model = rapidocr_models / "ch_PP-OCRv4_rec_infer.onnx"
        has_rec = rec_model.is_file()
        checks.append(("RapidOCR: PP-OCRv4 rec model", has_rec))
        if not has_rec:
            errors.append(f"missing RapidOCR model: {rec_model}")

    ort_capi = root / "onnxruntime" / "capi"
    has_ort_capi = ort_capi.is_dir()
    checks.append(("ONNX Runtime: capi dir", has_ort_capi))
    if not has_ort_capi:
        errors.append(f"missing directory: {ort_capi}")
    else:
        ort_dll = ort_capi / "onnxruntime.dll"
        has_dll = ort_dll.is_file()
        checks.append(("ONNX Runtime: onnxruntime.dll", has_dll))
        if not has_dll:
            errors.append(f"missing ONNX Runtime DLL: {ort_dll}")



    # ── pywin32 — Excel COM support ──────────────────────────────────────────
    for pattern in _PYWIN32_DLL_PATTERNS:
        matches = list(root.rglob(pattern))
        ok = bool(matches)
        checks.append((f"pywin32: bundled {pattern}", ok))
        if not ok:
            errors.append(
                f"missing pywin32 runtime DLL matching {pattern} under: {root}\n"
                "  (Excel COM PDF export will be unavailable in the EXE)"
            )

    # ── Python package structure — catches missing __init__.py bugs ───────────
    # In PyInstaller onedir mode, pure-Python packages from the app source are
    # compiled into the PYZ archive (not as visible directories). However, when
    # collect_submodules() picks them up, PyInstaller records them.  The most
    # reliable CI-time check is to inspect the Analysis object output — but since
    # we run this AFTER the build, we check the _internal tree for package
    # namespace markers OR verify the EXE itself can import key modules.
    #
    # Practical approach: verify that the dist directory structure is consistent
    # by checking for the presence of known non-Python bundled directories.
    # For Python modules, we check that critical source dirs weren't silently
    # excluded by confirming collect_submodules would have found them (via
    # presence of __init__.py in the SOURCE — not in dist, since pyc files
    # are archived). We surface a WARNING if the source package marker is absent.
    _REQUIRED_APP_PACKAGES = [
        # (source-relative path, human label)
        ("app/portals/newindia/automation/__init__.py",
         "app.portals.newindia.automation package marker"),
        ("app/portals/newindia/__init__.py",
         "app.portals.newindia package marker"),
        ("app/ui/components/__init__.py",
         "app.ui.components package marker"),
        # ── OIC portal — added for EXE vs local parity ──────────────────────
        ("app/portals/oic/__init__.py",
         "app.portals.oic package marker"),
        ("app/portals/oic/automation/__init__.py",
         "app.portals.oic.automation package marker"),
        # ── app.data — Excel extraction and OIC assessment generation ────────
        ("app/data/__init__.py",
         "app.data package marker (OIC Excel extractor + assessment generator)"),
        ("app/automation/services/__init__.py",
         "app.automation.services package marker"),
    ]
    # The source tree is the CWD when this script runs in CI (repo root).
    import pathlib as _pathlib
    _source_root = _pathlib.Path(__file__).parent.parent  # repo root
    for rel_path, label in _REQUIRED_APP_PACKAGES:
        src = _source_root / rel_path
        if not src.is_file():
            errors.append(
                f"Source package marker missing: {rel_path}\n"
                f"  → '{label}' has no __init__.py — "
                f"PyInstaller will NOT bundle this package and its modules "
                f"will raise ModuleNotFoundError at runtime."
            )
        checks.append((f"source pkg: {rel_path}", src.is_file()))

    return errors, checks



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dist_dir",
        nargs="?",
        default=str(Path("dist") / APP_NAME),
        help="Path to the PyInstaller onedir output.",
    )
    args = parser.parse_args()

    dist_dir = Path(args.dist_dir)
    errors, checks = verify(dist_dir)

    print(f"\nPackaged runtime verification — {dist_dir}")
    print("=" * 60)
    for description, passed in checks:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {description}")
    print("=" * 60)

    if errors:
        print(f"\nVERIFICATION FAILED — {len(errors)} error(s):\n")
        for error in errors:
            print(f"  [FAIL] {error}")
        print()
        return 1

    root = _resource_root(dist_dir)
    print(f"\nVERIFICATION PASSED  ({len(checks)} checks)")
    print(f"Resource root: {root}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
