"""
main_window.py  — Premium Dark Dashboard UI for UIIC Automation.

Layout:
  ┌──────────────── TOP BAR ────────────────┐
  │ UIIC AUTOMATION   [Home][Progress]  ● ▪ │
  ├─────────────────────────────────────────┤
  │         QStackedWidget                  │
  │  Page 0 (Home):                         │
  │    Row 1: [Config Card] [Folder Card]   │
  │    Row 2: [Stats ◻ ◻ ◻ ◻]              │
  │    Row 3: [Extracted Data Table]        │
  │  Page 1 (Progress):                     │
  │    [Step Pipeline ● ● ● ● ● ●]         │
  │    [Progress Bar Card]                  │
  │    [Live Log Card]                      │
  ├─────────────── ACTION BAR ──────────────┤
  │ [▶ Start]  [■ Stop]      [Clear][Export]│
  └─────────────────────────────────────────┘
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
    QSpacerItem, QApplication, QStackedWidget,
)

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")

from app.ui.worker import AutomationWorker
from app.ui.components.widgets import (
    STEPS, hline as _hline, create_label as _label, field_label as _field_label,
    create_input as _input, card as _card, stat_card as _stat_card, StepPipeline
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

    # ══════════════════════════════════════════════════════════════════
    # BUILD UI
    # ══════════════════════════════════════════════════════════════════
    def _setup_ui(self):
        self.setWindowTitle("UIIC Automation")
        self.setMinimumSize(1060, 720)
        self.resize(1260, 880)

        root_widget = QWidget()
        root_widget.setObjectName("rootWidget")
        root_layout = QVBoxLayout(root_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root_widget)

        # Top bar
        root_layout.addWidget(self._build_topbar())

        # Stacked pages: Home (0) / Progress (1)
        self.stack = QStackedWidget()
        self.stack.setObjectName("pageStack")
        self.stack.addWidget(self._build_home_page())       # index 0
        self.stack.addWidget(self._build_progress_page())    # index 1
        root_layout.addWidget(self.stack, 1)

        # Bottom action bar
        root_layout.addWidget(self._build_action_bar())

    # ── TOPBAR ─────────────────────────────────────────────────────────
    def _build_topbar(self):
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(56)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(24, 0, 24, 0)

        # Left: Logo
        logo_container = QWidget()
        logo_container.setObjectName("logoContainer")
        logo_lay = QHBoxLayout(logo_container)
        logo_lay.setContentsMargins(0, 0, 0, 0)
        logo_lay.setSpacing(8)

        logo = QLabel("UIIC")
        logo.setObjectName("appLogo")
        logo_sub = QLabel("AUTOMATION")
        logo_sub.setObjectName("appLogoSub")
        logo_lay.addWidget(logo)
        logo_lay.addWidget(logo_sub)

        lay.addWidget(logo_container)
        lay.addStretch()

        # Center: Nav buttons
        nav = QWidget()
        nav.setObjectName("navContainer")
        nav_lay = QHBoxLayout(nav)
        nav_lay.setContentsMargins(4, 4, 4, 4)
        nav_lay.setSpacing(4)

        self.btn_home = QPushButton("⌂  Home")
        self.btn_home.setObjectName("navBtn")
        self.btn_home.setProperty("active", True)
        self.btn_home.setMinimumHeight(36)
        self.btn_home.setMinimumWidth(110)
        self.btn_home.clicked.connect(lambda: self._switch_page(0))

        self.btn_progress = QPushButton("◎  Progress")
        self.btn_progress.setObjectName("navBtn")
        self.btn_progress.setProperty("active", False)
        self.btn_progress.setMinimumHeight(36)
        self.btn_progress.setMinimumWidth(110)
        self.btn_progress.clicked.connect(lambda: self._switch_page(1))

        nav_lay.addWidget(self.btn_home)
        nav_lay.addWidget(self.btn_progress)

        lay.addWidget(nav)
        lay.addStretch()

        # Right: Version + Status
        ver = QLabel("v3.0")
        ver.setObjectName("appVersion")

        self.status_pill = QLabel("● Ready")
        self.status_pill.setObjectName("statusPill")
        self.status_pill.setProperty("status", "ready")

        lay.addWidget(ver)
        lay.addWidget(self.status_pill)

        return bar

    # ── PAGE SWITCHING ─────────────────────────────────────────────────
    def _switch_page(self, idx):
        self.stack.setCurrentIndex(idx)
        self.btn_home.setProperty("active", idx == 0)
        self.btn_progress.setProperty("active", idx == 1)
        for btn in [self.btn_home, self.btn_progress]:
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # ══════════════════════════════════════════════════════════════════
    # HOME PAGE
    # ══════════════════════════════════════════════════════════════════
    def _build_home_page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget()
        inner.setObjectName("homePage")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)

        # ── Page heading ────────────────────────────────────────────
        heading_sub = QLabel("AUTOMATION ENGINE")
        heading_sub.setObjectName("pageHeadingSub")
        heading = QLabel("Claim Processing")
        heading.setObjectName("pageHeading")
        lay.addWidget(heading_sub)
        lay.addWidget(heading)
        lay.addSpacing(4)

        # ── Row 1: Config | Folder ──────────────────────────────────
        row1 = QWidget()
        row1_lay = QHBoxLayout(row1)
        row1_lay.setContentsMargins(0, 0, 0, 0)
        row1_lay.setSpacing(16)

        row1_lay.addWidget(self._build_credentials_card(), 1)
        row1_lay.addWidget(self._build_folder_card(), 1)
        lay.addWidget(row1)

        # ── Stats Row ───────────────────────────────────────────────
        lay.addWidget(self._build_stats_row())

        # ── Row 2: Extracted Data ───────────────────────────────────
        lay.addWidget(self._build_preview_card())

        lay.addStretch()
        scroll.setWidget(inner)
        return scroll

    # ══════════════════════════════════════════════════════════════════
    # PROGRESS PAGE
    # ══════════════════════════════════════════════════════════════════
    def _build_progress_page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget()
        inner.setObjectName("progressPage")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)

        # Step pipeline (horizontal)
        self.step_list = StepPipeline()
        lay.addWidget(_card(self.step_list, title="Automation Steps",
                            subtitle="Track each stage of the claim process"))

        # Progress bar
        lay.addWidget(self._build_progress_card())

        # Log
        lay.addWidget(self._build_log_card())

        lay.addStretch()
        scroll.setWidget(inner)
        return scroll

    # ══════════════════════════════════════════════════════════════════
    # CARD BUILDERS
    # ══════════════════════════════════════════════════════════════════
    def _build_credentials_card(self):
        w = QWidget()
        grid = QGridLayout(w)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        grid.addWidget(_field_label("USERNAME"), 0, 0)
        self.inp_username = _input("Portal username / ID")
        grid.addWidget(self.inp_username, 1, 0)

        grid.addWidget(_field_label("PASSWORD"), 2, 0)
        self.inp_password = _input("Portal password", echo_password=True)
        grid.addWidget(self.inp_password, 3, 0)

        grid.addWidget(_field_label("CLAIM NUMBER"), 0, 1)
        self.inp_claim_no = _input("Auto-detected or enter manually")
        grid.addWidget(self.inp_claim_no, 1, 1)

        grid.addWidget(_field_label("CLAIM TYPE"), 2, 1)
        self.inp_claim_type = QComboBox()
        self.inp_claim_type.addItems(["Non Maruti", "Maruti"])
        self.inp_claim_type.setMinimumHeight(40)
        grid.addWidget(self.inp_claim_type, 3, 1)

        return _card(w, title="⚙  Configuration",
                     subtitle="Portal credentials and claim details")

    def _build_folder_card(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(10)

        lay.addWidget(_field_label("CLAIM FOLDER PATH"))

        row = QWidget()
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(10)

        self.inp_folder = _input("Click Browse to select the claim folder...")
        self.inp_folder.setReadOnly(True)
        self.inp_folder.setStyleSheet(
            "QLineEdit { background:#F1F5F9; border:1.5px solid #E2E8F0; "
            "border-radius:10px; padding:9px 14px; color:#64748B; }"
        )

        btn = QPushButton("Browse...")
        btn.setObjectName("btnBrowse")
        btn.setFixedWidth(110)
        btn.setMinimumHeight(40)
        btn.clicked.connect(self._browse_folder)

        row_lay.addWidget(self.inp_folder, 1)
        row_lay.addWidget(btn)
        lay.addWidget(row)

        # Document status
        self.doc_status_label = QLabel("No folder selected — click Browse to begin.")
        self.doc_status_label.setWordWrap(True)
        self.doc_status_label.setStyleSheet(
            "color:#8894A7; font-size:8.5pt; padding:4px 0;"
        )
        lay.addWidget(self.doc_status_label)

        return _card(w, title="📂  Claim Folder",
                     subtitle="Select folder with Excel file and scanned documents")

    def _build_stats_row(self):
        row = QWidget()
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(16)

        card1, self._stat_fields_val = _stat_card("—", "Fields Extracted", "#3B82F6")
        card2, self._stat_docs_val   = _stat_card("—", "Documents Found", "#10B981")
        card3, self._stat_missing_val = _stat_card("—", "Missing Critical", "#F59E0B")
        card4, self._stat_status_val = _stat_card("Ready", "Status", "#8B5CF6")

        row_lay.addWidget(card1, 1)
        row_lay.addWidget(card2, 1)
        row_lay.addWidget(card3, 1)
        row_lay.addWidget(card4, 1)

        return row

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
            "background:#FEF2F2; color:#DC2626; "
            "border:1px solid #FECACA; "
            "border-radius:10px; padding:10px 14px; font-size:8.5pt;"
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
        self.preview_table.setMinimumHeight(300)
        self.preview_table.setMaximumHeight(500)
        vlay.addWidget(self.preview_table)

        return _card(container, title="📊  Extracted Data",
                     subtitle="🔴 Critical missing  /  🟡 Optional  /  🟢 Found")

    def _build_progress_card(self):
        container = QWidget()
        vlay = QVBoxLayout(container)
        vlay.setContentsMargins(0, 4, 0, 0)
        vlay.setSpacing(8)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, len(STEPS) - 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        vlay.addWidget(self.progress_bar)

        self.progress_label = QLabel("Waiting for folder selection...")
        self.progress_label.setStyleSheet("color:#8894A7; font-size:9.5pt;")
        vlay.addWidget(self.progress_label)

        return _card(container, title="📈  Progress")

    def _build_log_card(self):
        self.log_panel = QTextEdit()
        self.log_panel.setObjectName("logPanel")
        self.log_panel.setReadOnly(True)
        self.log_panel.setMinimumHeight(300)
        self.log_panel.setMaximumHeight(500)

        return _card(self.log_panel, title="🖥  Live Log",
                     subtitle="Real-time automation output")

    # ── ACTION BAR ─────────────────────────────────────────────────────
    def _build_action_bar(self):
        bar = QFrame()
        bar.setObjectName("actionBar")
        bar.setMinimumHeight(68)
        bar.setMaximumHeight(68)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(28, 0, 28, 0)
        lay.setSpacing(10)

        self.btn_start = QPushButton("  ▶  Start Automation  ")
        self.btn_start.setObjectName("btnStart")
        self.btn_start.setMinimumHeight(44)
        self.btn_start.setMinimumWidth(220)
        self.btn_start.clicked.connect(self._start_automation)

        self.btn_stop = QPushButton("■  Stop")
        self.btn_stop.setObjectName("btnStop")
        self.btn_stop.setFixedWidth(110)
        self.btn_stop.setMinimumHeight(44)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_automation)

        self.btn_clear = QPushButton("Clear Log")
        self.btn_clear.setObjectName("btnClear")
        self.btn_clear.setFixedWidth(110)
        self.btn_clear.setMinimumHeight(44)
        self.btn_clear.clicked.connect(self._clear_log)

        self.btn_export = QPushButton("Export Log")
        self.btn_export.setObjectName("btnExport")
        self.btn_export.setFixedWidth(120)
        self.btn_export.setMinimumHeight(44)
        self.btn_export.clicked.connect(self._export_log)

        lay.addWidget(self.btn_start)
        lay.addWidget(self.btn_stop)
        lay.addStretch()
        lay.addWidget(self.btn_clear)
        lay.addWidget(self.btn_export)

        return bar

    # ══════════════════════════════════════════════════════════════════
    # LOGIC — All preserved from original
    # ══════════════════════════════════════════════════════════════════
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
                
                # ── PDF Extraction for Workshop Invoice ──
                invoice_pdf = self._scan_result.assessment_files.get("invoice")
                if invoice_pdf and os.path.exists(invoice_pdf):
                    try:
                        import pdfplumber
                        import re
                        self._append_log("📄 Extracting Workshop Invoice details from PDF...")
                        with pdfplumber.open(invoice_pdf) as pdf:
                            text = pdf.pages[0].extract_text()
                            if text:
                                inv_match = re.search(r'Tax Invoice No\.(.*?)\(', text, re.IGNORECASE)
                                if not inv_match:
                                    inv_match = re.search(r'Tax Invoice No\.?\s*([A-Za-z0-9-]+)', text, re.IGNORECASE)
                                
                                date_match = re.search(r'Invoice Date and Time\s*(\d{2}/\d{2}/\d{4})', text, re.IGNORECASE)
                                
                                if inv_match:
                                    ext_inv = inv_match.group(1).strip()
                                    self._claim.workshop_invoice_no = ext_inv
                                    self._claim._excel_coords["workshop_invoice_no"] = "PDF Source"
                                    self._append_log(f"  ✅ WS Invoice No (from PDF): {ext_inv}")
                                
                                if date_match:
                                    ext_date = date_match.group(1).strip()
                                    self._claim.workshop_invoice_date = ext_date
                                    self._claim._excel_coords["workshop_invoice_date"] = "PDF Source"
                                    self._append_log(f"  ✅ WS Invoice Date (from PDF): {ext_date}")
                    except Exception as e:
                        self._append_log(f"  ⚠️ Could not parse invoice PDF: {e}")
                
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
        self._update_stats()

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
                "background:#FEF2F2; color:#DC2626; "
                "border:1px solid #FECACA; "
                "border-radius:10px; padding:10px 14px; font-size:8.5pt;"
            )
            self.validation_bar.setText(err_text)
            self.validation_bar.setVisible(True)
        elif warnings:
            self.validation_bar.setStyleSheet(
                "background:#FFFBEB; color:#B45309; "
                "border:1px solid #FDE68A; "
                "border-radius:10px; padding:10px 14px; font-size:8.5pt;"
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
            k_item.setForeground(QColor("#475569"))
            self.preview_table.setItem(i, 0, k_item)

            # Value column
            display = value if value else "—"
            v_item = QTableWidgetItem(display)
            if has_value:
                v_item.setForeground(QColor("#1A1A2E"))
                font = v_item.font()
                font.setWeight(QFont.Weight.DemiBold)
                v_item.setFont(font)
            elif is_critical:
                v_item.setForeground(QColor("#DC2626"))
            else:
                v_item.setForeground(QColor("#CBD5E1"))
            self.preview_table.setItem(i, 1, v_item)

            # Source column
            src_display = source_coord if source_coord else "—"
            src_item = QTableWidgetItem(src_display)
            src_item.setForeground(QColor("#7C83FF") if source_coord else QColor("#CBD5E1"))
            self.preview_table.setItem(i, 2, src_item)

            if has_value:
                status = "✓ OK"
            elif is_critical:
                status = "✕ MISS"
            else:
                status = "– OPT"
            s_item = QTableWidgetItem(status)
            s_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if has_value:
                s_item.setForeground(QColor("#059669"))
            elif is_critical:
                s_item.setForeground(QColor("#DC2626"))
            else:
                s_item.setForeground(QColor("#CBD5E1"))
            self.preview_table.setItem(i, 3, s_item)

        self._update_stats()

    def _update_stats(self):
        """Update the KPI stat cards on the Home page."""
        if not self._claim:
            return
        all_fields = self._claim.all_fields_for_preview()
        filled = sum(1 for _, v, _, _ in all_fields
                     if v and str(v).strip() not in ("", "—"))
        total = len(all_fields)
        missing_critical = sum(1 for _, v, c, _ in all_fields
                               if c and not (v and str(v).strip() not in ("", "—")))

        docs = 0
        if self._scan_result:
            docs = len(self._scan_result.claim_doc_files) + len(self._scan_result.assessment_files)

        self._stat_fields_val.setText(f"{filled}/{total}")
        self._stat_docs_val.setText(str(docs))
        self._stat_missing_val.setText(str(missing_critical))

        if missing_critical > 0:
            self._stat_status_val.setText("Warn")
            self._stat_status_val.setStyleSheet(
                "color: #F59E0B; font-size: 22pt; font-weight: 800; "
                "background: transparent; border: none;"
            )
        else:
            self._stat_status_val.setText("Ready")
            self._stat_status_val.setStyleSheet(
                "color: #8B5CF6; font-size: 22pt; font-weight: 800; "
                "background: transparent; border: none;"
            )

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
                "color:#475569; font-size:8.5pt; padding:4px 0;"
            )
            self.doc_status_label.setText("  │  ".join(parts))
        else:
            self.doc_status_label.setStyleSheet(
                "color:#DC2626; font-size:8.5pt; padding:4px 0;"
            )
            self.doc_status_label.setText("No documents detected — check folder contents.")

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

        # Auto-switch to Progress page so user sees the live log
        self._switch_page(1)

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
            color = "#4ADE80"   # green
        elif any(x in raw_message for x in ("❌", "ERROR", "failed", "STOPPED")):
            color = "#F87171"   # red
        elif any(x in raw_message for x in ("⚠️", "warning", "retrying", "⚠")):
            color = "#FBBF24"   # yellow
        elif "━" in raw_message:
            color = "#E2E8F0"   # bright white (bold separators)
        elif any(x in raw_message for x in ("🎉", "COMPLETE")):
            color = "#4ADE80"
        elif any(x in raw_message for x in ("📤", "📊", "📁", "🔩", "🔧", "🚀", "📋")):
            color = "#7C83FF"   # indigo for section headers
        else:
            color = "#CBD5E1"   # light slate

        display_message = html.escape(raw_message)
        if "━" in raw_message:
            display_message = f"<b>{display_message}</b>"

        log_html = (
            f'<span style="color:#64748B; font-size:8pt;">[{ts}]</span>'
            f'&nbsp;<span style="color:{color};">{display_message}</span>'
        )
        self.log_panel.append(log_html)
        self.log_panel.moveCursor(QTextCursor.MoveOperation.End)

        # B3/P1 FIX: Write to already-open file handle (not open/close per call)
        if self._log_file:
            try:
                full_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._log_file.write(f"[{full_ts}] {raw_message}\n")
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
