"""
main_window.py  — Premium Dark Dashboard UI for UIIC Automation.
Modularized version delegating to component classes.
"""

import os
from datetime import datetime

from PyQt6.QtCore import (
    Qt,
    QThread,
    QPropertyAnimation,
    QEasingCurve,
    QPointF,
)
from PyQt6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QFrame,
    QComboBox,
    QMessageBox,
    QStackedWidget,
    QGraphicsOpacityEffect,
)

from app.utils import (
    resource_path,
    load_settings,
    doc_mapping_paths,
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
        self._scan_thread = None
        self._scan_worker = None
        self._scan_context = None
        self._scan_generation = 0
        self._active_scan_token = None
        self._active_scan_portal_id = None
        self._active_scan_folder = ""

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
        self.settings_page.set_portal(get_active_portal_id() or "uiic")

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

    def _is_scan_running(self):
        return bool(self._scan_thread and self._scan_thread.isRunning())

    def _write_portal_audit_event(self, event: str, **extra):
        payload = {
            "timestamp": datetime.now().isoformat(),
            "event": event,
            "source": "main_window",
            **extra,
        }
        try:
            import json

            audit_path = os.path.join(user_data_dir("logs"), "portal_audit.jsonl")
            ensure_dir(os.path.dirname(audit_path))
            with open(audit_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as exc:
            warning = (
                "[Portal Isolation] Portal audit JSON write failed; continuing. "
                f"Event={event}; Error={exc}; Details={payload}"
            )
            try:
                self._append_log(warning)
            except Exception:
                pass

    def _set_portal_selector_locked(self, locked: bool, reason: str = ""):
        self.portal_combo.setEnabled(not locked)
        self.portal_combo.setToolTip(reason if locked else "")

    def _reset_portal_combo_to_active(self):
        current_portal_id = get_active_portal_id() or "uiic"
        idx = self.portal_combo.findData(current_portal_id)
        if idx >= 0 and idx != self.portal_combo.currentIndex():
            self.portal_combo.blockSignals(True)
            try:
                self.portal_combo.setCurrentIndex(idx)
            finally:
                self.portal_combo.blockSignals(False)

    def _cancel_active_scan_for_portal_change(self, old_portal_id, new_portal_id):
        if not self._is_scan_running():
            return False
        token = self._active_scan_token
        folder = self._active_scan_folder
        if self._scan_worker:
            self._scan_worker.request_stop()
        self._active_scan_token = None
        self._set_status("running", "Cancelling Scan...")
        self.workspace_page.doc_status_label.setText(
            "Portal changed. Cancelling current scan; please rescan for the selected portal."
        )
        self._append_log(
            "[Portal Isolation] Portal changed during scan. Current scan was "
            "cancelled and its result will be ignored. Please rescan the folder."
        )
        QMessageBox.information(
            self,
            "Scan Cancelled",
            "The current scan was cancelled because the portal changed. Please rescan the folder for the selected portal.",
        )
        self._write_portal_audit_event(
            "scan_cancelled_due_to_portal_change",
            old_portal_id=old_portal_id,
            new_portal_id=new_portal_id,
            folder_path=folder,
            scan_token=token,
            action="cancel_and_ignore_result",
        )
        return True

    def _on_portal_changed(self, index):
        """Handle portal dropdown change — switch all config resolution."""
        if self._worker:
            self._reset_portal_combo_to_active()
            QMessageBox.information(
                self,
                "Automation Running",
                "Automation is running. Please stop the current automation before switching portal.",
            )
            self._append_log(
                "[Portal Isolation] Portal switch blocked because automation is running. "
                "Stop the current automation before switching portal."
            )
            self._write_portal_audit_event(
                "portal_switch_blocked_during_automation",
                active_portal_id=get_active_portal_id() or "uiic",
                action="blocked",
            )
            return

        portal_id = self.portal_combo.itemData(index)
        if portal_id is None:
            return
        old_portal_id = get_active_portal_id() or "uiic"
        old_portal = get_active_portal()
        try:
            set_active_portal(portal_id)
        except ValueError:
            return

        old_context = self._scan_context
        portal = get_active_portal()
        self._append_log(f"🔄 Portal switched to: {portal.display_name}")

        scan_cancelled = self._cancel_active_scan_for_portal_change(
            old_portal_id, portal_id
        )

        # Update window title to show active portal
        self.setWindowTitle(f"Surveyor Automation — {portal.display_name}")
        self.workspace_page.set_portal(portal_id)

        # Reload settings page to show portal-specific settings
        self.settings_page.set_portal(portal_id)

        claim_cleared = self._clear_loaded_claim_for_portal_change(old_context, portal)
        self._write_portal_audit_event(
            "portal_changed",
            old_portal_id=old_portal_id,
            old_portal_name=getattr(old_portal, "display_name", old_portal_id),
            new_portal_id=portal_id,
            new_portal_name=getattr(portal, "display_name", portal_id),
            folder_path=self._active_scan_folder,
            scan_cancelled=scan_cancelled,
            claim_cleared=claim_cleared,
            action="clear_claim_require_rescan",
        )

    def _clear_loaded_claim_for_portal_change(self, old_context, new_portal):
        """Clear scanned data whenever the selected portal changes."""
        had_claim = self._claim is not None or self._scan_result is not None
        self._claim = None
        self._scan_result = None
        self._scan_context = None
        self.workspace_page.reset_state()
        if had_claim:
            old_name = getattr(old_context, "portal_display_name", "previous portal")
            new_name = getattr(new_portal, "display_name", "selected portal")
            self._set_status("ready", "Rescan Required")
            self._append_log(
                "[Portal Isolation] Cleared scanned claim data because portal "
                f"changed from {old_name} to {new_name}. Please rescan the folder."
            )
            QMessageBox.information(
                self,
                "Rescan Required",
                "Claim data was cleared because the portal changed. Please rescan the folder for the selected portal.",
            )
        return had_claim

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

            # 2. Cleanup old plain-text log files (keep last 20 plain text logs).
            existing_logs = sorted(
                glob.glob(os.path.join(log_dir, "automation_*.log")),
                key=lambda path: (os.path.getmtime(path), path),
            )
            for old_log in existing_logs[:-20]:
                try:
                    if os.path.abspath(old_log) != os.path.abspath(base_log):
                        os.remove(old_log)
                except Exception:
                    pass

            # 3. Cleanup old structured JSON log files per portal (keep last 20 JSON logs per portal).
            from app.portals.registry import list_portals

            for portal in list_portals():
                portal_log_dir = os.path.join(log_dir, portal.portal_id)
                if os.path.exists(portal_log_dir):
                    existing_jsons = sorted(
                        glob.glob(os.path.join(portal_log_dir, "*.json")),
                        key=lambda path: (os.path.getmtime(path), path),
                    )
                    for old_json in existing_jsons[:-20]:
                        try:
                            os.remove(old_json)
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
        from app.ui.worker import FolderScanWorker

        if self._is_scan_running():
            QMessageBox.information(
                self,
                "Scan Running",
                "A folder scan is still running. Please wait for it to stop before starting another scan.",
            )
            self._append_log(
                "[Portal Isolation] New scan blocked because a previous scan is still running."
            )
            return

        portal_id = get_active_portal_id() or "uiic"
        self._scan_generation += 1
        scan_token = self._scan_generation
        self._active_scan_token = scan_token
        self._active_scan_portal_id = portal_id
        self._active_scan_folder = folder
        # Always derive config_dir from portal_id so FolderScanWorker and
        # config_dir stay in sync. The old `CONFIG_DIR` fallback caused a
        # mismatch: portal_id="uiic" was passed but config_dir pointed to the
        # legacy app/config directory (a different location on portal refactors).
        config_dir = os.path.dirname(doc_mapping_paths(portal_id=portal_id)["default"])

        # Update status to running scan
        self._set_status("running", "Scanning...")
        self.workspace_page.doc_status_label.setText(
            "📁 Indexing and extracting documents via OCR... Please wait."
        )
        self._append_log(f"📁 Starting background scan for: {folder}")

        # Disable buttons to prevent concurrent triggers
        self.workspace_page.btn_start.setEnabled(False)
        btn_browse = self.workspace_page.findChild(QPushButton, "btnBrowse")
        if btn_browse:
            btn_browse.setEnabled(False)

        # Initialize thread and worker
        self._scan_thread = QThread()
        self._scan_worker = FolderScanWorker(
            folder, config_dir, portal_id, scan_token=scan_token
        )
        self._scan_worker.moveToThread(self._scan_thread)

        # Connect signals
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.done_signal.connect(self._on_scan_completed)
        self._scan_worker.done_signal.connect(self._scan_thread.quit)
        self._scan_thread.finished.connect(self._on_scan_thread_finished)

        # Start background scan thread
        self._scan_thread.start()

    def _on_scan_completed(self, result):
        result_token = getattr(result, "scan_token", None)
        result_portal_id = getattr(result, "scan_portal_id", None)
        current_portal_id = get_active_portal_id() or "uiic"
        if (
            result_token != self._active_scan_token
            or result_portal_id != current_portal_id
        ):
            self._append_log(
                "[Portal Isolation] Ignored stale scan result because the portal "
                "or scan session changed. Please rescan for the selected portal."
            )
            self._write_portal_audit_event(
                "stale_scan_result_ignored",
                result_portal_id=result_portal_id,
                current_portal_id=current_portal_id,
                result_scan_token=result_token,
                active_scan_token=self._active_scan_token,
                folder_path=getattr(result, "scan_folder", ""),
                action="ignored",
            )
            self._active_scan_portal_id = None
            self._active_scan_folder = ""
            self._set_status("ready", "Rescan Required")
            self.workspace_page.btn_start.setEnabled(False)
            btn_browse = self.workspace_page.findChild(QPushButton, "btnBrowse")
            if btn_browse:
                btn_browse.setEnabled(True)
            return

        self._active_scan_token = None
        self._active_scan_portal_id = None
        self._active_scan_folder = ""

        # Log all lines produced by the scanner service
        for line in result.log_lines:
            self._append_log(line)

        # Process success/failure
        if result.success:
            self._claim = result.claim
            self._scan_result = result.scan_result
            self._scan_context = getattr(result.claim, "_scan_context", None)
            if self._scan_context:
                self._append_log(
                    "[Portal Isolation] Scan locked to "
                    f"{self._scan_context.portal_display_name} "
                    f"({self._scan_context.portal_id})."
                )
            self.workspace_page.update_data(self._claim, self._scan_result)
            self._set_status("ready", "Ready")
        else:
            self._scan_result = result.scan_result
            self._claim = None
            self._scan_context = None
            self.workspace_page.doc_status_label.setText(
                "❌ No valid Excel data source found."
            )
            self.workspace_page.set_scan_failed()
            self._set_status("error", "Scan Failed")

        # Re-enable buttons
        self.workspace_page.btn_start.setEnabled(True)
        btn_browse = self.workspace_page.findChild(QPushButton, "btnBrowse")
        if btn_browse:
            btn_browse.setEnabled(True)

    def _on_scan_thread_finished(self):
        # Safely clean up thread and worker references
        self._scan_worker = None
        self._scan_thread = None

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

        scan_context = getattr(self._claim, "_scan_context", None)
        if scan_context is None:
            QMessageBox.critical(
                self,
                "Rescan Required",
                "This claim does not have a scan portal context. Please rescan the folder before starting automation.",
            )
            self.log(
                "[Portal Isolation] Start blocked: scanned claim has no portal context."
            )
            return

        current_portal_id = get_active_portal_id()
        if current_portal_id != scan_context.portal_id:
            QMessageBox.critical(
                self,
                "Portal Mismatch",
                "This claim was scanned for "
                f"{scan_context.portal_display_name}. Please rescan after changing portals.",
            )
            self.log(
                "[Portal Isolation] Start blocked: current portal "
                f"'{current_portal_id}' differs from scanned portal "
                f"'{scan_context.portal_id}'."
            )
            return

        portal_id = scan_context.portal_id
        settings = load_settings(portal_id=portal_id)

        self._thread = QThread()
        self._worker = AutomationWorker(
            self._claim, settings_override=settings, portal_id=portal_id
        )
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.done_signal.connect(self._thread.quit)  # stop event loop
        self._worker.done_signal.connect(self._on_automation_ui_reset)  # update UI
        self._thread.finished.connect(self._on_thread_fully_stopped)  # clear refs

        self._worker.log_signal.connect(self._append_log)
        self._worker.step_signal.connect(self.workspace_page.set_step)

        self.workspace_page.set_automation_running(True)
        self._set_portal_selector_locked(
            True,
            "Automation is running. Please stop the current automation before switching portal.",
        )
        self._append_log(
            "[Portal Isolation] Portal switching is disabled while automation is running. "
            "Stop the current automation before switching portal."
        )
        self._write_portal_audit_event(
            "portal_switch_locked_for_automation",
            portal_id=portal_id,
            action="locked",
        )
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
        self._set_portal_selector_locked(False)
        self._write_portal_audit_event(
            "portal_switch_unlocked_after_automation",
            portal_id=get_active_portal_id() or "uiic",
            action="unlocked",
        )
        success = getattr(self, "_last_success", False)
        message = getattr(self, "_last_message", "Automation finished.")
        if success:
            self.log(f"SUCCESS: {message}")
        else:
            self.log(f"STOPPED: {message}")

    def _append_log(self, text):
        self.workspace_page.append_log(text)
        if self._log_file and not self._log_file.closed:
            import re

            match = re.match(r"^\[(\d{2}:\d{2}:\d{2}(?:\.\d{3})?)\] (.*)$", text)
            if match:
                today = datetime.now().strftime("%Y-%m-%d")
                self._log_file.write(f"[{today} {match.group(1)}] {match.group(2)}\n")
            else:
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
                self._worker.stop()  # signal engine to stop
            self._thread.quit()  # ask event loop to exit
            if not self._thread.wait(5000):  # up to 5s graceful wait
                self._thread.terminate()  # force-kill if still running
                self._thread.wait(2000)

        # ── Gracefully stop folder scanning thread before closing ───────────────
        if (
            hasattr(self, "_scan_thread")
            and self._scan_thread
            and self._scan_thread.isRunning()
        ):
            if hasattr(self, "_scan_worker") and self._scan_worker:
                try:
                    self._scan_worker.request_stop()
                except Exception:
                    pass
            self._scan_thread.quit()
            self._scan_thread.wait(2000)

        # Clean up temporary pre-compressed files registered during scanning
        if hasattr(self, "_claim") and self._claim:
            temp_files = getattr(self._claim, "_temporary_files", [])
            if temp_files:
                for temp_path in temp_files:
                    if temp_path and os.path.isfile(temp_path):
                        try:
                            os.remove(temp_path)
                        except Exception:
                            pass

        if self._log_file:
            try:
                self._log_file.close()
            except Exception:
                pass
        super().closeEvent(event)
