"""
main.py - Application entry point.

Works both from source and from the PyInstaller onedir bundle.
"""

import hashlib
import logging
import os
import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

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


def main() -> None:
    _configure_logging()
    _configure_frozen_environment()

    logger = logging.getLogger(__name__)
    logger.info("Starting UIIC Surveyor Automation")

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
        logging.getLogger(__name__).exception("Fatal startup error")
        raise
