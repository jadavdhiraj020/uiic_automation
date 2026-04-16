"""
main.py — Application entry point
Loads stylesheet, creates QApplication and launches MainWindow.
"""
import sys
import os
import logging

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui     import QIcon

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

    # Load QSS stylesheet
    qss_path = os.path.join(os.path.dirname(__file__), "app", "ui", "styles.qss")
    if os.path.exists(qss_path):
        with open(qss_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())

    # Set app icon if available
    icon_path = os.path.join(os.path.dirname(__file__), "assets", "icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    from app.ui.main_window import MainWindow
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
