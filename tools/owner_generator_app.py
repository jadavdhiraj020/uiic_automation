"""
Standalone Desktop GUI for the Software Owner — UIIC License Key Generator.

Packaged into its own private Windows EXE (UIIC_License_Generator.exe, console=False)
with zero terminal windows and zero technical setup jargon.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.licensing.codec import SignedLicense, format_lic_file_content
from app.licensing.fingerprint import FingerprintError, decode_request_code, get_request_code
from app.utils import resource_path
from tools.owner_vault import OwnerVault, is_dpapi_supported


def _atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def format_owner_whatsapp_message(signed: SignedLicense, friend_name: str = "") -> str:
    who = (friend_name or "").strip()
    header_extra = f"For: {who}\n" if who else ""
    return (
        "UIIC Surveyor Automation — Activation Key\n"
        f"{header_extra}"
        f"PC Code: {signed.request_code}\n"
        f"License ID: {signed.license_id}\n\n"
        "License Key:\n"
        f"{signed.token}\n\n"
        "How to activate:\n"
        "1. Open UIIC_Surveyor_Automation.exe\n"
        "2. Copy this message (or just the UIIC1-... key) and paste it into Step 2\n"
        "3. Click 'Activate Software' (or click 'Load .lic File...' if a file was sent)"
    )


def get_owner_window_class():
    """Define OwnerGeneratorWindow lazily so non-GUI tools/tests have zero Qt dependency."""
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import (
        QApplication,
        QCheckBox,
        QDialog,
        QFileDialog,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QRadioButton,
        QStackedWidget,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )

    class _LockSettingsDialog(QDialog):
        def __init__(self, current_mode: str, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Startup Security Preference")
            self.setMinimumWidth(420)
            self.selected_mode = current_mode
            self.selected_pin = ""

            root = QVBoxLayout(self)
            root.setContentsMargins(18, 18, 18, 18)
            root.setSpacing(12)

            lbl = QLabel("Choose how this tool unlocks on startup:")
            lbl.setStyleSheet("font-weight: 700; font-size: 10pt; color: #0F172A;")
            root.addWidget(lbl)

            self.rb_auto = QRadioButton("Open automatically on this PC (Recommended)")
            self.rb_auto.setEnabled(is_dpapi_supported())
            self.rb_pin = QRadioButton("Ask for a PIN every time it opens")
            root.addWidget(self.rb_auto)
            root.addWidget(self.rb_pin)

            self.pin_box = QWidget()
            pl = QGridLayout(self.pin_box)
            pl.setContentsMargins(20, 4, 0, 4)
            pl.setSpacing(8)
            self.txt_pin = QLineEdit()
            self.txt_pin.setEchoMode(QLineEdit.EchoMode.Password)
            self.txt_pin.setPlaceholderText("New PIN (at least 4 characters)")
            self.txt_confirm = QLineEdit()
            self.txt_confirm.setEchoMode(QLineEdit.EchoMode.Password)
            self.txt_confirm.setPlaceholderText("Confirm PIN")
            pl.addWidget(QLabel("New PIN:"), 0, 0)
            pl.addWidget(self.txt_pin, 0, 1)
            pl.addWidget(QLabel("Confirm PIN:"), 1, 0)
            pl.addWidget(self.txt_confirm, 1, 1)
            root.addWidget(self.pin_box)

            self.lbl_err = QLabel()
            self.lbl_err.setWordWrap(True)
            self.lbl_err.setStyleSheet("color: #991B1B; font-weight: 600;")
            self.lbl_err.hide()
            root.addWidget(self.lbl_err)

            btns = QHBoxLayout()
            btns.addStretch()
            btn_cancel = QPushButton("Cancel")
            btn_cancel.clicked.connect(self.reject)
            btn_save = QPushButton("Save Setting")
            btn_save.setStyleSheet(
                "background-color: #0F172A; color: #FFFFFF; border-radius: 7px; padding: 7px 14px; font-weight: 600;"
            )
            btn_save.clicked.connect(self._on_save)
            btns.addWidget(btn_cancel)
            btns.addWidget(btn_save)
            root.addLayout(btns)

            if current_mode == "pin" or not is_dpapi_supported():
                self.rb_pin.setChecked(True)
            else:
                self.rb_auto.setChecked(True)
            self.rb_pin.toggled.connect(self._sync_pin_fields)
            self._sync_pin_fields()

        def _sync_pin_fields(self) -> None:
            self.pin_box.setEnabled(self.rb_pin.isChecked())

        def _on_save(self) -> None:
            self.lbl_err.hide()
            if self.rb_auto.isChecked():
                self.selected_mode = "dpapi"
                self.selected_pin = ""
                self.accept()
                return
            pin = self.txt_pin.text().strip()
            confirm = self.txt_confirm.text().strip()
            if len(pin) < 4:
                self.lbl_err.setText("PIN must be at least 4 characters or digits.")
                self.lbl_err.show()
                return
            if pin != confirm:
                self.lbl_err.setText("PINs do not match.")
                self.lbl_err.show()
                return
            self.selected_mode = "pin"
            self.selected_pin = pin
            self.accept()

    class OwnerGeneratorWindow(QMainWindow):
        """Plain-English desktop license generator for the software owner."""

        def __init__(self, vault: OwnerVault):
            super().__init__()
            self.vault = vault
            self._private_key: Optional[Ed25519PrivateKey] = None
            self._last_signed: Optional[SignedLicense] = None
            self._last_friend_name: str = ""
            self._history_rows: List[Dict[str, str]] = []
            self._local_request_code: str = self._safe_local_request_code()

            self._setup_ui()
            self._select_initial_page()

        @staticmethod
        def _safe_local_request_code() -> str:
            try:
                return get_request_code()
            except FingerprintError:
                return ""

        def _setup_ui(self) -> None:
            self.setWindowTitle("UIIC License Key Generator")
            self.resize(800, 680)
            icon_path = resource_path("assets", "icon.ico")
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))

            self.setStyleSheet(
                """
                QMainWindow, QWidget#centralRoot {
                    background-color: #F8FAFC;
                    font-family: "Segoe UI", Arial, sans-serif;
                    color: #0F172A;
                }
                #headerBar {
                    background-color: #0F172A;
                    border-radius: 10px;
                }
                #headerTitle {
                    color: #FFFFFF;
                    font-size: 14pt;
                    font-weight: 700;
                    background: transparent;
                }
                #headerSub {
                    color: #94A3B8;
                    font-size: 9.5pt;
                    background: transparent;
                }
                #licCard {
                    background-color: #FFFFFF;
                    border: 1px solid #E2E8F0;
                    border-radius: 10px;
                }
                #sectionTitle {
                    color: #0F172A;
                    font-size: 11pt;
                    font-weight: 700;
                    background: transparent;
                }
                #hintText {
                    color: #475569;
                    font-size: 9pt;
                    background: transparent;
                }
                QLineEdit, QPlainTextEdit {
                    background-color: #FFFFFF;
                    border: 1px solid #CBD5E1;
                    border-radius: 7px;
                    padding: 8px 10px;
                    color: #0F172A;
                    font-size: 9.5pt;
                }
                QLineEdit:focus, QPlainTextEdit:focus {
                    border: 1.5px solid #2563EB;
                }
                QPushButton {
                    border-radius: 7px;
                    font-weight: 600;
                    font-size: 9.5pt;
                    padding: 8px 14px;
                }
                #btnPrimary {
                    background-color: #0F172A;
                    color: #FFFFFF;
                    border: none;
                }
                #btnPrimary:hover { background-color: #1E293B; }
                #btnPrimary:disabled { background-color: #94A3B8; }
                #btnSecondary {
                    background-color: #F1F5F9;
                    color: #0F172A;
                    border: 1px solid #CBD5E1;
                }
                #btnSecondary:hover { background-color: #E2E8F0; }
                QTableWidget {
                    background-color: #FFFFFF;
                    border: 1px solid #E2E8F0;
                    border-radius: 8px;
                    gridline-color: #F1F5F9;
                    font-size: 9pt;
                }
                QHeaderView::section {
                    background-color: #F1F5F9;
                    color: #334155;
                    font-weight: 700;
                    padding: 6px 8px;
                    border: none;
                    border-bottom: 1px solid #CBD5E1;
                }
                """
            )

            central = QWidget()
            central.setObjectName("centralRoot")
            self.setCentralWidget(central)

            root = QVBoxLayout(central)
            root.setContentsMargins(18, 18, 18, 18)
            root.setSpacing(14)

            header = QFrame()
            header.setObjectName("headerBar")
            hl = QVBoxLayout(header)
            hl.setContentsMargins(18, 14, 18, 14)
            hl.setSpacing(3)
            t = QLabel("UIIC License Key Generator")
            t.setObjectName("headerTitle")
            s = QLabel("Create offline PC-locked activation keys for your users")
            s.setObjectName("headerSub")
            hl.addWidget(t)
            hl.addWidget(s)
            root.addWidget(header)

            self.stack = QStackedWidget()
            root.addWidget(self.stack, 1)

            self.page_setup = self._build_setup_page()
            self.page_pin = self._build_pin_page()
            self.page_main = self._build_main_page()

            self.stack.addWidget(self.page_setup)
            self.stack.addWidget(self.page_pin)
            self.stack.addWidget(self.page_main)

        def _build_setup_page(self) -> QWidget:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)

            card = QFrame()
            card.setObjectName("licCard")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(20, 18, 20, 18)
            cl.setSpacing(12)

            title = QLabel("Welcome! One-Time Key Setup")
            title.setObjectName("sectionTitle")
            cl.addWidget(title)

            hint = QLabel(
                "Load the setup file (OwnerKey.uikey) given by your developer and enter the Setup Code once. "
                "After this, you can generate license keys with one click."
            )
            hint.setObjectName("hintText")
            hint.setWordWrap(True)
            cl.addWidget(hint)

            self.lbl_setup_info = QLabel()
            self.lbl_setup_info.setWordWrap(True)
            self.lbl_setup_info.hide()
            cl.addWidget(self.lbl_setup_info)

            self.lbl_setup_err = QLabel()
            self.lbl_setup_err.setWordWrap(True)
            self.lbl_setup_err.hide()
            cl.addWidget(self.lbl_setup_err)

            file_row = QHBoxLayout()
            self.txt_uikey_path = QLineEdit()
            self.txt_uikey_path.setPlaceholderText("Select OwnerKey.uikey file...")
            btn_browse = QPushButton("Browse...")
            btn_browse.setObjectName("btnSecondary")
            btn_browse.clicked.connect(self._on_browse_uikey)
            file_row.addWidget(self.txt_uikey_path, 1)
            file_row.addWidget(btn_browse)
            cl.addWidget(QLabel("Setup Key File (.uikey):"))
            cl.addLayout(file_row)

            code_row = QHBoxLayout()
            self.txt_setup_code = QLineEdit()
            self.txt_setup_code.setEchoMode(QLineEdit.EchoMode.Password)
            self.txt_setup_code.setPlaceholderText("Enter the Setup Code sent on WhatsApp")
            self.chk_show_code = QCheckBox("Show")
            self.chk_show_code.toggled.connect(
                lambda checked: self.txt_setup_code.setEchoMode(
                    QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
                )
            )
            code_row.addWidget(self.txt_setup_code, 1)
            code_row.addWidget(self.chk_show_code)
            cl.addWidget(QLabel("Setup Code:"))
            cl.addLayout(code_row)

            cl.addWidget(QLabel("How should this app open next time?"))
            self.rb_setup_auto = QRadioButton("Open automatically on this PC (Recommended — no PIN needed)")
            self.rb_setup_pin = QRadioButton("Ask for a PIN every time I open it:")
            dpapi_ok = is_dpapi_supported()
            self.rb_setup_auto.setEnabled(dpapi_ok)
            if dpapi_ok:
                self.rb_setup_auto.setChecked(True)
            else:
                self.rb_setup_pin.setChecked(True)
            cl.addWidget(self.rb_setup_auto)
            cl.addWidget(self.rb_setup_pin)

            self.setup_pin_panel = QWidget()
            spl = QGridLayout(self.setup_pin_panel)
            spl.setContentsMargins(22, 0, 0, 0)
            spl.setSpacing(8)
            self.txt_setup_pin = QLineEdit()
            self.txt_setup_pin.setEchoMode(QLineEdit.EchoMode.Password)
            self.txt_setup_pin.setPlaceholderText("Choose a PIN (min 4 characters)")
            self.txt_setup_pin_confirm = QLineEdit()
            self.txt_setup_pin_confirm.setEchoMode(QLineEdit.EchoMode.Password)
            self.txt_setup_pin_confirm.setPlaceholderText("Confirm PIN")
            spl.addWidget(QLabel("PIN:"), 0, 0)
            spl.addWidget(self.txt_setup_pin, 0, 1)
            spl.addWidget(QLabel("Confirm PIN:"), 1, 0)
            spl.addWidget(self.txt_setup_pin_confirm, 1, 1)
            cl.addWidget(self.setup_pin_panel)
            self.rb_setup_pin.toggled.connect(self._update_setup_pin_visibility)
            self._update_setup_pin_visibility()

            btn_row = QHBoxLayout()
            btn_row.addStretch()
            self.btn_complete_setup = QPushButton("Complete Setup")
            self.btn_complete_setup.setObjectName("btnPrimary")
            self.btn_complete_setup.clicked.connect(self._on_complete_setup)
            btn_row.addWidget(self.btn_complete_setup)
            cl.addLayout(btn_row)

            layout.addWidget(card)
            layout.addStretch()
            return page

        def _build_pin_page(self) -> QWidget:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)

            card = QFrame()
            card.setObjectName("licCard")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(20, 18, 20, 18)
            cl.setSpacing(12)

            title = QLabel("Enter Your PIN")
            title.setObjectName("sectionTitle")
            cl.addWidget(title)

            self.lbl_pin_err = QLabel()
            self.lbl_pin_err.setWordWrap(True)
            self.lbl_pin_err.hide()
            cl.addWidget(self.lbl_pin_err)

            self.txt_unlock_pin = QLineEdit()
            self.txt_unlock_pin.setEchoMode(QLineEdit.EchoMode.Password)
            self.txt_unlock_pin.setPlaceholderText("Enter your PIN to continue...")
            self.txt_unlock_pin.returnPressed.connect(self._on_unlock_pin)
            cl.addWidget(self.txt_unlock_pin)

            row = QHBoxLayout()
            self.btn_pin_switch = QPushButton("Load Different Key File...")
            self.btn_pin_switch.setObjectName("btnSecondary")
            self.btn_pin_switch.clicked.connect(self._on_switch_key_file)
            row.addWidget(self.btn_pin_switch)
            row.addStretch()
            self.btn_unlock_pin = QPushButton("Unlock")
            self.btn_unlock_pin.setObjectName("btnPrimary")
            self.btn_unlock_pin.clicked.connect(self._on_unlock_pin)
            row.addWidget(self.btn_unlock_pin)
            cl.addLayout(row)

            layout.addWidget(card)
            layout.addStretch()
            return page

        def _build_main_page(self) -> QWidget:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(12)

            # Status + quick lock settings bar
            bar = QFrame()
            bar.setObjectName("licCard")
            bl = QHBoxLayout(bar)
            bl.setContentsMargins(14, 10, 14, 10)
            bl.setSpacing(10)

            self.lbl_ready_status = QLabel("Ready to generate activation keys")
            self.lbl_ready_status.setStyleSheet("color: #065F46; font-weight: 600;")
            bl.addWidget(self.lbl_ready_status, 1)

            self.btn_lock_mode = QPushButton("Change PIN / Auto-Unlock...")
            self.btn_lock_mode.setObjectName("btnSecondary")
            self.btn_lock_mode.clicked.connect(self._on_change_lock_mode)
            bl.addWidget(self.btn_lock_mode)

            self.btn_switch_key = QPushButton("Replace Key File...")
            self.btn_switch_key.setObjectName("btnSecondary")
            self.btn_switch_key.clicked.connect(self._on_switch_key_file)
            bl.addWidget(self.btn_switch_key)
            layout.addWidget(bar)

            # Create Key card
            issue_card = QFrame()
            issue_card.setObjectName("licCard")
            il = QVBoxLayout(issue_card)
            il.setContentsMargins(16, 14, 16, 14)
            il.setSpacing(10)

            head = QHBoxLayout()
            ititle = QLabel("Create Activation Key")
            ititle.setObjectName("sectionTitle")
            head.addWidget(ititle)
            head.addStretch()
            if self._local_request_code:
                self.btn_use_this_pc = QPushButton("Fill This PC's Code")
                self.btn_use_this_pc.setObjectName("btnSecondary")
                self.btn_use_this_pc.clicked.connect(self._on_use_this_pc)
                head.addWidget(self.btn_use_this_pc)
            il.addLayout(head)

            grid = QGridLayout()
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(8)
            grid.addWidget(QLabel("Friend / User Name:"), 0, 0)
            self.txt_friend_name = QLineEdit()
            self.txt_friend_name.setPlaceholderText("e.g. Rajesh Office PC")
            grid.addWidget(self.txt_friend_name, 0, 1)

            grid.addWidget(QLabel("16-Character PC Code:"), 1, 0)
            self.txt_request_code = QLineEdit()
            self.txt_request_code.setPlaceholderText("XXXX-XXXX-XXXX-XXXX")
            self.txt_request_code.setStyleSheet(
                'font-family: "Consolas", "Courier New", monospace; font-size: 11pt; font-weight: 700;'
            )
            self.txt_request_code.textChanged.connect(self._on_code_text_changed)
            grid.addWidget(self.txt_request_code, 1, 1)
            il.addLayout(grid)

            val_row = QHBoxLayout()
            self.lbl_code_check = QLabel(
                "Ask your user to open the app, click 'Copy Code', and send the code on WhatsApp."
            )
            self.lbl_code_check.setObjectName("hintText")
            val_row.addWidget(self.lbl_code_check, 1)

            self.btn_generate = QPushButton("Generate License Key")
            self.btn_generate.setObjectName("btnPrimary")
            self.btn_generate.clicked.connect(self._on_generate_license)
            val_row.addWidget(self.btn_generate)
            il.addLayout(val_row)

            self.lbl_issued_meta = QLabel()
            self.lbl_issued_meta.hide()
            il.addWidget(self.lbl_issued_meta)

            self.txt_output_token = QPlainTextEdit()
            self.txt_output_token.setReadOnly(True)
            self.txt_output_token.setFixedHeight(64)
            self.txt_output_token.setPlaceholderText("Your generated activation key will appear here")
            self.txt_output_token.setStyleSheet(
                'font-family: "Consolas", "Courier New", monospace; font-size: 9pt;'
            )
            il.addWidget(self.txt_output_token)

            out_btns = QHBoxLayout()
            self.btn_copy_whatsapp = QPushButton("Copy WhatsApp Message")
            self.btn_copy_whatsapp.setObjectName("btnPrimary")
            self.btn_copy_whatsapp.setEnabled(False)
            self.btn_copy_whatsapp.clicked.connect(self._on_copy_whatsapp)

            self.btn_copy_token = QPushButton("Copy Key Only")
            self.btn_copy_token.setObjectName("btnSecondary")
            self.btn_copy_token.setEnabled(False)
            self.btn_copy_token.clicked.connect(self._on_copy_token)

            self.btn_save_lic = QPushButton("Save License File (.lic)...")
            self.btn_save_lic.setObjectName("btnSecondary")
            self.btn_save_lic.setEnabled(False)
            self.btn_save_lic.clicked.connect(self._on_save_lic)

            out_btns.addWidget(self.btn_copy_whatsapp)
            out_btns.addWidget(self.btn_copy_token)
            out_btns.addWidget(self.btn_save_lic)
            out_btns.addStretch()
            il.addLayout(out_btns)
            layout.addWidget(issue_card)

            # History table card
            hist_card = QFrame()
            hist_card.setObjectName("licCard")
            hl = QVBoxLayout(hist_card)
            hl.setContentsMargins(16, 12, 16, 14)
            hl.setSpacing(6)

            htitle = QLabel("Previously Issued Keys (click a row to copy again)")
            htitle.setObjectName("sectionTitle")
            hl.addWidget(htitle)

            self.tbl_history = QTableWidget(0, 4)
            self.tbl_history.setHorizontalHeaderLabels(
                ["Date", "Friend / User Name", "PC Code", "License ID"]
            )
            self.tbl_history.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.tbl_history.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            self.tbl_history.verticalHeader().setVisible(False)
            hdr = self.tbl_history.horizontalHeader()
            hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            self.tbl_history.cellClicked.connect(self._on_history_row_clicked)
            hl.addWidget(self.tbl_history)

            layout.addWidget(hist_card, 1)
            return page

        def _update_setup_pin_visibility(self) -> None:
            self.setup_pin_panel.setVisible(self.rb_setup_pin.isChecked())

        def _prefill_nearby_uikey(self) -> None:
            found = self.vault.find_nearby_uikey()
            if found:
                self.txt_uikey_path.setText(str(found))
                self.lbl_setup_info.setText(f"Found setup file automatically: {found.name}")
                self.lbl_setup_info.setStyleSheet(
                    "background-color: #ECFDF5; border: 1px solid #A7F3D0; color: #065F46; "
                    "border-radius: 7px; padding: 8px 10px; font-weight: 600;"
                )
                self.lbl_setup_info.show()
            else:
                self.lbl_setup_info.hide()

        def _select_initial_page(self) -> None:
            if self.vault.has_vault():
                try:
                    priv = self.vault.auto_unlock()
                except Exception as exc:
                    self._show_error(self.lbl_setup_err, str(exc))
                    self._prefill_nearby_uikey()
                    self.stack.setCurrentWidget(self.page_setup)
                    return
                if priv is not None:
                    self._enter_main_page(priv)
                    return
                self.stack.setCurrentWidget(self.page_pin)
                return

            self._prefill_nearby_uikey()
            self.stack.setCurrentWidget(self.page_setup)

        @staticmethod
        def _show_error(label: QLabel, text: str) -> None:
            label.setText(text)
            label.setStyleSheet(
                "background-color: #FEF2F2; border: 1px solid #FECACA; color: #991B1B; "
                "border-radius: 7px; padding: 8px 10px; font-weight: 600;"
            )
            label.show()

        def _on_browse_uikey(self) -> None:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Select Setup Key File",
                "",
                "Owner Setup Key (*.uikey);;All Files (*)",
            )
            if file_path:
                self.txt_uikey_path.setText(file_path)

        def _on_complete_setup(self) -> None:
            self.lbl_setup_err.hide()
            path_text = self.txt_uikey_path.text().strip()
            if not path_text:
                self._show_error(self.lbl_setup_err, "Please select your OwnerKey.uikey file.")
                return
            mode = "dpapi" if self.rb_setup_auto.isChecked() else "pin"
            try:
                priv = self.vault.import_uikey_and_save(
                    Path(path_text),
                    self.txt_setup_code.text(),
                    unlock_mode=mode,
                    pin=self.txt_setup_pin.text(),
                    confirm_pin=self.txt_setup_pin_confirm.text(),
                )
            except Exception as exc:
                self._show_error(self.lbl_setup_err, str(exc))
                return

            self.txt_setup_code.clear()
            self.txt_setup_pin.clear()
            self.txt_setup_pin_confirm.clear()
            self._enter_main_page(priv)

        def _on_unlock_pin(self) -> None:
            self.lbl_pin_err.hide()
            try:
                priv = self.vault.unlock_with_pin(self.txt_unlock_pin.text())
            except Exception as exc:
                self._show_error(self.lbl_pin_err, str(exc))
                return
            self.txt_unlock_pin.clear()
            self._enter_main_page(priv)

        def _enter_main_page(self, priv: Ed25519PrivateKey) -> None:
            self._private_key = priv
            self._refresh_status_bar()
            self._refresh_history_table()
            self.stack.setCurrentWidget(self.page_main)

        def _refresh_status_bar(self) -> None:
            mode = self.vault.unlock_mode()
            label = "Auto-Unlock Enabled (This PC)" if mode == "dpapi" else "PIN Protected"
            self.lbl_ready_status.setText(f"Ready to issue license keys • Security: {label}")

        def _refresh_history_table(self) -> None:
            rows = self.vault.load_history()
            self._history_rows = rows
            self.tbl_history.setRowCount(len(rows))
            for r_idx, row in enumerate(rows):
                vals = (
                    row.get("issued_date", "") or row.get("issued_at_utc", ""),
                    row.get("friend_name", ""),
                    row.get("request_code", ""),
                    row.get("license_id", ""),
                )
                for c_idx, val in enumerate(vals):
                    self.tbl_history.setItem(r_idx, c_idx, QTableWidgetItem(str(val)))

        def _on_history_row_clicked(self, row_idx: int, _col_idx: int) -> None:
            if row_idx < 0 or row_idx >= len(self._history_rows):
                return
            row = self._history_rows[row_idx]
            token = row.get("token", "")
            if not token:
                return
            self._set_active_signed_license(
                SignedLicense(
                    token=token,
                    license_id=row.get("license_id", ""),
                    request_code=row.get("request_code", ""),
                    issued_date=row.get("issued_date", ""),
                ),
                friend_name=row.get("friend_name", ""),
                prefix="Loaded",
            )

        def _set_active_signed_license(
            self, signed: SignedLicense, *, friend_name: str = "", prefix: str = "Ready"
        ) -> None:
            self._last_signed = signed
            self._last_friend_name = friend_name
            who = f" for {friend_name}" if friend_name else ""
            self.lbl_issued_meta.setText(
                f"{prefix}{who}: {signed.license_id} ({signed.issued_date})"
            )
            self.lbl_issued_meta.setStyleSheet("color: #065F46; font-weight: 700;")
            self.lbl_issued_meta.show()
            self.txt_output_token.setPlainText(signed.token)
            self.btn_copy_whatsapp.setEnabled(True)
            self.btn_copy_token.setEnabled(True)
            self.btn_save_lic.setEnabled(True)

        def _on_change_lock_mode(self) -> None:
            if self._private_key is None:
                return
            cur_mode = self.vault.unlock_mode() or "dpapi"
            dlg = _LockSettingsDialog(cur_mode, parent=self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            try:
                self.vault.change_unlock_mode(
                    self._private_key,
                    dlg.selected_mode,
                    pin=dlg.selected_pin,
                )
                self._refresh_status_bar()
            except Exception as exc:
                QMessageBox.critical(self, "Could Not Update Security Setting", str(exc))

        def _on_switch_key_file(self) -> None:
            self.lbl_setup_err.hide()
            self._prefill_nearby_uikey()
            self.stack.setCurrentWidget(self.page_setup)

        def _on_use_this_pc(self) -> None:
            if self._local_request_code:
                if not self.txt_friend_name.text().strip():
                    self.txt_friend_name.setText("This PC")
                self.txt_request_code.setText(self._local_request_code)

        def _on_code_text_changed(self, text: str) -> None:
            cleaned = re.sub(r"[\s\-_]", "", text or "")
            if not cleaned:
                self.lbl_code_check.setText(
                    "Ask your user to open the app, click 'Copy Code', and send the code on WhatsApp."
                )
                self.lbl_code_check.setStyleSheet("color: #475569; font-weight: 400;")
                return
            try:
                decoded = decode_request_code(text)
                self.lbl_code_check.setText(f"Code looks good -> {decoded.formatted_code}")
                self.lbl_code_check.setStyleSheet("color: #065F46; font-weight: 600;")
            except FingerprintError:
                self.lbl_code_check.setText(
                    "That code looks incomplete or mistyped — ask your friend to use 'Copy Code'."
                )
                self.lbl_code_check.setStyleSheet("color: #991B1B; font-weight: 600;")

        def _on_generate_license(self) -> None:
            if self._private_key is None:
                return
            friend = self.txt_friend_name.text().strip()
            try:
                signed = self.vault.issue_license(
                    self._private_key,
                    friend,
                    self.txt_request_code.text(),
                )
            except FingerprintError:
                QMessageBox.warning(
                    self,
                    "Check PC Code",
                    "The 16-character PC Code looks mistyped. Ask your friend to click 'Copy Code' and resend it.",
                )
                return
            except Exception as exc:
                QMessageBox.warning(self, "Cannot Create Key", str(exc))
                return

            self._set_active_signed_license(signed, friend_name=friend, prefix="Created")
            self._refresh_history_table()

        def _flash_button(self, button: QPushButton, orig_text: str, temp_text: str) -> None:
            button.setText(temp_text)
            QTimer.singleShot(1600, lambda: button.setText(orig_text))

        def _on_copy_whatsapp(self) -> None:
            if not self._last_signed:
                return
            cb = QApplication.clipboard()
            if cb is not None:
                cb.setText(
                    format_owner_whatsapp_message(self._last_signed, self._last_friend_name)
                )
            self._flash_button(self.btn_copy_whatsapp, "Copy WhatsApp Message", "Copied!")

        def _on_copy_token(self) -> None:
            if not self._last_signed:
                return
            cb = QApplication.clipboard()
            if cb is not None:
                cb.setText(self._last_signed.token)
            self._flash_button(self.btn_copy_token, "Copy Key Only", "Copied!")

        def _on_save_lic(self) -> None:
            if not self._last_signed:
                return
            safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", self._last_friend_name).strip("_")
            default_name = (
                f"{safe_name}_License.lic"
                if safe_name
                else f"UIIC_License_{self._last_signed.license_id}.lic"
            )
            dest, _ = QFileDialog.getSaveFileName(
                self,
                "Save License File (.lic)",
                str(Path.home() / "Desktop" / default_name),
                "UIIC License Files (*.lic);;All Files (*)",
            )
            if not dest:
                return
            try:
                _atomic_write_text(Path(dest), format_lic_file_content(self._last_signed))
                QMessageBox.information(
                    self,
                    "License File Saved",
                    f"Saved to:\n{dest}\n\nSend this file on WhatsApp to your user.",
                )
            except Exception as exc:
                QMessageBox.critical(self, "Could Not Save File", str(exc))

    return OwnerGeneratorWindow


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="UIIC License Key Generator (Owner Edition)")
    parser.add_argument("--data-dir", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    try:
        from PyQt6.QtWidgets import QApplication

        window_cls = get_owner_window_class()
    except ImportError as exc:
        print(
            f"PyQt6 GUI could not load on this PC ({exc}).\n"
            "Wait for CI to build UIIC_License_Generator.exe for the Owner, "
            "or run with '--dev' if you are the developer:\n"
            "  python tools/license_generator.py --dev",
            file=sys.stderr,
        )
        return 1

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("UIIC License Key Generator")
    vault = OwnerVault(data_dir=args.data_dir)
    win = window_cls(vault)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
