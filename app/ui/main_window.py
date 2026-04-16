"""
main_window.py  - Desktop UI and worker orchestration.
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
    QFileDialog, QFrame, QSizePolicy, QScrollArea,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QSpacerItem, QApplication,
)

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")

STEPS = [
    ("Login",            "🔐"),
    ("Navigate to Claim","🗺"),
    ("Interim Report",   "📋"),
    ("Claim Documents",  "📂"),
    ("Claim Assessment", "📊"),
    ("Complete",         "✅"),
]


# ── Automation Worker ────────────────────────────────────────────────
class AutomationWorker(QObject):
    log_signal  = pyqtSignal(str)
    step_signal = pyqtSignal(int, str)
    done_signal = pyqtSignal(bool, str)

    def __init__(self, claim, settings_override):
        super().__init__()
        self.claim             = claim
        self.settings_override = settings_override
        self._engine           = None

    def run(self):
        from app.automation.engine import AutomationEngine
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._engine = AutomationEngine(
            log_cb  = lambda msg: self.log_signal.emit(msg),
            step_cb = lambda i, s: self.step_signal.emit(i, s),
        )
        try:
            result = loop.run_until_complete(
                self._engine.run(self.claim, self.settings_override)
            )
            success = bool(getattr(result, "success", False))
            message = getattr(result, "message", "Automation finished.")
            self.done_signal.emit(success, message)
        except Exception as e:
            self.done_signal.emit(False, str(e))
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            asyncio.set_event_loop(None)
            loop.close()

    def stop(self):
        if self._engine:
            self._engine.request_stop()


# ── Reusable Widgets ─────────────────────────────────────────────────
def _hline():
    """Thin horizontal separator line."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet("background:#E5E7EB; border:none;")
    return line


def _label(text, object_name=None, bold=False, secondary=False):
    lbl = QLabel(text)
    if object_name:
        lbl.setObjectName(object_name)
    if bold:
        lbl.setStyleSheet("font-weight:700;")
    if secondary:
        lbl.setStyleSheet("color:#6B7280; font-size:8.5pt;")
    return lbl


def _field_label(text):
    lbl = QLabel(text)
    lbl.setObjectName("fieldLabel")
    return lbl


def _input(placeholder="", echo_password=False):
    inp = QLineEdit()
    inp.setPlaceholderText(placeholder)
    if echo_password:
        inp.setEchoMode(QLineEdit.EchoMode.Password)
    inp.setMinimumHeight(34)
    return inp


def _card(content_widget, title=None, subtitle=None):
    """Wrap a widget in a white card with optional title."""
    outer = QWidget()
    outer.setObjectName("card")
    lay = QVBoxLayout(outer)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(8)
    if title:
        row = QHBoxLayout()
        t = QLabel(title)
        t.setObjectName("cardTitle")
        row.addWidget(t)
        row.addStretch()
        lay.addLayout(row)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("cardSubtitle")
        lay.addWidget(s)
    lay.addWidget(content_widget)
    return outer


# ── Sidebar Step Widget ───────────────────────────────────────────────
class SidebarStepList(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._lay    = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(2)
        self._buttons = []

        title = QLabel("PROGRESS")
        title.setObjectName("sidebarTitle")
        self._lay.addWidget(title)

        for i, (name, icon) in enumerate(STEPS):
            btn = QPushButton(f"  {icon}  {name}")
            btn.setObjectName("stepItem")
            btn.setProperty("state", "pending")
            btn.setMinimumHeight(36)
            btn.setCheckable(False)
            btn.setFlat(True)
            btn.setCursor(Qt.CursorShape.ArrowCursor)
            self._buttons.append(btn)
            self._lay.addWidget(btn)

        self._lay.addStretch()

    def set_step(self, active_idx: int):
        for i, btn in enumerate(self._buttons):
            if i < active_idx:
                btn.setProperty("state", "done")
            elif i == active_idx:
                btn.setProperty("state", "active")
            else:
                btn.setProperty("state", "pending")
            # Force style refresh
            btn.style().unpolish(btn)
            btn.style().polish(btn)


# ── Main Window ───────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._worker      = None
        self._thread      = None
        self._claim       = None
        self._scan_result = None
        self._setup_ui()
        self._load_settings()

    # ── BUILD UI ───────────────────────────────────────────────────────
    def _setup_ui(self):
        self.setWindowTitle("UIIC Surveyor Automation")
        self.setMinimumSize(1020, 700)
        self.resize(1160, 820)

        root_widget = QWidget()
        root_widget.setObjectName("rootWidget")
        root_widget.setStyleSheet("background:#F9FAFB;")
        root_layout = QVBoxLayout(root_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root_widget)

        # Top bar
        topbar = self._build_topbar()
        root_layout.addWidget(topbar)

        # Body: sidebar + content
        body = QWidget()
        body.setStyleSheet("background:#F9FAFB;")
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
        bar.setFixedHeight(52)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 0, 20, 0)

        logo = QLabel("⚡  UIIC Automation")
        logo.setObjectName("appLogo")

        ver = QLabel("v1.0")
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
        sidebar.setFixedWidth(190)
        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(0, 0, 0, 16)
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
        inner.setStyleSheet("background:#F9FAFB;")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        # Page heading
        heading = QLabel("Claim Automation")
        heading.setStyleSheet("font-size:18pt; font-weight:800; color:#111827; letter-spacing:-0.5px;")
        sub = QLabel("Fill and submit insurance claim forms automatically.")
        sub.setStyleSheet("font-size:9.5pt; color:#6B7280; margin-bottom:4px;")
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
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        # Row 0
        grid.addWidget(_field_label("Username"), 0, 0)
        self.inp_username = _input("Portal username / ID")
        grid.addWidget(self.inp_username, 1, 0)

        grid.addWidget(_field_label("Password"), 0, 1)
        self.inp_password = _input("Portal password", echo_password=True)
        grid.addWidget(self.inp_password, 1, 1)

        grid.addWidget(_field_label("Claim Number"), 0, 2)
        self.inp_claim_no = _input("Auto-detected or enter manually")
        grid.addWidget(self.inp_claim_no, 1, 2)

        grid.addWidget(_field_label("Claim Type"), 0, 3)
        self.inp_claim_type = _input("e.g. Non Maruti")
        grid.addWidget(self.inp_claim_type, 1, 3)

        outer = _card(w, title="Configuration", subtitle="Portal credentials and claim details")
        return outer

    def _build_folder_card(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self.inp_folder = _input("Click Browse to select the folder containing Excel + documents...")
        self.inp_folder.setReadOnly(True)
        self.inp_folder.setStyleSheet(
            "QLineEdit { background:#F9FAFB; border:1.5px solid #E5E7EB; border-radius:6px; padding:7px 10px; color:#374151; }"
        )

        btn = QPushButton("Browse")
        btn.setObjectName("btnBrowse")
        btn.setFixedWidth(90)
        btn.setMinimumHeight(34)
        btn.clicked.connect(self._browse_folder)
        lay.addWidget(self.inp_folder, 1)
        lay.addWidget(btn)

        outer = _card(w, title="Claim Folder", subtitle="Select folder with Excel file and scanned documents")
        return outer

    def _build_preview_card(self):
        container = QWidget()
        vlay = QVBoxLayout(container)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(8)

        # Summary table
        self.preview_table = QTableWidget(0, 2)
        self.preview_table.setHorizontalHeaderLabels(["Field", "Value"])
        self.preview_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.preview_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.preview_table.setShowGrid(False)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setStyleSheet(
            "QTableWidget { alternate-background-color:#F9FAFB; }"
        )
        self.preview_table.setMaximumHeight(220)
        vlay.addWidget(self.preview_table)

        # Document chips
        self.doc_status_label = QLabel("No folder selected. Click Browse to begin.")
        self.doc_status_label.setWordWrap(True)
        self.doc_status_label.setStyleSheet(
            "color:#9CA3AF; font-size:8.5pt; padding:4px 0;"
        )
        vlay.addWidget(self.doc_status_label)

        outer = _card(container, title="Extracted Data", subtitle="Values auto-populated from Excel file")
        return outer

    def _build_progress_card(self):
        container = QWidget()
        vlay = QVBoxLayout(container)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(6)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, len(STEPS) - 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(5)
        vlay.addWidget(self.progress_bar)

        self.progress_label = QLabel("Waiting for folder selection...")
        self.progress_label.setStyleSheet("color:#6B7280; font-size:8.5pt;")
        vlay.addWidget(self.progress_label)

        outer = _card(container, title="Progress")
        return outer

    def _build_log_card(self):
        self.log_panel = QTextEdit()
        self.log_panel.setObjectName("logPanel")
        self.log_panel.setReadOnly(True)
        self.log_panel.setMinimumHeight(220)
        self.log_panel.setMaximumHeight(320)

        outer = _card(self.log_panel, title="Live Log", subtitle="Real-time automation output")
        return outer

    # ── ACTION BAR ─────────────────────────────────────────────────────
    def _build_action_bar(self):
        bar = QFrame()
        bar.setStyleSheet(
            "background:#FFFFFF; border-top:1px solid #E5E7EB;"
        )
        bar.setFixedHeight(60)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(24, 0, 24, 0)
        lay.setSpacing(8)

        self.btn_start = QPushButton("▶  Start Automation")
        self.btn_start.setObjectName("btnStart")
        self.btn_start.setMinimumHeight(38)
        self.btn_start.clicked.connect(self._start_automation)

        self.btn_stop = QPushButton("■  Stop")
        self.btn_stop.setObjectName("btnStop")
        self.btn_stop.setFixedWidth(90)
        self.btn_stop.setMinimumHeight(38)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_automation)

        self.btn_export = QPushButton("↓  Export Log")
        self.btn_export.setObjectName("btnExport")
        self.btn_export.setFixedWidth(110)
        self.btn_export.setMinimumHeight(38)
        self.btn_export.clicked.connect(self._export_log)

        lay.addWidget(self.btn_start)
        lay.addWidget(self.btn_stop)
        lay.addStretch()
        lay.addWidget(self.btn_export)

        return bar

    # ── LOGIC (unchanged) ──────────────────────────────────────────────
    def _load_settings(self):
        try:
            with open(os.path.join(CONFIG_DIR, "settings.json"), "r") as f:
                s = json.load(f)
            self.inp_username.setText(s.get("username", ""))
            self.inp_password.setText(s.get("password", ""))
            self.inp_claim_type.setText(s.get("claim_type", "Non Maruti"))
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
                if self.inp_claim_no.text().strip():
                    self._claim.claim_no = self.inp_claim_no.text().strip()
                elif self._claim.claim_no:
                    self.inp_claim_no.setText(self._claim.claim_no)
                if not self._claim.claim_no:
                    self._append_log("⚠️  Claim No not found in Excel — enter manually.")
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
        fields = [
            ("Claim No",           self._claim.claim_no or "—"),
            ("Date of Survey",     self._claim.date_of_survey or "—"),
            ("Place of Survey",    self._claim.place_of_survey or "—"),
            ("Odometer",           self._claim.odometer or "—"),
            ("Initial Loss (₹)",   self._claim.initial_loss_amount or "—"),
            ("Labour (Excl GST)",  f"₹ {self._claim.labour_excl_gst}"),
            ("Compulsory Excess",  f"₹ {self._claim.compulsory_excess}"),
            ("Report No",          self._claim.final_report_no or "—"),
            ("Total Survey Fee",   f"₹ {self._claim.total_claimed_amount}"),
        ]
        self.preview_table.setRowCount(len(fields))
        for i, (k, v) in enumerate(fields):
            k_item = QTableWidgetItem(k)
            k_item.setForeground(QColor("#6B7280"))
            v_item = QTableWidgetItem(str(v))
            v_item.setForeground(QColor("#111827") if v and v != "—" else QColor("#9CA3AF"))
            if v and v != "—":
                font = v_item.font()
                font.setWeight(QFont.Weight.Medium)
                v_item.setFont(font)
            self.preview_table.setItem(i, 0, k_item)
            self.preview_table.setItem(i, 1, v_item)

    def _update_doc_chips(self):
        if not self._scan_result:
            return
        docs  = list(self._scan_result.claim_doc_files.keys())
        asses = list(self._scan_result.assessment_files.keys())
        all_docs = docs + asses
        unkn = len(self._scan_result.unknown_files)
        if all_docs:
            chips  = "  ".join([f"● {d}" for d in all_docs])
            unkn_t = f"  +{unkn} unrecognised" if unkn else ""
            self.doc_status_label.setStyleSheet(
                "color:#374151; font-size:8.5pt; padding:4px 0;"
            )
            self.doc_status_label.setText(
                f"{len(all_docs)} documents detected — {chips}{unkn_t}"
            )
        else:
            self.doc_status_label.setText("No documents detected. Check folder contents.")

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

        settings_override = {
            "username":   self.inp_username.text().strip(),
            "password":   self.inp_password.text().strip(),
            "claim_type": self.inp_claim_type.text().strip(),
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
        if any(x in raw_message for x in ("✅", "successful", "complete", "found")):
            color = "#059669"
        elif any(x in raw_message for x in ("❌", "ERROR", "failed", "STOPPED")):
            color = "#DC2626"
        elif any(x in raw_message for x in ("⚠️", "warning", "retrying")):
            color = "#D97706"
        elif "━" in raw_message:
            color = "#374151"
        elif any(x in raw_message for x in ("🎉", "COMPLETE")):
            color = "#059669"
        else:
            color = "#374151"

        display_message = html.escape(raw_message)
        if "━" in raw_message:
            display_message = f"<b>{display_message}</b>"

        log_html = (
            f'<span style="color:#9CA3AF; font-size:8pt;">[{ts}]</span>'
            f'&nbsp;<span style="color:{color};">{display_message}</span>'
        )
        self.log_panel.append(log_html)
        self.log_panel.moveCursor(QTextCursor.MoveOperation.End)

        # Write to file
        log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "automation.log"), "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {raw_message}\n")

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
        super().closeEvent(event)
