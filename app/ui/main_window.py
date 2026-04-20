"""
main_window.py  - Desktop UI and worker orchestration.

FIXES 2026-04-18:
  B3/P1: Log file now buffered — opened once per session, not per call.
  B4:    has_value check: '0' is valid — never shown as red/missing.
  F2:    Claim No field edit triggers preview refresh via textChanged signal.
  F3:    Automation done marks the final 'Complete' step in the sidebar.
  F6:    'Clear Log' button added to action bar.
  F7:    Validation bar style correctly resets between error/warning states.
"""
import html
import json
import os
import asyncio
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore    import Qt, QThread, pyqtSignal, QObject, QSize
from PyQt6.QtGui     import QFont, QColor, QTextCursor, QIcon
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QProgressBar, QTextEdit,
    QFileDialog, QFrame, QSizePolicy, QScrollArea, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QSpacerItem, QApplication,
)

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")

from app.ui.worker import AutomationWorker
from app.ui.components.widgets import (
    STEPS, hline as _hline, create_label as _label, field_label as _field_label,
    create_input as _input, card as _card, SidebarStepList
)


# ── Main Window ───────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._worker      = None
        self._thread      = None
        self._claim       = None
        self._scan_result = None
        # B3/P1: Single log file handle opened once, closed on exit
        self._log_file    = None
        self._open_log_file()
        self._setup_ui()
        self._load_settings()

    # ── BUILD UI ───────────────────────────────────────────────────────
    def _setup_ui(self):
        self.setWindowTitle("UIIC Surveyor Automation")
        self.setMinimumSize(1060, 720)
        self.resize(1220, 860)

        root_widget = QWidget()
        root_widget.setObjectName("rootWidget")
        root_layout = QVBoxLayout(root_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root_widget)

        # Top bar
        topbar = self._build_topbar()
        root_layout.addWidget(topbar)

        # Body: sidebar + content
        body = QWidget()
        body.setObjectName("bodyWidget")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        sidebar = self._build_sidebar()
        body_layout.addWidget(sidebar)

        content = self._build_content()
        body_layout.addWidget(content, 1)

        root_layout.addWidget(body, 1)

        # Bottom action bar
        action_bar = self._build_action_bar()
        root_layout.addWidget(action_bar)

    # ── TOPBAR ─────────────────────────────────────────────────────────
    def _build_topbar(self):
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(48)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 0, 20, 0)

        logo = QLabel("UIIC Automation")
        logo.setObjectName("appLogo")

        ver = QLabel("v2.0")
        ver.setObjectName("appVersion")

        lay.addWidget(logo)
        lay.addWidget(ver)
        lay.addStretch()

        self.status_pill = QLabel("● Ready")
        self.status_pill.setObjectName("statusPill")
        self.status_pill.setProperty("status", "ready")
        lay.addWidget(self.status_pill)

        return bar

    # ── SIDEBAR ────────────────────────────────────────────────────────
    def _build_sidebar(self):
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(200)
        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.step_list = SidebarStepList()
        lay.addWidget(self.step_list)

        return sidebar

    # ── MAIN CONTENT ───────────────────────────────────────────────────
    def _build_content(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget()
        inner.setObjectName("innerWidget")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        # Page heading
        heading = QLabel("Claim Automation")
        heading.setStyleSheet("font-size:18pt; font-weight:bold; color:#111111;")
        sub = QLabel("Fill and submit insurance claim forms automatically")
        sub.setStyleSheet("font-size:9.5pt; color:#777777; margin-bottom:4px;")
        lay.addWidget(heading)
        lay.addWidget(sub)

        # Card 1: Credentials
        lay.addWidget(self._build_credentials_card())

        # Card 2: Folder
        lay.addWidget(self._build_folder_card())

        # Card 3: Data preview
        lay.addWidget(self._build_preview_card())

        # Card 4: Progress
        lay.addWidget(self._build_progress_card())

        # Card 5: Log
        lay.addWidget(self._build_log_card())

        lay.addStretch()
        scroll.setWidget(inner)
        return scroll

    def _build_credentials_card(self):
        w = QWidget()
        grid = QGridLayout(w)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(3, 1)

        grid.addWidget(_field_label("USERNAME"), 0, 0)
        self.inp_username = _input("Portal username / ID")
        grid.addWidget(self.inp_username, 1, 0)

        grid.addWidget(_field_label("PASSWORD"), 0, 1)
        self.inp_password = _input("Portal password", echo_password=True)
        grid.addWidget(self.inp_password, 1, 1)

        grid.addWidget(_field_label("CLAIM NUMBER"), 0, 2)
        self.inp_claim_no = _input("Auto-detected or enter manually")
        grid.addWidget(self.inp_claim_no, 1, 2)

        grid.addWidget(_field_label("CLAIM TYPE"), 0, 3)
        self.inp_claim_type = QComboBox()
        self.inp_claim_type.addItems(["Non Maruti", "Maruti"])
        self.inp_claim_type.setMinimumHeight(36)
        grid.addWidget(self.inp_claim_type, 1, 3)

        return _card(w, title="Configuration", subtitle="Portal credentials and claim details")

    def _build_folder_card(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(10)

        self.inp_folder = _input("Click Browse to select the claim folder...")
        self.inp_folder.setReadOnly(True)
        self.inp_folder.setStyleSheet(
            "QLineEdit { background:#F5F5F5; border:1.5px solid #DDDDDD; border-radius:6px; padding:7px 10px; color:#333333; }"
        )

        btn = QPushButton("Browse...")
        btn.setObjectName("btnBrowse")
        btn.setFixedWidth(110)
        btn.setMinimumHeight(38)
        btn.clicked.connect(self._browse_folder)
        lay.addWidget(self.inp_folder, 1)
        lay.addWidget(btn)

        return _card(w, title="Claim Folder", subtitle="Select folder with Excel file and scanned documents")

    def _build_preview_card(self):
        container = QWidget()
        vlay = QVBoxLayout(container)
        vlay.setContentsMargins(0, 4, 0, 0)
        vlay.setSpacing(8)

        # Validation warning bar (hidden until folder scanned)
        self.validation_bar = QLabel("")
        self.validation_bar.setWordWrap(True)
        self.validation_bar.setVisible(False)
        self.validation_bar.setStyleSheet(
            "background:#FFEEEE; color:#CC0000; border:1px solid #FFCCCC;"
            "border-radius:6px; padding:8px 12px; font-size:8.5pt;"
        )
        vlay.addWidget(self.validation_bar)

        # Summary table — all fields color coded
        self.preview_table = QTableWidget(0, 4)
        self.preview_table.setHorizontalHeaderLabels(["FIELD", "VALUE", "SOURCE", "STATUS"])
        self.preview_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.preview_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.preview_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.preview_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.preview_table.setShowGrid(False)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setStyleSheet(
            "QTableWidget { alternate-background-color:#FAFAFA; border:1px solid #EEEEEE; border-radius:4px; }"
            "QHeaderView::section { background-color:#F0F0F0; font-weight:bold; color:#555555; padding:6px; border:none; border-bottom:1px solid #DDDDDD; }"
            "QTableWidget::item { padding: 4px 8px; }"
        )
        self.preview_table.setMinimumHeight(280)
        self.preview_table.setMaximumHeight(400)
        vlay.addWidget(self.preview_table)

        # Document status bar
        self.doc_status_label = QLabel("No folder selected -- click Browse to begin.")
        self.doc_status_label.setWordWrap(True)
        self.doc_status_label.setStyleSheet(
            "color:#AAAAAA; font-size:8.5pt; padding:4px 0;"
        )
        vlay.addWidget(self.doc_status_label)

        return _card(container, title="Extracted Data",
                     subtitle="Red = Critical missing  /  Yellow = Optional  /  Green = Found")

    def _build_progress_card(self):
        container = QWidget()
        vlay = QVBoxLayout(container)
        vlay.setContentsMargins(0, 4, 0, 0)
        vlay.setSpacing(8)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, len(STEPS) - 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        vlay.addWidget(self.progress_bar)

        self.progress_label = QLabel("Waiting for folder selection...")
        self.progress_label.setStyleSheet("color:#888888; font-size:9pt;")
        vlay.addWidget(self.progress_label)

        return _card(container, title="Progress")

    def _build_log_card(self):
        self.log_panel = QTextEdit()
        self.log_panel.setObjectName("logPanel")
        self.log_panel.setReadOnly(True)
        self.log_panel.setMinimumHeight(240)
        self.log_panel.setMaximumHeight(360)

        return _card(self.log_panel, title="Live Log", subtitle="Real-time automation output")

    # ── ACTION BAR ─────────────────────────────────────────────────────
    def _build_action_bar(self):
        bar = QFrame()
        bar.setObjectName("actionBar")
        bar.setMinimumHeight(64)
        bar.setMaximumHeight(64)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(28, 0, 28, 0)
        lay.setSpacing(10)

        self.btn_start = QPushButton("  Start Automation  ")
        self.btn_start.setObjectName("btnStart")
        self.btn_start.setMinimumHeight(42)
        self.btn_start.setMinimumWidth(200)
        self.btn_start.clicked.connect(self._start_automation)

        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setObjectName("btnStop")
        self.btn_stop.setFixedWidth(100)
        self.btn_stop.setMinimumHeight(42)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_automation)

        self.btn_clear = QPushButton("Clear Log")
        self.btn_clear.setObjectName("btnClear")
        self.btn_clear.setFixedWidth(110)
        self.btn_clear.setMinimumHeight(42)
        self.btn_clear.clicked.connect(self._clear_log)

        self.btn_export = QPushButton("Export Log")
        self.btn_export.setObjectName("btnExport")
        self.btn_export.setFixedWidth(120)
        self.btn_export.setMinimumHeight(42)
        self.btn_export.clicked.connect(self._export_log)

        lay.addWidget(self.btn_start)
        lay.addWidget(self.btn_stop)
        lay.addStretch()
        lay.addWidget(self.btn_clear)
        lay.addWidget(self.btn_export)

        return bar

    # ── LOGIC ─────────────────────────────────────────────────────────
    def _open_log_file(self):
        """B3/P1: Open log file once at startup instead of per log call.
           Implements log rotation to keep the last 5 sessions."""
        try:
            log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
            os.makedirs(log_dir, exist_ok=True)
            
            base_log = os.path.join(log_dir, "automation.log")
            
            if os.path.exists(base_log):
                for i in range(4, 0, -1):
                    old_log = f"{base_log}.{i}"
                    new_log = f"{base_log}.{i+1}"
                    if os.path.exists(old_log):
                        if os.path.exists(new_log):
                            os.remove(new_log)
                        os.rename(old_log, new_log)
                
                new_log_1 = f"{base_log}.1"
                if os.path.exists(new_log_1):
                    os.remove(new_log_1)
                os.rename(base_log, new_log_1)
                
            self._log_file = open(base_log, "w", encoding="utf-8")
        except Exception:
            self._log_file = None

    def _load_settings(self):
        try:
            with open(os.path.join(CONFIG_DIR, "settings.json"), "r") as f:
                s = json.load(f)
            self.inp_username.setText(s.get("username", ""))
            self.inp_password.setText(s.get("password", ""))
            self.inp_claim_type.setCurrentText(s.get("claim_type", "Non Maruti"))
        except Exception:
            pass

    def _save_settings(self, overrides: dict):
        path = os.path.join(CONFIG_DIR, "settings.json")
        try:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    settings = json.load(f)
            except Exception:
                settings = {}
            settings.update(overrides)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2)
        except Exception as exc:
            self._append_log(f"⚠️  Could not save settings: {exc}")

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Claim Folder")
        if not folder:
            return
        self.inp_folder.setText(folder)
        self._scan_folder(folder)

    def _scan_folder(self, folder: str):
        from app.data.folder_scanner import scan_folder
        from app.data.excel_reader   import read_excel
        self._append_log(f"📁 Scanning folder: {folder}")
        try:
            self._scan_result = scan_folder(folder, CONFIG_DIR)
            if not self._scan_result.excel_path:
                self._append_log("⚠️  No Excel file found in folder!")
                self._set_status("ready", "No Excel found")
            else:
                self._append_log(f"📊 Excel: {Path(self._scan_result.excel_path).name}")
                self._claim = read_excel(self._scan_result.excel_path, CONFIG_DIR)
                self._claim.claim_doc_files  = self._scan_result.claim_doc_files
                self._claim.assessment_files = self._scan_result.assessment_files
                
                # Output the exact coordinates of where data was found
                if hasattr(self._claim, "_excel_logs") and self._claim._excel_logs:
                    self._append_log("📌 Excel Data Sources Map:")
                    for lg in self._claim._excel_logs:
                        self._append_log(lg)
                
                if self.inp_claim_no.text().strip():
                    self._claim.claim_no = self.inp_claim_no.text().strip()
                elif self._claim.claim_no:
                    self.inp_claim_no.setText(self._claim.claim_no)
                if not self._claim.claim_no:
                    self._append_log("⚠️  Claim No not found in Excel — enter manually.")
                # F2: connect claim_no edits to live preview refresh (once)
                try:
                    self.inp_claim_no.textChanged.disconnect()
                except Exception:
                    pass
                self.inp_claim_no.textChanged.connect(self._on_claim_no_changed)
                self._update_preview()
                self._set_status("ready", "Folder scanned — ready to start")
        except Exception as exc:
            self._claim = None
            self._scan_result = None
            self._set_status("error", "Folder scan failed")
            self._append_log(f"❌ ERROR: Failed to read selected folder: {exc}")
        self._update_doc_chips()

    def _update_preview(self):
        if not self._claim:
            return

        # Sync claim_no from UI field into claim object before validating
        typed_claim_no = self.inp_claim_no.text().strip()
        if typed_claim_no:
            self._claim.claim_no = typed_claim_no
        elif self._claim.claim_no:
            self.inp_claim_no.setText(self._claim.claim_no)

        # Run validation and show errors/warnings
        errors, warnings = self._claim.validate()
        if errors:
            err_text = "❌ MISSING CRITICAL FIELDS — Automation cannot start:\n" + \
                       "\n".join(f"  • {e}" for e in errors)
            if warnings:
                err_text += "\n⚠️  Warnings: " + " | ".join(warnings)
            self.validation_bar.setStyleSheet(
                "background:#FFEEEE; color:#CC0000; border:1px solid #FFCCCC;"
                "border-radius:6px; padding:8px 12px; font-size:8.5pt;"
            )
            self.validation_bar.setText(err_text)
            self.validation_bar.setVisible(True)
        elif warnings:
            self.validation_bar.setStyleSheet(
                "background:#FFFFF0; color:#886600; border:1px solid #EEEE99;"
                "border-radius:6px; padding:8px 12px; font-size:8.5pt;"
            )
            self.validation_bar.setText(
                "⚠️  Optional fields missing: " + " | ".join(warnings)
            )
            self.validation_bar.setVisible(True)
        else:
            self.validation_bar.setVisible(False)

        # Populate all fields table with color coding
        all_fields = self._claim.all_fields_for_preview()
        self.preview_table.setRowCount(len(all_fields))
        for i, (label, value, is_critical, source_coord) in enumerate(all_fields):
            # B4 FIX: "0" IS a valid value (odometer, zero amounts) — do NOT mark as missing
            has_value = bool(value and str(value).strip() not in ("", "—"))

            k_item = QTableWidgetItem(label)
            k_item.setForeground(QColor("#333333"))
            self.preview_table.setItem(i, 0, k_item)

            # Value column
            display = value if value else "—"
            v_item = QTableWidgetItem(display)
            if has_value:
                v_item.setForeground(QColor("#000000"))
                font = v_item.font()
                font.setWeight(QFont.Weight.DemiBold)
                v_item.setFont(font)
            elif is_critical:
                v_item.setForeground(QColor("#CC0000"))
            else:
                v_item.setForeground(QColor("#AAAAAA"))
            self.preview_table.setItem(i, 1, v_item)

            # Source column (Column 2)
            src_display = source_coord if source_coord else "—"
            src_item = QTableWidgetItem(src_display)
            src_item.setForeground(QColor("#0066CC") if source_coord else QColor("#AAAAAA"))
            self.preview_table.setItem(i, 2, src_item)

            if has_value:
                status = "OK"
            elif is_critical:
                status = "MISS"
            else:
                status = "OPT"
            s_item = QTableWidgetItem(status)
            s_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if has_value:
                s_item.setForeground(QColor("#000000"))
            elif is_critical:
                s_item.setForeground(QColor("#CC0000"))
            else:
                s_item.setForeground(QColor("#AAAAAA"))
            self.preview_table.setItem(i, 3, s_item)

    def _update_doc_chips(self):
        if not self._scan_result:
            return
        docs  = self._scan_result.claim_doc_files
        asses = self._scan_result.assessment_files
        unkn  = getattr(self._scan_result, 'unknown_files', [])
        total = len(docs) + len(asses)
        if total:
            claim_part = f"Claim docs: {len(docs)}" if docs else ""
            asses_part = f"Assessment: {len(asses)}" if asses else ""
            unkn_part  = f"Unknown: {len(unkn)}" if unkn else ""
            parts = [p for p in [claim_part, asses_part, unkn_part] if p]
            self.doc_status_label.setStyleSheet(
                "color:#333333; font-size:8.5pt; padding:4px 0;"
            )
            self.doc_status_label.setText("  |  ".join(parts))
        else:
            self.doc_status_label.setStyleSheet(
                "color:#CC0000; font-size:8.5pt; padding:4px 0;"
            )
            self.doc_status_label.setText("No documents detected -- check folder contents.")

    def _set_status(self, status: str, text: str):
        icons = {"ready": "●", "running": "◉", "error": "✕"}
        self.status_pill.setText(f"{icons.get(status,'●')} {text}")
        self.status_pill.setProperty("status", status)
        self.status_pill.style().unpolish(self.status_pill)
        self.status_pill.style().polish(self.status_pill)

    def _start_automation(self):
        if not self._claim:
            QMessageBox.warning(self, "No Folder", "Please select a claim folder first.")
            return
        if not self.inp_username.text().strip() or not self.inp_password.text().strip():
            QMessageBox.warning(self, "Credentials Required", "Enter the portal username and password.")
            return
        self._claim.claim_no = self.inp_claim_no.text().strip() or self._claim.claim_no
        if not self._claim.claim_no:
            QMessageBox.warning(self, "Claim No Required", "Enter the Claim Number.")
            return

        # ── Validation gate — block start if critical fields missing ──────────
        errors, warnings = self._claim.validate()
        if errors:
            error_list = "\n".join(f"  • {e}" for e in errors)
            QMessageBox.critical(
                self, "Data Validation Failed",
                f"Cannot start — the following critical fields are missing from Excel:\n\n"
                f"{error_list}\n\n"
                f"Fix the Excel file or enter values manually and re-scan."
            )
            return
        if warnings:
            warn_list = "\n".join(f"  • {w}" for w in warnings)
            reply = QMessageBox.question(
                self, "Optional Fields Missing",
                f"Some optional fields are missing:\n\n{warn_list}\n\n"
                f"These fields will be skipped. Continue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        settings_override = {
            "username":   self.inp_username.text().strip(),
            "password":   self.inp_password.text().strip(),
            "claim_type": self.inp_claim_type.currentText().strip(),
        }
        self._save_settings(settings_override)
        self.progress_bar.setValue(0)
        self.step_list.set_step(0)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._set_status("running", "Automation running...")
        self._append_log("━" * 44)
        self._append_log(f"🚀 Automation started — Claim: {self._claim.claim_no}")
        self._append_log("━" * 44)

        self._worker = AutomationWorker(self._claim, settings_override)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log_signal.connect(self._append_log)
        self._worker.step_signal.connect(self._on_step)
        self._worker.done_signal.connect(self._on_done)
        self._worker.done_signal.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _stop_automation(self):
        if self._worker:
            self._worker.stop()
        self.btn_stop.setEnabled(False)
        self._append_log("■  Stop requested by user.")
        self._set_status("running", "Stopping...")
        self.progress_label.setText("Stopping automation and closing browser...")

    def _on_claim_no_changed(self, text: str):
        """F2: Refresh preview when claim number is edited manually."""
        if self._claim and text.strip():
            self._claim.claim_no = text.strip()
            self._update_preview()

    def _on_step(self, idx: int, name: str):
        self.step_list.set_step(idx)
        self.progress_bar.setValue(idx)
        if idx >= len(STEPS) - 1:
            self.progress_label.setText("Forms filled. Review in browser, then click Stop to close the session.")
        else:
            self.progress_label.setText(f"Step {idx + 1} of {len(STEPS)} — {name}")

    def _on_done(self, success: bool, msg: str):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        if success:
            # F3: mark the final 'Complete' step as active/done
            self.step_list.set_step(len(STEPS) - 1)
            self.progress_bar.setValue(len(STEPS) - 1)
            self.progress_label.setText(msg)
            self._set_status("ready", "Complete ✓")
            self._append_log(msg)
        elif "stopped by user" in msg.lower() or "cancelled" in msg.lower():
            self.progress_label.setText(msg)
            self._set_status("ready", "Stopped")
            self._append_log(msg)
        else:
            self.progress_label.setText(f"Error: {msg}")
            self._set_status("error", "Error")
            self._append_log(f"❌ ERROR: {msg}")

    def _on_thread_finished(self):
        self._worker = None
        self._thread = None

    def _append_log(self, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        raw_message = "" if message is None else str(message)
        # Colors tuned for dark terminal background (#0F172A)
        if any(x in raw_message for x in ("✅", "successful", "complete", "found")):
            color = "#66FF66"   # green
        elif any(x in raw_message for x in ("❌", "ERROR", "failed", "STOPPED")):
            color = "#FF6666"   # red
        elif any(x in raw_message for x in ("⚠️", "warning", "retrying")):
            color = "#FFCC66"   # yellow
        elif "━" in raw_message:
            color = "#FFFFFF"   # white (bold separators)
        elif any(x in raw_message for x in ("🎉", "COMPLETE")):
            color = "#66FF66"
        else:
            color = "#CCCCCC"   # light gray

        display_message = html.escape(raw_message)
        if "━" in raw_message:
            display_message = f"<b>{display_message}</b>"

        log_html = (
            f'<span style="color:#777777; font-size:8pt;">[{ts}]</span>'
            f'&nbsp;<span style="color:{color};">{display_message}</span>'
        )
        self.log_panel.append(log_html)
        self.log_panel.moveCursor(QTextCursor.MoveOperation.End)

        # B3/P1 FIX: Write to already-open file handle (not open/close per call)
        if self._log_file:
            try:
                self._log_file.write(f"[{ts}] {raw_message}\n")
                self._log_file.flush()
            except Exception:
                pass

    def _clear_log(self):
        """F6: Clear the log panel."""
        self.log_panel.clear()

    def _export_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Log",
            f"uiic_log_{datetime.now():%Y%m%d_%H%M%S}.txt",
            "Text Files (*.txt)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log_panel.toPlainText())
            self._append_log(f"📋 Log exported to: {path}")

    def closeEvent(self, event):
        if self._worker:
            self._worker.stop()
        if self._thread and self._thread.isRunning():
            self._thread.wait(5000)
        # B3 cleanup: close log file handle on exit
        if self._log_file:
            try:
                self._log_file.close()
            except Exception:
                pass
        super().closeEvent(event)
