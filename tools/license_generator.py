"""
Standalone Developer License Generator for UIIC Surveyor Automation.

Runs ONLY on the developer's PC (excluded from the packaged EXE):
  python tools/license_generator.py          # Owner Desktop GUI
  python tools/license_generator.py --dev    # Developer GUI (or CLI fallback)
  python tools/license_generator.py --cli    # Developer interactive terminal mode

Stores your password-encrypted Ed25519 private key and issued-license log OUTSIDE Git in:
  %LOCALAPPDATA%\\UIIC_License_Issuer\\

Never commit private_key.pem or issued_licenses.jsonl to version control.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.licensing.codec import (
    SignedLicense,
    derive_public_key_b64,
    format_lic_file_content,
    generate_keypair,
    load_private_key,
    sign_license_token,
)
from app.licensing.fingerprint import FingerprintError, decode_request_code, get_request_code
from app.licensing.public_key import update_public_key_file
from tools.owner_vault import export_owner_bundle

_PUB_ASSIGN_RE = re.compile(r'^PUBLIC_KEY_B64\s*=\s*["\']([^"\']*)["\']\s*$', re.MULTILINE)


def default_issuer_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "UIIC_License_Issuer"


def default_public_key_file() -> Path:
    return REPO_ROOT / "app" / "licensing" / "public_key.py"


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def format_whatsapp_message(signed: SignedLicense) -> str:
    return (
        "UIIC Surveyor Automation — Activation Key\n"
        f"License ID: {signed.license_id}\n"
        f"For PC Code: {signed.request_code}\n\n"
        "License Key:\n"
        f"{signed.token}\n\n"
        "How to activate:\n"
        "1. Open UIIC_Surveyor_Automation.exe\n"
        "2. Copy this message (or just the UIIC1-... key) and paste it into Step 2\n"
        "3. Click 'Activate Software' (or use 'Load .lic File...' if a file was sent)"
    )


class IssuerStore:
    """Manages encrypted Ed25519 private key storage, public key syncing, and audit logs."""

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        public_key_file: Optional[Path] = None,
    ):
        self.data_dir = Path(data_dir) if data_dir else default_issuer_dir()
        self.public_key_file = (
            Path(public_key_file) if public_key_file else default_public_key_file()
        )

    @property
    def private_key_path(self) -> Path:
        return self.data_dir / "private_key.pem"

    @property
    def history_path(self) -> Path:
        return self.data_dir / "issued_licenses.jsonl"

    def has_private_key(self) -> bool:
        return self.private_key_path.is_file()

    def initialize_keypair(
        self,
        passphrase: str,
        confirm_passphrase: str,
        *,
        sync_public_key: bool = True,
    ) -> Tuple[Ed25519PrivateKey, str]:
        if self.has_private_key():
            raise FileExistsError(
                f"Private key already exists at {self.private_key_path}. "
                "Unlock the existing key instead of overwriting it."
            )
        if passphrase != confirm_passphrase:
            raise ValueError("Passphrases do not match.")
        pem_bytes, pub_b64 = generate_keypair(passphrase)
        _atomic_write_bytes(self.private_key_path, pem_bytes)
        priv_key = load_private_key(pem_bytes, passphrase)
        if sync_public_key:
            update_public_key_file(pub_b64, target_path=self.public_key_file)
        return priv_key, pub_b64

    def unlock_private_key(self, passphrase: str) -> Ed25519PrivateKey:
        if not self.has_private_key():
            raise FileNotFoundError(f"Private key not found at {self.private_key_path}.")
        if not passphrase:
            raise ValueError("Please enter your Master Passphrase.")
        pem_bytes = self.private_key_path.read_bytes()
        try:
            return load_private_key(pem_bytes, passphrase)
        except Exception as exc:
            raise ValueError("Incorrect Master Passphrase or corrupted private key.") from exc

    def read_embedded_public_key_b64(self) -> str:
        if not self.public_key_file.is_file():
            return "MISSING_FILE"
        content = self.public_key_file.read_text(encoding="utf-8")
        match = _PUB_ASSIGN_RE.search(content)
        return match.group(1).strip() if match else "MISSING_ASSIGNMENT"

    def public_key_sync_status(self, private_key: Ed25519PrivateKey) -> Tuple[str, str, str]:
        derived = derive_public_key_b64(private_key)
        embedded = self.read_embedded_public_key_b64()
        if embedded == derived:
            return "synced", derived, embedded
        if embedded in ("UNCONFIGURED", "", "MISSING_FILE", "MISSING_ASSIGNMENT"):
            return "unconfigured", derived, embedded
        return "mismatch", derived, embedded

    def sync_public_key(self, private_key: Ed25519PrivateKey) -> str:
        pub_b64 = derive_public_key_b64(private_key)
        update_public_key_file(pub_b64, target_path=self.public_key_file)
        return pub_b64

    def issue_license(
        self,
        private_key: Ed25519PrivateKey,
        friend_name: str,
        request_code: str,
    ) -> SignedLicense:
        clean_name = (friend_name or "").strip()
        if not clean_name:
            raise ValueError("Please enter your friend's name or PC label.")
        signed = sign_license_token(request_code, private_key)
        record = {
            "issued_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "issued_date": signed.issued_date,
            "friend_name": clean_name,
            "request_code": signed.request_code,
            "license_id": signed.license_id,
            "token_prefix": signed.token[:22] + "...",
            "token": signed.token,
        }
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return signed

    def load_history(self) -> List[Dict[str, str]]:
        if not self.history_path.is_file():
            return []
        rows: List[Dict[str, str]] = []
        for line in self.history_path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
            except Exception:
                continue
        rows.reverse()  # Newest first
        return rows

    def export_backup_pem(self, dest_path: Path) -> Path:
        if not self.has_private_key():
            raise FileNotFoundError("No private key exists to back up yet.")
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.private_key_path, dest)
        return dest


def get_generator_window_class():
    """
    Lazily import PyQt6 and define LicenseGeneratorWindow so non-GUI workflows and
    tests continue working cleanly even when PyQt6 QtWidgets is unavailable.
    """
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import (
        QApplication,
        QCheckBox,
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
        QStackedWidget,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )

    class LicenseGeneratorWindow(QMainWindow):
        """Developer desktop utility to create encrypted signing keys and issue PC-locked licenses."""

        def __init__(self, store: IssuerStore):
            super().__init__()
            self.store = store
            self._private_key: Optional[Ed25519PrivateKey] = None
            self._last_signed: Optional[SignedLicense] = None
            self._history_rows: List[Dict[str, str]] = []
            self._local_request_code: str = self._safe_local_request_code()

            self._setup_ui()
            self._select_initial_page()

        @staticmethod
        def _safe_local_request_code() -> str:
            try:
                return get_request_code()
            except FingerprintError:
                return "UNAVAILABLE"

        def _setup_ui(self) -> None:
            self.setWindowTitle("UIIC Surveyor Automation — Developer License Generator")
            self.resize(840, 720)
            self.setStyleSheet(
                """
                QMainWindow, QWidget#centralRoot {
                    background-color: #F8FAFC;
                    font-family: "Segoe UI", Arial, sans-serif;
                    color: #0F172A;
                }
                QLabel {
                    color: #0F172A;
                    font-size: 9.5pt;
                }
                QRadioButton {
                    color: #0F172A;
                    font-size: 9.5pt;
                    spacing: 8px;
                }
                QCheckBox {
                    color: #0F172A;
                    font-size: 9.5pt;
                    spacing: 6px;
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
                    font-size: 9pt;
                    background: transparent;
                }
                #licCard {
                    background-color: #FFFFFF;
                    border: 1px solid #E2E8F0;
                    border-radius: 10px;
                }
                #sectionTitle {
                    color: #0F172A;
                    font-size: 10.5pt;
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
                    padding: 7px 10px;
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

            # Header
            header = QFrame()
            header.setObjectName("headerBar")
            hl = QVBoxLayout(header)
            hl.setContentsMargins(18, 14, 18, 14)
            hl.setSpacing(3)
            t = QLabel("Developer License Generator (Offline Ed25519)")
            t.setObjectName("headerTitle")
            s = QLabel(f"Issuer vault (never commit to Git): {self.store.data_dir}")
            s.setObjectName("headerSub")
            s.setWordWrap(True)
            hl.addWidget(t)
            hl.addWidget(s)
            root.addWidget(header)

            self.stack = QStackedWidget()
            root.addWidget(self.stack, 1)

            self.page_setup = self._build_setup_page()
            self.page_unlock = self._build_unlock_page()
            self.page_main = self._build_main_page()

            self.stack.addWidget(self.page_setup)
            self.stack.addWidget(self.page_unlock)
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

            title = QLabel("First-Time Master Keypair Setup")
            title.setObjectName("sectionTitle")
            cl.addWidget(title)

            hint = QLabel(
                "Create a Master Passphrase (at least 8 characters) to encrypt your private signing key. "
                "Your private key stays in AppData and is NEVER committed to Git. If you lose both the "
                "key file and passphrase, you cannot issue new keys for existing builds."
            )
            hint.setObjectName("hintText")
            hint.setWordWrap(True)
            cl.addWidget(hint)

            self.lbl_setup_err = QLabel()
            self.lbl_setup_err.setWordWrap(True)
            self.lbl_setup_err.hide()
            cl.addWidget(self.lbl_setup_err)

            self.txt_setup_pass = QLineEdit()
            self.txt_setup_pass.setEchoMode(QLineEdit.EchoMode.Password)
            self.txt_setup_pass.setPlaceholderText("Master Passphrase (min 8 characters)")
            cl.addWidget(QLabel("Master Passphrase:"))
            cl.addWidget(self.txt_setup_pass)

            self.txt_setup_confirm = QLineEdit()
            self.txt_setup_confirm.setEchoMode(QLineEdit.EchoMode.Password)
            self.txt_setup_confirm.setPlaceholderText("Confirm Master Passphrase")
            self.txt_setup_confirm.returnPressed.connect(self._on_create_keypair)
            cl.addWidget(QLabel("Confirm Passphrase:"))
            cl.addWidget(self.txt_setup_confirm)

            self.chk_setup_sync = QCheckBox(
                f"Automatically write PUBLIC_KEY_B64 into {self.store.public_key_file.name}"
            )
            self.chk_setup_sync.setChecked(True)
            cl.addWidget(self.chk_setup_sync)

            btn_row = QHBoxLayout()
            btn_row.addStretch()
            self.btn_create_key = QPushButton("Create Master Keypair")
            self.btn_create_key.setObjectName("btnPrimary")
            self.btn_create_key.clicked.connect(self._on_create_keypair)
            btn_row.addWidget(self.btn_create_key)
            cl.addLayout(btn_row)

            layout.addWidget(card)
            layout.addStretch()
            return page

        def _build_unlock_page(self) -> QWidget:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)

            card = QFrame()
            card.setObjectName("licCard")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(20, 18, 20, 18)
            cl.setSpacing(12)

            title = QLabel("Unlock Signing Key")
            title.setObjectName("sectionTitle")
            cl.addWidget(title)

            hint = QLabel(f"Encrypted private key found: {self.store.private_key_path}")
            hint.setObjectName("hintText")
            hint.setWordWrap(True)
            cl.addWidget(hint)

            self.lbl_unlock_err = QLabel()
            self.lbl_unlock_err.setWordWrap(True)
            self.lbl_unlock_err.hide()
            cl.addWidget(self.lbl_unlock_err)

            self.txt_unlock_pass = QLineEdit()
            self.txt_unlock_pass.setEchoMode(QLineEdit.EchoMode.Password)
            self.txt_unlock_pass.setPlaceholderText("Enter Master Passphrase to unlock...")
            self.txt_unlock_pass.returnPressed.connect(self._on_unlock)
            cl.addWidget(self.txt_unlock_pass)

            row = QHBoxLayout()
            row.addStretch()
            self.btn_unlock = QPushButton("Unlock License Generator")
            self.btn_unlock.setObjectName("btnPrimary")
            self.btn_unlock.clicked.connect(self._on_unlock)
            row.addWidget(self.btn_unlock)
            cl.addLayout(row)

            layout.addWidget(card)
            layout.addStretch()
            return page

        def _build_main_page(self) -> QWidget:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(12)

            sync_card = QFrame()
            sync_card.setObjectName("licCard")
            sl = QHBoxLayout(sync_card)
            sl.setContentsMargins(14, 10, 14, 10)
            sl.setSpacing(10)

            self.lbl_sync_status = QLabel()
            self.lbl_sync_status.setWordWrap(True)
            sl.addWidget(self.lbl_sync_status, 1)

            self.btn_sync_pub = QPushButton("Sync Public Key to App")
            self.btn_sync_pub.setObjectName("btnSecondary")
            self.btn_sync_pub.clicked.connect(self._on_sync_public_key)
            sl.addWidget(self.btn_sync_pub)

            self.btn_backup_key = QPushButton("Backup Encrypted Key...")
            self.btn_backup_key.setObjectName("btnSecondary")
            self.btn_backup_key.clicked.connect(self._on_backup_key)
            sl.addWidget(self.btn_backup_key)

            layout.addWidget(sync_card)

            issue_card = QFrame()
            issue_card.setObjectName("licCard")
            il = QVBoxLayout(issue_card)
            il.setContentsMargins(16, 14, 16, 14)
            il.setSpacing(10)

            head_row = QHBoxLayout()
            ititle = QLabel("Issue Permanent PC-Locked License")
            ititle.setObjectName("sectionTitle")
            head_row.addWidget(ititle)
            head_row.addStretch()
            self.lbl_this_pc = QLabel(f"This PC: {self._local_request_code}")
            self.lbl_this_pc.setObjectName("hintText")
            head_row.addWidget(self.lbl_this_pc)
            self.btn_use_this_pc = QPushButton("Use This PC Code")
            self.btn_use_this_pc.setObjectName("btnSecondary")
            self.btn_use_this_pc.setEnabled(self._local_request_code != "UNAVAILABLE")
            self.btn_use_this_pc.clicked.connect(self._on_use_this_pc)
            head_row.addWidget(self.btn_use_this_pc)
            il.addLayout(head_row)

            grid = QGridLayout()
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(8)

            grid.addWidget(QLabel("Friend / PC Label:"), 0, 0)
            self.txt_friend_name = QLineEdit()
            self.txt_friend_name.setPlaceholderText("e.g. Friend 1 - Rajesh Office PC")
            grid.addWidget(self.txt_friend_name, 0, 1)

            grid.addWidget(QLabel("16-Char Request Code:"), 1, 0)
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
                "Enter the 16-character code your friend sent on WhatsApp."
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
            self.txt_output_token.setPlaceholderText(
                "Generated UIIC1-... license key will appear here"
            )
            self.txt_output_token.setStyleSheet(
                'font-family: "Consolas", "Courier New", monospace; font-size: 9pt;'
            )
            il.addWidget(self.txt_output_token)

            out_btns = QHBoxLayout()
            self.btn_copy_token = QPushButton("Copy License Key")
            self.btn_copy_token.setObjectName("btnSecondary")
            self.btn_copy_token.setEnabled(False)
            self.btn_copy_token.clicked.connect(self._on_copy_token)

            self.btn_copy_whatsapp = QPushButton("Copy WhatsApp Message")
            self.btn_copy_whatsapp.setObjectName("btnSecondary")
            self.btn_copy_whatsapp.setEnabled(False)
            self.btn_copy_whatsapp.clicked.connect(self._on_copy_whatsapp)

            self.btn_save_lic = QPushButton("Save .lic File...")
            self.btn_save_lic.setObjectName("btnSecondary")
            self.btn_save_lic.setEnabled(False)
            self.btn_save_lic.clicked.connect(self._on_save_lic)

            out_btns.addWidget(self.btn_copy_token)
            out_btns.addWidget(self.btn_copy_whatsapp)
            out_btns.addWidget(self.btn_save_lic)
            out_btns.addStretch()
            il.addLayout(out_btns)

            layout.addWidget(issue_card)

            hist_card = QFrame()
            hist_card.setObjectName("licCard")
            hl = QVBoxLayout(hist_card)
            hl.setContentsMargins(16, 12, 16, 14)
            hl.setSpacing(8)

            htitle = QLabel("Issued Licenses Audit Log")
            htitle.setObjectName("sectionTitle")
            hl.addWidget(htitle)

            self.tbl_history = QTableWidget(0, 5)
            self.tbl_history.setHorizontalHeaderLabels(
                ["Issued At", "Friend / PC", "Request Code", "License ID", "Key Prefix"]
            )
            self.tbl_history.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.tbl_history.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            self.tbl_history.verticalHeader().setVisible(False)
            hdr = self.tbl_history.horizontalHeader()
            hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
            self.tbl_history.cellClicked.connect(self._on_history_row_clicked)
            hl.addWidget(self.tbl_history)

            layout.addWidget(hist_card, 1)
            return page

        def _select_initial_page(self) -> None:
            if self.store.has_private_key():
                self.stack.setCurrentWidget(self.page_unlock)
            else:
                self.stack.setCurrentWidget(self.page_setup)

        @staticmethod
        def _show_error(label: QLabel, text: str) -> None:
            label.setText(text)
            label.setStyleSheet(
                "background-color: #FEF2F2; border: 1px solid #FECACA; color: #991B1B; "
                "border-radius: 7px; padding: 8px 10px; font-weight: 600;"
            )
            label.show()

        def _on_create_keypair(self) -> None:
            self.lbl_setup_err.hide()
            try:
                priv_key, _ = self.store.initialize_keypair(
                    self.txt_setup_pass.text(),
                    self.txt_setup_confirm.text(),
                    sync_public_key=self.chk_setup_sync.isChecked(),
                )
            except Exception as exc:
                self._show_error(self.lbl_setup_err, str(exc))
                return

            self.txt_setup_pass.clear()
            self.txt_setup_confirm.clear()
            self._enter_main_page(priv_key)

        def _on_unlock(self) -> None:
            self.lbl_unlock_err.hide()
            try:
                priv_key = self.store.unlock_private_key(self.txt_unlock_pass.text())
            except Exception as exc:
                self._show_error(self.lbl_unlock_err, str(exc))
                return

            self.txt_unlock_pass.clear()
            self._enter_main_page(priv_key)

        def _enter_main_page(self, priv_key: Ed25519PrivateKey) -> None:
            self._private_key = priv_key
            self._refresh_sync_banner()
            self._refresh_history_table()
            self.stack.setCurrentWidget(self.page_main)

        def _refresh_sync_banner(self) -> None:
            if self._private_key is None:
                return
            state, derived, _ = self.store.public_key_sync_status(self._private_key)
            short = derived[:12] + "..." + derived[-6:]
            if state == "synced":
                self.lbl_sync_status.setText(
                    f"Public key SYNCED in {self.store.public_key_file.name} ({short}). "
                    "Your built EXE will accept keys issued here."
                )
                self.lbl_sync_status.setStyleSheet("color: #065F46; font-weight: 600;")
                self.btn_sync_pub.setText("Re-Sync Public Key")
            elif state == "unconfigured":
                self.lbl_sync_status.setText(
                    f"Action required: {self.store.public_key_file.name} is UNCONFIGURED. "
                    "Click 'Sync Public Key to App' before building your EXE."
                )
                self.lbl_sync_status.setStyleSheet("color: #991B1B; font-weight: 700;")
                self.btn_sync_pub.setText("Sync Public Key to App")
            else:
                self.lbl_sync_status.setText(
                    f"WARNING: {self.store.public_key_file.name} holds a DIFFERENT public key ({short}). "
                    "Click 'Sync Public Key to App' and rebuild your EXE."
                )
                self.lbl_sync_status.setStyleSheet("color: #991B1B; font-weight: 700;")
                self.btn_sync_pub.setText("Sync Public Key to App")

        def _refresh_history_table(self) -> None:
            rows = self.store.load_history()
            self._history_rows = rows
            self.tbl_history.setRowCount(len(rows))
            for r_idx, row in enumerate(rows):
                vals = (
                    row.get("issued_at_utc", ""),
                    row.get("friend_name", ""),
                    row.get("request_code", ""),
                    row.get("license_id", ""),
                    row.get("token_prefix", ""),
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
                prefix="Loaded from log",
            )

        def _set_active_signed_license(
            self, signed: SignedLicense, *, prefix: str = "Issued"
        ) -> None:
            self._last_signed = signed
            self.lbl_issued_meta.setText(
                f"{prefix} {signed.license_id} ({signed.issued_date}) for PC Code {signed.request_code}"
            )
            self.lbl_issued_meta.setStyleSheet("color: #065F46; font-weight: 700;")
            self.lbl_issued_meta.show()
            self.txt_output_token.setPlainText(signed.token)
            self.btn_copy_token.setEnabled(True)
            self.btn_copy_whatsapp.setEnabled(True)
            self.btn_save_lic.setEnabled(True)

        def _on_sync_public_key(self) -> None:
            if self._private_key is None:
                return
            try:
                self.store.sync_public_key(self._private_key)
                self._refresh_sync_banner()
                QMessageBox.information(
                    self,
                    "Public Key Synced",
                    f"Updated PUBLIC_KEY_B64 in:\n{self.store.public_key_file}\n\n"
                    "Commit public_key.py (it contains ONLY the public key) and rebuild your EXE.",
                )
            except Exception as exc:
                QMessageBox.critical(self, "Sync Failed", str(exc))

        def _on_backup_key(self) -> None:
            dest, _ = QFileDialog.getSaveFileName(
                self,
                "Save Backup of Encrypted Private Key",
                str(Path.home() / "Desktop" / "uiic_private_key_backup.pem"),
                "PEM Key Files (*.pem);;All Files (*)",
            )
            if not dest:
                return
            try:
                saved = self.store.export_backup_pem(Path(dest))
                QMessageBox.information(
                    self,
                    "Backup Saved",
                    f"Encrypted private key copied to:\n{saved}\n\n"
                    "Store this backup safely (still protected by your Master Passphrase).",
                )
            except Exception as exc:
                QMessageBox.critical(self, "Backup Failed", str(exc))

        def _on_use_this_pc(self) -> None:
            if self._local_request_code != "UNAVAILABLE":
                if not self.txt_friend_name.text().strip():
                    self.txt_friend_name.setText("Developer PC")
                self.txt_request_code.setText(self._local_request_code)

        def _on_code_text_changed(self, text: str) -> None:
            cleaned = re.sub(r"[\s\-_]", "", text or "")
            if not cleaned:
                self.lbl_code_check.setText(
                    "Enter the 16-character code your friend sent on WhatsApp."
                )
                self.lbl_code_check.setStyleSheet("color: #475569; font-weight: 400;")
                return
            try:
                decoded = decode_request_code(text)
                anchors = bin(decoded.present_mask).count("1")
                self.lbl_code_check.setText(
                    f"Valid code ({anchors}/4 PC anchors) -> {decoded.formatted_code}"
                )
                self.lbl_code_check.setStyleSheet("color: #065F46; font-weight: 600;")
            except FingerprintError as exc:
                self.lbl_code_check.setText(str(exc))
                self.lbl_code_check.setStyleSheet("color: #991B1B; font-weight: 600;")

        def _on_generate_license(self) -> None:
            if self._private_key is None:
                return
            try:
                signed = self.store.issue_license(
                    self._private_key,
                    self.txt_friend_name.text(),
                    self.txt_request_code.text(),
                )
            except Exception as exc:
                QMessageBox.warning(self, "Cannot Issue License", str(exc))
                return

            self._set_active_signed_license(signed, prefix="Issued")
            self._refresh_history_table()

        def _flash_button(self, button: QPushButton, orig_text: str, temp_text: str) -> None:
            button.setText(temp_text)
            QTimer.singleShot(1600, lambda: button.setText(orig_text))

        def _on_copy_token(self) -> None:
            if not self._last_signed:
                return
            cb = QApplication.clipboard()
            if cb is not None:
                cb.setText(self._last_signed.token)
            self._flash_button(self.btn_copy_token, "Copy License Key", "Copied!")

        def _on_copy_whatsapp(self) -> None:
            if not self._last_signed:
                return
            cb = QApplication.clipboard()
            if cb is not None:
                cb.setText(format_whatsapp_message(self._last_signed))
            self._flash_button(self.btn_copy_whatsapp, "Copy WhatsApp Message", "Copied Message!")

        def _on_save_lic(self) -> None:
            if not self._last_signed:
                return
            safe_code = self._last_signed.request_code.replace("-", "")[:8]
            default_name = f"uiic_license_{safe_code}.lic"
            dest, _ = QFileDialog.getSaveFileName(
                self,
                "Save License File (.lic)",
                str(Path.home() / "Desktop" / default_name),
                "UIIC License Files (*.lic);;All Files (*)",
            )
            if not dest:
                return
            try:
                content = format_lic_file_content(self._last_signed)
                _atomic_write_bytes(Path(dest), content.encode("utf-8"))
                QMessageBox.information(
                    self,
                    ".lic File Saved",
                    f"Saved license file to:\n{dest}\n\n"
                    "You can send this file to your friend on WhatsApp.",
                )
            except Exception as exc:
                QMessageBox.critical(self, "Save Failed", str(exc))

    return LicenseGeneratorWindow


def _prompt_secret(prompt: str = "Passphrase: ") -> str:
    """
    Read a passphrase in the terminal, echoing '*' per character on Windows TTY
    so users can see length and Backspace clearly without revealing characters.
    """
    if sys.platform == "win32" and sys.stdin is not None and sys.stdin.isatty():
        try:
            import msvcrt

            sys.stdout.write(prompt)
            sys.stdout.flush()
            chars: List[str] = []
            while True:
                ch = msvcrt.getwch()
                if ch in ("\r", "\n"):
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return "".join(chars)
                if ch == "\x03":
                    raise KeyboardInterrupt
                if ch in ("\b", "\x08", "\x7f"):
                    if chars:
                        chars.pop()
                        sys.stdout.write("\b \b")
                        sys.stdout.flush()
                    continue
                if ch in ("\x00", "\xe0"):
                    # Discard extended function/arrow key scan code second byte
                    msvcrt.getwch()
                    continue
                if ord(ch) < 32:
                    continue
                chars.append(ch)
                sys.stdout.write("*")
                sys.stdout.flush()
        except Exception:
            pass
    return getpass.getpass(prompt)


def run_cli(
    store: IssuerStore,
    *,
    input_fn: Callable[[str], str] = input,
    secret_fn: Callable[[str], str] = _prompt_secret,
    output_fn: Callable[[str], None] = print,
) -> int:
    """Interactive terminal interface (works without PyQt6 or on headless setups)."""
    output_fn("=" * 64)
    output_fn("UIIC Surveyor Automation — Developer License Generator (CLI)")
    output_fn(f"Issuer Vault: {store.data_dir}")
    output_fn(f"Public Key File: {store.public_key_file}")
    try:
        local_code = get_request_code()
    except FingerprintError:
        local_code = "UNAVAILABLE"
    output_fn(f"This PC Code: {local_code}")
    output_fn("=" * 64)

    priv_key: Optional[Ed25519PrivateKey] = None
    if not store.has_private_key():
        output_fn(
            "\n[First-Time Setup] Create a Master Passphrase\n"
            "  - Any letters, numbers, or symbols are allowed (minimum 8 characters).\n"
            "  - Typed characters show as '*' so you can count length cleanly."
        )
        while priv_key is None:
            p1 = secret_fn("Master Passphrase (min 8 chars): ")
            if len(p1) < 8:
                output_fn("Error: Master passphrase must be at least 8 characters long.")
                continue
            p2 = secret_fn("Confirm Master Passphrase: ")
            if p1 != p2:
                output_fn("Error: Passphrases do not match. Please try again.")
                continue
            sync_ans = input_fn("Sync PUBLIC_KEY_B64 into app now? [Y/n]: ").strip().lower()
            try:
                priv_key, pub_b64 = store.initialize_keypair(
                    p1, p2, sync_public_key=(sync_ans != "n")
                )
                output_fn(f"Created encrypted private key: {store.private_key_path}")
                output_fn(f"Public Key: {pub_b64}")
            except Exception as exc:
                output_fn(f"Error: {exc}")
    else:
        output_fn(f"\nEncrypted private key found: {store.private_key_path}")
        for attempt in range(3):
            pwd = secret_fn("Enter Master Passphrase: ")
            try:
                priv_key = store.unlock_private_key(pwd)
                break
            except Exception as exc:
                output_fn(f"Error ({attempt + 1}/3): {exc}")
        if priv_key is None:
            return 1

    state, derived, _ = store.public_key_sync_status(priv_key)
    output_fn(f"\nPublic key sync status: {state.upper()} ({derived[:14]}...)")

    while True:
        output_fn(
            "\nActions:\n"
            "  1) Issue permanent PC-locked license\n"
            "  2) Sync PUBLIC_KEY_B64 to app\n"
            "  3) Show issued licenses history\n"
            "  4) Backup encrypted private key (.pem)\n"
            "  5) Export Owner Setup File (OwnerKey.uikey) for your client\n"
            "  0) Exit"
        )
        choice = input_fn("Select [1/2/3/4/5/0]: ").strip()
        if choice == "0":
            return 0
        elif choice == "1":
            label = input_fn("Friend / PC label: ").strip()
            prompt_code = (
                f"16-char Request Code (press Enter for this PC {local_code}): "
                if local_code != "UNAVAILABLE"
                else "16-char Request Code: "
            )
            code = input_fn(prompt_code).strip()
            if not code and local_code != "UNAVAILABLE":
                code = local_code
            try:
                signed = store.issue_license(priv_key, label, code)
                output_fn("\n" + "-" * 64)
                output_fn(format_whatsapp_message(signed))
                output_fn("-" * 64)
                save_path = input_fn("Optional path to save .lic file (or Enter to skip): ").strip()
                if save_path:
                    _atomic_write_bytes(
                        Path(save_path), format_lic_file_content(signed).encode("utf-8")
                    )
                    output_fn(f"Saved .lic file to: {save_path}")
            except Exception as exc:
                output_fn(f"Error issuing license: {exc}")
        elif choice == "2":
            try:
                pub = store.sync_public_key(priv_key)
                output_fn(f"Synced PUBLIC_KEY_B64 ({pub[:14]}...) to {store.public_key_file}")
            except Exception as exc:
                output_fn(f"Sync failed: {exc}")
        elif choice == "3":
            rows = store.load_history()
            if not rows:
                output_fn("No licenses issued yet.")
            else:
                for row in rows:
                    output_fn(
                        f"- {row.get('issued_at_utc')} | {row.get('friend_name')} | "
                        f"{row.get('request_code')} | {row.get('license_id')}"
                    )
        elif choice == "4":
            dest = input_fn("Backup .pem destination file path: ").strip()
            if dest:
                try:
                    saved = store.export_backup_pem(Path(dest))
                    output_fn(f"Backup saved to: {saved}")
                except Exception as exc:
                    output_fn(f"Backup failed: {exc}")
        elif choice == "5":
            default_uikey = REPO_ROOT.parent / "OwnerKey.uikey"
            dest_raw = input_fn(
                f"Output .uikey path (press Enter for {default_uikey}): "
            ).strip()
            dest_path = Path(dest_raw) if dest_raw else default_uikey
            c1 = secret_fn("Create a simple Setup Code for the Owner (min 4 chars/digits): ").strip()
            if len(c1) < 4:
                output_fn("Error: Setup Code must be at least 4 characters or digits.")
                continue
            c2 = secret_fn("Confirm Setup Code: ").strip()
            if c1 != c2:
                output_fn("Error: Setup Codes do not match.")
                continue
            try:
                saved = export_owner_bundle(priv_key, c1, dest_path)
                output_fn(
                    f"\nSaved Owner Setup File: {saved}\n"
                    "Next steps:\n"
                    "  1. Put OwnerKey.uikey next to UIIC_License_Generator.exe and send to Owner.\n"
                    "  2. Send the Setup Code to Owner privately (they enter it once).\n"
                    "  3. Never commit OwnerKey.uikey to Git."
                )
            except Exception as exc:
                output_fn(f"Export failed: {exc}")
        else:
            output_fn("Invalid choice.")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="UIIC Surveyor Automation — Owner & Developer License Generator"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Override issuer directory (defaults to %%LOCALAPPDATA%%\\UIIC_License_Issuer)",
    )
    parser.add_argument(
        "--public-key-file",
        type=Path,
        default=None,
        help="Override path to app/licensing/public_key.py",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Use interactive terminal mode",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Developer mode: manage keypair, export OwnerKey.uikey, sync public key",
    )
    args = parser.parse_args(argv)

    if not args.dev and not args.cli:
        from tools.owner_generator_app import main as owner_main

        owner_argv: List[str] = []
        if args.data_dir is not None:
            owner_argv.extend(["--data-dir", str(args.data_dir)])
        return owner_main(owner_argv)

    store = IssuerStore(data_dir=args.data_dir, public_key_file=args.public_key_file)

    if args.cli:
        return run_cli(store)

    try:
        from PyQt6.QtWidgets import QApplication

        window_cls = get_generator_window_class()
    except ImportError as exc:
        print(f"Note: PyQt6 GUI unavailable ({exc}). Switching to CLI mode.\n")
        return run_cli(store)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("UIIC License Generator (Dev)")
    win = window_cls(store)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
