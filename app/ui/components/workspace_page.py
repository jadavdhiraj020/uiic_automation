import html
import os
import re
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QHeaderView,
    QVBoxLayout,
    QWidget,
)

from app.ui.components.widgets import (
    card as _card,
    create_input as _input,
    field_label as _field_label,
    search_row as _search_row,
    stat_card as _stat_card,
)
from app.ui.portal_ui_metadata import get_portal_ui_metadata


class WorkflowRail(QWidget):
    stage_selected = pyqtSignal(int)

    STAGES = [
        ("Folder", "Select claim folder"),
        ("Data", "Review extracted fields"),
        ("Documents", "Check mapped files"),
        ("Logs", "Automation activity"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("workflowRail")
        self._buttons = []
        self._states = ["pending"] * len(self.STAGES)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(10)

        title = QLabel("Workflow")
        title.setObjectName("railTitle")
        lay.addWidget(title)

        for idx, (label, subtitle) in enumerate(self.STAGES):
            btn = QPushButton(f"{idx + 1}. {label}\n{subtitle}")
            btn.setObjectName("workflowStepBtn")
            btn.setProperty("state", "pending")
            btn.setProperty("active", idx == 0)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(64)
            btn.clicked.connect(lambda checked=False, i=idx: self.stage_selected.emit(i))
            lay.addWidget(btn)
            self._buttons.append(btn)

        lay.addStretch()

    def set_active(self, idx: int):
        for i, btn in enumerate(self._buttons):
            btn.setProperty("active", i == idx)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def set_stage_state(self, idx: int, state: str):
        if 0 <= idx < len(self._buttons):
            self._states[idx] = state
            self._buttons[idx].setProperty("state", state)
            self._buttons[idx].style().unpolish(self._buttons[idx])
            self._buttons[idx].style().polish(self._buttons[idx])

    def reset(self):
        for i in range(len(self._buttons)):
            self.set_stage_state(i, "pending")
        self.set_active(0)


class LogsDrawer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("logsDrawer")
        self._log_entries = []
        self._expanded = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 10, 18, 12)
        lay.setSpacing(8)

        header = QWidget()
        h = QHBoxLayout(header)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)

        self.btn_toggle = QPushButton("Logs")
        self.btn_toggle.setObjectName("logsToggleBtn")
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.clicked.connect(self.toggle)
        self.latest_label = QLabel("No activity yet.")
        self.latest_label.setObjectName("logsLatest")
        self.latest_label.setWordWrap(False)

        self.btn_copy = QPushButton("Copy")
        self.btn_copy.setObjectName("logsSmallBtn")
        self.btn_copy.setToolTip("Copy logs")
        self.btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.log_text()))
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setObjectName("logsSmallBtn")
        self.btn_clear.setToolTip("Clear logs")
        self.btn_export = QPushButton("Export")
        self.btn_export.setObjectName("logsSmallBtn")
        self.btn_export.setToolTip("Export logs")

        h.addWidget(self.btn_toggle)
        h.addWidget(self.latest_label, 1)
        h.addWidget(self.btn_copy)
        h.addWidget(self.btn_clear)
        h.addWidget(self.btn_export)
        lay.addWidget(header)

        body = QWidget()
        b = QVBoxLayout(body)
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(8)
        search, self.log_search_input = _search_row("Filter activity log...", self._filter_log)
        b.addWidget(search)
        self.log_output = QTextEdit()
        self.log_output.setObjectName("logPanel")
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(260)
        b.addWidget(self.log_output)
        self.body = body
        lay.addWidget(self.body)
        self.body.setVisible(False)

    def toggle(self):
        self._expanded = not self._expanded
        self.body.setVisible(self._expanded)
        self.btn_toggle.setText("Hide Logs" if self._expanded else "Logs")

    def append_log(self, html_text: str):
        self._log_entries.append(html_text)
        plain = self._plain_log_text(html_text).strip()
        if plain:
            self.latest_label.setText(plain[:220])
        if self._log_matches_filter(html_text, self.log_search_input.text()):
            self.log_output.append(html_text)
        self.log_output.ensureCursorVisible()

    def clear_logs(self):
        self._log_entries.clear()
        self.log_output.clear()
        self.latest_label.setText("No activity yet.")

    def log_text(self) -> str:
        return self.log_output.toPlainText()

    def _plain_log_text(self, html_text: str) -> str:
        return re.sub(r"<[^>]+>", " ", str(html_text)).lower()

    def _log_matches_filter(self, html_text: str, text: str) -> bool:
        text = (text or "").strip().lower()
        return not text or text in self._plain_log_text(html_text)

    def _filter_log(self, text):
        self.log_output.clear()
        for entry in self._log_entries:
            if self._log_matches_filter(entry, text):
                self.log_output.append(entry)
        self.log_output.ensureCursorVisible()


class StructuredLogsPanel(QWidget):
    copy_clicked = pyqtSignal()
    clear_clicked = pyqtSignal()
    export_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries = []
        self._auto_scroll = True
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(10)

        title_row = QWidget()
        title_lay = QHBoxLayout(title_row)
        title_lay.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Logs")
        title.setObjectName("workspaceHeading")
        title_lay.addWidget(title)
        title_lay.addStretch()
        self.auto_scroll_check = QCheckBox("Auto-scroll")
        self.auto_scroll_check.setChecked(True)
        self.auto_scroll_check.toggled.connect(self._set_auto_scroll)
        title_lay.addWidget(self.auto_scroll_check)
        root.addWidget(title_row)

        filters = QWidget()
        fl = QHBoxLayout(filters)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(10)
        search, self.search_input = _search_row("Search logs by action, phase, file, warning, error, or upload...", self._apply_filters)
        self.btn_copy = QPushButton("Copy")
        self.btn_copy.setObjectName("logsSmallBtn")
        self.btn_copy.setToolTip("Copy visible logs")
        self.btn_copy.clicked.connect(self.copy_clicked.emit)
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setObjectName("logsSmallBtn")
        self.btn_clear.setToolTip("Clear logs")
        self.btn_clear.clicked.connect(self.clear_clicked.emit)
        self.btn_export = QPushButton("Export")
        self.btn_export.setObjectName("logsSmallBtn")
        self.btn_export.setToolTip("Export logs")
        self.btn_export.clicked.connect(self.export_clicked.emit)
        fl.addWidget(search, 1)
        fl.addWidget(self.btn_copy)
        fl.addWidget(self.btn_clear)
        fl.addWidget(self.btn_export)
        root.addWidget(filters)

        self.table = QTableWidget(0, 4)
        self.table.setObjectName("logsTable")
        self.table.setHorizontalHeaderLabels(["TIME", "LEVEL", "PHASE", "ACTION"])
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        root.addWidget(self.table, 1)

    def append_log(self, text, portal_id="uiic", phase=""):
        entry = self._parse_entry(text, portal_id, phase)
        if not entry:
            return
        self._entries.append(entry)
        self._append_table_row(entry)
        self._apply_filters()

    def clear_logs(self):
        self._entries.clear()
        self.table.setRowCount(0)

    def log_text(self, visible_only=False):
        rows = []
        for row, entry in enumerate(self._entries):
            if visible_only and self.table.isRowHidden(row):
                continue
            rows.append(f"[{entry['time']}] [{entry['level']}] [{entry['phase']}] {entry['message']}")
        return "\n".join(rows)

    def _set_auto_scroll(self, checked):
        self._auto_scroll = checked

    def _parse_entry(self, text, portal_id, phase):
        raw = "" if text is None else str(text)
        plain = html.unescape(re.sub(r"<[^>]+>", " ", raw)).strip()
        ts_match = re.search(r"\[(\d{2}:\d{2}:\d{2}(?:\.\d{3})?)\]", plain)
        timestamp = ts_match.group(1) if ts_match else datetime.now().strftime("%H:%M:%S.%f")[:-3]
        if ts_match:
            plain = (plain[:ts_match.start()] + plain[ts_match.end():]).strip()
        plain = self._clean_action_text(plain)
        if not plain:
            return None

        lower = plain.lower()
        level = "Info"
        if any(x in lower for x in ("error", "failed", "❌", "stopped")):
            level = "Error"
        elif any(x in lower for x in ("warning", "missing", "⚠")):
            level = "Warning"
        elif any(x in lower for x in ("success", "complete", "completed", "✅")):
            level = "Success"
        elif any(x in lower for x in ("retry", "attempt", "🔄")):
            level = "Retry"
        elif any(x in lower for x in ("wait", "waiting", "⏳")):
            level = "Wait"

        phase_match = re.search(r"STEP\s+\d+/\d+\s+[—-]\s+(.+)", plain)
        inferred_phase = phase_match.group(1).strip() if phase_match else (phase or "General")

        return {
            "time": timestamp,
            "level": level,
            "portal": (portal_id or "uiic").upper(),
            "phase": inferred_phase or "General",
            "message": plain,
            "search": " ".join([timestamp, level, portal_id or "", inferred_phase or "", plain]).lower(),
        }

    def _clean_action_text(self, text):
        text = (text or "").replace("\u00a0", " ")
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return ""

        # Hide pure visual separators and box borders from the operator table.
        decorative = r"=\-─═━|║╔╗╚╝╠╣╦╩╬┌┐└┘├┤┬┴┼█▔▁▏▕_ "
        if not re.sub(f"[{re.escape(decorative)}]", "", text).strip():
            return ""

        # Keep banner content, but remove the surrounding box art.
        text = text.strip(decorative)
        text = re.sub(r"^[|║]+", "", text).strip()
        text = re.sub(r"[|║]+$", "", text).strip()
        text = re.sub(r"\s*[|║]{2,}\s*", "  ", text).strip()
        return re.sub(r"\s+", " ", text).strip()

    def _append_table_row(self, entry):
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = [entry["time"], entry["level"], entry["phase"], entry["message"]]
        for col, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            if col == 0:
                item.setFont(QFont("Cascadia Code", 9))
            if col == 1:
                item.setForeground(self._level_color(entry["level"]))
                item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                item.setBackground(self._level_background(entry["level"]))
            if col == 3:
                item.setToolTip(str(value))
            self.table.setItem(row, col, item)
        if self._auto_scroll and not self.search_input.text().strip():
            self.table.scrollToBottom()

    def _level_color(self, level):
        return {
            "Error": QColor("#DC2626"),
            "Warning": QColor("#D97706"),
            "Success": QColor("#059669"),
            "Retry": QColor("#7C3AED"),
            "Wait": QColor("#0284C7"),
        }.get(level, QColor("#0F172A"))

    def _level_background(self, level):
        return {
            "Error": QColor("#FEF2F2"),
            "Warning": QColor("#FFFBEB"),
            "Success": QColor("#ECFDF5"),
            "Retry": QColor("#F5F3FF"),
            "Wait": QColor("#F0F9FF"),
        }.get(level, QColor("#FFFFFF"))

    def _apply_filters(self, *_args):
        text = self.search_input.text().strip().lower()
        for row, entry in enumerate(self._entries):
            visible = True
            if text and text not in entry["search"]:
                visible = False
            self.table.setRowHidden(row, not visible)
        if self._auto_scroll and not text:
            self.table.scrollToBottom()


class FolderReviewPanel(QWidget):
    browse_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(18)

        header = QLabel("Folder Intake")
        header.setObjectName("workspaceHeading")
        lay.addWidget(header)

        folder = QWidget()
        fl = QVBoxLayout(folder)
        fl.setContentsMargins(0, 4, 0, 0)
        fl.setSpacing(10)
        fl.addWidget(_field_label("CLAIM FOLDER PATH"))
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)
        self.inp_folder = _input("Click Browse...")
        self.inp_folder.setReadOnly(True)
        btn = QPushButton("Browse...")
        btn.setObjectName("btnBrowse")
        btn.setMinimumHeight(42)
        btn.setFixedWidth(120)
        btn.clicked.connect(self.browse_clicked.emit)
        rl.addWidget(self.inp_folder, 1)
        rl.addWidget(btn)
        fl.addWidget(row)
        self.doc_status_label = QLabel("No folder selected.")
        self.doc_status_label.setObjectName("helperTextItalic")
        fl.addWidget(self.doc_status_label)
        lay.addWidget(_card(folder, "Claim Folder", "Select the source folder with Excel data and documents"))

        lay.addWidget(self._build_readiness_card())
        lay.addStretch()

    def _build_readiness_card(self):
        row = QWidget()
        r = QHBoxLayout(row)
        r.setContentsMargins(0, 0, 0, 0)
        r.setSpacing(14)
        c1, self.stat_fields = _stat_card("—", "Fields Extracted", "#3B82F6")
        c2, self.stat_docs = _stat_card("—", "Documents Found", "#10B981")
        c3, self.stat_missing = _stat_card("—", "Missing Critical", "#F59E0B")
        c4, self.stat_status = _stat_card("Ready", "Status", "#8B5CF6")
        for c in (c1, c2, c3, c4):
            r.addWidget(c, 1)
        return _card(row, "Readiness Summary", "High-level status before automation")

    def reset(self):
        self.inp_folder.setText("")
        self.doc_status_label.setText("No folder selected.")
        self.stat_fields.setText("—")
        self.stat_docs.setText("—")
        self.stat_missing.setText("—")
        self.stat_status.setText("Ready")


class DataReviewPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        self._tables = []
        self._metadata = get_portal_ui_metadata("uiic")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.inner = QWidget()
        self.inner.setObjectName("workspaceScrollInner")
        self.lay = QVBoxLayout(self.inner)
        self.lay.setContentsMargins(32, 28, 32, 28)
        self.lay.setSpacing(16)

        header = QLabel("Extraction Review")
        header.setObjectName("workspaceHeading")
        self.lay.addWidget(header)

        self.validation_bar = QLabel("")
        self.validation_bar.setWordWrap(True)
        self.validation_bar.setVisible(False)
        self.lay.addWidget(self.validation_bar)

        search, self.preview_search_input = _search_row(
            "Filter extracted data by field, value, source, or status...",
            self._filter_tables,
        )
        self.lay.addWidget(search)
        self.empty_label = QLabel("Select a claim folder to review extracted fields.")
        self.empty_label.setObjectName("workspaceEmpty")
        self.lay.addWidget(_card(self.empty_label, "No Data Loaded", "Extraction details appear here after folder scan"))
        self.no_results_label = QLabel("No extracted fields match the current search.")
        self.no_results_label.setObjectName("workspaceEmpty")
        self.no_results_card = _card(self.no_results_label, "No Matches", "Try a different field, value, source, status, or section name")
        self.no_results_card.setVisible(False)
        self.lay.addWidget(self.no_results_card)
        self.lay.addStretch()
        scroll.setWidget(self.inner)
        root.addWidget(scroll)

    def reset(self):
        self.update_data(None, None)

    def update_data(self, claim, portal_id):
        self._clear_dynamic()
        self._rows = []
        self._metadata = get_portal_ui_metadata(portal_id)

        if not claim:
            self.validation_bar.setVisible(False)
            self.empty_label.parentWidget().setVisible(True)
            self.no_results_card.setVisible(False)
            self.lay.addStretch()
            return

        self.empty_label.parentWidget().setVisible(False)
        errors, warnings = claim.validate()
        if errors:
            self.validation_bar.setText("MISSING FIELDS - Review before starting:\n" + "\n".join(f"  - {e}" for e in errors))
            self.validation_bar.setObjectName("validationError")
            self.validation_bar.setStyleSheet("")
            self.validation_bar.style().unpolish(self.validation_bar)
            self.validation_bar.style().polish(self.validation_bar)
            self.validation_bar.setVisible(True)
        elif warnings:
            self.validation_bar.setText("Optional fields missing: " + " | ".join(warnings))
            self.validation_bar.setObjectName("validationWarn")
            self.validation_bar.setStyleSheet("")
            self.validation_bar.style().unpolish(self.validation_bar)
            self.validation_bar.style().polish(self.validation_bar)
            self.validation_bar.setVisible(True)
        else:
            self.validation_bar.setVisible(False)

        all_fields = claim.all_fields_for_preview()
        self._rows = list(all_fields)

        # Flatten ALL rows into one single table (no categories)
        if self._rows:
            self._add_flat_table(self._rows)

        self.lay.addStretch()
        self._filter_tables(self.preview_search_input.text())

    def summary_counts(self):
        total = len(self._rows)
        filled = 0
        missing_critical = 0
        pdf_sources = 0
        for _, value, is_critical, source in self._rows:
            has_val = bool(value and str(value).strip() not in ("", "—"))
            if has_val:
                filled += 1
            elif is_critical:
                missing_critical += 1
            if source and "pdf" in str(source).lower():
                pdf_sources += 1
        return filled, total, missing_critical, pdf_sources

    def _clear_dynamic(self):
        self._tables.clear()
        while self.lay.count() > 5:
            item = self.lay.takeAt(5)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _add_flat_table(self, rows):
        """Render all extracted fields in a single flat table — no category grouping."""
        table = self._build_table(rows)
        self._tables.append((table, table, "all", rows))
        self.lay.addWidget(table)

    def _build_table(self, rows):
        table = QTableWidget(0, 4)
        table.setAlternatingRowColors(True)
        table.setHorizontalHeaderLabels(["FIELD", "VALUE", "SOURCE", "STATUS"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(40)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setWordWrap(False)
        table.setMinimumHeight(min(380, max(120, 48 + len(rows) * 42)))
        table.setRowCount(len(rows))
        for i, (label, value, is_critical, source) in enumerate(rows):
            has_val = bool(value and str(value).strip() not in ("", "—"))
            table.setItem(i, 0, QTableWidgetItem(label))
            v_item = QTableWidgetItem(str(value) if value else "—")
            v_item.setForeground(QColor("#0F172A") if has_val else (QColor("#EF4444") if is_critical else QColor("#94A3B8")))
            table.setItem(i, 1, v_item)
            src_item = QTableWidgetItem(source or "—")
            src_item.setForeground(QColor("#6366F1") if source else QColor("#CBD5E1"))
            table.setItem(i, 2, src_item)
            status = "OK" if has_val else ("CRITICAL" if is_critical else "OPTIONAL")
            s_item = QTableWidgetItem(status)
            s_item.setForeground(QColor("#059669") if has_val else (QColor("#DC2626") if is_critical else QColor("#94A3B8")))
            table.setItem(i, 3, s_item)
        return table

    def _filter_tables(self, text):
        text = (text or "").strip().lower()
        any_visible = False
        for _, table, _title, _rows in self._tables:
            visible = 0
            for row in range(table.rowCount()):
                values = []
                for col in range(table.columnCount()):
                    item = table.item(row, col)
                    if item:
                        values.append(item.text().lower())
                hidden = bool(text) and text not in " ".join(values)
                table.setRowHidden(row, hidden)
                if not hidden:
                    visible += 1
            table.setVisible(visible > 0 or not text)
            any_visible = any_visible or (visible > 0 or not text)
        self.no_results_card.setVisible(bool(text) and not any_visible)


class DocumentReviewPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.inner = QWidget()
        self.lay = QVBoxLayout(self.inner)
        self.inner.setObjectName("workspaceScrollInner")
        self.lay.setContentsMargins(32, 28, 32, 28)
        self.lay.setSpacing(16)
        self.header = QLabel("Document Review")
        self.header.setObjectName("workspaceHeading")
        self.lay.addWidget(self.header)
        self.empty = QLabel("Select a claim folder to inspect document mapping.")
        self.empty.setObjectName("workspaceEmpty")
        self.lay.addWidget(_card(self.empty, "No Documents Loaded", "Matched, missing, skipped, and unknown files appear here"))
        search, self.doc_search_input = _search_row(
            "Search documents by type, filename, status, bucket, or reason...",
            self._filter_documents,
        )
        self.lay.addWidget(search)
        self.no_results = QLabel("No documents match the current search.")
        self.no_results.setObjectName("workspaceEmpty")
        self.no_results_card = _card(self.no_results, "No Matches", "Try a different filename, status, or document type")
        self.no_results_card.setVisible(False)
        self.lay.addWidget(self.no_results_card)
        self._doc_tables = []
        self.lay.addStretch()
        scroll.setWidget(self.inner)
        root.addWidget(scroll)

    def reset(self):
        self.update_data(None)

    def update_data(self, scan_result):
        self._clear_dynamic()
        if not scan_result:
            self.empty.parentWidget().setVisible(True)
            self.no_results_card.setVisible(False)
            self.lay.addStretch()
            return
        self.empty.parentWidget().setVisible(False)

        claim_docs = getattr(scan_result, "claim_doc_files", {}) or {}
        assessment = getattr(scan_result, "assessment_files", {}) or {}
        upload_docs = getattr(scan_result, "upload_doc_files", {}) or {}
        claim_related = getattr(scan_result, "claim_related_files", []) or []
        claim_related_pdf = getattr(scan_result, "claim_related_merged_pdf", None)
        expected = getattr(scan_result, "expected_docs", []) or []
        compressed_keys = getattr(scan_result, "compressed_upload_doc_files", set()) or set()
        missing = [doc for doc in expected if doc not in claim_docs]

        # Friendly display names for upload doc keys
        _UPLOAD_LABELS = {
            "driving_license":          "Driving License",
            "registration_certificate": "Registration Certificate",
            "claim_form":               "Claim Form",
        }

        stats = QWidget()
        grid = QGridLayout(stats)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        # Stat cards: Matched (claim+assessment+upload+claim_related), Missing mandatory
        claim_related_count = 1 if claim_related_pdf else 0
        for i, (value, label, color) in enumerate(
            [
                (len(claim_docs) + len(assessment) + len(upload_docs) + claim_related_count, "Matched", "#10B981"),
                (len(missing), "Missing", "#EF4444"),
            ]
        ):
            card, val = _stat_card(str(value), label, color)
            grid.addWidget(card, 0, i)
        self.lay.addWidget(stats)

        # Table: claim docs + assessment + upload docs + claim_related row + missing
        mapped_rows = []
        for k, v in claim_docs.items():
            mapped_rows.append((k, v, "claim_doc_files", "OK", False))
        for k, v in assessment.items():
            mapped_rows.append((k, v, "assessment_files", "OK", False))
        for k, v in upload_docs.items():
            friendly = _UPLOAD_LABELS.get(k, k.replace("_", " ").title())
            was_compressed = k in compressed_keys
            mapped_rows.append((friendly, v, "upload_doc_files", "OK", was_compressed))
        # Claim Related Documents — use pre-merged PDF path if available
        if claim_related_pdf:
            n = len(claim_related)
            label = f"Claim Related Documents ({n} file(s) merged)"
            mapped_rows.append((label, claim_related_pdf, "claim_related", "OK", False))
        elif claim_related:  # Files found but merge failed
            mapped_rows.append(("Claim Related Documents", "", "claim_related", "PENDING", False))
        for m in missing:
            mapped_rows.append((m, "", "expected_docs", "MISSING", False))

        if mapped_rows:
            self._add_flat_doc_table(mapped_rows)

        self.lay.addStretch()
        self._filter_documents(self.doc_search_input.text())

    def _clear_dynamic(self):
        self._doc_tables.clear()
        while self.lay.count() > 4:
            item = self.lay.takeAt(4)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _add_flat_doc_table(self, rows):
        """Render all documents in a single flat table — 4 columns, no category headers."""
        table = QTableWidget(0, 4)
        table.setAlternatingRowColors(True)
        table.setHorizontalHeaderLabels(["STATUS", "PORTAL / TYPE", "FILENAME", "DETAIL"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(42)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setWordWrap(False)
        table.setMinimumHeight(min(480, max(96, 48 + len(rows) * 38)))
        table.setRowCount(len(rows))
        for i, row_data in enumerate(rows):
            # Support both old 4-tuple and new 5-tuple (with compressed flag)
            if len(row_data) == 5:
                doc_type, value, bucket, status, was_compressed = row_data
            else:
                doc_type, value, bucket, status = row_data
                was_compressed = False
            filename = Path(value).name if value and os.path.exists(str(value)) else ("—" if not value else str(value))
            detail = ""
            if value and os.path.exists(str(value)):
                size_mb = os.path.getsize(value) / (1024 * 1024)
                detail = f"{size_mb:.1f} MB"
                if was_compressed:
                    detail += " ⚡ compressed"
            elif bucket == "skipped_files":
                detail = str(value)
            table.setItem(i, 0, QTableWidgetItem(status))
            table.setItem(i, 1, QTableWidgetItem(str(doc_type)))
            table.setItem(i, 2, QTableWidgetItem(filename))
            table.setItem(i, 3, QTableWidgetItem(detail or "—"))
        self._doc_tables.append((table, table, "all"))
        self.lay.addWidget(table)

    def _filter_documents(self, text):
        text = (text or "").strip().lower()
        any_visible = False
        for _, table, _title in self._doc_tables:
            visible = 0
            for row in range(table.rowCount()):
                values = []
                for col in range(table.columnCount()):
                    item = table.item(row, col)
                    if item:
                        values.append(item.text().lower())
                hidden = bool(text) and text not in " ".join(values)
                table.setRowHidden(row, hidden)
                if not hidden:
                    visible += 1
            table.setVisible(visible > 0 or not text)
            any_visible = any_visible or (visible > 0 or not text)
        self.no_results_card.setVisible(bool(text) and not any_visible)


class WorkspacePage(QWidget):
    browse_clicked = pyqtSignal()
    start_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    export_log_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._claim = None
        self._scan_result = None
        self._portal_id = "uiic"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        main = QWidget()
        main.setObjectName("workspacePage")
        ml = QHBoxLayout(main)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)

        rail_wrap = QWidget()
        rail_wrap.setObjectName("workflowRailWrap")
        rail_lay = QVBoxLayout(rail_wrap)
        rail_lay.setContentsMargins(0, 0, 0, 0)
        rail_lay.setSpacing(0)
        self.rail = WorkflowRail()
        self.rail.stage_selected.connect(self.set_stage)
        rail_lay.addWidget(self.rail, 1)

        actions = QWidget()
        actions.setObjectName("railActions")
        al = QVBoxLayout(actions)
        al.setContentsMargins(18, 12, 18, 18)
        al.setSpacing(8)
        self.btn_start = QPushButton("Start Automation")
        self.btn_start.setObjectName("btnStart")
        self.btn_start.clicked.connect(self.start_clicked.emit)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setObjectName("btnStop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_clicked.emit)
        al.addWidget(self.btn_start)
        al.addWidget(self.btn_stop)
        rail_lay.addWidget(actions)

        self.stack = QStackedWidget()
        self.folder_panel = FolderReviewPanel()
        self.folder_panel.browse_clicked.connect(self.browse_clicked.emit)
        self.data_panel = DataReviewPanel()
        self.document_panel = DocumentReviewPanel()
        self.logs_panel = StructuredLogsPanel()
        self._current_phase = "General"
        for panel in (
            self.folder_panel,
            self.data_panel,
            self.document_panel,
            self.logs_panel,
        ):
            self.stack.addWidget(panel)

        ml.addWidget(rail_wrap)
        ml.addWidget(self.stack, 1)
        root.addWidget(main, 1)

        self.logs_drawer = LogsDrawer()
        self.logs_drawer.btn_clear.clicked.connect(self.clear_logs)
        self.logs_drawer.btn_export.clicked.connect(self.export_log_clicked.emit)
        self.logs_panel.copy_clicked.connect(lambda: QApplication.clipboard().setText(self.logs_panel.log_text(visible_only=True)))
        self.logs_panel.clear_clicked.connect(self.clear_logs)
        self.logs_panel.export_clicked.connect(self.export_log_clicked.emit)

        # Compatibility handles used by MainWindow during the migration.
        self.inp_folder = self.folder_panel.inp_folder
        self.doc_status_label = self.folder_panel.doc_status_label
        self.stat_fields = self.folder_panel.stat_fields
        self.stat_docs = self.folder_panel.stat_docs
        self.stat_missing = self.folder_panel.stat_missing
        self.stat_status = self.folder_panel.stat_status
        self.validation_bar = self.data_panel.validation_bar
        self.log_output = self.logs_drawer.log_output

    def set_portal(self, portal_id):
        self._portal_id = portal_id or "uiic"

    def set_stage(self, idx: int):
        self.stack.setCurrentIndex(idx)
        self.rail.set_active(idx)

    def reset_state(self):
        self._claim = None
        self._scan_result = None
        self.folder_panel.reset()
        self.data_panel.reset()
        self.document_panel.reset()
        self.logs_panel.clear_logs()
        self.logs_drawer.clear_logs()
        self._current_phase = "General"
        self.rail.reset()
        self.set_stage(0)

    def update_data(self, claim, scan_result):
        self._claim = claim
        self._scan_result = scan_result
        self.data_panel.update_data(claim, self._portal_id)
        self.document_panel.update_data(scan_result)

        filled, total, missing_critical, _pdf_sources = self.data_panel.summary_counts()
        self.stat_fields.setText(f"{filled}/{total}" if total else "—")
        self.stat_missing.setText(str(missing_critical))
        self.stat_status.setText("Warn" if missing_critical else "Ready")

        total_docs = 0
        if scan_result:
            claim_docs = getattr(scan_result, "claim_doc_files", {}) or {}
            assessment = getattr(scan_result, "assessment_files", {}) or {}
            upload_docs = getattr(scan_result, "upload_doc_files", {}) or {}
            unknown = getattr(scan_result, "unknown_files", []) or []
            total_docs = len(claim_docs) + len(assessment) + len(upload_docs)
            parts = [
                f"Claim docs: {len(claim_docs)}" if claim_docs else "",
                f"Assessment: {len(assessment)}" if assessment else "",
                f"Upload docs: {len(upload_docs)}" if upload_docs else "",
                f"Unknown: {len(unknown)}" if unknown else "",
            ]
            self.doc_status_label.setText("  |  ".join([p for p in parts if p]) or "No documents detected.")
        self.stat_docs.setText(str(total_docs) if scan_result else "—")


        self.rail.set_stage_state(0, "done")
        self.rail.set_stage_state(1, "warning" if missing_critical else "done")
        missing_docs = []
        if scan_result:
            expected = getattr(scan_result, "expected_docs", []) or []
            claim_docs = getattr(scan_result, "claim_doc_files", {}) or {}
            missing_docs = [doc for doc in expected if doc not in claim_docs]
        self.rail.set_stage_state(2, "warning" if missing_docs else "done")

    def set_scan_failed(self):
        self.rail.set_stage_state(0, "failed")
        self.rail.set_stage_state(1, "pending")
        self.rail.set_stage_state(2, "pending")
        self.document_panel.update_data(self._scan_result)

    def set_automation_running(self, running: bool):
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self._current_phase = "Startup" if running else "General"
        self.rail.set_stage_state(3, "active" if running else "done")
        self.set_stage(3)

    def set_automation_finished(self, success: bool):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._current_phase = "Finished" if success else "Stopped"
        self.rail.set_stage_state(3, "done" if success else "failed")
        self.set_stage(3)

    def append_log(self, text):
        self.logs_drawer.append_log(text)
        self.logs_panel.append_log(text, portal_id=self._portal_id, phase=self._current_phase or "General")

    def clear_logs(self):
        self.logs_drawer.clear_logs()
        self.logs_panel.clear_logs()

    def log_text(self):
        return self.logs_panel.log_text() or self.logs_drawer.log_text()

    def set_step(self, idx: int, name: str = ""):
        if name:
            self._current_phase = name
        self.rail.set_stage_state(3, "active")
        self.set_stage(3)
