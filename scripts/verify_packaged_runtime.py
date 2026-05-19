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
REQUIRED_JSON = ("settings.json", "field_mapping.json", "doc_mapping.json")
REQUIRED_PORTALS = ("uiic", "newindia")

# Specific PaddleOCR model subdirectory names (relative to .paddleocr root).
# These are the directories that must be present for CAPTCHA OCR to work in
# the packaged EXE. An empty or partial .paddleocr bundle will fail here.
_PADDLEOCR_REQUIRED_SUBDIRS = (
    # Text detection model
    "whl/det",
    # Text recognition model
    "whl/rec",
    # Text direction classifier model
    "whl/cls",
)


def _resource_root(dist_dir: Path) -> Path:
    internal = dist_dir / "_internal"
    return internal if internal.is_dir() else dist_dir


def _require_file(path: Path, errors: list[str]) -> None:
    if not path.is_file():
        errors.append(f"missing file: {path}")


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
        ok = path.is_file()
        checks.append((f"shared config: {name}", ok))
        if not ok:
            errors.append(f"missing file: {path}")

    # ── Portal-specific config JSONs (UIIC + New India) ───────────────────────
    for portal_id in REQUIRED_PORTALS:
        for name in REQUIRED_JSON:
            path = root / "app" / "portals" / portal_id / "config" / name
            ok = path.is_file()
            checks.append((f"{portal_id} config: {name}", ok))
            if not ok:
                errors.append(f"missing file: {path}")

    # ── UI stylesheet ─────────────────────────────────────────────────────────
    qss = root / "app" / "ui" / "styles.qss"
    ok = qss.is_file()
    checks.append(("UI: styles.qss", ok))
    if not ok:
        errors.append(f"missing file: {qss}")

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

    # ── PaddleOCR — structural model check ───────────────────────────────────
    # Verify .paddleocr exists AND contains the three required model subtrees.
    # This catches partial bundles (e.g. only det is present but rec is missing)
    # which would cause silent CAPTCHA failures at runtime.
    paddleocr_root = root / ".paddleocr"
    has_paddleocr = paddleocr_root.is_dir()
    checks.append(("PaddleOCR: root dir", has_paddleocr))
    if not has_paddleocr:
        errors.append(f"missing directory: {paddleocr_root}")
    else:
        for subdir in _PADDLEOCR_REQUIRED_SUBDIRS:
            # The exact model name inside det/rec/cls varies by version —
            # we only require that the subdir is non-empty.
            sub_path = paddleocr_root / Path(subdir)
            has_sub = sub_path.is_dir() and any(sub_path.iterdir())
            label = f"PaddleOCR: {subdir}/ (non-empty)"
            checks.append((label, has_sub))
            if not has_sub:
                errors.append(
                    f"PaddleOCR model directory missing or empty: {sub_path}\n"
                    f"  (CAPTCHA OCR will fail at runtime without this)"
                )

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
            print(f"  ✗ {error}")
        print()
        return 1

    root = _resource_root(dist_dir)
    print(f"\nVERIFICATION PASSED  ({len(checks)} checks)")
    print(f"Resource root: {root}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())


