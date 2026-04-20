"""
main.py — Application entry point
Loads stylesheet, creates QApplication and launches MainWindow.

Works both from source (uv run main.py) and from the PyInstaller exe.
"""
import sys
import os
import logging

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui     import QIcon

# ── Frozen-exe support ─────────────────────────────────────────────────────
# When running as a PyInstaller bundle, set Playwright browser path
# to the bundled Chromium before any Playwright import occurs.
if getattr(sys, "frozen", False):
    _base = sys._MEIPASS
    _pw_browsers = os.path.join(_base, "playwright_browsers")
    if os.path.isdir(_pw_browsers):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _pw_browsers
else:
    _base = os.path.dirname(os.path.abspath(__file__))

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("UIIC Surveyor Automation")
    app.setOrganizationName("UIIC")

    # Load QSS stylesheet (works in both frozen and source mode)
    qss_path = os.path.join(_base, "app", "ui", "styles.qss")
    if os.path.exists(qss_path):
        with open(qss_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())

    # Set app icon if available
    icon_path = os.path.join(_base, "assets", "icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    from app.ui.main_window import MainWindow
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
