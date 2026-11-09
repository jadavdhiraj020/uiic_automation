"""PyQt6 Activation Dialog and startup gate for offline PC-locked licensing."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from app.licensing.fingerprint import FingerprintError, get_request_code
from app.licensing.public_key import is_public_key_configured
from app.licensing.verifier import (
    LicenseStatus,
    activate_from_file,
    activate_license,
    is_test_bypass_active,
    verify_stored_license,
)

logger = logging.getLogger(__name__)


class ActivationDialog(QDialog):
    """Modal blocking activation screen shown before MainWindow when PC is unlicensed."""

    def __init__(
        self,
        initial_status: LicenseStatus,
        *,
        license_path: Optional[Path] = None,
        public_key_b64: Optional[str] = None,
        current_fp: Optional[bytes] = None,
        request_code_override: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._license_path = license_path
        self._public_key_b64 = public_key_b64
        self._current_fp = current_fp
        self._activated_status: Optional[LicenseStatus] = None

        if request_code_override is not None:
            self._request_code = request_code_override
            self._fp_error = ""
        else:
            try:
                self._request_code = get_request_code()
                self._fp_error = ""
            except FingerprintError as exc:
                self._request_code = "UNAVAILABLE"
                self._fp_error = str(exc)

        self._setup_ui(initial_status)

    @property
    def activated_status(self) -> Optional[LicenseStatus]:
        return self._activated_status

    def _setup_ui(self, initial_status: LicenseStatus) -> None:
        self.setWindowTitle("Activate UIIC Surveyor Automation")
        self.setMinimumWidth(560)
        self.setModal(True)
        self.setStyleSheet(
            """
            QDialog {
                background-color: #F8FAFC;
                font-family: "Segoe UI", Arial, sans-serif;
            }
            #headerBar {
                background-color: #0F172A;
                border-radius: 10px;
            }
            #headerTitle {
                color: #FFFFFF;
                font-size: 14pt;
                font-weight: 700;
            }
            #headerSub {
                color: #94A3B8;
                font-size: 9.5pt;
            }
            #licCard {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 10px;
            }
            #stepTitle {
                color: #0F172A;
                font-size: 10.5pt;
                font-weight: 700;
            }
            #hintText {
                color: #475569;
                font-size: 9.5pt;
            }
            #codeLabel {
                background-color: #F1F5F9;
                border: 1px solid #CBD5E1;
                border-radius: 8px;
                color: #0F172A;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 16pt;
                font-weight: 700;
                letter-spacing: 1.5px;
                padding: 10px 14px;
            }
            QPlainTextEdit {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 8px;
                color: #0F172A;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 9.5pt;
                padding: 8px;
            }
            QPlainTextEdit:focus {
                border: 1.5px solid #2563EB;
            }
            QPushButton {
                border-radius: 7px;
                font-weight: 600;
                font-size: 9.5pt;
                padding: 8px 16px;
            }
            #btnPrimary {
                background-color: #0F172A;
                color: #FFFFFF;
                border: none;
            }
            #btnPrimary:hover {
                background-color: #1E293B;
            }
            #btnPrimary:disabled {
                background-color: #94A3B8;
            }
            #btnSecondary {
                background-color: #F1F5F9;
                color: #0F172A;
                border: 1px solid #CBD5E1;
            }
            #btnSecondary:hover {
                background-color: #E2E8F0;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        # Header
        header = QFrame()
        header.setObjectName("headerBar")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(18, 14, 18, 14)
        hl.setSpacing(4)
        lbl_title = QLabel("Activate UIIC Surveyor Automation")
        lbl_title.setObjectName("headerTitle")
        lbl_sub = QLabel(
            "One-time offline activation locked to this PC. No internet license server required."
        )
        lbl_sub.setObjectName("headerSub")
        lbl_sub.setWordWrap(True)
        hl.addWidget(lbl_title)
        hl.addWidget(lbl_sub)
        root.addWidget(header)

        # Status banner
        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.lbl_status)

        # Step 1: Request Code
        card1 = QFrame()
        card1.setObjectName("licCard")
        c1 = QVBoxLayout(card1)
        c1.setContentsMargins(16, 14, 16, 14)
        c1.setSpacing(8)
        s1_title = QLabel("Step 1 — Copy this PC Code and send it on WhatsApp")
        s1_title.setObjectName("stepTitle")
        c1.addWidget(s1_title)

        code_row = QHBoxLayout()
        code_row.setSpacing(10)
        self.lbl_code = QLabel(self._request_code)
        self.lbl_code.setObjectName("codeLabel")
        self.lbl_code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.btn_copy = QPushButton("Copy Code")
        self.btn_copy.setObjectName("btnSecondary")
        self.btn_copy.setMinimumHeight(46)
        self.btn_copy.setEnabled(self._request_code != "UNAVAILABLE")
        self.btn_copy.clicked.connect(self._on_copy_code)
        code_row.addWidget(self.lbl_code, 1)
        code_row.addWidget(self.btn_copy)
        c1.addLayout(code_row)
        root.addWidget(card1)

        # Step 2: Paste Key or Load .lic
        card2 = QFrame()
        card2.setObjectName("licCard")
        c2 = QVBoxLayout(card2)
        c2.setContentsMargins(16, 14, 16, 14)
        c2.setSpacing(8)
        s2_title = QLabel("Step 2 — Paste your License Key (or load the .lic file)")
        s2_title.setObjectName("stepTitle")
        c2.addWidget(s2_title)

        s2_hint = QLabel(
            "Paste the key you received on WhatsApp below, OR click 'Load .lic File...' to select the license file."
        )
        s2_hint.setObjectName("hintText")
        s2_hint.setWordWrap(True)
        c2.addWidget(s2_hint)

        self.txt_key = QPlainTextEdit()
        self.txt_key.setPlaceholderText("Paste license key here (starts with UIIC1-...)...")
        self.txt_key.setFixedHeight(84)
        c2.addWidget(self.txt_key)

        file_row = QHBoxLayout()
        self.btn_load_file = QPushButton("Load .lic File...")
        self.btn_load_file.setObjectName("btnSecondary")
        self.btn_load_file.clicked.connect(self._on_load_file)
        file_row.addWidget(self.btn_load_file)
        file_row.addStretch()
        c2.addLayout(file_row)
        root.addWidget(card2)

        # Action footer
        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.btn_exit = QPushButton("Exit")
        self.btn_exit.setObjectName("btnSecondary")
        self.btn_exit.clicked.connect(self.reject)

        self.btn_activate = QPushButton("Activate Software")
        self.btn_activate.setObjectName("btnPrimary")
        self.btn_activate.setMinimumHeight(40)
        self.btn_activate.clicked.connect(self._on_activate_clicked)

        footer.addWidget(self.btn_exit)
        footer.addStretch()
        footer.addWidget(self.btn_activate)
        root.addLayout(footer)

        # Set initial status message
        if not is_public_key_configured(self._public_key_b64):
            self._set_banner(
                "Developer setup needed: Public signing key is not configured yet. "
                "Run tools/license_generator.py once to generate your keypair.",
                kind="error",
            )
            self.btn_activate.setEnabled(False)
            self.btn_load_file.setEnabled(False)
        elif self._fp_error:
            self._set_banner(
                f"Unable to inspect this PC's hardware ID: {self._fp_error}",
                kind="error",
            )
            self.btn_activate.setEnabled(False)
        elif initial_status.reason == "missing":
            self._set_banner(
                "This PC is not activated yet. Share the code above to receive your license key.",
                kind="info",
            )
        else:
            self._set_banner(initial_status.message, kind="error")

    def _set_banner(self, text: str, kind: str = "info") -> None:
        palettes = {
            "info": ("#EFF6FF", "#BFDBFE", "#1E3A8A"),
            "error": ("#FEF2F2", "#FECACA", "#991B1B"),
            "success": ("#ECFDF5", "#A7F3D0", "#065F46"),
        }
        bg, border, fg = palettes.get(kind, palettes["info"])
        self.lbl_status.setText(text)
        self.lbl_status.setStyleSheet(
            f"background-color: {bg}; border: 1px solid {border}; color: {fg}; "
            f"border-radius: 8px; padding: 10px 12px; font-size: 9.5pt; font-weight: 600;"
        )

    def _on_copy_code(self) -> None:
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(self._request_code)
        self.btn_copy.setText("Copied!")
        QTimer.singleShot(1800, lambda: self.btn_copy.setText("Copy Code"))

    def _on_load_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select License File",
            "",
            "License Files (*.lic *.txt);;All Files (*)",
        )
        if not file_path:
            return
        status = activate_from_file(
            file_path,
            license_path=self._license_path,
            public_key_b64=self._public_key_b64,
            current_fp=self._current_fp,
        )
        self._handle_activation_result(status)

    def _on_activate_clicked(self) -> None:
        raw_key = self.txt_key.toPlainText().strip()
        if not raw_key:
            self._set_banner(
                "Please paste your license key or click 'Load .lic File...'.",
                kind="error",
            )
            return
        status = activate_license(
            raw_key,
            license_path=self._license_path,
            public_key_b64=self._public_key_b64,
            current_fp=self._current_fp,
        )
        self._handle_activation_result(status)

    def _handle_activation_result(self, status: LicenseStatus) -> None:
        if status.valid:
            self._activated_status = status
            self._set_banner(
                f"Activated successfully! License {status.license_id} is now locked to this PC.",
                kind="success",
            )
            self.accept()
        else:
            self._set_banner(status.message, kind="error")


def ensure_activated_or_exit(
    app: Optional[QApplication] = None,
    *,
    force: bool = False,
    license_path: Optional[Path] = None,
    public_key_b64: Optional[str] = None,
    current_fp: Optional[bytes] = None,
) -> LicenseStatus:
    """
    Verify stored license on startup before opening MainWindow.
    If missing/invalid, displays ActivationDialog and exits cleanly if cancelled.
    """
    if not force and is_test_bypass_active():
        return LicenseStatus(
            valid=True,
            reason="pytest_bypass",
            message="Automated test environment bypass active.",
            license_id="LIC-PYTEST",
        )

    status = verify_stored_license(
        license_path=license_path,
        public_key_b64=public_key_b64,
        current_fp=current_fp,
    )
    if status.valid:
        logger.info("License verified: %s", status.license_id)
        return status

    if app is None:
        app = QApplication.instance() or QApplication(sys.argv)

    dialog = ActivationDialog(
        status,
        license_path=license_path,
        public_key_b64=public_key_b64,
        current_fp=current_fp,
    )
    if dialog.exec() == QDialog.DialogCode.Accepted and dialog.activated_status:
        return dialog.activated_status

    logger.info("Application closed at license activation prompt.")
    sys.exit(0)
