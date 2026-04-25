from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPainterPath
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QStackedWidget, QScrollArea, QGridLayout,
    QLineEdit, QTableWidget, QHeaderView, QFileDialog, QMessageBox,
    QTableWidgetItem
)
import os
import json
from app.utils import (
    load_settings, save_settings, settings_paths,
    load_field_mapping, save_field_mapping, reset_field_mapping,
    load_doc_mapping, save_doc_mapping, reset_doc_mapping
)

class SettingsPage(QWidget):
    def __init__(self, parent=None, append_log_cb=None):
        super().__init__(parent)
        self.append_log = append_log_cb or (lambda x: None)
        self._create_icons()
        self._setup_ui()
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
        h_lay = QHBoxLayout(header); h_lay.setContentsMargins(32, 0, 32, 0)
        title = QLabel("\u2699  Settings"); title.setStyleSheet("font-size:15pt; font-weight:700; color:#1E293B;")
        h_lay.addWidget(title); h_lay.addStretch(); root.addWidget(header)

        # Tabs
        self.tab_bar = QFrame(); tl = QHBoxLayout(self.tab_bar); tl.setContentsMargins(32, 10, 32, 0)
        self.tabs = []
        for i, name in enumerate(["General", "Field Mapping", "Document Mapping", "PDF Mapping"]):
            btn = QPushButton(name); btn.setObjectName("settingsTabBtn"); btn.setProperty("active", i==0)
            btn.setMinimumSize(150, 38); btn.clicked.connect(lambda ch, idx=i: self._switch_tab(idx))
            tl.addWidget(btn); self.tabs.append(btn)
        tl.addStretch(); root.addWidget(self.tab_bar)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_general_tab())
        self.stack.addWidget(self._build_field_mapping_tab())
        self.stack.addWidget(self._build_doc_mapping_tab())
        self.stack.addWidget(self._build_pdf_mapping_tab())
        root.addWidget(self.stack, 1)

        # Footer
        footer = QFrame(); footer.setFixedHeight(68); fl = QHBoxLayout(footer); fl.setContentsMargins(32, 0, 32, 0)
        br = QPushButton("  Reset to Defaults  "); br.clicked.connect(self._reset_defaults); fl.addWidget(br); fl.addStretch()
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
            lbl = QLabel(text); lbl.setStyleSheet("color:#475569; font-weight:600;"); return lbl

        l.addWidget(_f("Username"))
        self.inp_username = QLineEdit(); self.inp_username.setMinimumHeight(40); l.addWidget(self.inp_username)
        l.addWidget(_f("Password"))
        row = QWidget(); rl = QHBoxLayout(row); rl.setContentsMargins(0,0,0,0)
        self.inp_password = QLineEdit(); self.inp_password.setEchoMode(QLineEdit.EchoMode.Password); self.inp_password.setMinimumHeight(40)
        self.btn_eye = QPushButton(); self.btn_eye.setIcon(self._icon_eye_closed); self.btn_eye.setFixedSize(40, 40); self.btn_eye.setCheckable(True); self.btn_eye.clicked.connect(self._toggle_pwd)
        rl.addWidget(self.inp_password); rl.addWidget(self.btn_eye); l.addWidget(row)
        l.addWidget(_f("Portal URL"))
        self.inp_url = QLineEdit(); self.inp_url.setMinimumHeight(40); l.addWidget(self.inp_url)
        l.addWidget(_f("Slow-Mo (ms)"))
        self.inp_slowmo = QLineEdit(); self.inp_slowmo.setMinimumHeight(40); l.addWidget(self.inp_slowmo)
        l.addWidget(_f("Timeout (ms)"))
        self.inp_timeout = QLineEdit(); self.inp_timeout.setMinimumHeight(40); l.addWidget(self.inp_timeout)
        l.addStretch(); s.setWidget(w); return s

    def _toggle_pwd(self, ch):
        self.inp_password.setEchoMode(QLineEdit.EchoMode.Normal if ch else QLineEdit.EchoMode.Password)
        self.btn_eye.setIcon(self._icon_eye_open if ch else self._icon_eye_closed)

    def _build_field_mapping_tab(self):
        s = QScrollArea(); s.setWidgetResizable(True); s.setFrameShape(QFrame.Shape.NoFrame)
        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(32, 24, 32, 24)
        self.mapping_table = QTableWidget(0, 4)
        self.mapping_table.setHorizontalHeaderLabels(["FIELD NAME", "SEARCH LABEL", "SHEET", "COL OFFSET"])
        self.mapping_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.mapping_table.verticalHeader().setVisible(False); l.addWidget(self.mapping_table)
        s.setWidget(w); return s

    def _build_doc_mapping_tab(self):
        s = QScrollArea(); s.setWidgetResizable(True); s.setFrameShape(QFrame.Shape.NoFrame)
        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(32, 24, 32, 24)
        self.doc_table = QTableWidget(0, 3)
        self.doc_table.setHorizontalHeaderLabels(["SECTION", "PORTAL DOC TYPE", "FILENAME KEYWORDS"])
        self.doc_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.doc_table.verticalHeader().setVisible(False); l.addWidget(self.doc_table)
        s.setWidget(w); return s

    def _build_pdf_mapping_tab(self):
        s = QScrollArea(); s.setWidgetResizable(True); s.setFrameShape(QFrame.Shape.NoFrame)
        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(32, 24, 32, 24); l.setSpacing(16)
        l.addWidget(QLabel("Invoice No Labels"))
        self.inp_pdf_inv = QLineEdit(); self.inp_pdf_inv.setMinimumHeight(40); l.addWidget(self.inp_pdf_inv)
        l.addWidget(QLabel("Invoice Date Labels"))
        self.inp_pdf_date = QLineEdit(); self.inp_pdf_date.setMinimumHeight(40); l.addWidget(self.inp_pdf_date)
        l.addStretch(); s.setWidget(w); return s

    def _load_data(self):
        s = load_settings()
        self.inp_username.setText(s.get("username", ""))
        self.inp_password.setText(s.get("password", ""))
        self.inp_url.setText(s.get("portal_url", ""))
        self.inp_slowmo.setText(str(s.get("browser_slow_mo_ms", 400)))
        self.inp_timeout.setText(str(s.get("timeout_ms", 4000)))
        self.inp_pdf_inv.setText(" | ".join(s.get("pdf_invoice_no_labels", [])))
        self.inp_pdf_date.setText(" | ".join(s.get("pdf_invoice_date_labels", [])))

        # Field Mapping
        m = load_field_mapping()
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
            self.mapping_table.setItem(i, 2, QTableWidgetItem(cfg.get("sheet", "ALL")))
            self.mapping_table.setItem(i, 3, QTableWidgetItem(str(cfg.get("col_offset", 1))))

        # Doc Mapping
        dm = load_doc_mapping()
        rows = []
        for sk in ("claim_documents_tab", "claim_assessment_tab"):
            sec = dm.get(sk, {})
            lbl = "Claim Docs" if "claim_doc" in sk else "Assessment"
            for dt, kws in sec.items():
                rows.append((lbl, dt, " | ".join(kws) if isinstance(kws, list) else str(kws)))
        self.doc_table.setRowCount(len(rows))
        for i, (sec, dt, kws) in enumerate(rows):
            self.doc_table.setItem(i, 0, QTableWidgetItem(sec))
            self.doc_table.item(i, 0).setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.doc_table.setItem(i, 1, QTableWidgetItem(dt))
            self.doc_table.item(i, 1).setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.doc_table.setItem(i, 2, QTableWidgetItem(kws))

    def _save_all(self):
        try:
            overrides = {
                "username": self.inp_username.text().strip(),
                "password": self.inp_password.text().strip(),
                "portal_url": self.inp_url.text().strip(),
                "browser_slow_mo_ms": int(self.inp_slowmo.text() or 400),
                "timeout_ms": int(self.inp_timeout.text() or 4000),
                "pdf_invoice_no_labels": [l.strip() for l in self.inp_pdf_inv.text().split("|") if l.strip()],
                "pdf_invoice_date_labels": [l.strip() for l in self.inp_pdf_date.text().split("|") if l.strip()],
            }
            save_settings(overrides)

            # Field Mapping Save
            m = load_field_mapping()
            nm = {k: v for k, v in m.items() if k.startswith("_")}
            for r in range(self.mapping_table.rowCount()):
                fn = self.mapping_table.item(r, 0).text()
                lt = self.mapping_table.item(r, 1).text().strip()
                sh = self.mapping_table.item(r, 2).text().strip() or "ALL"
                try: co = int(self.mapping_table.item(r, 3).text())
                except: co = 1
                old = m.get(fn, {})
                labels = [l.strip() for l in lt.split("|") if l.strip()]
                nm[fn] = {**old, "sheet": sh, "search_labels": labels, "col_offset": co}
                if "search_label" in nm[fn]: del nm[fn]["search_label"]
            save_field_mapping(nm)

            # Doc Mapping Save
            dm = load_doc_mapping()
            ndm = {k: v for k, v in dm.items() if k.startswith("_")}
            cd, ad = {}, {}
            for r in range(self.doc_table.rowCount()):
                sec = self.doc_table.item(r, 0).text()
                dt = self.doc_table.item(r, 1).text()
                kws = [k.strip() for k in self.doc_table.item(r, 2).text().split("|") if k.strip()]
                if "Claim" in sec: cd[dt] = kws
                else: ad[dt] = kws
            ndm["claim_documents_tab"], ndm["claim_assessment_tab"] = cd, ad
            save_doc_mapping(ndm)

            self.append_log("\u2705  Settings saved.")
            QMessageBox.information(self, "Success", "All settings saved.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Save failed: {e}")

    def _reset_defaults(self):
        if QMessageBox.question(self, "Reset", "Reset all to defaults?") == QMessageBox.StandardButton.Yes:
            reset_field_mapping(); reset_doc_mapping()
            # Reset user settings by removing file
            sp = settings_paths()
            if os.path.exists(sp["user"]): os.remove(sp["user"])
            self._load_data()
            self.append_log("\u2139  Settings reset.")
