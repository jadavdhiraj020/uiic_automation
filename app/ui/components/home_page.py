from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QScrollArea, QGridLayout, QTableWidget, QHeaderView, QTableWidgetItem
)
from app.ui.components.widgets import (
    create_label as _label, field_label as _field_label,
    create_input as _input, card as _card, stat_card as _stat_card
)

class HomePage(QWidget):
    browse_clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget(); inner.setObjectName("homePage")
        lay = QVBoxLayout(inner); lay.setContentsMargins(32, 24, 32, 24); lay.setSpacing(24)

        # Row 1: Folder Card
        self.folder_card = self._build_folder_card()
        lay.addWidget(self.folder_card)

        # Validation Bar
        self.validation_bar = QLabel("")
        self.validation_bar.setWordWrap(True)
        self.validation_bar.setVisible(False)
        self.validation_bar.setStyleSheet("border-radius:10px; padding:10px 14px; font-size:8.5pt;")
        lay.addWidget(self.validation_bar)

        # Row 2: Stats
        self.stats_row = self._build_stats_row()
        lay.addWidget(self.stats_row)

        # Row 3: Preview
        self.preview_card = self._build_preview_card()
        lay.addWidget(self.preview_card)

        lay.addStretch()
        scroll.setWidget(inner)
        main_lay = QVBoxLayout(self); main_lay.setContentsMargins(0,0,0,0); main_lay.addWidget(scroll)

    def _build_folder_card(self):
        w = QWidget()
        lay = QVBoxLayout(w); lay.setContentsMargins(0, 4, 0, 0); lay.setSpacing(10)
        lay.addWidget(_field_label("CLAIM FOLDER PATH"))
        row = QWidget(); rlay = QHBoxLayout(row); rlay.setContentsMargins(0,0,0,0); rlay.setSpacing(10)
        self.inp_folder = _input("Click Browse...")
        self.inp_folder.setReadOnly(True)
        self.inp_folder.setStyleSheet("""
            QLineEdit { 
                background: #F8FAFC; 
                border: 1px solid #CBD5E1; 
                border-radius: 8px; 
                padding: 10px 15px; 
                color: #0F172A; 
                font-weight: 700; 
                font-size: 10.5pt;
            }
        """)
        btn = QPushButton("Browse..."); btn.setObjectName("btnBrowse"); btn.setFixedWidth(120); btn.setMinimumHeight(44)
        btn.clicked.connect(self.browse_clicked.emit)
        rlay.addWidget(self.inp_folder, 1); rlay.addWidget(btn)
        lay.addWidget(row)
        self.doc_status_label = QLabel("No folder selected.")
        self.doc_status_label.setObjectName("helperTextItalic")
        lay.addWidget(self.doc_status_label)
        return _card(w, "\U0001F4C2  Claim Folder", "Select folder with Excel file and scanned documents")

    def _build_stats_row(self):
        row = QWidget(); rlay = QHBoxLayout(row); rlay.setContentsMargins(0,0,0,0); rlay.setSpacing(16)
        c1, self.stat_fields = _stat_card("—", "Fields Extracted", "#3B82F6")
        c2, self.stat_docs   = _stat_card("—", "Documents Found", "#10B981")
        c3, self.stat_missing = _stat_card("—", "Missing Critical", "#F59E0B")
        c4, self.stat_status = _stat_card("Ready", "Status", "#8B5CF6")
        rlay.addWidget(c1, 1); rlay.addWidget(c2, 1); rlay.addWidget(c3, 1); rlay.addWidget(c4, 1)
        return row

    def _build_preview_card(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(0, 4, 0, 0); lay.setSpacing(8)
        self.preview_table = QTableWidget(0, 4)
        self.preview_table.setHorizontalHeaderLabels(["FIELD", "VALUE", "SOURCE", "STATUS"])
        self.preview_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.preview_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.preview_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.preview_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.verticalHeader().setDefaultSectionSize(44)
        self.preview_table.setMinimumHeight(450)
        self.preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.preview_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.preview_table.setStyleSheet("""
            QTableWidget { 
                border: 2px solid #0F172A; 
                border-radius: 0px; 
                background-color: #FFFFFF; 
                gridline-color: #E2E8F0;
                color: #0F172A; 
                font-size: 10pt;
                font-weight: 600;
            }
            QTableWidget::item { padding: 12px; }
            QTableWidget::item:selected { background-color: #F8FAFC; color: #4F46E5; }
            QHeaderView::section { 
                background-color: #FFFFFF; 
                color: #0F172A; 
                font-weight: 800; 
                font-size: 8.5pt; 
                padding: 14px 10px; 
                border: none; 
                border-bottom: 3px solid #0F172A; 
                text-transform: uppercase; 
            }
        """)
        lay.addWidget(self.preview_table)
        return _card(w, "📊  Extracted Data", "🔴 Critical missing  /  🟡 Optional  /  🟢 Found")

    def update_data(self, claim, scan_result):
        if not claim: return
        errors, warnings = claim.validate()
        if errors:
            self.validation_bar.setText("⚠  MISSING FIELDS — Review before starting:\n" + "\n".join(f"  • {e}" for e in errors))
            self.validation_bar.setStyleSheet("background:#FFF7ED; color:#C2410C; border:2px solid #C2410C; border-radius:0px; padding:16px; font-size:10pt; font-weight:800;")
            self.validation_bar.setVisible(True)
        elif warnings:
            self.validation_bar.setText("⚠️  Optional fields missing: " + " | ".join(warnings))
            self.validation_bar.setStyleSheet("background:#FFFBEB; color:#B45309; border:2px solid #B45309; border-radius:0px; padding:16px; font-size:10pt; font-weight:800;")
            self.validation_bar.setVisible(True)
        else:
            self.validation_bar.setVisible(False)

        all_fields = claim.all_fields_for_preview()
        self.preview_table.setRowCount(len(all_fields))
        filled_count = 0
        missing_critical = 0
        for i, (label, value, is_critical, source) in enumerate(all_fields):
            has_val = bool(value and str(value).strip() not in ("", "—"))
            if has_val: filled_count += 1
            elif is_critical: missing_critical += 1

            self.preview_table.setItem(i, 0, QTableWidgetItem(label))
            v_item = QTableWidgetItem(str(value) if value else "—")
            if has_val: v_item.setForeground(QColor("#0F172A"))
            elif is_critical: v_item.setForeground(QColor("#EF4444"))
            else: v_item.setForeground(QColor("#94A3B8"))
            self.preview_table.setItem(i, 1, v_item)
            
            src_item = QTableWidgetItem(source or "—")
            src_item.setForeground(QColor("#6366F1") if source else QColor("#CBD5E1"))
            self.preview_table.setItem(i, 2, src_item)
            
            status = "✓ OK" if has_val else ("⚠ CRITICAL" if is_critical else "○ OPTIONAL")
            s_item = QTableWidgetItem(status)
            s_item.setForeground(QColor("#059669") if has_val else (QColor("#DC2626") if is_critical else QColor("#94A3B8")))
            self.preview_table.setItem(i, 3, s_item)

        self.stat_fields.setText(f"{filled_count}/{len(all_fields)}")
        self.stat_missing.setText(str(missing_critical))
        
        if missing_critical > 0:
            self.stat_status.setText("Warn")
            self.stat_status.setStyleSheet("color: #F59E0B; font-size: 22pt; font-weight: 800; background: transparent;")
        else:
            self.stat_status.setText("Ready")
            self.stat_status.setStyleSheet("color: #8B5CF6; font-size: 22pt; font-weight: 800; background: transparent;")

        if scan_result:
            docs = scan_result.claim_doc_files
            asses = scan_result.assessment_files
            unkn = getattr(scan_result, 'unknown_files', [])
            total = len(docs) + len(asses)
            if total:
                parts = [f"Claim docs: {len(docs)}" if docs else "", f"Assessment: {len(asses)}" if asses else "", f"Unknown: {len(unkn)}" if unkn else ""]
                self.doc_status_label.setText("  │  ".join([p for p in parts if p]))
                self.doc_status_label.setStyleSheet("color:#475569; font-size:8.5pt;")
            else:
                self.doc_status_label.setText("No documents detected — check folder contents.")
                self.doc_status_label.setStyleSheet("color:#DC2626; font-size:8.5pt;")
            self.stat_docs.setText(str(total))
