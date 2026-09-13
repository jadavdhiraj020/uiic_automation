"""Compact, high-contrast, professional Web Queue dashboard."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from PyQt6.QtCore import QTimer, Qt, pyqtSignal, QRect, QRectF, QSize, QUrl, QEvent, QPointF
from PyQt6.QtGui import (
    QColor, QDesktopServices, QFont, QFontMetrics, QIcon, QPainter,
    QPainterPath, QPen, QPixmap
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLineEdit, QPushButton,
    QLabel, QListWidget, QComboBox, QInputDialog, QScrollArea, QFrame,
    QStyledItemDelegate, QStyle, QMessageBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QCheckBox, QFileDialog, QApplication, QStackedWidget
)

from app.ui.components.widgets import (
    card as _card,
    field_label as _field_label,
    hline as _hline,
    stat_card as _stat_card,
    search_row as _search_row,
    _hex_to_rgba,
)
from app.ui.components.table_clipboard import attach_row_copy_on_double_click
from app.utils import user_data_dir
from .client import Client, ApiError
from .zip_downloads import download_case_preferred as download_case
from .storage import (
    CaseRepository, CaseState, CompletedCaseStore,
    CredentialStore, OperatorCredentialStore, readable_case_folder,
    portal_for, atomic_json,
)
from .queue_helpers import (
    dispatch_id as _dispatch_id,
    is_stale_dispatch_error as _is_stale_dispatch_error,
    short_insurer_label,
)
from .manifest import StagedCaseValidationError, validate_staged_case


def _make_eye_toggle(line_edit: QLineEdit) -> QPushButton:
    """Compact password toggle button with clean vector eye icon."""
    btn = QPushButton()
    btn.setObjectName("iconButton")
    btn.setFixedSize(32, 32)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setToolTip("Show / Hide password")

    def _draw_eye(closed=False):
        s = 18
        px = QPixmap(s, s)
        px.fill(QColor(0, 0, 0, 0))
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#64748B"))
        pen.setWidthF(1.5)
        p.setPen(pen)
        cy, mx = s / 2, 3
        path = QPainterPath()
        path.moveTo(mx, cy)
        path.quadTo(s / 2, cy - 5, s - mx, cy)
        path.quadTo(s / 2, cy + 5, mx, cy)
        p.drawPath(path)
        p.setBrush(QColor("#64748B"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(int(s / 2 - 2), int(cy - 2), 4, 4)
        if closed:
            pen2 = QPen(QColor("#EF4444"))
            pen2.setWidthF(1.6)
            p.setPen(pen2)
            p.drawLine(3, 3, s - 3, s - 3)
        p.end()
        return QIcon(px)

    icon_open = _draw_eye(False)
    icon_closed = _draw_eye(True)
    btn.setIcon(icon_closed)

    def _toggle():
        if line_edit.echoMode() == QLineEdit.EchoMode.Password:
            line_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            btn.setIcon(icon_open)
        else:
            line_edit.setEchoMode(QLineEdit.EchoMode.Password)
            btn.setIcon(icon_closed)

    btn.clicked.connect(_toggle)
    return btn


class CaseListDelegate(QStyledItemDelegate):
    """High-contrast, spacious list item renderer for queued cases with action pills."""

    def __init__(self, parent=None, page=None):
        super().__init__(parent)
        self.list_widget = parent
        self.page = page

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 122)

    def _button_rects(self, rect):
        y = int(rect.bottom() - 32)
        h = 26
        del_w = 98
        folder_w = 118
        start_w = 122

        del_x = int(rect.right() - 14 - del_w)
        r_del = QRect(del_x, y, del_w, h)

        folder_x = int(del_x - 6 - folder_w)
        r_folder = QRect(folder_x, y, folder_w, h)

        start_x = int(folder_x - 6 - start_w)
        r_start = QRect(start_x, y, start_w, h)

        return {
            "start": r_start,
            "folder": r_folder,
            "delete": r_del,
        }

    def _images_button_rect(self, rect):
        return self._button_rects(rect)["folder"]

    def editorEvent(self, event, model, option, index):
        rect = option.rect.adjusted(4, 3, -4, -3)
        rects = self._button_rects(rect)
        pt = None
        if hasattr(event, "position"):
            pt = event.position().toPoint()
        elif hasattr(event, "pos"):
            pt = event.pos()

        if pt is not None:
            if event.type() == QEvent.Type.MouseMove:
                if any(r.contains(pt) for r in rects.values()):
                    if self.list_widget and hasattr(self.list_widget, "viewport"):
                        self.list_widget.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                else:
                    if self.list_widget and hasattr(self.list_widget, "viewport"):
                        self.list_widget.viewport().setCursor(Qt.CursorShape.ArrowCursor)
                return False
            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                if self.page:
                    if rects["start"].contains(pt):
                        self.page.start_automation_by_index(index)
                        return True
                    elif rects["folder"].contains(pt):
                        self.page.open_case_folder_by_index(index)
                        return True
                    elif rects["delete"].contains(pt):
                        metadata = index.data(Qt.ItemDataRole.UserRole) or {}
                        if self.page.can_delete_case_metadata(metadata):
                            self.page.delete_case_by_index(index)
                        else:
                            self.page.result.setText(
                                "Delete Case is disabled for the active unresolved case. "
                                "Submit it successfully or deliberately Stop/Fail it first."
                            )
                        return True
        return super().editorEvent(event, model, option, index)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect.adjusted(4, 3, -4, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        raw_text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        parts = [p.strip() for p in raw_text.split("|")]
        has_display_number = bool(parts and parts[0].startswith("#"))
        offset = 1 if has_display_number else 0
        display_number = parts[0] if has_display_number else ""
        case_ref = parts[offset] if len(parts) > offset else raw_text
        vehicle_no = parts[offset + 1] if len(parts) > offset + 1 else ""
        insurer = parts[offset + 2] if len(parts) > offset + 2 else ""
        surveyor = parts[offset + 3] if len(parts) > offset + 3 else ""
        status_text = parts[offset + 4] if len(parts) > offset + 4 and parts[offset + 4] else "Queued"

        # Card Background & Border
        if selected:
            painter.setBrush(QColor("#EEF2FF"))
            painter.setPen(QPen(QColor("#6366F1"), 1.8))
        elif hovered:
            painter.setBrush(QColor("#F8FAFC"))
            painter.setPen(QPen(QColor("#94A3B8"), 1.2))
        else:
            painter.setBrush(QColor("#FFFFFF"))
            painter.setPen(QPen(QColor("#E2E8F0"), 1.0))

        painter.drawRoundedRect(rect, 8, 8)

        # Left status accent bar (4px wide rounded indicator)
        st_lower = status_text.lower()
        if "ready" in st_lower or "workspace" in st_lower or "prepared" in st_lower:
            accent_col = QColor("#10B981")  # Emerald
        elif "failed" in st_lower or "error" in st_lower or "attention" in st_lower:
            accent_col = QColor("#EF4444")  # Red
        elif "active" in st_lower or "scanning" in st_lower or "staging" in st_lower:
            accent_col = QColor("#6366F1")  # Indigo
        else:
            accent_col = QColor("#3B82F6")  # Blue

        accent_rect = QRectF(rect.left() + 2, rect.top() + 10, 4, rect.height() - 20)
        painter.setBrush(accent_col)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(accent_rect, 2, 2)

        # ── Line 1: Case Reference (bold 10pt) ──
        font = painter.font()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        title_x = int(rect.left() + 16)
        if display_number:
            painter.setPen(QColor("#2563EB"))
            painter.drawText(title_x, int(rect.top() + 25), display_number)
            title_x += QFontMetrics(font).horizontalAdvance(display_number) + 12
        painter.setPen(QColor("#0F172A"))
        painter.drawText(title_x, int(rect.top() + 25), case_ref)

        # Right-side Badges on Line 1
        r_offset = rect.right() - 14

        # 1. Status badge
        badge_font = painter.font()
        badge_font.setBold(True)
        badge_font.setPointSize(8)
        painter.setFont(badge_font)
        fm = QFontMetrics(badge_font)

        if "ready" in st_lower or "workspace" in st_lower:
            st_bg, st_border, st_text = QColor("#ECFDF5"), QColor("#A7F3D0"), QColor("#047857")
        elif "failed" in st_lower or "error" in st_lower or "attention" in st_lower:
            st_bg, st_border, st_text = QColor("#FEF2F2"), QColor("#FECACA"), QColor("#B91C1C")
        elif "active" in st_lower or "scanning" in st_lower or "staging" in st_lower:
            st_bg, st_border, st_text = QColor("#EEF2FF"), QColor("#C7D2FE"), QColor("#4338CA")
        else:
            st_bg, st_border, st_text = QColor("#EFF6FF"), QColor("#BFDBFE"), QColor("#1D4ED8")

        st_w = fm.horizontalAdvance(status_text) + 16
        st_h = 22
        st_rect = QRectF(r_offset - st_w, rect.top() + 12, st_w, st_h)
        painter.setBrush(st_bg)
        painter.setPen(QPen(st_border, 1.2))
        painter.drawRoundedRect(st_rect, 4, 4)
        painter.setPen(st_text)
        painter.drawText(st_rect, Qt.AlignmentFlag.AlignCenter, status_text)

        r_offset -= (st_w + 8)

        # 2. Insurer Pill Badge
        if insurer:
            display_insurer = short_insurer_label(insurer)
            ins_lower = insurer.lower()
            if "united" in ins_lower or "uiic" in ins_lower:
                ins_bg, ins_border, ins_col = QColor("#EFF6FF"), QColor("#BFDBFE"), QColor("#1D4ED8")
            elif "new india" in ins_lower or "nia" in ins_lower:
                ins_bg, ins_border, ins_col = QColor("#ECFDF5"), QColor("#A7F3D0"), QColor("#047857")
            elif "oriental" in ins_lower or "oic" in ins_lower:
                ins_bg, ins_border, ins_col = QColor("#FFFBEB"), QColor("#FDE68A"), QColor("#B45309")
            else:
                ins_bg, ins_border, ins_col = QColor("#F1F5F9"), QColor("#E2E8F0"), QColor("#475569")

            ins_w = fm.horizontalAdvance(display_insurer) + 18
            ins_h = 22
            ins_rect = QRectF(r_offset - ins_w, rect.top() + 12, ins_w, ins_h)
            painter.setBrush(ins_bg)
            painter.setPen(QPen(ins_border, 1.2))
            painter.drawRoundedRect(ins_rect, 11, 11)
            painter.setPen(ins_col)
            painter.drawText(ins_rect, Qt.AlignmentFlag.AlignCenter, display_insurer)

        # ── Line 2: Vehicle & Surveyor (y ~ top + 52) ──
        line2_font = painter.font()
        line2_font.setPointSize(8)
        line2_font.setBold(False)
        painter.setFont(line2_font)

        # Vehicle
        v_tag = f"🚗  Vehicle: {vehicle_no}" if vehicle_no else "🚗  Vehicle: N/A"
        painter.setPen(QColor("#334155"))
        painter.drawText(int(rect.left() + 16), int(rect.top() + 52), v_tag)
        fm2 = QFontMetrics(line2_font)
        v_tag_w = fm2.horizontalAdvance(v_tag)

        # Surveyor
        if surveyor:
            surv_text = f"  •   👤  Surveyor: {surveyor}"
            painter.setPen(QColor("#64748B"))
            painter.drawText(int(rect.left() + 16 + v_tag_w), int(rect.top() + 52), surv_text)

        # ── Line 3: Document Status & Images Action Pill (y ~ top + 86) ──
        user_data = index.data(Qt.ItemDataRole.UserRole) or {}
        record = user_data.get("record") if isinstance(user_data, dict) else {}
        folder_str = (record or {}).get("folder", "")
        folder_path = Path(folder_str) if folder_str else None

        line3_font = painter.font()
        line3_font.setPointSize(8)
        line3_font.setBold(False)
        painter.setFont(line3_font)

        if folder_path and folder_path.is_dir():
            try:
                img_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".pdf"}
                img_count = sum(1 for p in folder_path.iterdir() if p.is_file() and p.suffix.lower() in img_exts)
                doc_text = f"📁 Staged Locally: {img_count} document(s) & images ready in workspace"
            except Exception:
                doc_text = "📁 Staged Locally: Ready in local workspace folder"
            painter.setPen(QColor("#059669"))
        elif "restage required" in st_lower or (record or {}).get("deleted_by_operator"):
            doc_text = "🗑 Deleted Locally: Click Restage to download this case again"
            painter.setPen(QColor("#B45309"))
        elif "attention" in st_lower and (record or {}).get("state_recovery_error"):
            doc_text = "⚠️ Local state recovered safely: click Restage Case"
            painter.setPen(QColor("#B45309"))
        elif "failed" in st_lower:
            doc_text = "⚠️ Staging Failed: Could not download case files from cloud"
            painter.setPen(QColor("#DC2626"))
        elif user_data.get("kind") == "active":
            doc_text = "⚡ Automation Active: Workspace loaded for portal fill"
            painter.setPen(QColor("#4F46E5"))
        else:
            doc_text = "☁ Cloud Queued: Available for automatic download and inspection"
            painter.setPen(QColor("#64748B"))

        rects = self._button_rects(rect)
        fm3 = QFontMetrics(line3_font)
        max_text_w = max(40, int(rects["start"].left() - rect.left() - 20))
        elided_doc_text = fm3.elidedText(doc_text, Qt.TextElideMode.ElideRight, max_text_w)
        painter.drawText(int(rect.left() + 16), int(rect.top() + 86), elided_doc_text)

        btn_font = painter.font()
        btn_font.setPointSize(8)
        btn_font.setBold(True)
        painter.setFont(btn_font)

        # 1. [ Start Automation ]
        recovery_needed = bool((record or {}).get("state_recovery_error"))
        can_start = (
            (record or {}).get("local_status") in ("ready", "workspace ready")
            and user_data.get("kind") != "active"
            and "attention" not in st_lower
        )
        if recovery_needed:
            painter.setBrush(QColor("#FFFBEB"))
            painter.setPen(QPen(QColor("#FDE68A"), 1.2))
            painter.drawRoundedRect(rects["start"], 5, 5)
            painter.setPen(QColor("#B45309"))
            painter.drawText(rects["start"], Qt.AlignmentFlag.AlignCenter, "Restage Case")
        elif can_start:
            painter.setBrush(QColor("#ECFDF5"))
            painter.setPen(QPen(QColor("#A7F3D0"), 1.2))
            painter.drawRoundedRect(rects["start"], 5, 5)
            painter.setPen(QColor("#059669"))
            painter.drawText(rects["start"], Qt.AlignmentFlag.AlignCenter, "Start Automation")
        else:
            painter.setBrush(QColor("#F8FAFC"))
            painter.setPen(QPen(QColor("#E2E8F0"), 1.0))
            painter.drawRoundedRect(rects["start"], 5, 5)
            painter.setPen(QColor("#94A3B8"))
            painter.drawText(rects["start"], Qt.AlignmentFlag.AlignCenter, "Start Automation")

        # 2. [ View Case Folder ]
        painter.setBrush(QColor("#F0F9FF"))
        painter.setPen(QPen(QColor("#7DD3FC"), 1.2))
        painter.drawRoundedRect(rects["folder"], 5, 5)
        painter.setPen(QColor("#0284C7"))
        painter.drawText(rects["folder"], Qt.AlignmentFlag.AlignCenter, "View Case Folder")

        # 3. [ Delete Case ]
        can_delete = not self.page or self.page.can_delete_case_metadata(user_data)
        painter.setBrush(QColor("#FEF2F2") if can_delete else QColor("#F8FAFC"))
        painter.setPen(QPen(QColor("#FECACA") if can_delete else QColor("#E2E8F0"), 1.2))
        painter.drawRoundedRect(rects["delete"], 5, 5)
        painter.setPen(QColor("#DC2626") if can_delete else QColor("#94A3B8"))
        painter.drawText(rects["delete"], Qt.AlignmentFlag.AlignCenter, "🗑 Delete Case")

        painter.restore()


class ConnectionStatusLabel(QLabel):
    """Status label that automatically reflects connection state in its parent pill."""

    def __init__(self, pill_frame, dot_label, parent=None):
        super().__init__("Disconnected", parent)
        self.setObjectName("statusText")
        self._pill = pill_frame
        self._dot = dot_label
        self._update_pill("Disconnected")

    def setText(self, text):
        super().setText(text)
        self._update_pill(text)

    def _update_pill(self, text):
        t = (text or "").lower()
        if "connected" in t and "disconnected" not in t:
            self._dot.setStyleSheet("background-color: #10B981; border-radius: 4px;")
            self.setStyleSheet("color: #059669; font-weight: 700; font-size: 8.5pt;")
            self._pill.setStyleSheet(
                "QFrame#statusPill { background-color: rgba(16, 185, 129, 0.10); "
                "border: 1px solid rgba(16, 185, 129, 0.35); border-radius: 999px; padding: 4px 12px; }"
            )
        elif "retrying" in t or "syncing" in t:
            self._dot.setStyleSheet("background-color: #6366F1; border-radius: 4px;")
            self.setStyleSheet("color: #4F46E5; font-weight: 700; font-size: 8.5pt;")
            self._pill.setStyleSheet(
                "QFrame#statusPill { background-color: rgba(99, 102, 241, 0.10); "
                "border: 1px solid rgba(99, 102, 241, 0.25); border-radius: 999px; padding: 4px 12px; }"
            )
        else:
            self._dot.setStyleSheet("background-color: #EF4444; border-radius: 4px;")
            self.setStyleSheet("color: #DC2626; font-weight: 700; font-size: 8.5pt;")
            self._pill.setStyleSheet(
                "QFrame#statusPill { background-color: rgba(239, 68, 68, 0.10); "
                "border: 1px solid rgba(239, 68, 68, 0.25); border-radius: 999px; padding: 4px 12px; }"
            )


class ResultBannerLabel(QLabel):
    """Result label that dynamically styles its enclosing notification box and status badges."""

    def __init__(self, frame, status_pill, time_label, on_update=None, parent=None):
        super().__init__("No result yet.", parent)
        self._frame = frame
        self._status_pill = status_pill
        self._time_label = time_label
        self._on_update = on_update
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self._update_style("No result yet.")

    def setText(self, text):
        super().setText(text)
        self._update_style(text)

    def set_report_result(self, text, reported_status, returned_status):
        outcome = "attention"
        if reported_status == "success" and returned_status == "uploaded":
            outcome = "success"
        super().setText(text)
        self._update_style(text, outcome)

    def _update_style(self, text, outcome=None):
        t = (text or "").lower()
        now_str = datetime.now().strftime("%H:%M:%S")

        if self._on_update and text and text != "No result yet.":
            try:
                self._on_update(text, outcome)
            except Exception:
                pass

        if not text or text == "No result yet.":
            self._frame.setStyleSheet(
                "QFrame#resultBanner { background-color: #F8FAFC; border: 1px solid #CBD5E1; "
                "border-radius: 6px; padding: 12px 16px; }"
            )
            self.setStyleSheet("color: #64748B; font-weight: 500; font-size: 9.5pt;")
            self._status_pill.setText("  IDLE  ")
            self._status_pill.setStyleSheet("background-color: #F1F5F9; color: #64748B; border: 1px solid #CBD5E1; border-radius: 4px; font-weight: 700; font-size: 7.5pt; padding: 2px 8px;")
            self._time_label.setText("Standing by for case activity")
        elif outcome == "success":
            self._frame.setStyleSheet(
                "QFrame#resultBanner { background-color: #ECFDF5; border: 1px solid #A7F3D0; "
                "border-radius: 6px; padding: 12px 16px; }"
            )
            self.setStyleSheet("color: #065F46; font-weight: 700; font-size: 10pt;")
            self._status_pill.setText("  CONFIRMED SUCCESS  ")
            self._status_pill.setStyleSheet("background-color: #D1FAE5; color: #047857; border: 1px solid #6EE7B7; border-radius: 4px; font-weight: 800; font-size: 7.5pt; padding: 2px 8px;")
            self._time_label.setText(f"Recorded at {now_str}")
        elif outcome == "attention" or any(k in t for k in ("ready_for_upload", "pending", "error", "fail", "cannot", "unable", "invalid", "missing", "wrong", "blocked", "uncertain", "needs attention")):
            self._frame.setStyleSheet(
                "QFrame#resultBanner { background-color: #FEF2F2; border: 1px solid #FCA5A5; "
                "border-radius: 6px; padding: 12px 16px; }"
            )
            self.setStyleSheet("color: #991B1B; font-weight: 700; font-size: 10pt;")
            self._status_pill.setText("  FAILED / NEEDS ATTENTION  ")
            self._status_pill.setStyleSheet("background-color: #FEE2E2; color: #B91C1C; border: 1px solid #FCA5A5; border-radius: 4px; font-weight: 800; font-size: 7.5pt; padding: 2px 8px;")
            self._time_label.setText(f"Logged at {now_str}")
        elif any(k in t for k in ("download", "downloading", "progress", "processing", "claiming", "syncing")):
            self._frame.setStyleSheet(
                "QFrame#resultBanner { background-color: #FFFBEB; border: 1px solid #FDE68A; "
                "border-radius: 6px; padding: 12px 16px; }"
            )
            self.setStyleSheet("color: #92400E; font-weight: 600; font-size: 9.5pt;")
            self._status_pill.setText("  DOWNLOADING / PROCESSING  ")
            self._status_pill.setStyleSheet("background-color: #FEF3C7; color: #B45309; border: 1px solid #FCD34D; border-radius: 4px; font-weight: 800; font-size: 7.5pt; padding: 2px 8px;")
            self._time_label.setText(f"Updated at {now_str}")
        elif any(k in t for k in ("ready", "workspace", "prepared")):
            self._frame.setStyleSheet(
                "QFrame#resultBanner { background-color: #EFF6FF; border: 1px solid #BFDBFE; "
                "border-radius: 6px; padding: 12px 16px; }"
            )
            self.setStyleSheet("color: #1E40AF; font-weight: 600; font-size: 9.5pt;")
            self._status_pill.setText("  READY IN WORKSPACE  ")
            self._status_pill.setStyleSheet("background-color: #DBEAFE; color: #1D4ED8; border: 1px solid #93C5FD; border-radius: 4px; font-weight: 800; font-size: 7.5pt; padding: 2px 8px;")
            self._time_label.setText(f"Updated at {now_str}")
        else:
            self._frame.setStyleSheet(
                "QFrame#resultBanner { background-color: #F8FAFC; border: 1px solid #CBD5E1; "
                "border-radius: 6px; padding: 12px 16px; }"
            )
            self.setStyleSheet("color: #334155; font-weight: 600; font-size: 9.5pt;")
            self._status_pill.setText("  QUEUED / ACTIVITY  ")
            self._status_pill.setStyleSheet("background-color: #EFF6FF; color: #1D4ED8; border: 1px solid #BFDBFE; border-radius: 4px; font-weight: 800; font-size: 7.5pt; padding: 2px 8px;")
            self._time_label.setText(f"Updated at {now_str}")


class WebQueueWorkflowRail(QWidget):
    stage_selected = pyqtSignal(int)

    STAGES = [
        ("Cases", "Select & stage claims"),
        ("Connection", "DocWriter & credentials"),
        ("Live Logs", "Automation activity"),
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


class CompletedCasesTable(QTableWidget):
    """Clean, high-contrast, structured table for completed cases."""

    COLUMNS = ["CASE REF", "VEHICLE", "INSURER", "COMPLETED AT", "STATUS / RESULT"]

    def __init__(self, parent=None):
        super().__init__(0, len(self.COLUMNS), parent)
        self.setObjectName("completedCasesTable")
        self.setHorizontalHeaderLabels(self.COLUMNS)
        self.setAlternatingRowColors(True)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(36)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.setMinimumHeight(150)
        self.setMaximumHeight(240)
        self.setStyleSheet("""
            QTableWidget#completedCasesTable {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                gridline-color: #F1F5F9;
                font-size: 8.5pt;
                color: #0F172A;
            }
            QTableWidget#completedCasesTable::item {
                padding: 4px 10px;
                border-bottom: 1px solid #F1F5F9;
            }
            QTableWidget#completedCasesTable::item:selected {
                background-color: #EEF2FF;
                color: #1E293B;
            }
            QTableWidget#completedCasesTable QHeaderView::section {
                background-color: #F8FAFC;
                color: #475569;
                font-weight: 700;
                font-size: 8pt;
                border: none;
                border-bottom: 1px solid #CBD5E1;
                padding: 6px 10px;
            }
        """)

    def count(self) -> int:
        return self.rowCount()

    def clear(self):
        self.setRowCount(0)

    def item(self, row: int, column: int = 0):
        return super().item(row, column)

    def setCurrentRow(self, row: int):
        if 0 <= row < self.rowCount():
            self.setCurrentCell(row, 0)

    def currentItem(self):
        row = self.currentRow()
        if row >= 0:
            return self.item(row, 0)
        return super().currentItem()

    def add_case_entry(self, entry: dict):
        row = self.rowCount()
        self.insertRow(row)

        case_ref = str(entry.get("case_ref", "N/A"))
        vehicle_no = str(entry.get("vehicle_no", "N/A"))
        insurer = str(entry.get("insurer", "N/A"))
        completed_at = entry.get("formatted_completed_at", "")
        if not completed_at:
            completed_at = entry.get("completed_at", "")
            try:
                completed_at = datetime.fromisoformat(completed_at).astimezone().strftime("%d %b %Y %I:%M %p")
            except (TypeError, ValueError):
                completed_at = completed_at or "Unknown"

        result_text = str(entry.get("display_result", entry.get("result", "Completed Locally")))

        # Col 0: Case Ref (bold Segoe UI)
        item_ref = QTableWidgetItem(case_ref)
        item_ref.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        item_ref.setForeground(QColor("#0F172A"))

        # Col 1: Vehicle (Cascadia Code)
        item_veh = QTableWidgetItem(vehicle_no)
        item_veh.setFont(QFont("Cascadia Code", 8))
        item_veh.setForeground(QColor("#334155"))

        # Col 2: Insurer
        item_ins = QTableWidgetItem(short_insurer_label(insurer))
        item_ins.setFont(QFont("Segoe UI", 8))
        item_ins.setForeground(QColor("#475569"))

        # Col 3: Date & Time
        item_time = QTableWidgetItem(completed_at)
        item_time.setFont(QFont("Segoe UI", 8))
        item_time.setForeground(QColor("#64748B"))

        # Col 4: Result / Status badge
        item_res = QTableWidgetItem(result_text)
        item_res.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        res_lower = result_text.lower()
        if "success" in res_lower:
            item_res.setForeground(QColor("#047857"))
            item_res.setBackground(QColor("#D1FAE5"))
        elif "failed" in res_lower or "attention" in res_lower or "error" in res_lower or entry.get("unresolved"):
            item_res.setForeground(QColor("#B91C1C"))
            item_res.setBackground(QColor("#FEE2E2"))
        else:
            item_res.setForeground(QColor("#1D4ED8"))
            item_res.setBackground(QColor("#EFF6FF"))

        # Set UserRole on all cells so selection on any column retrieves the case dict
        entry_copy = dict(entry)
        for itm in (item_ref, item_veh, item_ins, item_time, item_res):
            itm.setData(Qt.ItemDataRole.UserRole, entry_copy)

        self.setItem(row, 0, item_ref)
        self.setItem(row, 1, item_veh)
        self.setItem(row, 2, item_ins)
        self.setItem(row, 3, item_time)
        self.setItem(row, 4, item_res)

    def addItem(self, text_or_entry):
        if isinstance(text_or_entry, dict):
            self.add_case_entry(text_or_entry)
        else:
            parts = [p.strip() for p in str(text_or_entry).split("|")]
            entry = {
                "case_ref": parts[0] if len(parts) > 0 else "N/A",
                "vehicle_no": parts[1] if len(parts) > 1 else "N/A",
                "insurer": parts[2] if len(parts) > 2 else "N/A",
                "formatted_completed_at": parts[3] if len(parts) > 3 else "",
                "display_result": parts[4] if len(parts) > 4 else "Completed Locally",
            }
            self.add_case_entry(entry)


class WebQueuePage(QWidget):
    completed = pyqtSignal(str, object, object)
    staging_completed = pyqtSignal(str, object, object)
    download_progress = pyqtSignal(str, object)
    submission_received = pyqtSignal(object)

    def __init__(self, window, root=None):
        super().__init__()
        self.window = window
        self.root = Path(root or user_data_dir("web_sync"))
        # Keep encrypted credentials and state in AppData, but put operator-visible
        # working copies in the Windows user's Automations folder.  An explicit
        # root remains isolated for development/embedded use.
        self.cases_root = Path(root) / "cases" if root is not None else Path.home() / "Automations"
        self.store = CredentialStore(self.root / "portal_credentials.dpapi")
        self.operator_store = OperatorCredentialStore(self.root / "operator_credentials.dpapi")
        self.completed_store = CompletedCaseStore(self.root / "completed_cases.json")
        self.state_error = ""
        self.state_recovery_blocked = ""
        try:
            self.case_repo = CaseRepository(self.root / "state")
            self.state = CaseState(self.root / "active_case.json")
            if self.state.recovery_error:
                active_phases = {"automation active", "report pending", "needs final resolution"}
                candidates = [
                    record for record in self.case_repo.all()
                    if record.get("local_status") in active_phases or record.get("phase") in active_phases
                ]
                if len(candidates) == 1:
                    recovered = dict(candidates[0])
                    recovered.pop("case_id", None)
                    self.state.set(recovered)
                else:
                    self.state_recovery_blocked = (
                        "Needs Attention: the active-case journal was damaged and quarantined. "
                        "Incoming cases remain available, but Start Automation is blocked until the active state is restored."
                    )
            legacy = CaseState(self.root / "current_case.json")
            if self.state.current is None and legacy.current:
                current = dict(legacy.current)
                job = current["job"]
                self.case_repo.upsert(
                    job["case_id"], **current,
                    local_status=current.get("phase", "needs attention"),
                    base44_status=job.get("status", "automation_in_progress"),
                )
                self.state.set(current)
                legacy.set(None)
            elif self.state.current:
                current = self.state.current
                persisted = {key: value for key, value in current.items() if key != "case_id"}
                self.case_repo.upsert(
                    current["job"]["case_id"], **persisted,
                )
        except (ValueError, OSError) as exc:
            self.state = SimpleStateUnavailable()
            self.case_repo = None
            self.state_error = f"Web Queue state could not be read: {exc}. Restore current_case.json before using Web Queue."
        self.client = None
        self.jobs = []
        self.completed_cases = []
        self.selected_job = None
        self._pending_start_case_id = None
        self._credential_case_id = None
        self.busy = False
        self.closing = False
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="web-sync")
        self.stage_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="web-stage")
        self.staging_ids = set()
        self.staging_dispatches = {}
        self.deleted_case_ids = set()
        self._live_log_entries = []
        self.completed.connect(self._completed)
        self.staging_completed.connect(self._staging_completed)
        self.download_progress.connect(self._download_progress)
        self.submission_received.connect(self._submission)

        # Fallback dummy labels for compatibility
        self.stat_queued = QLabel("0")
        self.stat_active = QLabel("None")
        self.stat_phase = QLabel("IDLE")
        self.stat_security = QLabel("DPAPI Encrypted")

        self._setup_ui()

        self.timer = QTimer(self)
        self.timer.setInterval(30_000)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

        try:
            self._recover_evidence()
        except (ValueError, OSError) as exc:
            self.state_error = f"Web Queue recovery needs attention: {exc}"
        if self.state_error or self.state_recovery_blocked:
            self.result.setText(self.state_error or self.state_recovery_blocked)
        self.refresh()

        QTimer.singleShot(0, self.restore_login)

    def _setup_ui(self):
        self.setObjectName("webQueuePageRoot")
        outer_layout = QHBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # ── Left Workflow Rail ─────────────────────────────────────────
        rail_wrap = QWidget()
        rail_wrap.setObjectName("workflowRailWrap")
        rail_lay = QVBoxLayout(rail_wrap)
        rail_lay.setContentsMargins(0, 0, 0, 0)
        rail_lay.setSpacing(0)

        self.rail = WebQueueWorkflowRail()
        self.rail.stage_selected.connect(self.set_stage)
        rail_lay.addWidget(self.rail, 1)

        # Rail Bottom Actions (Start & Stop)
        rail_actions = QWidget()
        rail_actions.setObjectName("railActions")
        al = QVBoxLayout(rail_actions)
        al.setContentsMargins(18, 12, 18, 18)
        al.setSpacing(8)

        self.start_button = QPushButton("Start Automation")
        self.start_button.setObjectName("btnStart")
        self.start_button.setMinimumHeight(42)
        self.start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_button.clicked.connect(self.start_automation)
        al.addWidget(self.start_button)

        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("btnStop")
        self.stop_button.setMinimumHeight(38)
        self.stop_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_button.setToolTip("Stops running automation safely. When stopped, click again to deliberately fail/report.")
        self.stop_button.clicked.connect(self.stop_or_fail_case)
        self.fail_button = self.stop_button
        al.addWidget(self.stop_button)

        rail_lay.addWidget(rail_actions)
        outer_layout.addWidget(rail_wrap)

        # ── Right Content Area ─────────────────────────────────────────
        right_container = QWidget()
        rc_lay = QVBoxLayout(right_container)
        rc_lay.setContentsMargins(0, 0, 0, 0)
        rc_lay.setSpacing(0)

        # Top Bar (Header & Global Web Sync Controls)
        header_bar = QWidget()
        header_bar.setStyleSheet("background: #FFFFFF; border-bottom: 1px solid #E2E8F0;")
        hb_lay = QHBoxLayout(header_bar)
        hb_lay.setContentsMargins(28, 14, 28, 14)
        hb_lay.setSpacing(16)

        title_col = QWidget()
        t_lay = QVBoxLayout(title_col)
        t_lay.setContentsMargins(0, 0, 0, 0)
        t_lay.setSpacing(2)

        self.stage_title_label = QLabel("Case Intake & Workspace")
        self.stage_title_label.setObjectName("workspaceHeading")
        self.stage_desc_label = QLabel("Select incoming cases from Base44, stage documents locally, and launch automation.")
        self.stage_desc_label.setStyleSheet("color: #64748B; font-size: 9pt; font-weight: 500;")
        t_lay.addWidget(self.stage_title_label)
        t_lay.addWidget(self.stage_desc_label)
        hb_lay.addWidget(title_col, 1)

        # Right Side Toolbar: Connection Pill + Refresh
        top_right = QWidget()
        tr_lay = QHBoxLayout(top_right)
        tr_lay.setContentsMargins(0, 0, 0, 0)
        tr_lay.setSpacing(10)

        pill_frame = QFrame()
        pill_frame.setObjectName("statusPill")
        p_lay = QHBoxLayout(pill_frame)
        p_lay.setContentsMargins(10, 5, 12, 5)
        p_lay.setSpacing(8)

        dot = QLabel()
        dot.setObjectName("statusDot")
        dot.setFixedSize(8, 8)

        self.connection = ConnectionStatusLabel(pill_frame, dot)
        p_lay.addWidget(dot)
        p_lay.addWidget(self.connection)
        tr_lay.addWidget(pill_frame)

        self.btn_poll = QPushButton("↻ Refresh")
        self.btn_poll.setObjectName("btnPollQueue")
        self.btn_poll.setMinimumHeight(30)
        self.btn_poll.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_poll.setStyleSheet(
            "QPushButton#btnPollQueue { background-color: #FFFFFF; color: #334155; border: 1px solid #CBD5E1; "
            "border-radius: 6px; font-weight: 700; font-size: 8.5pt; padding: 4px 12px; } "
            "QPushButton#btnPollQueue:hover { background-color: #F8FAFC; border-color: #94A3B8; }"
        )
        self.btn_poll.clicked.connect(self.poll)
        tr_lay.addWidget(self.btn_poll)

        hb_lay.addWidget(top_right, 0, Qt.AlignmentFlag.AlignVCenter)
        rc_lay.addWidget(header_bar)

        # ── QStackedWidget with 3 Pages ────────────────────────────────
        self.stack = QStackedWidget()
        self.stack.setObjectName("webQueueStack")

        # ══════════════════════════════════════════════════════════════
        # PAGE 0: CASES (Intake, Readiness KPI, Case Workspace, Completed)
        # ══════════════════════════════════════════════════════════════
        page_cases_scroll = QScrollArea()
        page_cases_scroll.setWidgetResizable(True)
        page_cases_scroll.setFrameShape(QFrame.Shape.NoFrame)

        page_cases_inner = QWidget()
        pc_lay = QVBoxLayout(page_cases_inner)
        pc_lay.setContentsMargins(28, 20, 28, 20)
        pc_lay.setSpacing(16)

        # Case Workspace Card
        queue_content = QWidget()
        qc_lay = QVBoxLayout(queue_content)
        qc_lay.setContentsMargins(0, 4, 0, 0)
        qc_lay.setSpacing(10)

        q_header_row = QWidget()
        qhr_lay = QHBoxLayout(q_header_row)
        qhr_lay.setContentsMargins(0, 0, 0, 0)
        self.queue_badge = QLabel("0 Jobs Ready")
        self.queue_badge.setStyleSheet("background-color: #EFF6FF; color: #1D4ED8; border: 1px solid #BFDBFE; border-radius: 4px; font-size: 8pt; font-weight: 800; padding: 3px 8px;")
        qhr_lay.addWidget(_field_label("CASES READY FOR AUTOMATION"))
        qhr_lay.addSpacing(8)
        qhr_lay.addWidget(self.queue_badge)
        qhr_lay.addStretch()
        q_header_row.setVisible(False)
        qc_lay.addWidget(q_header_row)

        self.list = QListWidget()
        self.list.setObjectName("webQueueList")
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setSpacing(6)
        self.list.setMouseTracking(True)
        self.list.setItemDelegate(CaseListDelegate(self.list, page=self))
        self.list.currentRowChanged.connect(self._selected)
        self.list.itemClicked.connect(self._case_clicked)
        self.list.itemDoubleClicked.connect(lambda _item: self.start_case())
        qc_lay.addWidget(self.list)

        self.empty_label = QLabel("No queued or current case. Click Refresh or connect to DocWriter.")
        self.empty_label.setObjectName("helperTextItalic")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("padding: 14px; color: #94A3B8; font-size: 9pt;")
        self.empty_label.setVisible(False)
        qc_lay.addWidget(self.empty_label)

        queue_hint = QLabel(
            "Incoming cases download automatically into separate insurer folders. "
            "Select a Ready case to prepare Workspace; Start Automation remains manual."
        )
        queue_hint.setWordWrap(True)
        queue_hint.setStyleSheet("color:#64748B;font-size:8pt;")
        qc_lay.addWidget(queue_hint)

        self.current_label = QLabel("Current case: None")
        self.current_label.setVisible(False)
        qc_lay.addWidget(self.current_label)

        BTN_STYLE_IMAGES = (
            "QPushButton {"
            "  background-color: #F0F9FF; color: #0284C7; border: 1.5px solid #BAE6FD;"
            "  border-radius: 6px; font-size: 8.5pt; font-weight: 700; padding: 5px 14px; min-height: 30px;"
            "}"
            "QPushButton:hover {"
            "  background-color: #E0F2FE; border-color: #38BDF8; color: #0369A1;"
            "}"
            "QPushButton:pressed {"
            "  background-color: #BAE6FD;"
            "}"
            "QPushButton:disabled {"
            "  background-color: #F8FAFC; color: #94A3B8; border-color: #E2E8F0;"
            "}"
        )
        BTN_STYLE_RESTAGE = (
            "QPushButton {"
            "  background-color: #EEF2FF; color: #4F46E5; border: 1.5px solid #C7D2FE;"
            "  border-radius: 6px; font-size: 8.5pt; font-weight: 700; padding: 5px 14px; min-height: 30px;"
            "}"
            "QPushButton:hover {"
            "  background-color: #E0E7FF; border-color: #818CF8; color: #3730A3;"
            "}"
            "QPushButton:pressed {"
            "  background-color: #C7D2FE;"
            "}"
            "QPushButton:disabled {"
            "  background-color: #F8FAFC; color: #94A3B8; border-color: #E2E8F0;"
            "}"
        )
        BTN_STYLE_COMPLETED = (
            "QPushButton {"
            "  background-color: #ECFDF5; color: #059669; border: 1.5px solid #A7F3D0;"
            "  border-radius: 6px; font-size: 8.5pt; font-weight: 700; padding: 5px 14px; min-height: 30px;"
            "}"
            "QPushButton:hover {"
            "  background-color: #D1FAE5; border-color: #34D399; color: #047857;"
            "}"
            "QPushButton:pressed {"
            "  background-color: #A7F3D0;"
            "}"
            "QPushButton:disabled {"
            "  background-color: #F8FAFC; color: #94A3B8; border-color: #E2E8F0;"
            "}"
        )
        BTN_STYLE_DELETE = (
            "QPushButton {"
            "  background-color: #FEF2F2; color: #DC2626; border: 1.5px solid #FECACA;"
            "  border-radius: 6px; font-size: 8.5pt; font-weight: 700; padding: 5px 14px; min-height: 30px;"
            "}"
            "QPushButton:hover {"
            "  background-color: #FEE2E2; border-color: #F87171; color: #B91C1C;"
            "}"
            "QPushButton:pressed {"
            "  background-color: #FECACA;"
            "}"
            "QPushButton:disabled {"
            "  background-color: #F8FAFC; color: #94A3B8; border-color: #E2E8F0;"
            "}"
        )

        self.small_actions = QWidget(self)
        self.small_actions.setVisible(False)
        sa_lay = QHBoxLayout(self.small_actions)
        sa_lay.setContentsMargins(0, 4, 0, 0)
        sa_lay.setSpacing(10)
        self.view_images_button = QPushButton("🖼 VIEW IMAGES / DOCS")
        self.view_images_button.setObjectName("btnViewImages")
        self.restage_button = QPushButton("↻ DOWNLOAD / RESTAGE")
        self.restage_button.setObjectName("btnRestage")
        self.mark_completed_button = QPushButton("✓ MARK COMPLETED")
        self.mark_completed_button.setObjectName("btnMarkCompleted")
        self.delete_local_button = QPushButton("🗑 DELETE CASE")
        self.delete_local_button.setObjectName("btnDeleteLocal")

        for btn in (self.view_images_button, self.restage_button, self.mark_completed_button, self.delete_local_button):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self.view_images_button.setToolTip("Open local folder to view inspection images, RC copy, and estimate documents")
        self.restage_button.setToolTip("Re-download files and Excel from Base44 / Cloud Drive into local workspace")
        self.mark_completed_button.setToolTip("Mark case as finished and move to Completed Cases history")
        self.delete_local_button.setToolTip("Delete case completely from local workspace and disk")

        self.view_images_button.setStyleSheet(BTN_STYLE_IMAGES)
        self.restage_button.setStyleSheet(BTN_STYLE_RESTAGE)
        self.mark_completed_button.setStyleSheet(BTN_STYLE_COMPLETED)
        self.delete_local_button.setStyleSheet(BTN_STYLE_DELETE)

        self.view_images_button.clicked.connect(self.open_selected_case_images)
        self.restage_button.clicked.connect(self.restage_selected)
        self.mark_completed_button.clicked.connect(self.mark_completed)
        self.delete_local_button.clicked.connect(self.delete_current_local_copy)

        sa_lay.addStretch()
        sa_lay.addWidget(self.view_images_button)
        sa_lay.addWidget(self.restage_button)
        sa_lay.addWidget(self.mark_completed_button)
        sa_lay.addWidget(self.delete_local_button)
        # Note: small_actions omitted from qc_lay; action buttons are directly on each individual case card in CaseListDelegate

        pc_lay.addWidget(_card(queue_content))

        # Completed-case evidence remains persisted in CompletedCaseStore.  The
        # retired history table is intentionally not constructed or refreshed.

        page_cases_scroll.setWidget(page_cases_inner)
        self.stack.addWidget(page_cases_scroll)

        # ══════════════════════════════════════════════════════════════
        # PAGE 1: CONNECTION (DocWriter Connection & Surveyor Portal Credentials)
        # ══════════════════════════════════════════════════════════════
        page_conn_scroll = QScrollArea()
        page_conn_scroll.setWidgetResizable(True)
        page_conn_scroll.setFrameShape(QFrame.Shape.NoFrame)

        page_conn_inner = QWidget()
        pconn_lay = QVBoxLayout(page_conn_inner)
        pconn_lay.setContentsMargins(28, 20, 28, 20)
        pconn_lay.setSpacing(16)

        # DocWriter Connection Card
        conn_content = QWidget()
        cc_lay = QVBoxLayout(conn_content)
        cc_lay.setContentsMargins(0, 4, 0, 0)
        cc_lay.setSpacing(8)

        self.conn_connected_box = QWidget()
        conn_box_lay = QVBoxLayout(self.conn_connected_box)
        conn_box_lay.setContentsMargins(0, 0, 0, 0)
        conn_box_lay.setSpacing(8)

        conn_status_row = QWidget()
        csr_lay = QHBoxLayout(conn_status_row)
        csr_lay.setContentsMargins(0, 0, 0, 0)
        csr_lay.setSpacing(10)

        conn_badge = QLabel("✓ Connected")
        conn_badge.setStyleSheet(
            "background-color: #DCFCE7; color: #15803D; border: 1px solid #86EFAC; "
            "border-radius: 4px; font-weight: 800; font-size: 8pt; padding: 3px 8px;"
        )
        csr_lay.addWidget(conn_badge)

        self.conn_operator_email = QLabel("Operator: operator@base44.app")
        self.conn_operator_email.setStyleSheet("font-weight: 700; color: #0F172A; font-size: 9pt;")
        csr_lay.addWidget(self.conn_operator_email)
        csr_lay.addStretch()
        conn_box_lay.addWidget(conn_status_row)

        conn_actions_row = QWidget()
        car_lay = QHBoxLayout(conn_actions_row)
        car_lay.setContentsMargins(0, 0, 0, 0)
        car_lay.setSpacing(8)

        btn_reconnect = QPushButton("↻ Reconnect")
        btn_reconnect.setMinimumHeight(28)
        btn_reconnect.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reconnect.setStyleSheet(
            "background-color: #F8FAFC; color: #334155; border: 1px solid #CBD5E1; "
            "border-radius: 4px; font-size: 8pt; font-weight: 700; padding: 3px 10px;"
        )
        btn_reconnect.clicked.connect(self.poll)
        car_lay.addWidget(btn_reconnect)

        btn_change = QPushButton("Change Login")
        btn_change.setMinimumHeight(28)
        btn_change.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_change.setStyleSheet(
            "background-color: #F8FAFC; color: #334155; border: 1px solid #CBD5E1; "
            "border-radius: 4px; font-size: 8pt; font-weight: 700; padding: 3px 10px;"
        )
        btn_change.clicked.connect(self.change_login)
        car_lay.addWidget(btn_change)
        car_lay.addStretch()
        conn_box_lay.addWidget(conn_actions_row)

        cc_lay.addWidget(self.conn_connected_box)

        self.conn_form_box = QWidget()
        cfb_lay = QVBoxLayout(self.conn_form_box)
        cfb_lay.setContentsMargins(0, 0, 0, 0)
        cfb_lay.setSpacing(8)

        form_row = QWidget()
        fr_lay = QHBoxLayout(form_row)
        fr_lay.setContentsMargins(0, 0, 0, 0)
        fr_lay.setSpacing(10)

        email_col = QWidget()
        ec_lay = QVBoxLayout(email_col)
        ec_lay.setContentsMargins(0, 0, 0, 0)
        ec_lay.setSpacing(4)
        ec_lay.addWidget(_field_label("OPERATOR EMAIL"))
        self.email = QLineEdit()
        self.email.setPlaceholderText("operator@base44.app")
        self.email.setMinimumHeight(34)
        ec_lay.addWidget(self.email)
        fr_lay.addWidget(email_col, 1)

        pwd_col = QWidget()
        pc_lay = QVBoxLayout(pwd_col)
        pc_lay.setContentsMargins(0, 0, 0, 0)
        pc_lay.setSpacing(4)
        pc_lay.addWidget(_field_label("OPERATOR PASSWORD"))
        pwd_input_row = QWidget()
        pir_lay = QHBoxLayout(pwd_input_row)
        pir_lay.setContentsMargins(0, 0, 0, 0)
        pir_lay.setSpacing(4)
        self.password = QLineEdit()
        self.password.setPlaceholderText("Password")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setMinimumHeight(34)
        btn_eye_op = _make_eye_toggle(self.password)
        pir_lay.addWidget(self.password, 1)
        pir_lay.addWidget(btn_eye_op)
        pc_lay.addWidget(pwd_input_row)
        fr_lay.addWidget(pwd_col, 1)

        self.connect_button = QPushButton("Connect")
        self.connect_button.setObjectName("btnWebConnect")
        self.connect_button.setMinimumHeight(34)
        self.connect_button.setMinimumWidth(92)
        self.connect_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.connect_button.setStyleSheet(
            "background-color: #0F172A; color: #FFFFFF; font-weight: 700; "
            "border-radius: 6px; padding: 6px 14px;"
        )
        self.connect_button.clicked.connect(self.connect_client)
        fr_lay.addWidget(self.connect_button, 0, Qt.AlignmentFlag.AlignBottom)

        cfb_lay.addWidget(form_row)

        conn_note = QLabel("🔒 Operator login saved with Windows DPAPI. Access tokens stay in memory.")
        conn_note.setObjectName("helperTextItalic")
        conn_note.setStyleSheet("font-size: 8pt; color: #64748B;")
        cfb_lay.addWidget(conn_note)

        cc_lay.addWidget(self.conn_form_box)

        pconn_lay.addWidget(_card(conn_content, "DocWriter Connection", "Sign in with operator credentials to synchronize assigned claims"))

        # Surveyor Portal Login Card
        cred_content = QWidget()
        crc_lay = QVBoxLayout(cred_content)
        crc_lay.setContentsMargins(0, 4, 0, 0)
        crc_lay.setSpacing(8)

        surv_info_row = QWidget()
        sir_lay = QHBoxLayout(surv_info_row)
        sir_lay.setContentsMargins(0, 0, 0, 0)
        sir_lay.setSpacing(8)

        self.surveyor_name_label = QLabel("Surveyor: (Select a case)")
        self.surveyor_name_label.setStyleSheet("font-weight: 800; font-size: 9.5pt; color: #0F172A;")
        sir_lay.addWidget(self.surveyor_name_label)

        self.surveyor_profile_sub = QLabel("Profile ID: None")
        self.surveyor_profile_sub.setStyleSheet("font-size: 8pt; color: #64748B; font-weight: 500;")
        sir_lay.addWidget(self.surveyor_profile_sub)
        sir_lay.addStretch()
        crc_lay.addWidget(surv_info_row)

        self.profile = QLineEdit()
        self.profile.setVisible(False)
        crc_lay.addWidget(self.profile)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)

        grid.addWidget(_field_label("INSURER PORTAL"), 0, 0)
        self.insurer = QComboBox()
        self.insurer.setMinimumHeight(34)
        for label, value in (("United India", "uiic"), ("New India", "newindia"), ("Oriental", "oic")):
            self.insurer.addItem(label, value)
        grid.addWidget(self.insurer, 1, 0)

        grid.addWidget(_field_label("PORTAL USERNAME"), 0, 1)
        self.username = QLineEdit()
        self.username.setPlaceholderText("Portal login username")
        self.username.setMinimumHeight(34)
        grid.addWidget(self.username, 1, 1)

        grid.addWidget(_field_label("PORTAL PASSWORD"), 2, 0)
        secret_row = QWidget()
        sr_lay = QHBoxLayout(secret_row)
        sr_lay.setContentsMargins(0, 0, 0, 0)
        sr_lay.setSpacing(4)
        self.secret = QLineEdit()
        self.secret.setPlaceholderText("Portal login password")
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret.setMinimumHeight(34)
        btn_eye_portal = _make_eye_toggle(self.secret)
        sr_lay.addWidget(self.secret, 1)
        sr_lay.addWidget(btn_eye_portal)
        grid.addWidget(secret_row, 3, 0)

        grid.addWidget(_field_label("SURVEYOR CODE (OPTIONAL)"), 2, 1)
        self.code = QLineEdit()
        self.code.setPlaceholderText("e.g. SC-101 (optional)")
        self.code.setMinimumHeight(34)
        grid.addWidget(self.code, 3, 1)

        crc_lay.addLayout(grid)

        cred_action_row = QWidget()
        car2_lay = QHBoxLayout(cred_action_row)
        car2_lay.setContentsMargins(0, 2, 0, 0)
        car2_lay.setSpacing(10)

        self.cred_feedback = QLabel("")
        self.cred_feedback.setStyleSheet(
            "font-weight: 700; font-size: 8.5pt; color: #059669; padding: 4px 8px; border-radius: 4px;"
        )
        car2_lay.addWidget(self.cred_feedback, 1)

        self.save_btn = QPushButton("💾 Update Credentials")
        self.save_btn.setObjectName("btnSaveCreds")
        self.save_btn.setMinimumHeight(34)
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setStyleSheet(
            "QPushButton#btnSaveCreds { background-color: #F8FAFC; color: #0F172A; border: 1.5px solid #CBD5E1; "
            "border-radius: 6px; font-weight: 700; font-size: 8.5pt; padding: 4px 16px; } "
            "QPushButton#btnSaveCreds:hover { background-color: #F1F5F9; border-color: #94A3B8; }"
        )
        self.save_btn.clicked.connect(self.save_credentials)
        car2_lay.addWidget(self.save_btn, 0)

        crc_lay.addWidget(cred_action_row)

        cred_note = QLabel("🔒 Saved securely on this PC with Windows DPAPI. Never uploaded or shared.")
        cred_note.setObjectName("helperTextItalic")
        cred_note.setStyleSheet("font-size: 8pt; color: #64748B;")
        crc_lay.addWidget(cred_note)

        pconn_lay.addWidget(_card(cred_content, "Surveyor Portal Login", "Configure and store login passwords locally for automatic portal sign-in"))
        pconn_lay.addStretch()

        page_conn_scroll.setWidget(page_conn_inner)
        self.stack.addWidget(page_conn_scroll)

        # ══════════════════════════════════════════════════════════════
        # PAGE 2: LIVE LOGS (Status Banner, Toolbar, 4-Col Activity Table)
        # ══════════════════════════════════════════════════════════════
        page_logs_scroll = QScrollArea()
        page_logs_scroll.setWidgetResizable(True)
        page_logs_scroll.setFrameShape(QFrame.Shape.NoFrame)

        page_logs_inner = QWidget()
        plogs_lay = QVBoxLayout(page_logs_inner)
        plogs_lay.setContentsMargins(28, 20, 28, 20)
        plogs_lay.setSpacing(14)

        # Quick Status Banner (kept hidden to maximize space; status is shown in toolbar)
        self.result_frame = QFrame(self)
        self.result_frame.setObjectName("resultBanner")
        self.result_frame.setVisible(False)
        rf_lay = QVBoxLayout(self.result_frame)
        rf_lay.setContentsMargins(14, 10, 14, 10)
        rf_lay.setSpacing(4)

        res_header_row = QWidget()
        rhr_lay = QHBoxLayout(res_header_row)
        rhr_lay.setContentsMargins(0, 0, 0, 0)

        self.result_status_pill = QLabel("  IDLE  ")
        self.result_time_label = QLabel("Standing by for case activity")
        self.result_time_label.setStyleSheet("color: #64748B; font-size: 8.5pt; font-weight: 600;")
        rhr_lay.addWidget(self.result_status_pill)
        rhr_lay.addStretch()
        rhr_lay.addWidget(self.result_time_label)
        rf_lay.addWidget(res_header_row)

        self.result = ResultBannerLabel(
            self.result_frame, self.result_status_pill, self.result_time_label,
            on_update=self._on_banner_logged
        )
        rf_lay.addWidget(self.result)

        # Logs Card - starts directly at top of Live Logs tab
        logs_content = QWidget()
        lc_logs_lay = QVBoxLayout(logs_content)
        lc_logs_lay.setContentsMargins(0, 4, 0, 0)
        lc_logs_lay.setSpacing(10)

        toolbar = QWidget()
        tb_lay = QHBoxLayout(toolbar)
        tb_lay.setContentsMargins(0, 0, 0, 0)
        tb_lay.setSpacing(10)

        search_widget, self.log_search_input = _search_row(
            "Search activity logs by action, case, phase, file, error, or status...",
            self._filter_live_logs
        )
        tb_lay.addWidget(search_widget, 1)

        # Status pill & timestamp placed directly in toolbar next to search
        tb_lay.addWidget(self.result_status_pill)
        tb_lay.addWidget(self.result_time_label)

        self.log_auto_scroll = QCheckBox("Auto-scroll")
        self.log_auto_scroll.setChecked(True)
        self.log_auto_scroll.setStyleSheet("font-size: 8.5pt; color: #475569; font-weight: 600;")
        tb_lay.addWidget(self.log_auto_scroll)

        self.btn_copy_logs = QPushButton("Copy")
        self.btn_clear_logs = QPushButton("Clear")
        self.btn_export_logs = QPushButton("Export")
        for b in (self.btn_copy_logs, self.btn_clear_logs, self.btn_export_logs):
            b.setObjectName("logsSmallBtn")
            b.setMinimumHeight(32)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                "background-color: #FFFFFF; color: #334155; border: 1px solid #CBD5E1; "
                "border-radius: 6px; font-weight: 700; font-size: 8.5pt; padding: 4px 12px;"
            )
        self.btn_copy_logs.clicked.connect(self._copy_live_logs)
        self.btn_clear_logs.clicked.connect(self._clear_live_logs)
        self.btn_export_logs.clicked.connect(self._export_live_logs)
        tb_lay.addWidget(self.btn_copy_logs)
        tb_lay.addWidget(self.btn_clear_logs)
        tb_lay.addWidget(self.btn_export_logs)
        lc_logs_lay.addWidget(toolbar)

        self.logs_table = QTableWidget(0, 4)
        self.logs_table.setObjectName("logsTable")
        self.logs_table.setHorizontalHeaderLabels(["TIME", "LEVEL", "PHASE", "ACTION"])
        self.logs_table.setAlternatingRowColors(True)
        self.logs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.logs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.logs_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.logs_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.logs_table.verticalHeader().setVisible(False)
        self.logs_table.verticalHeader().setDefaultSectionSize(36)
        self.logs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.logs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.logs_table.setMinimumHeight(280)
        attach_row_copy_on_double_click(self.logs_table)
        lc_logs_lay.addWidget(self.logs_table)

        plogs_lay.addWidget(_card(logs_content))

        page_logs_scroll.setWidget(page_logs_inner)
        self.stack.addWidget(page_logs_scroll)

        rc_lay.addWidget(self.stack, 1)
        outer_layout.addWidget(right_container, 1)

    def set_stage(self, idx: int):
        if hasattr(self, "stack") and 0 <= idx < self.stack.count():
            self.stack.setCurrentIndex(idx)
            if hasattr(self, "rail"):
                self.rail.set_active(idx)
            stage_meta = [
                ("Case Intake & Workspace", "Select incoming cases from Base44, stage documents locally, and launch automation."),
                ("Connection & Credentials", "Sign in to Base44 DocWriter and configure surveyor portal logins."),
                ("Live Staging & Portal Activity", "Real-time intake events, document downloads, OCR pre-scan, and portal activity."),
            ]
            if 0 <= idx < len(stage_meta):
                title, desc = stage_meta[idx]
                if hasattr(self, "stage_title_label"):
                    self.stage_title_label.setText(title)
                if hasattr(self, "stage_desc_label"):
                    self.stage_desc_label.setText(desc)


    def _on_banner_logged(self, text, outcome=None):
        t = (text or "").lower()
        if any(w in t for w in ("staging", "download", "manifest", "drive", "base44 was not claimed")):
            phase = "Staging"
        elif any(w in t for w in ("portal", "browser", "submit", "submission", "uploaded")):
            phase = "Portal"
        else:
            phase = "Sync"
        level = "Success" if outcome == "success" or "success" in t else (
            "Error" if outcome == "attention" or any(w in t for w in ("failed", "error", "unable", "cannot")) else "Info"
        )
        current = self.state.current if getattr(self, "state", None) else None
        current_case_id = (current or {}).get("job", {}).get("case_id")
        self.append_log(text, phase=phase, level=level, case_id=current_case_id)

    def append_log(self, text: str, phase: str = "Sync", level: str = None, case_id: str = None):
        if not text or self.closing:
            return
        clean = str(text).strip()
        if not clean or clean == "No result yet.":
            return
        # Deduplicate consecutive identical actions
        if self._live_log_entries and self._live_log_entries[-1].get("action") == clean:
            return

        now_str = datetime.now().strftime("%H:%M:%S")
        if not level:
            lower = clean.lower()
            if any(w in lower for w in ("error", "fail", "failed", "cannot", "unable", "invalid", "missing")):
                level = "Error"
            elif any(w in lower for w in ("warn", "warning", "conflict", "attention", "claimed elsewhere")):
                level = "Warning"
            elif any(w in lower for w in ("success", "confirmed", "ready", "uploaded", "complete", "completed")):
                level = "Success"
            else:
                level = "Info"

        entry = {
            "time": now_str,
            "level": level,
            "phase": phase or "Sync",
            "action": clean,
            "search": f"{now_str} {level} {phase} {clean}".lower(),
        }
        self._live_log_entries.append(entry)
        if case_id:
            self._append_case_log(case_id, entry)

        if not hasattr(self, "logs_table"):
            return

        row = self.logs_table.rowCount()
        self.logs_table.insertRow(row)

        time_item = QTableWidgetItem(now_str)
        time_item.setFont(QFont("Cascadia Code", 8))
        time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        time_item.setForeground(QColor("#64748B"))

        level_item = QTableWidgetItem(level.upper())
        level_item.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        level_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        lvl_colors = {
            "Error": (QColor("#DC2626"), QColor("#FEF2F2")),
            "Warning": (QColor("#D97706"), QColor("#FFFBEB")),
            "Success": (QColor("#059669"), QColor("#ECFDF5")),
            "Info": (QColor("#2563EB"), QColor("#EFF6FF")),
        }
        fg, bg = lvl_colors.get(level, (QColor("#475569"), QColor("#F8FAFC")))
        level_item.setForeground(fg)
        level_item.setBackground(bg)

        phase_item = QTableWidgetItem(str(phase).upper())
        phase_item.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        phase_item.setForeground(QColor("#475569"))
        phase_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        action_item = QTableWidgetItem(clean)
        action_item.setFont(QFont("Segoe UI", 8))
        action_item.setForeground(QColor("#0F172A"))
        action_item.setToolTip(clean)

        self.logs_table.setItem(row, 0, time_item)
        self.logs_table.setItem(row, 1, level_item)
        self.logs_table.setItem(row, 2, phase_item)
        self.logs_table.setItem(row, 3, action_item)

        q = self.log_search_input.text().strip().lower() if hasattr(self, "log_search_input") else ""
        if q and q not in entry["search"]:
            self.logs_table.setRowHidden(row, True)
        elif hasattr(self, "log_auto_scroll") and self.log_auto_scroll.isChecked() and not q:
            self.logs_table.scrollToBottom()

    def _append_case_log(self, case_id, entry):
        """Append one readable event to the selected case's own audit log."""
        record = self._record(case_id)
        if (record or {}).get("local_copy_deleted") or (record or {}).get("deleted_by_operator"):
            return
        folder_value = (record or {}).get("folder")
        if not folder_value:
            return
        try:
            folder = Path(folder_value)
            folder.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
            action = str(entry.get("action", "")).replace("\r", " ").replace("\n", " ").strip()
            line = (
                f"{timestamp} [{entry.get('level', 'Info')}] "
                f"[{entry.get('phase', 'Sync')}] {action}\n"
            )
            with (folder / "case_activity.log").open("a", encoding="utf-8") as output:
                output.write(line)
        except OSError:
            # A logging failure must never interrupt staging or portal work.
            return

    def _filter_live_logs(self, query):
        q = (query or "").strip().lower()
        for row, entry in enumerate(self._live_log_entries):
            visible = True if not q or q in entry["search"] else False
            self.logs_table.setRowHidden(row, not visible)
        if hasattr(self, "log_auto_scroll") and self.log_auto_scroll.isChecked() and not q:
            self.logs_table.scrollToBottom()

    def _copy_live_logs(self):
        lines = []
        for row, entry in enumerate(self._live_log_entries):
            if not self.logs_table.isRowHidden(row):
                lines.append(f"[{entry['time']}] [{entry['level']}] [{entry['phase']}] {entry['action']}")
        text = "\n".join(lines)
        if text:
            QApplication.clipboard().setText(text)

    def _clear_live_logs(self):
        self._live_log_entries.clear()
        self.logs_table.setRowCount(0)

    def _export_live_logs(self):
        lines = [f"[{e['time']}] [{e['level']}] [{e['phase']}] {e['action']}" for e in self._live_log_entries]
        if not lines:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Web Queue Logs",
            f"web_queue_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            "Text Files (*.txt)"
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
            except Exception as e:
                QMessageBox.critical(self, "Export Failed", str(e))

    def _recover_evidence(self):
        current = self.state.current
        if current and current.get("folder") and not current.get("pending_report"):
            path = Path(current["folder"]) / "Portal_Submission_Result.json"
            if path.exists():
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("case_id") == current["job"]["case_id"] and record.get("confirmed_success"):
                    self._submission(record)

    @staticmethod
    def _status_for(current, automation_running=False):
        if automation_running:
            return "Automation Active"
        phase = (current or {}).get("local_status") or (current or {}).get("phase", "")
        if (current or {}).get("last_message") and phase not in ("report pending", "submitted successfully"):
            return "Needs Attention"
        return {
            "discovered": "Queued", "staging": "Downloading",
            "stage failed": "Stage Failed", "scanning": "Downloading",
            "workspace ready": "Workspace Ready", "automation active": "Automation Active",
            "ready": "Ready", "report pending": "Needs Attention",
            "submitted successfully": "Submitted Successfully",
            "needs final resolution": "Needs Attention",
            "claimed elsewhere": "Claimed Elsewhere",
            "stale/replaced": "Needs Attention",
            "local copy deleted": "Local Copy Deleted",
        }.get(phase, phase.title() if phase else "Queued")

    def _records(self):
        if not self.case_repo:
            return []
        try:
            return self.case_repo.all()
        except (OSError, ValueError) as exc:
            self.state_error = f"Web Queue case state could not be read: {exc}"
            self.result.setText(self.state_error)
            return []

    def _record(self, case_id):
        return self.case_repo.get(case_id) if self.case_repo and case_id else None

    def _active_update(self, **changes):
        current = self.state.current
        if not current:
            return None
        self.state.update(**changes)
        case_id = self.state.current["job"]["case_id"]
        return self.case_repo.upsert(case_id, **changes)

    def _valid_stage(self, record):
        return self._stage_validation_error(record, verify_md5=False) is None

    @staticmethod
    def _job_validation_errors(job):
        if not isinstance(job, dict):
            return ["job"]
        supplied = job.get("_queue_validation_errors")
        if isinstance(supplied, list):
            return [str(value) for value in supplied if value]
        required = ("case_id", "case_ref", "insurer", "surveyor_profile_id", "automation_dispatch_id")
        return [key for key in required if not isinstance(job.get(key), str) or not job[key].strip()]

    def _stage_validation_error(self, record, *, verify_md5):
        if not record:
            return "local case state is missing"
        job = record.get("job", record)
        try:
            validate_staged_case(
                record.get("folder"),
                job.get("case_id") or record.get("case_id"),
                _dispatch_id(record),
                record.get("latest_excel"),
                verify_md5=verify_md5,
            )
        except (OSError, StagedCaseValidationError, ValueError) as exc:
            return str(exc)
        return None

    def _display_status(self, record, automation_running=False):
        status = self._status_for(record, automation_running)
        if status in ("Ready", "Workspace Ready") and not self._valid_stage(record):
            return "Needs Attention"
        return status

    def _history(self):
        try:
            self.completed_cases = self.completed_store.all()
        except (OSError, ValueError) as exc:
            self.completed_cases = []
            if hasattr(self, "result"):
                self.result.setText(f"Needs Attention: local Completed Cases history could not be read: {exc}")
        return self.completed_cases

    @staticmethod
    def _case_text(job, status, display_number=None):
        parts = (
            str(job.get("case_ref", "N/A")), str(job.get("vehicle_no", "N/A")),
            str(job.get("insurer", "N/A")), str(job.get("surveyor_profile_id", "N/A")), status,
        )
        if display_number:
            parts = (f"#{int(display_number):03d}", *parts)
        return " | ".join(parts)

    def _next_display_number(self):
        used = [
            int(record["display_number"])
            for record in self._records()
            if str(record.get("display_number", "")).isdigit()
        ]
        for entry in self._history():
            if str(entry.get("display_number", "")).isdigit():
                used.append(int(entry["display_number"]))
        return max(used, default=0) + 1

    def _ensure_display_numbers(self):
        """Assign each local case one stable operator-facing sequence number."""
        if not self.case_repo:
            return
        records = {record["case_id"]: record for record in self._records()}
        next_number = self._next_display_number() - 1
        for job in self.jobs:
            case_id = job.get("case_id")
            record = records.get(case_id)
            if not case_id or (record and str(record.get("display_number", "")).isdigit()):
                continue
            next_number += 1
            errors = self._job_validation_errors(job)
            records[case_id] = self.case_repo.upsert(
                case_id,
                job=job,
                display_number=next_number,
                automation_dispatch_id=job.get("automation_dispatch_id", ""),
                automation_dispatched_at=job.get("automation_dispatched_at", ""),
                local_status="needs attention" if errors else "discovered",
                phase="needs attention" if errors else "discovered",
                last_error=("Missing Base44 fields: " + ", ".join(errors)) if errors else "",
            )

    def _resize_case_list(self):
        """Show every incoming case card and leave scrolling to the outer page."""
        count = self.list.count()
        if not count:
            self.list.setFixedHeight(120)
            return
        row_height = max(122, self.list.sizeHintForRow(0))
        spacing = self.list.spacing()
        content_height = count * row_height + (count + 1) * spacing + 2 * self.list.frameWidth()
        self.list.setFixedHeight(content_height)

    def _rebuild_case_lists(self):
        self._ensure_display_numbers()
        current = self.state.current
        previous_id = (self.selected_job or {}).get("case_id")
        rows = []
        active_id = current.get("job", {}).get("case_id") if current else None
        records = {record["case_id"]: record for record in self._records()}
        incoming_by_id = {job.get("case_id"): job for job in self.jobs}
        completed_ids = set()
        for entry in self._history():
            case_id = entry.get("case_id")
            if entry.get("section") != "completed" or not case_id:
                continue
            incoming_job = incoming_by_id.get(case_id)
            if not incoming_job or not _dispatch_id(entry) or _dispatch_id(entry) == _dispatch_id(incoming_job):
                completed_ids.add(case_id)
        deleted_ids = getattr(self, "deleted_case_ids", set())

        if current and not current.get("locally_completed") and active_id not in deleted_ids and active_id not in completed_ids:
            record = {**records.get(active_id, {}), **current, "case_id": active_id}
            rows.append((current["job"], "active", self._display_status(record, bool(self.window._worker)), record))
        for entry in self._history():
            c_id = entry.get("case_id")
            if entry.get("section") == "workspace" and c_id != active_id and c_id not in deleted_ids and c_id not in completed_ids:
                rows.append((entry, "resolved", entry.get("display_result", "Submitted Successfully"), entry))
        shown_ids = {job.get("case_id") for job, _kind, _status, _record in rows}
        for job in self.jobs:
            case_id = job.get("case_id")
            if case_id in shown_ids or case_id == active_id or case_id in deleted_ids or case_id in completed_ids:
                continue
            record = records.get(case_id)
            if record and (record.get("deleted_by_operator") or record.get("local_status") in ("deleted", "completed")):
                continue
            kind = "resolved" if record and record.get("base44_status") in ("uploaded", "ready_for_upload") else ("staged" if record else "queued")
            rows.append((job, kind, self._display_status(record), record or {"case_id": case_id, "job": job, "local_status": "discovered"}))
            shown_ids.add(case_id)
        for case_id, record in records.items():
            if case_id in shown_ids or case_id == active_id or case_id in deleted_ids or case_id in completed_ids:
                continue
            if record.get("deleted_by_operator") or record.get("local_status") in ("deleted", "completed"):
                continue
            rows.append((record.get("job", record), "staged", self._display_status(record), record))
            shown_ids.add(case_id)

        self.list.blockSignals(True)
        self.list.clear()
        selected_row = -1
        for index, (job, kind, status, record) in enumerate(rows):
            self.list.addItem(self._case_text(job, status, record.get("display_number")))
            item = self.list.item(index)
            item.setData(Qt.ItemDataRole.UserRole, {"job": dict(job), "kind": kind, "record": dict(record)})
            if kind == "active" or (selected_row < 0 and job.get("case_id") == previous_id):
                selected_row = index
        self._resize_case_list()
        if selected_row < 0 and rows:
            selected_row = 0
        self.list.setCurrentRow(selected_row)
        self.list.setEnabled(True)
        self.list.blockSignals(False)
        if selected_row >= 0:
            self._selected(selected_row)
        else:
            self.selected_job = None

    def refresh(self):
        current = self.state.current
        self._rebuild_case_lists()
        if current:
            self.current_label.setText(f"Current case: {current['job'].get('case_ref', 'N/A')} — {current.get('phase', 'active')}")
        else:
            self.current_label.setText("Current case: None")

        selected = self._selected_case_record()
        selected_id = (selected or {}).get("case_id") or (selected or {}).get("job", {}).get("case_id")
        active_id = current.get("job", {}).get("case_id") if current else None
        selected_folder = Path(selected["folder"]).resolve() if selected and selected.get("folder") else None
        claim_context = getattr(getattr(self.window, "_claim", None), "_scan_context", None)
        claim_folder = Path(getattr(claim_context, "claim_folder_path", "")).resolve() if claim_context else None
        workspace_ready = bool(
            selected and selected.get("local_status") in ("workspace ready", "needs final resolution", "automation active")
            and selected_folder == claim_folder and not selected.get("local_copy_deleted")
            and (not current or selected_id == active_id)
        )
        self.start_button.setEnabled(
            workspace_ready and not self.state_error and not self.state_recovery_blocked
            and bool(self.client) and not self.busy
            and not self.window._worker and not self.window._scan_thread
            and not (current and current.get("pending_report"))
        )
        self.stop_button.setEnabled(
            bool(current) and not self.busy and not (current and current.get("pending_report"))
        )
        selected_kind = self._selected_kind()
        self.mark_completed_button.setEnabled(selected_kind in ("active", "resolved") and not self.busy)
        selected_entry = selected
        self.delete_local_button.setEnabled(bool(selected_entry and selected_entry.get("folder")) and not self.busy)
        self.restage_button.setEnabled(bool(
            selected_entry and selected_id not in self.staging_ids
            and (not current or selected_id != active_id)
            and selected_entry.get("local_status") in ("discovered", "stage failed", "local copy deleted", "claimed elsewhere")
        ))
        if hasattr(self, "view_images_button"):
            self.view_images_button.setEnabled(bool(selected_entry or self.list.currentItem()) and not self.busy)
        self.connect_button.setEnabled(not self.busy)

        # Update connected state UI toggle
        is_connected = bool(self.client)
        if hasattr(self, "conn_connected_box"):
            self.conn_connected_box.setVisible(is_connected)
            self.conn_form_box.setVisible(not is_connected)
            if is_connected and hasattr(self.client, "email"):
                self.conn_operator_email.setText(f"Operator: {self.client.email}")

        # Update badge
        count = len(self.jobs)
        if hasattr(self, "queue_badge"):
            self.queue_badge.setText(f"{count} {'Incoming Case' if count == 1 else 'Incoming Cases'}")
            if count > 0:
                self.queue_badge.setStyleSheet(
                    "background-color: #D1FAE5; color: #047857; border: 1px solid #6EE7B7; "
                    "border-radius: 4px; font-size: 8pt; font-weight: 800; padding: 3px 8px;"
                )
            else:
                self.queue_badge.setStyleSheet(
                    "background-color: #F1F5F9; color: #64748B; border: 1px solid #CBD5E1; "
                    "border-radius: 4px; font-size: 8pt; font-weight: 800; padding: 3px 8px;"
                )

        # Update fallback labels
        self.stat_queued.setText(str(count))
        if current:
            self.stat_active.setText(current["job"].get("case_ref", "None"))
            self.stat_phase.setText(current.get("phase", "ACTIVE").upper())
        else:
            self.stat_active.setText("None")
            self.stat_phase.setText("IDLE")

        # Empty state handling
        if hasattr(self, "empty_label"):
            self.empty_label.setVisible(self.list.count() == 0)

        # Update rail step states
        if hasattr(self, "rail"):
            if self.state_error:
                self.rail.set_stage_state(0, "failed")
            elif current:
                self.rail.set_stage_state(0, "active")
            elif workspace_ready:
                self.rail.set_stage_state(0, "done")
            else:
                self.rail.set_stage_state(0, "pending")

            if is_connected:
                self.rail.set_stage_state(1, "done")
            else:
                self.rail.set_stage_state(1, "warning")

            has_error = any(entry.get("level") == "Error" for entry in self._live_log_entries[-5:])
            if has_error:
                self.rail.set_stage_state(2, "failed")
            elif self.staging_ids or (current and getattr(self.window, "_worker", None)):
                self.rail.set_stage_state(2, "active")
            else:
                self.rail.set_stage_state(2, "pending")

    def _auto_pickup_idle(self):
        return bool(
            not self.closing and self.client and not self.state_error
            and len(self.staging_ids) < 2
        )

    def _download_progress(self, case_id, event):
        """Show one detailed, case-specific row for each download event."""
        if not isinstance(event, dict):
            return
        kind = event.get("kind", "progress")
        message = str(event.get("message") or "Download progress")
        metadata = []
        if event.get("original_name"):
            metadata.append(f"Original: {event['original_name']}")
        if event.get("local_name"):
            metadata.append(f"Local: {event['local_name']}")
        if event.get("doc_type"):
            metadata.append(f"Type: {event['doc_type']}")
        if event.get("file_id"):
            metadata.append(f"File ID: {event['file_id']}")
        if metadata:
            message = f"{message} | {' | '.join(metadata)}"
        level = "Error" if kind == "file_error" else ("Warning" if kind == "warning" else ("Success" if kind in ("file_complete", "complete") else "Info"))
        self.append_log(message, phase="Download", level=level, case_id=case_id)

    def _maybe_auto_pickup(self):
        if not self.client or not self._auto_pickup_idle():
            return
        for job in self.jobs:
            if len(self.staging_ids) >= 2:
                break
            case_id = job.get("case_id")
            if self._job_validation_errors(job):
                continue
            record = self._record(case_id)
            if record and record.get("deleted_by_operator"):
                continue
            if record and record.get("state_recovery_error"):
                continue
            # A failed staging attempt needs an operator decision.  Retrying it on
            # every queue refresh creates a tight request loop and hides the real
            # Base44/Drive error behind a permanent "Downloading" state.
            if record and record.get("local_status") in ("stage failed", "stale/replaced"):
                continue
            if record and self._valid_stage(record) and record.get("local_status") in (
                "ready", "workspace ready", "automation active", "needs final resolution",
            ):
                continue
            if case_id not in self.staging_ids:
                self._stage_case(job, automatic=True)

    def _stage_case(self, job, automatic=False, force=False):
        if self.closing or not self.client or not self.case_repo:
            return
        case_id = job.get("case_id")
        dispatch_id = _dispatch_id(job)
        if not case_id or case_id in self.staging_ids:
            return
        job_errors = self._job_validation_errors(job)
        if job_errors:
            message = "Missing Base44 fields: " + ", ".join(job_errors)
            self.case_repo.upsert(
                case_id, job=job, local_status="needs attention", phase="needs attention",
                base44_status=job.get("status", "queued_for_automation"), last_error=message,
            )
            self.result.setText(f"Needs Attention: {message}. The case remains queued and was not claimed.")
            self.append_log(
                f"Staging blocked: {message}. The case remains visible and Base44 was not claimed.",
                phase="Stage", level="Error", case_id=case_id,
            )
            self.refresh()
            return
        if not dispatch_id:
            self.result.setText("Needs Attention: Base44 did not supply automation_dispatch_id. The case was not downloaded or claimed.")
            self.append_log(
                "Staging blocked because automation_dispatch_id is missing. Base44 was not claimed.",
                phase="Stage", level="Error", case_id=case_id,
            )
            return
        existing = self._record(case_id)
        if existing and existing.get("deleted_by_operator") and automatic and not force:
            return
        if existing and self._valid_stage(existing) and not force:
            return
        try:
            portal = portal_for(job.get("insurer"))
        except ValueError as exc:
            folder = self.cases_root / "Needs Attention" / readable_case_folder(job)
            self.case_repo.upsert(
                case_id, job=job, portal=None, folder=str(folder),
                local_status="stage failed", phase="stage failed",
                base44_status=job.get("status", "queued_for_automation"),
                automation_dispatch_id=dispatch_id,
                automation_dispatched_at=job.get("automation_dispatched_at", ""),
                deleted_by_operator=False, last_error=str(exc),
            )
            msg = f"Stage Failed for {job.get('case_ref', case_id)}: {exc}"
            self.result.setText(msg)
            self.append_log(
                f"{msg}. Files were not downloaded and the Base44 case was not claimed.",
                phase="Stage", level="Error", case_id=case_id,
            )
            self.refresh()
            return
        insurer_folder = {"uiic": "UIIC", "newindia": "New India", "oic": "OIC"}[portal]
        folder = self.cases_root / insurer_folder / readable_case_folder(job)
        self.case_repo.upsert(
            case_id, job=job, portal=portal,
            folder=str(folder), local_status="staging", phase="staging",
            base44_status=job.get("status", "queued_for_automation"),
            automation_dispatch_id=dispatch_id,
            automation_dispatched_at=job.get("automation_dispatched_at", ""),
            deleted_by_operator=False, last_error="",
        )
        self.staging_ids.add(case_id)
        self.staging_dispatches[case_id] = dispatch_id
        stage_source = "Auto-staging" if automatic else ("Restaging" if force else "Staging")
        self.append_log(
            f"{stage_source} started for {job.get('case_ref', case_id)} "
            f"(case ID: {case_id}; Drive -> {folder}). No Base44 claim has been made.",
            phase="Stage", level="Info", case_id=case_id,
        )
        self.result.setText(
            f"{stage_source} {job.get('case_ref', case_id)}. No Base44 case was claimed."
        )
        self.refresh()

        stage_client = self.client

        def stage():
            partial_id = hashlib.sha256(
                f"{case_id}:{dispatch_id}".encode("utf-8")
            ).hexdigest()[:16]
            temporary = folder.parent / f"{folder.name}.staging.{partial_id}"
            temporary.mkdir(parents=True, exist_ok=True)
            if folder.is_dir():
                for existing_file in folder.iterdir():
                    resume_file = temporary / existing_file.name
                    if existing_file.is_file() and not resume_file.exists():
                        shutil.copy2(existing_file, resume_file)
            try:
                latest_excel = download_case(
                    stage_client, case_id, temporary,
                    progress=lambda event: self.download_progress.emit(case_id, event),
                    automation_dispatch_id=dispatch_id,
                )
                current_record = self._record(case_id)
                if _dispatch_id(current_record) != dispatch_id:
                    raise RuntimeError("This download belongs to a replaced Base44 dispatch")
                old_log = folder / "case_activity.log"
                old_log_content = old_log.read_text(encoding="utf-8") if old_log.exists() else ""
                if folder.exists():
                    shutil.rmtree(folder)
                temporary.replace(folder)
                if old_log_content:
                    (folder / "case_activity.log").write_text(old_log_content, encoding="utf-8")
                return {
                    "folder": str(folder),
                    "latest_excel": latest_excel,
                    "automation_dispatch_id": dispatch_id,
                }
            except Exception as exc:
                current_record = self._record(case_id)
                if _is_stale_dispatch_error(exc) or _dispatch_id(current_record) != dispatch_id:
                    shutil.rmtree(temporary, ignore_errors=True)
                raise

        future = self.stage_pool.submit(stage)

        def finished(done):
            try:
                value, error = done.result(), None
            except Exception as exc:
                value, error = None, exc
            if not self.closing:
                self.staging_completed.emit(case_id, value, error)

        future.add_done_callback(finished)

    def _stage_failure_messages(self, record, error):
        """Build an operator-readable staging diagnosis without changing cloud state."""
        job = record.get("job", {})
        case_id = job.get("case_id") or record.get("case_id") or "Unknown"
        case_ref = job.get("case_ref") or case_id
        vehicle_no = job.get("vehicle_no") or "Not supplied"
        base44_status = job.get("status") or record.get("base44_status") or "Unknown"
        drive_folder_id = str(job.get("drive_folder_id") or "").strip()
        drive_folder_link = str(job.get("drive_folder_link") or "").strip()
        is_manifest_404 = isinstance(error, ApiError) and error.status == 404

        summary = (
            f"Stage Failed — {case_ref}: {error}. "
            "The case was not claimed and automatic staging will not retry it until you click Restage."
        )
        details = [
            (
                f"Stage failed | Case ref: {case_ref} | Vehicle: {vehicle_no} | "
                f"Case ID: {case_id} | Base44 status: {base44_status} | API error: {error}"
            )
        ]
        if is_manifest_404:
            if not drive_folder_id and not drive_folder_link:
                details.append(
                    "Cause: Base44 returned HTTP 404 for getAutomationCaseFiles, and this queued "
                    "case has no Drive folder ID and no Drive folder link. App-3 therefore has no "
                    "file manifest to download."
                )
            else:
                folder_text = drive_folder_id or "missing"
                link_text = drive_folder_link or "missing"
                details.append(
                    f"Cause: Base44 returned HTTP 404 for getAutomationCaseFiles. "
                    f"Drive folder ID: {folder_text} | Drive folder link: {link_text}. "
                    "The case file manifest is missing or not available to this operator."
                )
            details.append(
                "Operator action: In DocWriter, confirm the case has a Drive folder and downloadable "
                "files, then return to App-3 and click Restage."
            )
        else:
            details.append(
                "Operator action: Correct the Base44, Drive, or network problem shown above, then "
                "click Restage."
            )
        details.append(
            f"Safety: claimAutomationCase was not called. Base44 remains {base44_status}. "
            "Other queued cases may continue staging."
        )
        return summary, details

    def _staging_completed(self, case_id, value, error):
        self.staging_ids.discard(case_id)
        staged_dispatch_id = self.staging_dispatches.pop(case_id, "")
        record = self._record(case_id)
        if not record:
            return
        if staged_dispatch_id and _dispatch_id(record) != staged_dispatch_id:
            self.append_log(
                "Ignored completion from an older dispatch because Base44 has already replaced it.",
                phase="Stage", level="Warning", case_id=case_id,
            )
            self.refresh()
            QTimer.singleShot(0, self._maybe_auto_pickup)
            return
        if record.get("deleted_by_operator"):
            if value and value.get("folder"):
                try:
                    self._delete_local_folder({**record, "folder": value["folder"]})
                except (OSError, ValueError):
                    pass
            self.refresh()
            return
        if _is_stale_dispatch_error(error):
            message = "This staged send was replaced by a newer Base44 dispatch. Waiting for the next incoming-case refresh."
            self.case_repo.upsert(
                case_id, local_status="stale/replaced", phase="stale/replaced",
                last_error=str(error),
            )
            self.result.setText(f"Needs Attention: {message}")
            self.append_log(
                f"Staging stopped: {message} No Base44 claim was made.",
                phase="Stage", level="Warning", case_id=case_id,
            )
        elif error:
            summary, details = self._stage_failure_messages(record, error)
            self.case_repo.upsert(
                case_id, local_status="stage failed", phase="stage failed",
                last_error=str(error),
            )
            self.result.setText(summary)
            for index, message in enumerate(details):
                self.append_log(
                    message,
                    phase="Stage",
                    level="Error" if index < 2 else ("Warning" if message.startswith("Operator action") else "Info"),
                    case_id=case_id,
                )
        else:
            self.case_repo.upsert(
                case_id, **value, local_status="ready", phase="ready",
                staged_at=datetime.now(timezone.utc).isoformat(), last_error="",
            )
            msg = f"{record['job'].get('case_ref', case_id)} downloaded locally and is Ready. Base44 remains queued."
            self.result.setText(msg)
            self.append_log(
                f"{msg} Local folder: {value.get('folder', record.get('folder', 'Unknown'))}",
                phase="Stage", level="Success", case_id=case_id,
            )
        self.refresh()
        QTimer.singleShot(0, self._maybe_auto_pickup)

    def run_task(self, operation, function):
        if self.busy or self.closing:
            return
        self.busy = True
        self.refresh()
        future = self.pool.submit(function)

        def finished(f):
            try:
                value, error = f.result(), None
            except Exception as exc:
                value, error = None, exc
            if not self.closing:
                self.completed.emit(operation, value, error)

        future.add_done_callback(finished)

    def connect_client(self):
        if self.busy or self.closing:
            return
        if self.staging_ids:
            self.result.setText("Wait for local case staging to finish before changing the DocWriter login.")
            return
        if not self.email.text().strip() or not self.password.text():
            self.result.setText("Enter operator email and password.")
            return
        previous_client = self.client
        self.client = Client(self.email.text().strip(), self.password.text())
        if previous_client:
            previous_client.close()
        self.password.clear()
        self._login_and_load()

    def _login_and_load(self):
        client = self.client
        self.connection.setText("Connecting to DocWriter…")
        def login():
            client.login()
            self.operator_store.save(client.email, client.password)
            return client.jobs()
        self.run_task("login", login)

    def restore_login(self):
        if self.client or self.busy or self.closing or self.state_error:
            return
        try:
            saved = self.operator_store.get()
            if saved:
                self.email.setText(saved["email"])
                self.client = Client(saved["email"], saved["password"])
                self._login_and_load()
        except Exception:
            self.connection.setText("Disconnected")
            self.result.setText("Unable to read saved DocWriter login. Use Settings → Change Login or Forget Login.")
            if hasattr(self, "conn_connected_box"):
                self.conn_connected_box.setVisible(False)
                self.conn_form_box.setVisible(True)

    def change_login(self):
        if self.busy or self.staging_ids:
            self.result.setText("Wait for the current Web Queue request or local staging to finish before changing login.")
            return
        if hasattr(self.window, "_switch_page"):
            self.window._switch_page(2)
        self.set_stage(1)
        if hasattr(self, "conn_connected_box"):
            self.conn_connected_box.setVisible(False)
            self.conn_form_box.setVisible(True)
        self.password.clear()
        self.password.setFocus()
        self.result.setText("Enter the DocWriter operator email/password and click Connect. A successful login replaces the saved login.")

    def forget_login(self):
        if self.busy or self.staging_ids:
            self.result.setText("Wait for the current Web Queue request or local staging to finish before forgetting login.")
            return
        try:
            self.operator_store.forget()
        except OSError:
            self.result.setText("Unable to remove saved DocWriter login. Check local storage permissions.")
            return
        if self.client:
            self.client.close()
        self.client = None
        self.email.clear()
        self.password.clear()
        self.jobs = []
        self.list.clear()
        self.connection.setText("Disconnected")
        self.result.setText("DocWriter login forgotten. Current case and surveyor credentials are retained.")
        self.refresh()

    def poll(self):
        if self.client and not self.busy and not self.state_error:
            current = self.state.current
            if current and current.get("pending_report"):
                payload = dict(current["pending_report"])
                self.run_task("report", lambda: self.client.report(payload))
            else:
                self.run_task("poll", self.client.jobs)
        self.refresh()

    def _reconcile_jobs(self):
        incoming = {job["case_id"]: job for job in self.jobs}
        active_id = self.state.current["job"]["case_id"] if self.state.current else None
        for case_id, job in incoming.items():
            record = self._record(case_id)
            if not record:
                continue
            incoming_dispatch = _dispatch_id(job)
            local_dispatch = _dispatch_id(record)
            changes = {
                "job": job,
                "base44_status": job.get("status", "queued_for_automation"),
                "automation_dispatch_id": incoming_dispatch,
                "automation_dispatched_at": job.get("automation_dispatched_at", ""),
            }
            validation_errors = self._job_validation_errors(job)
            if validation_errors and case_id != active_id:
                changes.update(
                    local_status="needs attention",
                    phase="needs attention",
                    last_error="Missing Base44 fields: " + ", ".join(validation_errors),
                )
                self.case_repo.upsert(case_id, **changes)
                continue
            if not local_dispatch:
                # Migration for valid pre-dispatch records: bind the existing
                # local copy/deletion marker to the currently queued dispatch.
                if record.get("deleted_by_operator"):
                    changes["deleted_dispatch_id"] = incoming_dispatch
            elif local_dispatch != incoming_dispatch:
                if case_id == active_id:
                    self.append_log(
                        "Base44 returned a newer dispatch for the active unresolved case. "
                        "The current Workspace remains locked to its original dispatch.",
                        phase="Sync", level="Warning", case_id=case_id,
                    )
                    continue
                changes.update(
                    display_number=self._next_display_number(),
                    deleted_by_operator=False,
                    deleted_dispatch_id="",
                    local_copy_deleted=False,
                    local_status="discovered",
                    phase="discovered",
                    latest_excel="",
                    last_error="",
                    last_message="",
                )
                self.deleted_case_ids.discard(case_id)
                self.append_log(
                    f"New Base44 dispatch received for this case ({incoming_dispatch}). "
                    "It will appear as new incoming work and stage without being claimed.",
                    phase="Sync", level="Info", case_id=case_id,
                )
            if record.get("local_status") == "claimed elsewhere" and self._valid_stage(record):
                changes.update(local_status="ready", phase="ready")
            self.case_repo.upsert(case_id, **changes)
        self._ensure_display_numbers()
        # A prior authorized staging operation interrupted by restart is resumed.
        for record in self._records():
            case_id = record["case_id"]
            if (
                case_id != active_id and record.get("local_status") == "staging"
                and case_id in incoming and case_id not in self.staging_ids
            ):
                self._stage_case(incoming[case_id], force=True)

    def _completed(self, operation, value, error):
        self.busy = False
        if error:
            if operation.startswith("claim:"):
                case_id = operation.split(":", 1)[1]
                if _is_stale_dispatch_error(error):
                    self.case_repo.upsert(
                        case_id, local_status="stale/replaced", phase="stale/replaced",
                        last_error=str(error),
                    )
                    self.result.setText("This case was resent/replaced. Refresh the incoming cases. No insurer browser was started.")
                elif isinstance(error, ApiError) and error.status == 409:
                    self.case_repo.upsert(
                        case_id, local_status="claimed elsewhere", phase="claimed elsewhere",
                        base44_status="automation_in_progress", last_error=str(error),
                    )
                    self.result.setText("Claimed Elsewhere: another App-3 computer started this case. No insurer browser was started.")
                else:
                    self.case_repo.upsert(
                        case_id, local_status="workspace ready", phase="workspace ready",
                        last_error=str(error),
                    )
                    self.result.setText(f"Needs Attention: Base44 claim failed. Automation was not started: {error}")
                self.refresh()
                return
            if operation == "report" and _is_stale_dispatch_error(error):
                current = self.state.current
                message = (
                    "Base44 rejected this result because the case dispatch was replaced. "
                    "Local portal evidence was preserved; the Workspace remains locked for attention."
                )
                if current:
                    folder = current.get("folder")
                    if folder and Path(folder).exists():
                        atomic_json(Path(folder) / "Web_Sync_Stale_Result.json", {
                            "case_id": current["job"].get("case_id"),
                            "automation_dispatch_id": _dispatch_id(current),
                            "message": message,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                    self._active_update(
                        pending_report=None,
                        phase="needs final resolution",
                        local_status="needs attention",
                        last_message=message,
                        last_error=str(error),
                    )
                self.connection.setText("Connected to DocWriter")
                self.result.setText(f"Needs Attention: {message}")
                self.refresh()
                return
            self.result.setText(str(error))
            if isinstance(error, ApiError) and error.status == 401:
                self.connection.setText("Disconnected — sign in again")
            elif operation in ("login", "poll", "report"):
                self.connection.setText("Disconnected — retrying every 30 seconds")
            self.refresh()
            return
        self.connection.setText("Connected to DocWriter")
        if operation in ("login", "poll"):
            self.jobs = value
            self._reconcile_jobs()
            if getattr(self.client, "queue_warning", ""):
                self.result.setText(self.client.queue_warning)
        elif operation.startswith("claim:"):
            case_id = operation.split(":", 1)[1]
            record = self._record(case_id)
            original_job = record.get("job", {}) if record else {}
            try:
                identity_matches = bool(
                    record and value.get("case_id") == case_id
                    and _dispatch_id(value) == _dispatch_id(record)
                    and value.get("surveyor_profile_id") == original_job.get("surveyor_profile_id")
                    and portal_for(value.get("insurer")) == portal_for(original_job.get("insurer"))
                )
            except ValueError:
                identity_matches = False
            if not identity_matches:
                if record:
                    self.case_repo.upsert(case_id, local_status="needs attention", last_error="Claimed job identity changed")
                self.result.setText("Needs Attention: claimed case no longer matches the selected local case. Automation was not started.")
            else:
                claimed_job = {**original_job, **value}
                active = {
                    **record, "job": claimed_job, "portal": portal_for(value.get("insurer")),
                    "phase": "automation active", "local_status": "automation active",
                    "base44_status": "automation_in_progress",
                    "claimed_at": datetime.now(timezone.utc).isoformat(),
                }
                self.state.set(active)
                self.case_repo.set(active)
                self.result.setText("Case claimed by this App-3. Starting insurer automation.")
                self.window._start_automation()
        elif operation == "report":
            current = self.state.current
            if current.get("folder") and Path(current["folder"]).exists():
                atomic_json(Path(current["folder"]) / "Web_Sync_Report_Acknowledgement.json", value)
            reported_status = current["pending_report"]["status"]
            if reported_status == "success" and value["status"] == "uploaded":
                self.case_repo.upsert(
                    current["job"]["case_id"], local_status="submitted successfully",
                    phase="submitted successfully", base44_status="uploaded",
                    pending_report=None,
                )
                self.completed_store.upsert(self._history_entry(
                    current, section="workspace", base44_status="uploaded",
                    display_result="Submitted Successfully", unresolved=False,
                ))
            elif current.get("locally_completed"):
                self.case_repo.upsert(
                    current["job"]["case_id"], local_status="completed", phase="completed",
                    base44_status=value["status"], pending_report=None,
                )
                self.completed_store.upsert(self._history_entry(
                    current, section="completed", base44_status=value["status"],
                    display_result="Failed / Needs Attention", unresolved=False,
                ))
            else:
                self.case_repo.upsert(
                    current["job"]["case_id"], local_status="needs attention",
                    phase="needs attention", base44_status=value["status"],
                    pending_report=None,
                )
            self.state.set(None)
            self.result.set_report_result(
                f"Base44 acknowledged: {value['status']}. Stop/close the previous browser before starting another case.",
                reported_status, value["status"],
            )
        self.refresh()
        if operation in ("login", "poll") and not error:
            QTimer.singleShot(0, self._maybe_auto_pickup)

    def _selected(self, row):
        if 0 <= row < self.list.count():
            metadata = self.list.item(row).data(Qt.ItemDataRole.UserRole) or {}
            job = metadata.get("job", {})
        elif 0 <= row < len(self.jobs):
            # Compatibility for callers that update jobs before the next UI refresh.
            metadata = {"job": self.jobs[row], "kind": "queued"}
            job = self.jobs[row]
        else:
            return
        if job:
            active = self.state.current
            active_id = active.get("job", {}).get("case_id") if active else None
            if active_id and job.get("case_id") != active_id:
                for index in range(self.list.count()):
                    other = self.list.item(index).data(Qt.ItemDataRole.UserRole) or {}
                    if other.get("job", {}).get("case_id") == active_id:
                        self.list.blockSignals(True)
                        self.list.setCurrentRow(index)
                        self.list.blockSignals(False)
                        break
                self.result.setText("Workspace is locked to the active unresolved case. Other Ready cases remain staged.")
                return
            self.selected_job = dict(job)
            changed_case = job.get("case_id") != self._credential_case_id
            profile_id = job.get("surveyor_profile_id", "")
            self.profile.setText(profile_id)
            if hasattr(self, "surveyor_name_label"):
                self.surveyor_name_label.setText(f"Surveyor: {profile_id or 'Unassigned'}")
            if hasattr(self, "surveyor_profile_sub"):
                self.surveyor_profile_sub.setText(f"Profile ID: {profile_id}" if profile_id else "Profile ID: None")

            if changed_case:
                self._credential_case_id = job.get("case_id")
                self.username.clear()
                self.secret.clear()
                self.code.clear()
                self.cred_feedback.clear()

            try:
                portal = portal_for(job.get("insurer"))
                self.insurer.setCurrentIndex(self.insurer.findData(portal))
            except ValueError as exc:
                self.insurer.setCurrentIndex(-1)
                self.result.setText(str(exc))
                return
            try:
                self.store.get(profile_id, portal)
                self.username.setPlaceholderText("Username (saved)")
                self.secret.setPlaceholderText("•••••••• (saved)")
                self.code.setPlaceholderText("Code (saved)")
                self.cred_feedback.setText("Saved credentials available")
                self.cred_feedback.setStyleSheet(
                    "background-color: #DCFCE7; color: #166534; border: 1px solid #86EFAC; "
                    "border-radius: 4px; font-weight: 700; font-size: 8.5pt; padding: 4px 10px;"
                )
                if hasattr(self, "save_btn"):
                    self.save_btn.setText("💾 Update Credentials")
            except ValueError:
                self.username.setPlaceholderText("Portal login username")
                self.secret.setPlaceholderText("Portal login password")
                self.code.setPlaceholderText("e.g. SC-101 (optional)")
                self.cred_feedback.setText("Save credentials for this surveyor and insurer before starting.")
                self.cred_feedback.setStyleSheet(
                    "background-color: #FEF3C7; color: #92400E; border: 1px solid #FCD34D; "
                    "border-radius: 4px; font-weight: 700; font-size: 8.5pt; padding: 4px 10px;"
                )
                if hasattr(self, "save_btn"):
                    self.save_btn.setText("💾 Save Credentials")
            except Exception:
                self.cred_feedback.setText("Unable to read saved credentials. Check local credential storage.")
                self.cred_feedback.setStyleSheet(
                    "background-color: #FEE2E2; color: #991B1B; border: 1px solid #FCA5A5; "
                    "border-radius: 4px; font-weight: 700; font-size: 8.5pt; padding: 4px 10px;"
                )

    def _selected_kind(self):
        item = self.list.currentItem()
        metadata = item.data(Qt.ItemDataRole.UserRole) if item else None
        return metadata.get("kind") if isinstance(metadata, dict) else None

    def _selected_case_record(self):
        item = self.list.currentItem()
        metadata = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(metadata, dict):
            return None
        if metadata.get("kind") == "active":
            return self.state.current
        return metadata.get("record") or metadata.get("job")

    def _case_clicked(self, item):
        if item is None:
            return
        metadata = item.data(Qt.ItemDataRole.UserRole) or {}
        job = metadata.get("job", {})
        record = metadata.get("record", {})
        active = self.state.current
        active_id = active.get("job", {}).get("case_id") if active else None
        if active_id and job.get("case_id") != active_id:
            if record.get("local_status", "discovered") == "discovered":
                self._stage_case(job)
                return
            if record.get("deleted_by_operator") or record.get("local_status") == "local copy deleted":
                self.result.setText("Restage Required: this case was deleted locally. Click Restage to download it again.")
                self.refresh()
                return
            self.result.setText("Workspace is locked to the active unresolved case. Downloading other cases may continue.")
            self.refresh()
            return
        status = record.get("local_status", "discovered")
        if status == "discovered":
            self._stage_case(job)
            return
        if record.get("deleted_by_operator") or status == "local copy deleted":
            self.result.setText("Restage Required: this case was deleted locally. Click Restage to download it again.")
            self.refresh()
            return
        if status not in ("ready", "workspace ready", "automation active", "needs final resolution") or not self._valid_stage(record):
            return
        if self.window._worker or self.window._scan_thread:
            self.result.setText("Finish the current Workspace operation before opening another staged case.")
            return
        try:
            portal = portal_for(job.get("insurer"))
        except ValueError as exc:
            self.case_repo.upsert(job["case_id"], local_status="needs attention", last_error=str(exc))
            self.result.setText(f"Needs Attention: {exc}")
            self.refresh()
            return
        self.case_repo.upsert(job["case_id"], portal=portal, local_status="scanning", phase="scanning")
        prepared = self._record(job["case_id"])
        self.append_log(
            f"Opening local case in Workspace for review. Folder: {prepared.get('folder', 'Unknown')}",
            phase="Workspace", level="Info", case_id=job["case_id"],
        )
        self.window._open_web_case(prepared)
        self.result.setText("Scanning the selected local case. Base44 has not been claimed.")

    def restage_selected(self):
        record = self._selected_case_record()
        if not record:
            return
        job = record.get("job", self.selected_job or {})
        active = self.state.current
        if active and active["job"]["case_id"] == job.get("case_id"):
            return
        case_id = job.get("case_id")
        if not case_id:
            return
        self.deleted_case_ids.discard(case_id)
        self.case_repo.upsert(
            case_id,
            deleted_by_operator=False,
            local_copy_deleted=False,
            local_status="restage requested",
            phase="restage requested",
        )
        self._stage_case(job, force=True)

    def _portal_result(self, folder):
        if not folder:
            return {}
        path = Path(folder) / "Portal_Submission_Result.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _history_entry(self, current, **changes):
        job = current.get("job", current)
        folder = current.get("folder", job.get("folder", ""))
        portal_result = self._portal_result(folder)
        message = (
            changes.pop("result", None) or portal_result.get("portal_message")
            or (current.get("pending_report") or {}).get("portal_message")
            or current.get("last_message") or job.get("result", "")
        )
        return {
            "case_id": job.get("case_id", ""),
            "automation_dispatch_id": _dispatch_id(job),
            "automation_dispatched_at": job.get("automation_dispatched_at", ""),
            "display_number": current.get("display_number") or (self._record(job.get("case_id")) or {}).get("display_number"),
            "case_ref": job.get("case_ref", "N/A"),
            "vehicle_no": job.get("vehicle_no", "N/A"),
            "insurer": job.get("insurer", "N/A"),
            "surveyor_profile_id": job.get("surveyor_profile_id", "N/A"),
            "folder": str(folder or ""),
            "completed_at": current.get("completed_at") or datetime.now(timezone.utc).isoformat(),
            "result": message,
            **changes,
        }

    def start_automation(self):
        self._recover_evidence()
        selected = self._selected_case_record()
        if not self.start_button.isEnabled() or not selected:
            return
        case_id = selected.get("case_id") or selected.get("job", {}).get("case_id")
        current = self.state.current
        validation_error = self._stage_validation_error(selected, verify_md5=True)
        if validation_error:
            self.case_repo.upsert(
                case_id, local_status="needs attention", phase="needs attention",
                last_error=validation_error,
            )
            if current and current.get("job", {}).get("case_id") == case_id:
                self._active_update(
                    local_status="needs attention", phase="needs final resolution",
                    last_error=validation_error,
                )
            self.result.setText(f"Needs Attention: staged case validation failed: {validation_error}")
            self.append_log(
                f"Start Automation blocked before insurer launch: {validation_error}",
                phase="Automation", level="Error", case_id=case_id,
            )
            self.refresh()
            return
        if current:
            if current["job"]["case_id"] == case_id:
                self.window._start_automation()
                self.refresh()
            return
        job = selected.get("job", self.selected_job or {})
        try:
            portal = portal_for(job.get("insurer"))
            self.store.get(job.get("surveyor_profile_id", ""), portal)
        except Exception as exc:
            self.result.setText(f"Needs Attention: {exc}. Base44 was not claimed.")
            self.append_log(
                f"Start Automation blocked: {exc}. Base44 was not claimed.",
                phase="Automation", level="Error", case_id=case_id,
            )
            return
        self.result.setText("Claiming the selected case before insurer automation starts…")
        self.append_log(
            "Operator clicked Start Automation. Claiming this case in Base44 before opening the insurer automation.",
            phase="Automation", level="Info", case_id=case_id,
        )
        dispatch_id = _dispatch_id(job)
        if not dispatch_id:
            self.result.setText("Needs Attention: this case has no automation_dispatch_id. Base44 was not claimed.")
            return
        self.run_task(
            f"claim:{case_id}",
            lambda: self.client.claim(case_id, dispatch_id),
        )

    def start_automation_for_folder(self, folder):
        target = Path(folder).resolve()
        current = self.state.current
        if current and Path(current.get("folder", "")).resolve() != target:
            self.result.setText(
                "Workspace is locked to the active unresolved case. "
                "Stop/fail it or complete insurer submission before starting another case."
            )
            return False
        for index in range(self.list.count()):
            metadata = self.list.item(index).data(Qt.ItemDataRole.UserRole) or {}
            record = metadata.get("record") or {}
            if record.get("folder") and Path(record["folder"]).resolve() == target:
                self.list.setCurrentRow(index)
                self.start_automation()
                return True
        self.result.setText("Needs Attention: this Web Sync folder has no staged case state.")
        return False

    def stop_or_fail_case(self):
        if self._pending_start_case_id:
            self._pending_start_case_id = None
        if self.window._worker:
            self.window._stop_automation()
            self.result.setText("Stopping automation safely. The Base44 case remains in progress until you deliberately fail it or submission succeeds.")
            self.refresh()
            return
        self.fail_case()

    def workspace_scan_completed(self, folder, success, message=""):
        record = next((item for item in self._records() if item.get("folder") and Path(item["folder"]).resolve() == Path(folder).resolve()), None)
        if not record:
            return
        current = self.state.current
        if current and current["job"]["case_id"] != record["case_id"]:
            return
        if success:
            self.case_repo.upsert(record["case_id"], local_status="workspace ready", phase="workspace ready")
            if current:
                self._active_update(local_status="workspace ready", phase="workspace ready")
            self.result.setText("Workspace is ready. Review the case, then click Start Automation. Final Submit remains manual.")
            self.append_log(
                "Folder scan completed successfully. Workspace is ready for operator review; Start Automation remains manual.",
                phase="Workspace", level="Success", case_id=record["case_id"],
            )
        else:
            self.case_repo.upsert(
                record["case_id"], local_status="needs attention", phase="needs final resolution",
                last_message=message or "Folder scan failed",
            )
            if current:
                self._active_update(phase="needs final resolution", local_status="needs attention", last_message=message or "Folder scan failed")
            self.result.setText(f"Needs Attention: {message or 'Folder scan failed'}")
            self.append_log(
                f"Folder scan needs attention: {message or 'Folder scan failed'}",
                phase="Workspace", level="Error", case_id=record["case_id"],
            )
        self.refresh()
        if self._pending_start_case_id == record["case_id"]:
            self._pending_start_case_id = None
            if success:
                self.start_automation()

    def workspace_scan_started(self, folder):
        record = next((item for item in self._records() if item.get("folder") and Path(item["folder"]).resolve() == Path(folder).resolve()), None)
        if record:
            self.case_repo.upsert(record["case_id"], local_status="scanning", phase="scanning")
            self.refresh()

    def mark_completed(self):
        selected = self._selected_case_record()
        if not selected or self.busy:
            return
        kind = self._selected_kind()
        case_id = (selected.get("job", selected)).get("case_id")
        if kind == "active":
            current = self.state.current
            portal_result = self._portal_result(current.get("folder"))
            confirmed = bool(portal_result.get("confirmed_success"))
            if not confirmed:
                answer = QMessageBox.question(
                    self, "Mark Completed Locally",
                    "Final insurer submission has not been confirmed. Mark locally completed anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            entry = self._history_entry(
                current, section="completed", unresolved=not confirmed,
                display_result=("Submitted Successfully" if confirmed else "Completed Locally — Base44 Unresolved"),
            )
            self.completed_store.upsert(entry)
            if not confirmed:
                self._active_update(
                    locally_completed=True, phase="needs final resolution", local_status="needs final resolution",
                    last_message=entry.get("result") or "Needs Final Resolution",
                )
                self.result.setText("Needs Final Resolution: completed locally, but Base44 is unresolved. The Workspace remains locked.")
            else:
                if current.get("job", {}).get("case_id"):
                    self.case_repo.upsert(current["job"]["case_id"], local_status="completed", phase="completed")
                self.state.set(None)
                self.result.setText("Case completion and portal evidence saved locally.")
        elif kind == "resolved":
            entry = self._history_entry(selected, section="completed", unresolved=False)
            self.completed_store.upsert(entry)
            if entry.get("case_id") and self._record(entry["case_id"]):
                self.case_repo.upsert(entry["case_id"], local_status="completed", phase="completed")
            self.result.setText("Case completion saved locally. Base44 and Drive were not changed.")
        else:
            entry = self._history_entry(selected, section="completed", unresolved=False, display_result="Completed Locally")
            self.completed_store.upsert(entry)
            if case_id:
                self.case_repo.upsert(case_id, local_status="completed", phase="completed")
            self.result.setText("Case completion saved locally.")

        if case_id:
            self.jobs = [j for j in self.jobs if j.get("case_id") != case_id]
        self.refresh()

    def _confirm_delete_local(self):
        return QMessageBox.question(
            self, "Delete Case",
            "Delete this case and remove its local files from disk?\n\nCloud/Drive files will not be affected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes

    def _delete_local_folder(self, record):
        folder_text = record.get("folder", "")
        if not folder_text:
            return False
        folder = Path(folder_text).resolve()
        allowed_roots = {self.cases_root.resolve(), (self.root / "cases").resolve()}
        if not any(folder != allowed and allowed in folder.parents for allowed in allowed_roots):
            raise ValueError("Local case folder is outside the App-3 Web Sync cases folder")
        current = self.state.current
        if current and current.get("folder") and Path(current["folder"]).resolve() == folder:
            if self.window._worker or self.window._scan_thread:
                raise ValueError("Stop the current automation and scan before deleting its local copy")
        if folder.exists():
            shutil.rmtree(folder)
        for partial in folder.parent.glob(f"{folder.name}.staging.*"):
            if partial.is_dir():
                shutil.rmtree(partial)
        return True

    def delete_current_local_copy(self, record=None):
        record = record or self._selected_case_record()
        if not record:
            return
        case_id = (record.get("job", record)).get("case_id")
        current = self.state.current
        active_id = current.get("job", {}).get("case_id") if current else None
        if active_id and active_id == case_id:
            self.result.setText(
                "Delete Case is disabled for the active unresolved case. "
                "Submit it successfully or deliberately Stop/Fail it first."
            )
            return
        try:
            self._delete_local_folder(record)
            deleted_dispatch_id = _dispatch_id(record)
            for entry in self._history():
                if entry.get("case_id") == case_id:
                    self.completed_store.upsert({**entry, "folder": ""})
            if case_id:
                self.case_repo.upsert(
                    case_id, local_copy_deleted=True, deleted_by_operator=True,
                    deleted_dispatch_id=deleted_dispatch_id,
                    local_status="deleted", phase="deleted",
                )
            if case_id:
                self.deleted_case_ids.add(case_id)
            self.result.setText("Case deleted successfully. Removed from workspace and disk.")
        except (OSError, ValueError) as exc:
            self.result.setText(f"Needs Attention: {exc}")
        self.refresh()

    def open_selected_case_images(self):
        record = self._selected_case_record()
        current_item = self.list.currentItem()
        metadata = current_item.data(Qt.ItemDataRole.UserRole) if current_item else {}
        job = metadata.get("job") if isinstance(metadata, dict) else None
        if not record and not job:
            QMessageBox.information(self, "View Images", "Please select a case from the list first.")
            return

        folder = Path(record.get("folder", "")) if (record and record.get("folder")) else None
        if folder and folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
            return

        drive_url = (job or {}).get("drive_folder_url") or (job or {}).get("folder_url")
        if drive_url:
            QDesktopServices.openUrl(QUrl(str(drive_url)))
            return

        case_ref = (job or record or {}).get("case_ref", "this case")
        reply = QMessageBox.question(
            self,
            "Images Not Downloaded Locally",
            f"Case {case_ref} has not been downloaded to your computer yet.\n\n"
            "Would you like to download and stage its documents and photos now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes and job:
            self._stage_case(job, force=True)

    def open_case_images_by_index(self, index):
        row = index.row() if hasattr(index, "row") else int(index)
        if 0 <= row < self.list.count():
            self.list.setCurrentRow(row)
            self.open_selected_case_images()

    def open_case_folder_by_index(self, index):
        row = index.row() if hasattr(index, "row") else int(index)
        if not 0 <= row < self.list.count():
            return
        metadata = self.list.item(row).data(Qt.ItemDataRole.UserRole) or {}
        record = metadata.get("record") or {}
        folder = Path(record.get("folder", "")) if record and record.get("folder") else None
        if folder and folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        else:
            self.result.setText("Needs Attention: this case has not finished downloading to a local folder.")

    def start_automation_by_index(self, index):
        row = index.row() if hasattr(index, "row") else int(index)
        if not 0 <= row < self.list.count():
            return
        if self.state_recovery_blocked:
            self.result.setText(self.state_recovery_blocked)
            return
        item = self.list.item(row)
        metadata = item.data(Qt.ItemDataRole.UserRole) or {}
        record = metadata.get("record") or {}
        case_id = record.get("case_id") or metadata.get("job", {}).get("case_id")
        status = record.get("local_status")
        current = self.state.current
        active_id = current.get("job", {}).get("case_id") if current else None
        if active_id and active_id != case_id:
            self.result.setText("Workspace is locked to the active unresolved case.")
            return
        if record.get("state_recovery_error"):
            self.case_repo.upsert(
                case_id,
                state_recovery_error="",
                last_error="",
                local_status="restage requested",
                phase="restage requested",
            )
            self.result.setText("Recovering the quarantined local case state and downloading this case again.")
            self._stage_case(metadata.get("job", {}), force=True)
            return
        if status not in ("ready", "workspace ready") or not self._valid_stage(record):
            validation_error = self._stage_validation_error(record, verify_md5=False)
            if validation_error and case_id:
                self.case_repo.upsert(
                    case_id, local_status="needs attention", phase="needs attention",
                    last_error=validation_error,
                )
                self.result.setText(f"Needs Attention: staged case validation failed: {validation_error}")
                self.append_log(
                    f"Start Automation blocked before claim: {validation_error}",
                    phase="Automation", level="Error", case_id=case_id,
                )
                self.refresh()
                return
            self.result.setText("Start Automation is available only when this case is Ready.")
            return
        if self.window._worker or self.window._scan_thread:
            self.result.setText("Finish the current Workspace operation before starting automation.")
            return
        self.list.setCurrentRow(row)
        if status == "workspace ready":
            self.start_automation()
            return
        self._pending_start_case_id = case_id
        self._case_clicked(item)

    def restage_case_by_index(self, index):
        row = index.row() if hasattr(index, "row") else int(index)
        if 0 <= row < self.list.count():
            self.list.setCurrentRow(row)
            self.restage_selected()

    def mark_completed_by_index(self, index):
        row = index.row() if hasattr(index, "row") else int(index)
        if 0 <= row < self.list.count():
            self.list.setCurrentRow(row)
            self.mark_completed()

    def delete_case_by_index(self, index):
        row = index.row() if hasattr(index, "row") else int(index)
        if 0 <= row < self.list.count():
            metadata = self.list.item(row).data(Qt.ItemDataRole.UserRole) or {}
            self.delete_current_local_copy(metadata.get("record") or {})

    def can_delete_case_metadata(self, metadata):
        record = metadata.get("record") if isinstance(metadata, dict) else None
        job = metadata.get("job") if isinstance(metadata, dict) else None
        case_id = (record or {}).get("case_id") or (job or {}).get("case_id")
        current = self.state.current
        active_id = current.get("job", {}).get("case_id") if current else None
        return bool(case_id and case_id != active_id)

    def _selected_completed(self):
        return None

    def open_completed_result(self):
        entry = self._selected_completed()
        if not entry:
            return
        folder = Path(entry.get("folder", "")) if entry.get("folder") else None
        result_file = None
        if folder and folder.exists():
            evidence = self._portal_result(folder)
            screenshot = evidence.get("screenshot")
            candidates = ([folder / screenshot] if screenshot else []) + [folder / "Portal_Submission_Result.json"]
            result_file = next((path for path in candidates if path.exists()), None)
        if result_file:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(result_file)))
        else:
            QMessageBox.information(self, "Portal Result", entry.get("result") or "No saved portal result is available.")

    def delete_completed_local_copy(self):
        entry = self._selected_completed()
        if not entry or not self._confirm_delete_local():
            return
        try:
            self._delete_local_folder(entry)
            current = self.state.current
            unresolved_current = bool(
                entry.get("unresolved") and current
                and current.get("job", {}).get("case_id") == entry.get("case_id")
            )
            if unresolved_current:
                self.completed_store.upsert({**entry, "folder": ""})
                self._active_update(local_copy_deleted=True)
                self.result.setText("Local copy deleted. The unresolved Base44 case still locks the Workspace.")
            else:
                self.completed_store.remove(entry.get("case_id"))
                if entry.get("case_id") and self._record(entry["case_id"]):
                    self.case_repo.remove(entry["case_id"])
                self.result.setText("Local copy and local Completed entry deleted. Base44 and Drive were not changed.")
        except (OSError, ValueError) as exc:
            self.result.setText(f"Needs Attention: {exc}")
        self.refresh()

    def save_credentials(self):
        prof = self.profile.text().strip()
        port = self.insurer.currentData()
        try:
            self.store.save(prof, port, self.username.text(), self.secret.text(), self.code.text())
            if hasattr(self, "cred_feedback"):
                self.cred_feedback.setText(f"✓ Saved for {prof} ({self.insurer.currentText()})")
                self.cred_feedback.setStyleSheet(
                    "background-color: #DCFCE7; color: #166534; border: 1px solid #86EFAC; "
                    "border-radius: 4px; font-weight: 700; font-size: 8.5pt; padding: 4px 10px;"
                )
        except Exception as exc:
            if hasattr(self, "cred_feedback"):
                self.cred_feedback.setText(f"⚠ {exc}")
                self.cred_feedback.setStyleSheet(
                    "background-color: #FEE2E2; color: #991B1B; border: 1px solid #FCA5A5; "
                    "border-radius: 4px; font-weight: 700; font-size: 8.5pt; padding: 4px 10px;"
                )

    def start_case(self, checked=False, auto_pickup=False):
        if self.state_error or not self.client or self.state.current:
            return
        record = self._selected_case_record()
        job = (record or {}).get("job", self.selected_job or {})
        if not job or not job.get("case_id"):
            self.result.setText("Select an incoming case first.")
            return
        if (
            (record or {}).get("deleted_by_operator")
            or (record or {}).get("local_status") in ("deleted", "local copy deleted")
            or job.get("case_id") in self.deleted_case_ids
        ):
            self.result.setText("Restage Required: this case was deleted locally. Click Restage to download it again.")
            return
        self._stage_case(job, automatic=auto_pickup)

    def excel_for(self, folder):
        for record in self._records():
            if record.get("folder") and Path(record["folder"]).resolve() == Path(folder).resolve():
                return record.get("latest_excel")
        return None

    def settings_for(self, folder, portal):
        current = self.state.current
        if not current or Path(current["folder"]).resolve() != Path(folder).resolve():
            if (Path(folder) / "web_sync_manifest.json").exists():
                raise ValueError("This web case is not the current active case. Select it through Web Queue.")
            return {}
        if current.get("pending_report") or portal != current["portal"]:
            raise ValueError("Web case cannot start with this portal or while a result is pending")
        return {
            **self.store.get(current["job"]["surveyor_profile_id"], portal),
            "browser_headless": False,
            "_web_submission": {
                "case_id": current["job"]["case_id"],
                "automation_dispatch_id": _dispatch_id(current),
                "folder": current["folder"],
                "callback": self.submission_received.emit,
            },
        }

    def _submission(self, record):
        current = self.state.current
        if not current or current["job"]["case_id"] != record["case_id"] or current.get("pending_report"):
            return
        self.result.setText(record["portal_message"])
        if record["confirmed_success"]:
            self._active_update(
                phase="report pending", local_status="report pending",
                pending_report={
                    "case_id": record["case_id"],
                    "automation_dispatch_id": _dispatch_id(current),
                    "status": "success",
                    "portal_message": record["portal_message"],
                },
            )
            self.poll()
        else:
            self._active_update(last_message=record["portal_message"], local_status="needs final resolution")
        self.refresh()

    def fail_case(self):
        self._recover_evidence()
        current = self.state.current
        if not current or self.busy or current.get("pending_report"):
            return

        is_stale = bool(
            current.get("phase") == "needs final resolution"
            or _is_stale_dispatch_error(current.get("last_error"))
            or "stale_dispatch" in str(current.get("last_error", ""))
            or "dispatch was replaced" in str(current.get("last_message", ""))
        )
        if is_stale:
            answer = QMessageBox.question(
                self,
                "Release Stale Case & Unlock Workspace",
                "Base44 cloud rejected or replaced this case dispatch.\n\n"
                "Do you want to release this case locally and unlock the workspace?\n\n"
                "(All local files and evidence in the case folder will remain safe on disk.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                case_id = (current.get("job") or {}).get("case_id") or current.get("case_id")
                if case_id:
                    self.case_repo.upsert(
                        case_id,
                        local_status="stale/replaced",
                        phase="stale/replaced",
                        pending_report=None,
                        last_message="Released by operator after cloud dispatch rejection.",
                    )
                record = {
                    "case_id": case_id,
                    "portal_message": "Operator released stale dispatch locally.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "confirmed_success": False,
                    "operator_stopped": True,
                }
                if current.get("folder") and Path(current["folder"]).exists():
                    atomic_json(Path(current["folder"]) / "Portal_Submission_Result_Operator_Stop.json", record)
                self.state.set(None)
                self.result.setText("Case released locally. Workspace unlocked.")
                self.append_log(
                    f"Case {current.get('job', {}).get('case_ref', case_id)} released locally. Workspace unlocked.",
                    phase="Web Queue", level="Info", case_id=case_id,
                )
                self.refresh()
                return

        reason, accepted = QInputDialog.getText(
            self,
            "Deliberately stop / fail case",
            "Reason this case cannot presently be completed:",
            text=current.get("last_message", ""),
        )
        if not accepted or not reason.strip():
            return
        self._recover_evidence()
        if not self.state.current or self.state.current.get("pending_report"):
            return
        self.window._stop_automation()
        record = {
            "case_id": current["job"]["case_id"],
            "portal_message": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "confirmed_success": False,
            "operator_stopped": True,
        }
        if current.get("folder") and Path(current["folder"]).exists():
            atomic_json(Path(current["folder"]) / "Portal_Submission_Result_Operator_Stop.json", record)
        self._active_update(
            phase="report pending", local_status="report pending",
            pending_report={
                "case_id": record["case_id"],
                "automation_dispatch_id": _dispatch_id(current),
                "status": "failed",
                "portal_message": reason,
            },
        )
        self.poll()

    def shutdown(self):
        self.closing = True
        self.timer.stop()
        if self.client:
            self.client.close()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.stage_pool.shutdown(wait=False, cancel_futures=True)


class SimpleStateUnavailable:
    """Read-only placeholder: fail closed for Web Queue, leave manual UI usable."""
    current = None
