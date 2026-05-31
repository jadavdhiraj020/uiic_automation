from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPainterPath
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QStackedWidget, QScrollArea, QGridLayout,
    QLineEdit, QTableWidget, QHeaderView, QFileDialog, QMessageBox,
    QTableWidgetItem, QComboBox, QSpinBox, QCheckBox
)
import os
import json
from app.utils import (
    load_settings, save_settings, settings_paths,
    load_field_mapping, save_field_mapping, reset_field_mapping,
    load_doc_mapping, save_doc_mapping, reset_doc_mapping,
    load_automation_defaults, save_automation_defaults, reset_automation_defaults,
)
from app.ui.components.widgets import TagDelegate, ChipLineEdit, search_row as _search_row

class SafeComboBox(QComboBox):
    """Dropdown that ignores mouse wheel (prevents accidental changes while scrolling)."""
    def wheelEvent(self, event):
        event.ignore() # Pass to parent scroll area

class SafeSpinBox(QSpinBox):
    """Spinbox that ignores mouse wheel."""
    def wheelEvent(self, event):
        event.ignore()

class SettingsPage(QWidget):
    def __init__(self, parent=None, append_log_cb=None):
        super().__init__(parent)
        self.append_log = append_log_cb or (lambda x: None)
        self._portal_id = "uiic"
        self._create_icons()
        self._setup_ui()
        self._load_data()

    def set_portal(self, portal_id):
        if not portal_id or portal_id == self._portal_id:
            return
        self._portal_id = portal_id
        self._load_data()

    def _create_icons(self):
        def _draw_eye(closed=False):
            s = 28; px = QPixmap(s, s); px.fill(QColor(0, 0, 0, 0))
            p = QPainter(px); p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor("#475569")); pen.setWidthF(1.8); p.setPen(pen)
            cy, mx = s / 2, 4
            path = QPainterPath(); path.moveTo(mx, cy); path.quadTo(s / 2, cy - 9, s - mx, cy); path.quadTo(s / 2, cy + 9, mx, cy); p.drawPath(path)
            p.setBrush(QColor("#475569")); p.setPen(Qt.PenStyle.NoPen); p.drawEllipse(int(s/2-3.5), int(cy-3.5), 7, 7)
            if closed:
                pen2 = QPen(QColor("#EF4444")); pen2.setWidthF(2.0); p.setPen(pen2); p.drawLine(7, 6, s-7, s-6)
            p.end(); return QIcon(px)
        self._icon_eye_open = _draw_eye(False); self._icon_eye_closed = _draw_eye(True)

    def _setup_ui(self):
        self.setObjectName("settingsPageRoot")
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        
        # Header
        header = QFrame(); header.setFixedHeight(56)
        header.setObjectName("settingsHeader")
        h_lay = QHBoxLayout(header); h_lay.setContentsMargins(32, 0, 32, 0)
        title = QLabel("Settings"); title.setObjectName("settingsTitle")
        h_lay.addWidget(title); h_lay.addStretch(); root.addWidget(header)

        # Tabs
        self.tab_bar = QFrame(); tl = QHBoxLayout(self.tab_bar); tl.setContentsMargins(32, 10, 32, 0)
        self.tab_bar.setObjectName("settingsTabBar")
        self.tabs = []
        for i, name in enumerate(["General", "Automation Defaults", "Field Mapping", "Document Mapping", "PDF Mapping"]):
            btn = QPushButton(name); btn.setObjectName("settingsTabBtn"); btn.setProperty("active", i==0)
            btn.setMinimumSize(150, 38); btn.clicked.connect(lambda ch, idx=i: self._switch_tab(idx))
            tl.addWidget(btn); self.tabs.append(btn)
        tl.addStretch(); root.addWidget(self.tab_bar)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_general_tab())
        self.stack.addWidget(self._build_automation_defaults_tab())
        self.stack.addWidget(self._build_field_mapping_tab())
        self.stack.addWidget(self._build_doc_mapping_tab())
        self.stack.addWidget(self._build_pdf_mapping_tab())
        root.addWidget(self.stack, 1)

        # Footer
        footer = QFrame(); footer.setFixedHeight(68); fl = QHBoxLayout(footer); fl.setContentsMargins(32, 0, 32, 0)
        footer.setObjectName("settingsFooter")
        br = QPushButton("  Reset to Defaults  ")
        br.setObjectName("btnSettingsReset")
        br.clicked.connect(self._reset_defaults); fl.addWidget(br); fl.addStretch()
        bs = QPushButton("  Save All Settings  "); bs.setObjectName("btnSettingsSave"); bs.setMinimumSize(180, 42); bs.clicked.connect(self._save_all); fl.addWidget(bs)
        root.addWidget(footer)

    def _switch_tab(self, idx):
        self.stack.setCurrentIndex(idx)
        for i, b in enumerate(self.tabs):
            b.setProperty("active", i==idx); b.style().unpolish(b); b.style().polish(b)

    def _build_general_tab(self):
        s = QScrollArea(); s.setWidgetResizable(True); s.setFrameShape(QFrame.Shape.NoFrame)
        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(32, 24, 32, 24); l.setSpacing(16)
        
        def _f(text):
            lbl = QLabel(text); lbl.setObjectName("settingsFieldLabel"); return lbl

        l.addWidget(_f("Username"))
        self.inp_username = QLineEdit(); self.inp_username.setObjectName("settingsInput"); self.inp_username.setMinimumHeight(40); l.addWidget(self.inp_username)
        l.addWidget(_f("Password"))
        row = QWidget(); rl = QHBoxLayout(row); rl.setContentsMargins(0,0,0,0)
        self.inp_password = QLineEdit(); self.inp_password.setObjectName("settingsInput"); self.inp_password.setEchoMode(QLineEdit.EchoMode.Password); self.inp_password.setMinimumHeight(40)
        self.btn_eye = QPushButton(); self.btn_eye.setIcon(self._icon_eye_closed); self.btn_eye.setFixedSize(44, 44); self.btn_eye.setCheckable(True); self.btn_eye.clicked.connect(self._toggle_pwd)
        self.btn_eye.setObjectName("iconButton")
        self.btn_eye.setToolTip("Show password")
        rl.addWidget(self.inp_password); rl.addWidget(self.btn_eye); l.addWidget(row)
        l.addWidget(_f("Portal URL"))
        self.inp_url = QLineEdit(); self.inp_url.setObjectName("settingsInput"); self.inp_url.setMinimumHeight(40); l.addWidget(self.inp_url)
        
        # New inputs for previously hidden settings
        self.chk_headless = QCheckBox("Run Browser Headless (Invisible)"); self.chk_headless.setObjectName("settingsFieldLabel")
        l.addWidget(self.chk_headless)

        l.addWidget(_f("Slow-Mo (ms) - Time between clicks"))
        self.inp_slowmo = QLineEdit(); self.inp_slowmo.setObjectName("settingsInput"); self.inp_slowmo.setMinimumHeight(40); l.addWidget(self.inp_slowmo)
        
        l.addWidget(_f("Timeout (ms) - General max wait time"))
        self.inp_timeout = QLineEdit(); self.inp_timeout.setObjectName("settingsInput"); self.inp_timeout.setMinimumHeight(40); l.addWidget(self.inp_timeout)
        
        l.addWidget(_f("Captcha Max Retries"))
        self.inp_captcha = QLineEdit(); self.inp_captcha.setObjectName("settingsInput"); self.inp_captcha.setMinimumHeight(40); l.addWidget(self.inp_captcha)
        
        l.addWidget(_f("Upload Wait (ms)"))
        self.inp_upload_wait = QLineEdit(); self.inp_upload_wait.setObjectName("settingsInput"); self.inp_upload_wait.setMinimumHeight(40); l.addWidget(self.inp_upload_wait)
        
        l.addWidget(_f("Field Wait (ms)"))
        self.inp_field_wait = QLineEdit(); self.inp_field_wait.setObjectName("settingsInput"); self.inp_field_wait.setMinimumHeight(40); l.addWidget(self.inp_field_wait)

        l.addWidget(_f("Manual Login Timeout (s)"))
        self.inp_manual_login_timeout = QLineEdit(); self.inp_manual_login_timeout.setObjectName("settingsInput"); self.inp_manual_login_timeout.setMinimumHeight(40); l.addWidget(self.inp_manual_login_timeout)

        l.addStretch(); s.setWidget(w); return s

    def _toggle_pwd(self, ch):
        self.inp_password.setEchoMode(QLineEdit.EchoMode.Normal if ch else QLineEdit.EchoMode.Password)
        self.btn_eye.setIcon(self._icon_eye_open if ch else self._icon_eye_closed)
        self.btn_eye.setToolTip("Hide password" if ch else "Show password")

    def _automation_default_rows(self):
        rows_by_portal = {
            "uiic": [
                ("remarks_default", "Remarks Default", "Interim Report, Claim Assessment", "text"),
                ("observation_default", "Observation Default", "Surveyor Observation fallback", "text"),
            ],
            "newindia": [
                ("remarks_default", "Remarks Default", "Remarks fallback", "text"),
                ("observation_default", "Observation Default", "Observation fallback", "text"),
                ("missing_text_default", "Missing Text Default", "FIR / police / charge fallbacks", "text"),
                ("photo_charges_default", "Photo Charges Default", "Survey Fee Bill Photos Amount", "text"),
                ("assessment_parts_hsn_code", "Assessment Parts HSN Code", "Auto primary assessment spare parts", "text"),
                ("assessment_labour_hsn_code", "Assessment Labour HSN Code", "Auto primary assessment labour", "text"),
                ("hsn_code", "HSN Code", "Survey Fee Bill GST section", "text"),
                ("gst_applicable", "GST Applicable", "Survey Fee Bill GST dropdown", "yesno"),
                ("invoice_in_company_name", "Invoice In Company Name", "Claim Assessment, Survey Fee Bill", "yesno"),
                ("payment_method", "Payment Method", "NEFT payment method", "text"),
                ("account_type", "Account Type", "NEFT account type fallback", "text"),
                ("relationship_with_insured", "Relationship With Insured", "Driver details fallback", "text"),
                ("reinspection_required", "Reinspection Required", "Claim Assessment dropdown", "yesno"),
                ("table_boundary_keyword", "Table Boundary Keyword", "End-of-table marker(s) in Excel. Separate multiple with | (e.g. 'sub total|grand total')", "text"),
            ],
            "oic": [
                ("unknown_claim_type_default", "Unknown Payment Default", "Claim Search claim type fallback", "claimtype"),
                ("driver_relation_default",    "Relation of Driver",      "Driver Details — filled when Is Owner Driver = NO", "text"),
                ("gst_type", "GST Type", "Invoice Section GST dropdown fallback", "gsttype"),
                ("survey_gst_applicable", "Survey GST Applicable", "Survey Charges GST dropdown fallback", "yesno"),
                ("expense_description", "Expense Description", "Default description for all expense types", "text"),
                ("final_recommendation", "Final Recommendation", "Default surveyor recommendation text", "text"),
                ("declaration_checked", "Declaration Checked", "Auto-check declaration checkbox default", "yesno"),
                ("item_side_description", "Item Side Description", "Invoice item side (FRONT/REAR/LEFT/RIGHT/TOP)", "sidecode"),
                ("item_igst_rate",       "Item IGST Rate",       "IGST % for invoice spare parts & labour",  "igstrate"),
                ("item_hsn_code",        "Spare Parts HSN Code", "HSN code for spare parts (default 8512)",  "text"),
                ("labour_hsn_code",      "Labour HSN Code",      "HSN code for labour charges (default 8729)", "text"),
                ("labour_estimated_amount", "Labour Estimated Amt", "Default estimated amount for labour rows", "text"),
                ("table_boundary_keyword", "Table Boundary Keyword", "End-of-table marker(s) in Excel. Separate multiple with | (e.g. 'sub total|grand total')", "text"),
                ("upload_remarks",          "Upload Remarks",          "Remarks text filled on Document Upload step (min 10 chars)", "remarks"),
                ("instant_fill",               "Instant Form Filling",    "Fill fields instantly (faster) or type slowly", "yesno"),
                ("typing_delay_ms",            "Typing Delay (ms)",       "Delay per character when typing, 0–999 ms (used if not instant fill)", "spinbox"),
            ],
        }
        return rows_by_portal.get(self._portal_id, rows_by_portal["uiic"])

    def _build_automation_defaults_tab(self):
        s = QScrollArea(); s.setWidgetResizable(True); s.setFrameShape(QFrame.Shape.NoFrame)
        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(32, 24, 32, 24)
        self.defaults_table = QTableWidget(0, 3)
        self.defaults_table.setObjectName("settingsTable")
        self.defaults_table.setAlternatingRowColors(True)
        self.defaults_table.setHorizontalHeaderLabels(["SETTING", "VALUE", "USED IN"])
        self.defaults_table.verticalHeader().setVisible(False)
        self.defaults_table.verticalHeader().setDefaultSectionSize(48)
        self.defaults_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.defaults_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.defaults_table.setColumnWidth(1, 220)
        self.defaults_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        l.addWidget(self.defaults_table)
        s.setWidget(w); return s

    def _build_field_mapping_tab(self):
        s = QScrollArea(); s.setWidgetResizable(True); s.setFrameShape(QFrame.Shape.NoFrame)
        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(32, 24, 32, 24)
        search_box, self.search_input = _search_row(
            "Filter fields by name or label...",
            self._filter_table,
        )
        l.addWidget(search_box)

        self.mapping_table = QTableWidget(0, 4)
        self.mapping_table.setObjectName("settingsTable")
        self.mapping_table.setAlternatingRowColors(True)
        self.mapping_table.setHorizontalHeaderLabels(["FIELD NAME", "SEARCH LABEL", "SHEET", "COL OFFSET"])
        self.mapping_table.verticalHeader().setVisible(False)
        self.mapping_table.verticalHeader().setDefaultSectionSize(48)
        self.mapping_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.mapping_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.mapping_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.mapping_table.setColumnWidth(2, 120)
        self.mapping_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.mapping_table.setColumnWidth(3, 100)
        self.mapping_table.setItemDelegateForColumn(1, TagDelegate(self.mapping_table))
        l.addWidget(self.mapping_table)
        s.setWidget(w); return s

    def _build_doc_mapping_tab(self):
        s = QScrollArea(); s.setWidgetResizable(True); s.setFrameShape(QFrame.Shape.NoFrame)
        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(32, 24, 32, 24)
        
        # Main Excel Keywords field
        excel_label = QLabel("Main Excel Keywords (Filename keywords to identify the main claim data Excel)")
        excel_label.setObjectName("settingsFieldLabel")
        l.addWidget(excel_label)
        self.inp_main_excel_keywords = ChipLineEdit()
        l.addWidget(self.inp_main_excel_keywords)
        l.addSpacing(16)
        
        search, self.doc_search_input = _search_row(
            "Filter documents by section, portal type, or filename keyword...",
            self._filter_doc_table,
        )
        l.addWidget(search)
        self.doc_table = QTableWidget(0, 3)
        self.doc_table.setObjectName("settingsTable")
        self.doc_table.setAlternatingRowColors(True)
        self.doc_table.setHorizontalHeaderLabels(["SECTION", "PORTAL DOC TYPE", "FILENAME KEYWORDS"])
        self.doc_table.verticalHeader().setVisible(False)
        self.doc_table.verticalHeader().setDefaultSectionSize(48)
        self.doc_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.doc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.doc_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.doc_table.setItemDelegateForColumn(2, TagDelegate(self.doc_table))
        l.addWidget(self.doc_table)
        s.setWidget(w); return s

    def _build_pdf_mapping_tab(self):
        s = QScrollArea(); s.setWidgetResizable(True); s.setFrameShape(QFrame.Shape.NoFrame)
        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(32, 24, 32, 24); l.setSpacing(16)
        inv_label = QLabel("Invoice No Labels"); inv_label.setObjectName("settingsFieldLabel"); l.addWidget(inv_label)
        self.inp_pdf_inv = ChipLineEdit(); l.addWidget(self.inp_pdf_inv)
        date_label = QLabel("Invoice Date Labels"); date_label.setObjectName("settingsFieldLabel"); l.addWidget(date_label)
        self.inp_pdf_date = ChipLineEdit(); l.addWidget(self.inp_pdf_date)
        l.addStretch(); s.setWidget(w); return s

    def _load_data(self):
        s = load_settings(portal_id=self._portal_id)
        self.inp_username.setText(s.get("username", ""))
        self.inp_password.setText(s.get("password", ""))
        self.inp_url.setText(s.get("portal_url", ""))
        
        self.chk_headless.setChecked(s.get("browser_headless", False))
        
        self.inp_slowmo.setText(str(s.get("browser_slow_mo_ms", 400)))
        self.inp_timeout.setText(str(s.get("timeout_ms", 4000)))
        self.inp_captcha.setText(str(s.get("captcha_max_retries", 2)))
        self.inp_upload_wait.setText(str(s.get("upload_wait_ms", 3000)))
        self.inp_field_wait.setText(str(s.get("field_wait_ms", 600)))
        self.inp_manual_login_timeout.setText(str(s.get("manual_login_timeout_s", 45)))
        
        self.inp_pdf_inv.setText(" | ".join(s.get("pdf_invoice_no_labels", [])))
        self.inp_pdf_date.setText(" | ".join(s.get("pdf_invoice_date_labels", [])))

        # Automation Defaults
        defaults = load_automation_defaults(portal_id=self._portal_id)
        default_rows = self._automation_default_rows()
        self.defaults_table.setRowCount(len(default_rows))
        for i, (key, label, used_in, kind) in enumerate(default_rows):
            label_item = QTableWidgetItem(label)
            label_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            label_item.setData(Qt.ItemDataRole.UserRole, key)
            self.defaults_table.setItem(i, 0, label_item)

            raw_value = str(defaults.get(key, ""))
            if kind in {"yesno", "claimtype", "gsttype", "sidecode", "igstrate"}:
                value_widget = SafeComboBox()
                value_widget.setObjectName("embeddedCombo")
                if kind == "yesno":
                    value_widget.addItems(["Yes", "No"])
                elif kind == "gsttype":
                    value_widget.addItems(["IGST", "CGST/SGST"])
                elif kind == "sidecode":
                    value_widget.addItems(["FRONT", "REAR", "LEFT", "RIGHT", "TOP"])
                elif kind == "igstrate":
                    value_widget.addItems(["0%", "5%", "12%", "18%", "28%"])
                else:
                    value_widget.addItems(["CASHLESS", "REIMBURSEMENT"])
                idx = value_widget.findText(raw_value, Qt.MatchFlag.MatchFixedString)
                if idx >= 0:
                    value_widget.setCurrentIndex(idx)
                elif raw_value:
                    value_widget.addItem(raw_value)
                    value_widget.setCurrentText(raw_value)
                self.defaults_table.setCellWidget(i, 1, value_widget)
            elif kind == "spinbox":
                spin = SafeSpinBox()
                spin.setObjectName("embeddedSpin")
                spin.setRange(0, 999)
                spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
                spin.setSuffix(" ms")
                try:
                    spin.setValue(int(str(raw_value).strip()))
                except (ValueError, TypeError):
                    spin.setValue(25)  # safe fallback default
                self.defaults_table.setCellWidget(i, 1, spin)
            else:
                value_item = QTableWidgetItem(raw_value)
                self.defaults_table.setItem(i, 1, value_item)

            used_item = QTableWidgetItem(used_in)
            used_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.defaults_table.setItem(i, 2, used_item)

        # Field Mapping
        m = load_field_mapping(portal_id=self._portal_id)
        entries = [(k, v) for k, v in m.items() if not k.startswith("_")]
        self.mapping_table.setRowCount(len(entries))
        for i, (fn, cfg) in enumerate(entries):
            self.mapping_table.setItem(i, 0, QTableWidgetItem(fn))
            self.mapping_table.item(i, 0).setFlags(Qt.ItemFlag.ItemIsEnabled)
            raw_labels = cfg.get("search_labels")
            if not raw_labels:
                raw_label = cfg.get("search_label", "")
                labels = raw_label if isinstance(raw_label, list) else [raw_label]
            else:
                labels = raw_labels

            self.mapping_table.setItem(i, 1, QTableWidgetItem(" | ".join([str(l) for l in labels if l])))
            
            # Sheet Dropdown
            sheet_combo = SafeComboBox()
            sheet_combo.setObjectName("embeddedCombo")
            sheet_combo.addItems(["ALL", "Sheet1", "Sheet2", "Sheet3", "Sheet4", "Sheet5", "Sheet6", "Sheet7", "Sheet8", "Sheet9", "Sheet10"])
            sheet_val = cfg.get("sheet", "ALL")
            idx = sheet_combo.findText(sheet_val)
            if idx >= 0: sheet_combo.setCurrentIndex(idx)
            else:
                sheet_combo.addItem(sheet_val)
                sheet_combo.setCurrentText(sheet_val)
            self.mapping_table.setCellWidget(i, 2, sheet_combo)

            # Col Offset SpinBox
            offset_spin = SafeSpinBox()
            offset_spin.setObjectName("embeddedSpin")
            offset_spin.setRange(0, 100) # Prevent negative values as requested
            offset_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            offset_spin.setValue(int(cfg.get("col_offset", 1)))
            self.mapping_table.setCellWidget(i, 3, offset_spin)
        self._filter_table(self.search_input.text())

        # Doc Mapping
        dm = load_doc_mapping(portal_id=self._portal_id)
        self.inp_main_excel_keywords.setText(" | ".join(dm.get("main_excel_keywords", [])))
        rows = []
        for sk in ("claim_documents_tab", "claim_assessment_tab"):
            sec = dm.get(sk, {})
            lbl = "Claim Docs" if "claim_doc" in sk else "Assessment"
            for dt, kws in sec.items():
                rows.append((lbl, dt, " | ".join(kws) if isinstance(kws, list) else str(kws)))
        # Upload Docs section (DL, RC, Claim Form from document_upload_tab)
        upload_tab = {k: v for k, v in dm.get("document_upload_tab", {}).items() if not k.startswith("_")}
        for dt, kws in upload_tab.items():
            rows.append(("Upload Docs", dt, " | ".join(kws) if isinstance(kws, list) else str(kws)))
        # Claim Related Documents is auto-managed — not keyword-matched
        rows.append(("Upload Docs", "claim_related", "(auto-merged from remaining files)"))

        self.doc_table.setRowCount(len(rows))
        for i, (sec, dt, kws) in enumerate(rows):
            sec_item = QTableWidgetItem(sec)
            sec_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.doc_table.setItem(i, 0, sec_item)
            dt_item = QTableWidgetItem(dt)
            dt_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.doc_table.setItem(i, 1, dt_item)
            kw_item = QTableWidgetItem(kws)
            # Make claim_related row read-only (it's auto-managed, not user-editable)
            if dt == "claim_related":
                kw_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                kw_item.setForeground(QColor("#94A3B8"))
            self.doc_table.setItem(i, 2, kw_item)
        self._filter_doc_table(self.doc_search_input.text())

    def _filter_table(self, text):
        text = (text or "").strip().lower()
        for i in range(self.mapping_table.rowCount()):
            values = []
            for col in range(self.mapping_table.columnCount()):
                item = self.mapping_table.item(i, col)
                if item:
                    values.append(item.text().lower())
                widget = self.mapping_table.cellWidget(i, col)
                if isinstance(widget, QComboBox):
                    values.append(widget.currentText().lower())
                elif isinstance(widget, QSpinBox):
                    values.append(str(widget.value()))
            self.mapping_table.setRowHidden(i, bool(text) and text not in " ".join(values))

    def _filter_doc_table(self, text):
        text = (text or "").strip().lower()
        for row in range(self.doc_table.rowCount()):
            values = []
            for col in range(self.doc_table.columnCount()):
                item = self.doc_table.item(row, col)
                if item:
                    values.append(item.text().lower())
            self.doc_table.setRowHidden(row, bool(text) and text not in " ".join(values))

    def _save_all(self):
        try:
            current_settings = load_settings(portal_id=self._portal_id)
            def _int_from_input(widget, label, default):
                raw = widget.text().strip()
                if not raw:
                    return default
                try:
                    return int(raw)
                except ValueError as exc:
                    widget.setFocus()
                    raise ValueError(f"{label} must be a whole number.") from exc
            
            # Update only from UI widgets, keeping other keys (if any) intact
            current_settings.update({
                "username": self.inp_username.text().strip(),
                "password": self.inp_password.text().strip(),
                "portal_url": self.inp_url.text().strip(),
                "browser_headless": self.chk_headless.isChecked(),
                "browser_slow_mo_ms": _int_from_input(self.inp_slowmo, "Slow-Mo (ms)", 400),
                "timeout_ms": _int_from_input(self.inp_timeout, "Timeout (ms)", 4000),
                "captcha_max_retries": _int_from_input(self.inp_captcha, "Captcha Max Retries", 2),
                "upload_wait_ms": _int_from_input(self.inp_upload_wait, "Upload Wait (ms)", 3000),
                "field_wait_ms": _int_from_input(self.inp_field_wait, "Field Wait (ms)", 600),
                "manual_login_timeout_s": _int_from_input(self.inp_manual_login_timeout, "Manual Login Timeout (s)", 45),
                "pdf_invoice_no_labels": [l.strip() for l in self.inp_pdf_inv.text().split("|") if l.strip()],
                "pdf_invoice_date_labels": [l.strip() for l in self.inp_pdf_date.text().split("|") if l.strip()],
            })
            save_settings(current_settings, portal_id=self._portal_id)

            # Automation Defaults Save
            defaults = load_automation_defaults(portal_id=self._portal_id)
            _remarks_min_len = 10  # minimum character count enforced for 'remarks' kind fields
            for r in range(self.defaults_table.rowCount()):
                key_item = self.defaults_table.item(r, 0)
                if not key_item:
                    continue
                key = key_item.data(Qt.ItemDataRole.UserRole)
                if not key:
                    continue
                widget = self.defaults_table.cellWidget(r, 1)
                # SpinBox kind: read integer value directly, no text parsing needed
                if isinstance(widget, QSpinBox):
                    defaults[key] = str(widget.value())
                    continue
                if isinstance(widget, QComboBox):
                    defaults[key] = widget.currentText().strip()
                else:
                    value_item = self.defaults_table.item(r, 1)
                    raw = value_item.text().strip() if value_item else ""

                    def _scroll_to_error(vi=value_item):
                        if vi:
                            self.defaults_table.setCurrentItem(vi)
                            self.defaults_table.scrollToItem(vi)

                    # ── Validate: Upload Remarks minimum length ───────────────
                    if key == "upload_remarks" and len(raw) < _remarks_min_len:
                        _scroll_to_error()
                        raise ValueError(
                            f"Upload Remarks must be at least {_remarks_min_len} characters "
                            f"(currently {len(raw)}). Please enter a longer remark."
                        )

                    # ── Validate: Table Boundary Keyword ─────────────────────
                    # Must be a non-blank text keyword (e.g. "sub total").
                    # Typing "Yes" or "No" here is a common mistake — the field
                    # looks like a boolean in the table but it is a text keyword.
                    if key == "table_boundary_keyword":
                        if not raw:
                            _scroll_to_error()
                            raise ValueError(
                                "Table Boundary Keyword cannot be empty.\n"
                                "Enter the text that marks the end of the parts/labour table "
                                "in your Excel (e.g. 'sub total')."
                            )
                        if raw.lower() in {"yes", "no", "true", "false"}:
                            _scroll_to_error()
                            raise ValueError(
                                f"Table Boundary Keyword is set to '{raw}' which looks like a "
                                "Yes/No answer — but this field expects a text keyword from "
                                "your Excel (e.g. 'sub total' or 'grand total').\n"
                                "Please correct the value before saving."
                            )

                    defaults[key] = raw
            save_automation_defaults(defaults, portal_id=self._portal_id)

            # Field Mapping Save
            m = load_field_mapping(portal_id=self._portal_id)
            nm = {k: v for k, v in m.items() if k.startswith("_")}
            for r in range(self.mapping_table.rowCount()):
                fn = self.mapping_table.item(r, 0).text()
                lt = self.mapping_table.item(r, 1).text().strip()
                
                # Get values from widgets
                sheet_combo = self.mapping_table.cellWidget(r, 2)
                sh = sheet_combo.currentText() if sheet_combo else "ALL"
                
                offset_spin = self.mapping_table.cellWidget(r, 3)
                co = offset_spin.value() if offset_spin else 1
                
                old = m.get(fn, {})
                labels = [l.strip() for l in lt.split("|") if l.strip()]
                nm[fn] = {**old, "sheet": sh, "search_labels": labels, "col_offset": co}
                if "search_label" in nm[fn]: del nm[fn]["search_label"]
            save_field_mapping(nm, portal_id=self._portal_id)

            # Doc Mapping Save
            dm = load_doc_mapping(portal_id=self._portal_id)
            cd, ad, ud = {}, {}, {}
            for r in range(self.doc_table.rowCount()):
                sec = self.doc_table.item(r, 0).text()
                dt = self.doc_table.item(r, 1).text()
                kws_raw = self.doc_table.item(r, 2).text()
                # Skip auto-managed rows (claim_related is not keyword-matched)
                if kws_raw == "(auto-merged from remaining files)":
                    continue
                kws = [k.strip() for k in kws_raw.split("|") if k.strip()]
                if sec == "Claim Docs":
                    cd[dt] = kws
                elif sec == "Assessment":
                    ad[dt] = kws
                elif sec == "Upload Docs":
                    ud[dt] = kws
            # Preserve all other schema keys; overwrite only the three tab dicts
            dm["claim_documents_tab"] = cd
            dm["claim_assessment_tab"] = ad
            if ud:
                dm["document_upload_tab"] = ud
            dm["main_excel_keywords"] = [k.strip() for k in self.inp_main_excel_keywords.text().split("|") if k.strip()]
            save_doc_mapping(dm, portal_id=self._portal_id)

            self.append_log("\u2705  Settings saved.")
            QMessageBox.information(self, "Success", "All settings saved.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Save failed: {e}")

    def _reset_defaults(self):
        if QMessageBox.question(self, "Reset", "Reset all to defaults?") == QMessageBox.StandardButton.Yes:
            reset_field_mapping(portal_id=self._portal_id); reset_doc_mapping(portal_id=self._portal_id); reset_automation_defaults(portal_id=self._portal_id)
            # Reset user settings by removing file
            sp = settings_paths(portal_id=self._portal_id)
            if os.path.exists(sp["user"]): os.remove(sp["user"])
            self._load_data()
            self.append_log("\u2139  Settings reset.")
