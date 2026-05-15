"""
main_window.py  — Premium Dark Dashboard UI for UIIC Automation.
Modularized version delegating to component classes.
"""

import json
import os
import asyncio
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import (
    Qt,
    QThread,
    pyqtSignal,
    QObject,
    QSize,
    QPropertyAnimation,
    QEasingCurve,
    QPointF,
)
from PyQt6.QtGui import (
    QFont,
    QColor,
    QTextCursor,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
    QPainterPath,
)
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QProgressBar,
    QTextEdit,
    QFileDialog,
    QFrame,
    QSizePolicy,
    QScrollArea,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QSpacerItem,
    QApplication,
    QStackedWidget,
    QGraphicsOpacityEffect,
)

from app.utils import (
    resource_path,
    load_settings,
    settings_paths,
    user_data_dir,
    ensure_dir,
)
from app.portals.registry import (
    list_portals,
    set_active_portal,
    get_active_portal,
    get_active_portal_id,
)

from app.ui.worker import AutomationWorker
from app.ui.components.settings_page import SettingsPage
from app.ui.components.workspace_page import WorkspacePage

CONFIG_DIR = resource_path("app", "config")

# Set UIIC as default portal on startup (backward compatible)
try:
    set_active_portal("uiic")
except Exception:
    pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._worker = None
        self._thread = None
        self._claim = None
        self._scan_result = None
        self._log_file = None

        self._open_log_file()
        self._create_icons()
        self._setup_ui()
        self._setup_animations()

    def _create_icons(self):
        def _draw_nav_icon(draw_fn):
            s = 18
            px = QPixmap(s, s)
            px.fill(QColor(0, 0, 0, 0))
            p = QPainter(px)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            draw_fn(p, s)
            p.end()
            return QIcon(px)

        def _draw_home(p, s):
            pen = QPen(QColor("#94A3B8"))
            pen.setWidthF(1.6)
            p.setPen(pen)
            p.drawLine(2, 9, 9, 3)
            p.drawLine(9, 3, 16, 9)
            p.drawLine(4, 9, 4, 15)
            p.drawLine(14, 9, 14, 15)
            p.drawLine(4, 15, 14, 15)

        def _draw_progress(p, s):
            pen = QPen(QColor("#94A3B8"))
            pen.setWidthF(1.6)
            p.setPen(pen)
            p.drawEllipse(3, 3, 12, 12)
            p.setBrush(QColor("#94A3B8"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(9, 4), 1.5, 1.5)

        def _draw_settings(p, s):
            import math

            pen = QPen(QColor("#94A3B8"))
            pen.setWidthF(1.6)
            p.setPen(pen)
            p.drawEllipse(QPointF(9, 9), 5.0, 5.0)
            p.drawEllipse(QPointF(9, 9), 2.2, 2.2)
            for a in range(0, 360, 45):
                r = math.radians(a)
                x1, y1 = 9 + 4.2 * math.cos(r), 9 + 4.2 * math.sin(r)
                x2, y2 = 9 + 7 * math.cos(r), 9 + 7 * math.sin(r)
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        self._icon_home = _draw_nav_icon(_draw_home)
        self._icon_progress = _draw_nav_icon(_draw_progress)
        self._icon_settings = _draw_nav_icon(_draw_settings)

    def _setup_ui(self):
        self.setWindowTitle("UIIC Automation")
        self.setMinimumSize(1060, 720)
        self.resize(1260, 880)

        root = QWidget()
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Topbar
        lay.addWidget(self._build_topbar())

        # Stack
        self.stack = QStackedWidget()
        self.workspace_page = WorkspacePage()
        self.workspace_page.browse_clicked.connect(self._browse_folder)
        self.workspace_page.start_clicked.connect(self._start_automation)
        self.workspace_page.stop_clicked.connect(self._stop_automation)
        self.workspace_page.export_log_clicked.connect(self._export_log)
        self.settings_page = SettingsPage(append_log_cb=self._append_log)

        self.stack.addWidget(self.workspace_page)  # 0
        self.stack.addWidget(self.settings_page)  # 1
        lay.addWidget(self.stack, 1)

    def _build_topbar(self):
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(56)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(32, 0, 32, 0)

        logo = QLabel("UIIC")
        logo.setObjectName("appLogo")
        logo_sub = QLabel("AUTOMATION")
        logo_sub.setObjectName("appLogoSub")
        lay.addWidget(logo)
        lay.addWidget(logo_sub)
        lay.addStretch()

        self.btns = []
        for i, (name, icon) in enumerate(
            [
                ("  Workspace", self._icon_home),
                ("  Settings", self._icon_settings),
            ]
        ):
            b = QPushButton(name)
            b.setIcon(icon)
            b.setObjectName("navBtn")
            b.setMinimumSize(110, 36)
            b.setProperty("active", i == 0)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda ch, idx=i: self._switch_page(idx))
            lay.addWidget(b)
            self.btns.append(b)

        lay.addStretch()

        # Portal selector dropdown
        portal_frame = QFrame()
        portal_frame.setStyleSheet("QFrame { background: transparent; }")
        pl = QHBoxLayout(portal_frame)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(6)
        portal_label = QLabel("Portal:")
        portal_label.setStyleSheet(
            "color: #64748B; font-size: 8.5pt; font-weight: 600;"
        )
        self.portal_combo = QComboBox()
        self.portal_combo.setObjectName("portalCombo")
        self.portal_combo.setMinimumWidth(180)
        self.portal_combo.setFixedHeight(32)
        self.portal_combo.setStyleSheet("""
            QComboBox {
                background: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 6px;
                padding: 4px 10px; color: #0F172A; font-weight: 700; font-size: 9pt;
            }
            QComboBox:hover { border-color: #94A3B8; }
            QComboBox:focus { border-color: #6366F1; }
            QComboBox::drop-down { border: none; width: 24px; }
            QComboBox::down-arrow { image: none; border: none; }
        """)
        for portal in list_portals():
            self.portal_combo.addItem(portal.display_name, portal.portal_id)
        self.portal_combo.currentIndexChanged.connect(self._on_portal_changed)
        pl.addWidget(portal_label)
        pl.addWidget(self.portal_combo)
        lay.addWidget(portal_frame)
        lay.addSpacing(12)

        ver = QLabel("v3.0")
        ver.setObjectName("appVersion")
        lay.addWidget(ver)

        self.status_pill = QFrame()
        self.status_pill.setObjectName("statusPill")
        self.status_pill.setProperty("status", "ready")
        sl = QHBoxLayout(self.status_pill)
        sl.setContentsMargins(12, 0, 12, 0)
        sl.setSpacing(8)
        self.status_dot = QFrame()
        self.status_dot.setFixedSize(8, 8)
        self.status_dot.setObjectName("statusDot")
        self.status_text = QLabel("Ready")
        self.status_text.setObjectName("statusText")
        sl.addWidget(self.status_dot)
        sl.addWidget(self.status_text)
        lay.addWidget(self.status_pill)

        return bar

    def _build_action_bar(self):
        bar = QFrame()
        bar.setFixedHeight(84)
        bar.setObjectName("actionBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(32, 0, 32, 0)
        lay.setSpacing(12)

        self.btn_start = self.workspace_page.btn_start
        self.btn_stop = self.workspace_page.btn_stop
        self.btn_clear = self.workspace_page.logs_drawer.btn_clear
        self.btn_export = self.workspace_page.logs_drawer.btn_export

        lay.addWidget(self.btn_start)
        lay.addWidget(self.btn_stop)
        lay.addStretch()
        lay.addWidget(self.btn_clear)
        lay.addWidget(self.btn_export)
        return bar

    def _switch_page(self, idx):
        self.stack.setCurrentIndex(idx)
        for i, b in enumerate(self.btns):
            b.setProperty("active", i == idx)
            b.style().unpolish(b)
            b.style().polish(b)

    def _set_status(self, status, text):
        self.status_text.setText(text)
        self.status_pill.setProperty("status", status)
        for w in [self.status_pill, self.status_dot]:
            w.style().unpolish(w)
            w.style().polish(w)

    def _on_portal_changed(self, index):
        """Handle portal dropdown change — switch all config resolution."""
        portal_id = self.portal_combo.itemData(index)
        if portal_id is None:
            return
        try:
            set_active_portal(portal_id)
        except ValueError:
            return

        portal = get_active_portal()
        self._append_log(f"🔄 Portal switched to: {portal.display_name}")

        # Update window title to show active portal
        self.setWindowTitle(f"Surveyor Automation — {portal.display_name}")
        self.workspace_page.set_portal(portal_id)

        # Reload settings page to show portal-specific settings
        self.settings_page._load_data()

        # Clear any previously loaded claim data (it may not apply to the new portal)
        self._claim = None
        self._scan_result = None
        self.workspace_page.reset_state()

    def _setup_animations(self):
        self._pulse_eff = QGraphicsOpacityEffect(self.status_dot)
        self.status_dot.setGraphicsEffect(self._pulse_eff)
        self.pulse_anim = QPropertyAnimation(self._pulse_eff, b"opacity")
        self.pulse_anim.setDuration(800)
        self.pulse_anim.setStartValue(0.3)
        self.pulse_anim.setEndValue(1.0)
        self.pulse_anim.setLoopCount(-1)
        self.pulse_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.pulse_anim.start()

    def _open_log_file(self):
        try:
            log_dir = ensure_dir(user_data_dir("logs"))
            
            # 1. Create a unique timestamped log.
            import glob
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            base_log = os.path.join(log_dir, f"automation_{ts}_{os.getpid()}.log")
            self._log_file = open(base_log, "x", encoding="utf-8")

            # 2. Cleanup old logs after creating this one (keep last 10 total).
            existing_logs = sorted(
                glob.glob(os.path.join(log_dir, "automation_*.log")),
                key=lambda path: (os.path.getmtime(path), path),
            )
            for old_log in existing_logs[:-10]:
                try:
                    if os.path.abspath(old_log) != os.path.abspath(base_log):
                        os.remove(old_log)
                except Exception:
                    pass
        except Exception:
            pass

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Claim Folder")
        if folder:
            self.workspace_page.inp_folder.setText(folder)
            self._scan_folder(folder)

    def _scan_folder(self, folder):
        from app.ui.services.claim_folder_service import ClaimFolderService

        portal = get_active_portal()
        portal_id = get_active_portal_id() or "uiic"
        config_dir = portal.bundled_config_dir() if portal else CONFIG_DIR
        service = ClaimFolderService(config_dir=config_dir, portal_id=portal_id)
        result = service.process_folder(folder)

        for line in result.log_lines:
            self._append_log(line)

        if result.success:
            self._claim = result.claim
            self._scan_result = result.scan_result
            self.workspace_page.update_data(self._claim, self._scan_result)
            self._set_status("ready", "Ready")
        else:
            self._scan_result = result.scan_result
            self._claim = None
            self.workspace_page.doc_status_label.setText(
                "❌ No valid Excel data source found."
            )
            self.workspace_page.set_scan_failed()
            self._set_status("error", "Scan Failed")

    def _start_automation(self):
        if not self._claim:
            QMessageBox.warning(
                self, "No Data", "Please select a claim folder with valid data first."
            )
            return

        if self._worker:
            return

        self._switch_page(0)  # Workspace
        self.workspace_page.clear_logs()
        self.log("Starting automation thread...")

        portal_id = get_active_portal_id()
        settings = load_settings(portal_id=portal_id)

        self._thread = QThread()
        self._worker = AutomationWorker(self._claim, settings_override=settings, portal_id=portal_id)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.done_signal.connect(self._thread.quit)        # stop event loop
        self._worker.done_signal.connect(self._on_automation_ui_reset)  # update UI
        self._thread.finished.connect(self._on_thread_fully_stopped)    # clear refs
        
        self._worker.log_signal.connect(self._append_log)
        self._worker.step_signal.connect(self.workspace_page.set_step)

        self.workspace_page.set_automation_running(True)
        self.status_pill.setProperty("status", "running")
        self.status_text.setText("Running")
        self.status_pill.style().unpolish(self.status_pill)
        self.status_pill.style().polish(self.status_pill)

        self._thread.start()

    def _stop_automation(self):
        if self._worker:
            self._worker.stop()
            self.workspace_page.btn_stop.setEnabled(False)
            self.log("Stopping...")

    def _on_automation_ui_reset(self, success, message):
        """Called when automation finishes — updates UI. Thread may still be winding down."""
        self._last_success = success
        self._last_message = message
        self.workspace_page.set_automation_finished(success)
        self.status_pill.setProperty("status", "ready")
        self.status_text.setText("Ready")
        self.status_pill.style().unpolish(self.status_pill)
        self.status_pill.style().polish(self.status_pill)

    def _on_thread_fully_stopped(self):
        """Called by thread.finished — thread OS object has fully stopped. Safe to clear."""
        self._worker = None
        self._thread = None
        success = getattr(self, '_last_success', False)
        message = getattr(self, '_last_message', 'Automation finished.')
        if success:
            self.log(f"SUCCESS: {message}")
        else:
            self.log(f"STOPPED: {message}")

    def _append_log(self, text):
        self.workspace_page.append_log(text)
        if self._log_file and not self._log_file.closed:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._log_file.write(f"[{ts}] {text}\n")
            self._log_file.flush()

    def log(self, text):
        self._append_log(text)

    def _export_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Log",
            f"automation_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            "Text Files (*.txt)",
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.workspace_page.log_text())
                self.log(f"Log exported to {path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Failed", str(e))

    def _toggle_pwd(self, checked):
        self.settings_page.inp_password.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )
        self.settings_page.btn_eye.setIcon(
            self.settings_page._icon_eye_open
            if checked
            else self.settings_page._icon_eye_closed
        )

    def closeEvent(self, event):
        # ── Gracefully stop automation thread before closing ────────────────────
        if self._thread and self._thread.isRunning():
            if self._worker:
                self._worker.stop()          # signal engine to stop
            self._thread.quit()              # ask event loop to exit
            if not self._thread.wait(5000):  # up to 5s graceful wait
                self._thread.terminate()     # force-kill if still running
                self._thread.wait(2000)
        if self._log_file:
            try:
                self._log_file.close()
            except Exception:
                pass
        super().closeEvent(event)
