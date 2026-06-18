"""
main.py - Application entry point.

Works both from source and from the PyInstaller onedir bundle.
"""

import hashlib
import logging
import os
import sys

from app.utils import ensure_dir, resource_path, user_data_dir


def _configure_logging() -> None:
    log_dir = ensure_dir(user_data_dir("logs"))
    startup_log = os.path.join(log_dir, "startup.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(startup_log, encoding="utf-8"),
        ],
    )


def _configure_frozen_environment() -> None:
    if not getattr(sys, "frozen", False):
        return

    playwright_browsers = resource_path("playwright_browsers")
    if os.path.isdir(playwright_browsers):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = playwright_browsers


def _preflight_check() -> list:
    """
    Verify critical bundled resources are present before the main window opens.

    Only runs in the frozen EXE (onedir build). In source runs the repository
    layout guarantees all resources are present.

    Returns a list of human-readable error strings.  Empty = OK to launch.
    """
    if not getattr(sys, "frozen", False):
        return []

    errors = []

    # ── UI stylesheet (app will render unstyled without it) ────────────────
    qss = resource_path("app", "ui", "styles.qss")
    if not os.path.isfile(qss):
        errors.append("Missing bundled UI stylesheet: app/ui/styles.qss")

    # ── Shared config JSON (needed for default settings on first run) ───────
    shared_settings = resource_path("app", "config", "settings.json")
    if not os.path.isfile(shared_settings):
        errors.append("Missing bundled shared config: app/config/settings.json")

    # ── Portal config files (all three portals must have their JSON files) ──
    _required_portals = ("uiic", "newindia", "oic")
    _required_configs = ("settings.json", "field_mapping.json",
                         "doc_mapping.json", "automation_defaults.json")
    for _portal in _required_portals:
        for _cfg in _required_configs:
            _p = resource_path("app", "portals", _portal, "config", _cfg)
            if not os.path.isfile(_p):
                errors.append(f"Missing portal config: app/portals/{_portal}/config/{_cfg}")

    # ── Playwright browsers (portal automation requires Chromium) ───────────
    browsers_dir = resource_path("playwright_browsers")
    if not os.path.isdir(browsers_dir):
        errors.append(
            "Playwright browsers not bundled.\n"
            "Portal automation (UIIC / New India / OIC) will NOT work.\n"
            "Re-run build.bat to rebuild the EXE with browsers included."
        )
    else:
        has_chromium = any(
            d.name.lower().startswith("chromium")
            for d in os.scandir(browsers_dir)
            if d.is_dir()
        )
        if not has_chromium:
            errors.append(
                "Playwright browsers directory found but contains no Chromium payload.\n"
                "Portal automation will fail on launch.\n"
                "Re-run build.bat to rebuild with a valid Chromium bundle."
            )

    # ── PaddleOCR model trees (CAPTCHA solving requires all three) ──────────
    paddle_home = resource_path(".paddleocr")
    if not os.path.isdir(paddle_home):
        errors.append(
            "PaddleOCR models not bundled (.paddleocr/ missing).\n"
            "CAPTCHA solving and document OCR will be unavailable.\n"
            "Re-run build.bat to rebuild the EXE with OCR models included."
        )
    else:
        for _model_subdir in ("whl/det", "whl/rec", "whl/cls"):
            _mp = os.path.join(paddle_home, *_model_subdir.split("/"))
            if not os.path.isdir(_mp) or not os.listdir(_mp):
                errors.append(
                    f"PaddleOCR model missing or empty: .paddleocr/{_model_subdir}/\n"
                    "CAPTCHA solving will fail. Re-run build.bat to fix."
                )

    return errors


def main() -> None:
    # Check if we are running in headless helper mode for COM/PDF rendering to avoid loading the GUI
    if len(sys.argv) > 1 and sys.argv[1] in ("--headless-pdf-render", "--headless-reinspection-render"):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
        _configure_logging()
        _configure_frozen_environment()
        
        cmd = sys.argv[1]
        if cmd == "--headless-pdf-render":
            if len(sys.argv) < 4:
                print("ERROR: Missing arguments for PDF render", file=sys.stderr)
                sys.exit(1)
            excel_path = sys.argv[2]
            pdf_path = sys.argv[3]
            try:
                from app.data.printable_excel_service import run_headless_pdf_render_com
                success = run_headless_pdf_render_com(excel_path, pdf_path)
                sys.exit(0 if success else 1)
            except Exception as e:
                print(f"ERROR: Headless PDF render failed: {e}", file=sys.stderr)
                sys.exit(1)
                
        elif cmd == "--headless-reinspection-render":
            if len(sys.argv) < 5:
                print("ERROR: Missing arguments for reinspection render", file=sys.stderr)
                sys.exit(1)
            source_excel = sys.argv[2]
            target_pdf = sys.argv[3]
            try:
                sheet_index = int(sys.argv[4])
            except ValueError:
                print(f"ERROR: Invalid sheet index {sys.argv[4]}", file=sys.stderr)
                sys.exit(1)
            try:
                from app.data.folder_scanner import run_headless_reinspection_com
                success = run_headless_reinspection_com(source_excel, target_pdf, sheet_index)
                sys.exit(0 if success else 1)
            except Exception as e:
                print(f"ERROR: Headless reinspection render failed: {e}", file=sys.stderr)
                sys.exit(1)

    _configure_logging()
    _configure_frozen_environment()

    logger = logging.getLogger(__name__)
    logger.info("Starting UIIC Surveyor Automation")

    # Import PyQt6 early inside the main try/except loop to catch startup errors.
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication, QMessageBox

    # ── Pre-flight resource check (frozen EXE only) ─────────────────────────
    # Runs before QApplication so errors are visible even if Qt fails to load.
    # In non-frozen (source) runs this is a no-op.
    _pf_errors = _preflight_check()
    if _pf_errors:
        _pf_app = QApplication.instance() or QApplication(sys.argv)
        _msg = (
            "UIIC Surveyor Automation cannot start because critical bundled "
            "resources are missing.\n\n"
            + "\n\n".join(f"• {e}" for e in _pf_errors)
            + "\n\nPlease contact your system administrator or re-run build.bat "
            "to generate a new EXE."
        )
        logger.error("Pre-flight check FAILED:\n%s", _msg)
        QMessageBox.critical(None, "UIIC — Launch Error", _msg)
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("UIIC Surveyor Automation")
    app.setOrganizationName("UIIC")

    qss_path = resource_path("app", "ui", "styles.qss")
    if os.path.exists(qss_path):
        with open(qss_path, "r", encoding="utf-8") as handle:
            qss = handle.read()
            app.setStyleSheet(qss)
        qss_hash = hashlib.sha256(qss.encode("utf-8")).hexdigest()[:12]
        logger.info(
            "Loaded stylesheet: %s (%s bytes, sha256=%s)",
            qss_path,
            len(qss.encode("utf-8")),
            qss_hash,
        )
    else:
        logger.warning("Stylesheet not found: %s", qss_path)

    icon_path = resource_path("assets", "icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    from app.ui.main_window import MainWindow

    window = MainWindow()

    # Pre-warm PaddleOCR in background so it's fully loaded by the time OCR is needed
    from app.automation.ocr_engine import warmup_ocr_background
    warmup_ocr_background()
    # NOTE: warmup_ocr_background() spawns a daemon thread. If PaddleOCR init
    # fails, the error is logged at WARNING level in startup.log by
    # ensure_ocr_ready() (see ocr_engine.py). The UI will surface the error
    # message when OCR is first required (captcha, cheque, or invoice OCR).
    # Check startup.log if captcha solving silently fails at runtime.

    window.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        logging.getLogger(__name__).exception("Fatal startup error")
        # ── crash.log fallback ───────────────────────────────────────────────
        # The EXE is built with console=False so any unhandled exception before
        # the main window opens is completely silent to the user.  Write a
        # crash.log next to the EXE so the client can report the exact error.
        # Location: same directory as the EXE (not AppData — AppData dirs may
        # not exist yet if the crash happens during very early init).
        try:
            _exe_dir = (
                os.path.dirname(sys.executable)
                if getattr(sys, "frozen", False)
                else os.path.dirname(os.path.abspath(__file__))
            )
            _crash_path = os.path.join(_exe_dir, "crash.log")
            with open(_crash_path, "w", encoding="utf-8") as _cf:
                _cf.write(
                    f"UIIC Surveyor Automation — Fatal Crash Report\n"
                    f"{'=' * 60}\n"
                    f"{traceback.format_exc()}\n"
                )
        except Exception:
            pass  # If crash.log itself fails, there is nothing more we can do.
        raise
