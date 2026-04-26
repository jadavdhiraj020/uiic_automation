"""
main_window.py  — Premium Dark Dashboard UI for UIIC Automation.
Modularized version delegating to component classes.
"""
import json
import os
import asyncio
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore    import Qt, QThread, pyqtSignal, QObject, QSize, QPropertyAnimation, QEasingCurve, QPointF
from PyQt6.QtGui     import QFont, QColor, QTextCursor, QIcon, QPainter, QPen, QPixmap, QPainterPath
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QProgressBar, QTextEdit,
    QFileDialog, QFrame, QSizePolicy, QScrollArea, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QSpacerItem, QApplication, QStackedWidget, QGraphicsOpacityEffect
)

from app.utils import (
    resource_path, load_settings, settings_paths, user_data_dir, ensure_dir,
)

from app.ui.worker import AutomationWorker
from app.ui.components.home_page import HomePage
from app.ui.components.progress_page import ProgressPage
from app.ui.components.settings_page import SettingsPage

CONFIG_DIR = resource_path("app", "config")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._worker      = None
        self._thread      = None
        self._claim       = None
        self._scan_result = None
        self._log_file    = None
        
        self._open_log_file()
        self._create_icons()
        self._setup_ui()
        self._setup_animations()

    def _create_icons(self):
        def _draw_nav_icon(draw_fn):
            s = 18; px = QPixmap(s, s); px.fill(QColor(0, 0, 0, 0))
            p = QPainter(px); p.setRenderHint(QPainter.RenderHint.Antialiasing)
            draw_fn(p, s); p.end(); return QIcon(px)
        
        def _draw_home(p, s):
            pen = QPen(QColor("#94A3B8")); pen.setWidthF(1.6); p.setPen(pen)
            p.drawLine(2, 9, 9, 3); p.drawLine(9, 3, 16, 9); p.drawLine(4, 9, 4, 15); p.drawLine(14, 9, 14, 15); p.drawLine(4, 15, 14, 15)
        
        def _draw_progress(p, s):
            pen = QPen(QColor("#94A3B8")); pen.setWidthF(1.6); p.setPen(pen)
            p.drawEllipse(3, 3, 12, 12); p.setBrush(QColor("#94A3B8")); p.setPen(Qt.PenStyle.NoPen); p.drawEllipse(QPointF(9, 4), 1.5, 1.5)

        def _draw_settings(p, s):
            import math
            pen = QPen(QColor("#94A3B8")); pen.setWidthF(1.6); p.setPen(pen)
            p.drawEllipse(QPointF(9, 9), 5.0, 5.0); p.drawEllipse(QPointF(9, 9), 2.2, 2.2)
            for a in range(0, 360, 45):
                r = math.radians(a); x1, y1 = 9+4.2*math.cos(r), 9+4.2*math.sin(r); x2, y2 = 9+7*math.cos(r), 9+7*math.sin(r)
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        self._icon_home = _draw_nav_icon(_draw_home)
        self._icon_progress = _draw_nav_icon(_draw_progress)
        self._icon_settings = _draw_nav_icon(_draw_settings)

    def _setup_ui(self):
        self.setWindowTitle("UIIC Automation")
        self.setMinimumSize(1060, 720); self.resize(1260, 880)

        root = QWidget(); self.setCentralWidget(root)
        lay = QVBoxLayout(root); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)

        # Topbar
        lay.addWidget(self._build_topbar())

        # Stack
        self.stack = QStackedWidget()
        self.home_page = HomePage(); self.home_page.browse_clicked.connect(self._browse_folder)
        self.progress_page = ProgressPage()
        self.settings_page = SettingsPage(append_log_cb=self._append_log)
        
        self.stack.addWidget(self.home_page)     # 0
        self.stack.addWidget(self.progress_page) # 1
        self.stack.addWidget(self.settings_page) # 2
        lay.addWidget(self.stack, 1)

        # Action bar
        lay.addWidget(self._build_action_bar())

    def _build_topbar(self):
        bar = QFrame(); bar.setObjectName("topBar"); bar.setFixedHeight(56)
        lay = QHBoxLayout(bar); lay.setContentsMargins(32, 0, 32, 0)
        
        logo = QLabel("UIIC"); logo.setObjectName("appLogo")
        logo_sub = QLabel("AUTOMATION"); logo_sub.setObjectName("appLogoSub")
        lay.addWidget(logo); lay.addWidget(logo_sub); lay.addStretch()

        self.btns = []
        for i, (name, icon) in enumerate([("  Home", self._icon_home), ("  Progress", self._icon_progress), ("  Settings", self._icon_settings)]):
            b = QPushButton(name); b.setIcon(icon); b.setObjectName("navBtn"); b.setMinimumSize(110, 36); b.setProperty("active", i==0)
            b.setCursor(Qt.CursorShape.PointingHandCursor); b.clicked.connect(lambda ch, idx=i: self._switch_page(idx))
            lay.addWidget(b); self.btns.append(b)

        lay.addStretch()
        ver = QLabel("v3.0"); ver.setObjectName("appVersion"); lay.addWidget(ver)
        
        self.status_pill = QFrame(); self.status_pill.setObjectName("statusPill"); self.status_pill.setProperty("status", "ready")
        sl = QHBoxLayout(self.status_pill); sl.setContentsMargins(12, 0, 12, 0); sl.setSpacing(8)
        self.status_dot = QFrame(); self.status_dot.setFixedSize(8, 8); self.status_dot.setObjectName("statusDot")
        self.status_text = QLabel("Ready"); self.status_text.setObjectName("statusText")
        sl.addWidget(self.status_dot); sl.addWidget(self.status_text); lay.addWidget(self.status_pill)
        
        return bar

    def _build_action_bar(self):
        bar = QFrame(); bar.setFixedHeight(84); bar.setObjectName("actionBar")
        lay = QHBoxLayout(bar); lay.setContentsMargins(32, 0, 32, 0); lay.setSpacing(12)
        
        self.btn_start = QPushButton("  ▶  Start Automation  "); self.btn_start.setObjectName("btnStart"); self.btn_start.setMinimumHeight(44); self.btn_start.clicked.connect(self._start_automation)
        self.btn_stop = QPushButton("■  Stop"); self.btn_stop.setEnabled(False); self.btn_stop.setMinimumHeight(44); self.btn_stop.clicked.connect(self._stop_automation)
        self.btn_clear = QPushButton("Clear Log"); self.btn_clear.setFixedWidth(110); self.btn_clear.clicked.connect(lambda: self.progress_page.log_output.clear())
        self.btn_export = QPushButton("Export Log"); self.btn_export.setFixedWidth(120); self.btn_export.clicked.connect(self._export_log)
        
        lay.addWidget(self.btn_start); lay.addWidget(self.btn_stop); lay.addStretch(); lay.addWidget(self.btn_clear); lay.addWidget(self.btn_export)
        return bar

    def _switch_page(self, idx):
        self.stack.setCurrentIndex(idx)
        for i, b in enumerate(self.btns):
            b.setProperty("active", i == idx); b.style().unpolish(b); b.style().polish(b)

    def _setup_animations(self):
        self._pulse_eff = QGraphicsOpacityEffect(self.status_dot)
        self.status_dot.setGraphicsEffect(self._pulse_eff)
        self.pulse_anim = QPropertyAnimation(self._pulse_eff, b"opacity")
        self.pulse_anim.setDuration(800); self.pulse_anim.setStartValue(0.3); self.pulse_anim.setEndValue(1.0)
        self.pulse_anim.setLoopCount(-1); self.pulse_anim.setEasingCurve(QEasingCurve.Type.InOutSine); self.pulse_anim.start()

    def _open_log_file(self):
        try:
            log_dir = ensure_dir(user_data_dir("logs"))
            base_log = os.path.join(log_dir, "automation.log")
            self._log_file = open(base_log, "w", encoding="utf-8")
        except: pass

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Claim Folder")
        if folder:
            self.home_page.inp_folder.setText(folder)
            self._scan_folder(folder)

    def _scan_folder(self, folder):
        from app.ui.services.claim_folder_service import ClaimFolderService
        service = ClaimFolderService(config_dir=CONFIG_DIR)
        res = service.process_folder(folder)
        for line in res.log_lines: self._append_log(line)
        if res.success:
            self._claim = res.claim; self._scan_result = res.scan_result
            self.home_page.update_data(self._claim, self._scan_result)
            self._set_status("ready", "Ready")
        else:
            self._set_status("error", "Scan Failed")

    def _set_status(self, status, text):
        self.status_text.setText(text)
        self.status_pill.setProperty("status", status)
        for w in [self.status_pill, self.status_dot]: w.style().unpolish(w); w.style().polish(w)

    def _append_log(self, msg):
        from app.ui.services.log_formatter import format_log_html
        ts = datetime.now().strftime("%H:%M:%S")
        self.progress_page.append_log(format_log_html(msg, ts))
        if self._log_file:
            try:
                self._log_file.write(f"[{datetime.now()}] {msg}\n")
                self._log_file.flush()
            except: pass

    def _export_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Log", f"uiic_log_{datetime.now():%Y%m%d_%H%M%S}.txt", "Text Files (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f: f.write(self.progress_page.log_output.toPlainText())
            self._append_log(f"📋 Log exported to: {path}")

    def _start_automation(self):
        if not self._claim:
            QMessageBox.warning(self, "No Folder", "Select a claim folder first."); return
        s = load_settings()
        if not s.get("username") or not s.get("password"):
            QMessageBox.warning(self, "Setup Required", "Configure credentials in Settings first."); self._switch_page(2); return
        
        errors, warnings = self._claim.validate()
        if errors:
            if QMessageBox.warning(self, "Missing Fields", f"Missing:\n" + "\n".join(errors) + "\n\nContinue?", QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes: return

        self.btn_start.setEnabled(False); self.btn_stop.setEnabled(True); self._switch_page(1)
        self.progress_page.set_progress(0); self.progress_page.set_step(0)
        self._set_status("running", "Running...")
        self._worker = AutomationWorker(self._claim, s)
        self._thread = QThread(); self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log_signal.connect(self._append_log)
        self._worker.step_signal.connect(self.progress_page.set_step)
        self._worker.step_signal.connect(lambda idx, name: self.progress_page.set_progress(int(idx*100/5)))
        self._worker.done_signal.connect(self._on_done)
        self._thread.start()

    def _stop_automation(self):
        if self._worker: self._worker.stop()
        self.btn_stop.setEnabled(False); self._set_status("running", "Stopping...")

    def _on_done(self, success, msg):
        self.btn_start.setEnabled(True); self.btn_stop.setEnabled(False)
        self._append_log(msg)
        if success: self.progress_page.set_step(5); self.progress_page.set_progress(100); self._set_status("ready", "Complete ✓")
        else: self._set_status("error", "Failed")
        
        # Cleanup worker thread to prevent memory leak
        if self._thread:
            self._thread.quit()
            self._thread.wait(2000)
            self._thread.deleteLater()
        if self._worker:
            self._worker.deleteLater()
        self._thread = None
        self._worker = None

    def closeEvent(self, event):
        if self._log_file: self._log_file.close()
        super().closeEvent(event)
