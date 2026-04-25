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
    resource_path, save_settings, settings_paths, user_data_dir, ensure_dir,
    load_settings, load_field_mapping, save_field_mapping, reset_field_mapping,
    field_mapping_paths, load_doc_mapping, save_doc_mapping, reset_doc_mapping,
)

CONFIG_DIR = resource_path("app", "config")
_SETTINGS_PATHS = settings_paths()


def _writable_config_dir() -> str:
    # Backward-compatible: keep function but route to the canonical user config dir.
    return user_data_dir("config")

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
        self._create_icons()
        self._setup_ui()
        self._load_settings()
        self._setup_animations()

    def _create_icons(self):
        """Create custom-painted icons that render perfectly on every Windows system."""
        # ── Eye icons (password toggle) ──────────────────────────
        def _draw_eye(closed=False):
            s = 28
            px = QPixmap(s, s)
            px.fill(QColor(0, 0, 0, 0))
            p = QPainter(px)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor("#475569"))
            pen.setWidthF(1.8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            cy = s / 2
            mx = 4
            path = QPainterPath()
            path.moveTo(mx, cy)
            path.quadTo(s / 2, cy - 9, s - mx, cy)
            path.quadTo(s / 2, cy + 9, mx, cy)
            p.drawPath(path)
            p.setBrush(QColor("#475569"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(s / 2, cy), 3.5, 3.5)
            if closed:
                pen2 = QPen(QColor("#EF4444"))
                pen2.setWidthF(2.0)
                pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen2)
                p.drawLine(7, 6, s - 7, s - 6)
            p.end()
            return QIcon(px)

        self._icon_eye_open = _draw_eye(closed=False)
        self._icon_eye_closed = _draw_eye(closed=True)

        # ── Chevron-down icon (dropdown arrow) ───────────────────
        s = 16
        px = QPixmap(s, s)
        px.fill(QColor(0, 0, 0, 0))
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#475569"))
        pen.setWidthF(2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawLine(3, 5, 8, 10)
        p.drawLine(8, 10, 13, 5)
        p.end()
        icon_dir = ensure_dir(os.path.join(user_data_dir("cache"), "icons"))
        self._chevron_path = os.path.join(icon_dir, "chevron_down.png").replace("\\", "/")
        px.save(self._chevron_path, "PNG")

        # ── Nav icons (Home / Progress / Settings) ─────────────────
        def _draw_nav_icon(draw_fn):
            s = 18
            px2 = QPixmap(s, s)
            px2.fill(QColor(0, 0, 0, 0))
            p2 = QPainter(px2)
            p2.setRenderHint(QPainter.RenderHint.Antialiasing)
            draw_fn(p2, s)
            p2.end()
            return QIcon(px2)

        def _draw_home(p2, s):
            pen = QPen(QColor("#94A3B8"))
            pen.setWidthF(1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p2.setPen(pen)
            p2.drawLine(2, 9, 9, 3)
            p2.drawLine(9, 3, 16, 9)
            p2.drawLine(4, 9, 4, 15)
            p2.drawLine(14, 9, 14, 15)
            p2.drawLine(4, 15, 14, 15)

        def _draw_progress(p2, s):
            pen = QPen(QColor("#94A3B8"))
            pen.setWidthF(1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p2.setPen(pen)
            p2.drawEllipse(3, 3, 12, 12)
            p2.setBrush(QColor("#94A3B8"))
            p2.setPen(Qt.PenStyle.NoPen)
            p2.drawEllipse(QPointF(9, 4), 1.5, 1.5)

        def _draw_settings(p2, s):
            import math
            pen = QPen(QColor("#94A3B8"))
            pen.setWidthF(1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p2.setPen(pen)
            p2.setBrush(Qt.BrushStyle.NoBrush)
            p2.drawEllipse(QPointF(9, 9), 5.0, 5.0)
            p2.drawEllipse(QPointF(9, 9), 2.2, 2.2)
            for angle_deg in range(0, 360, 45):
                rad = math.radians(angle_deg)
                x1, y1 = 9 + 4.2 * math.cos(rad), 9 + 4.2 * math.sin(rad)
                x2, y2 = 9 + 7.0 * math.cos(rad), 9 + 7.0 * math.sin(rad)
                p2.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        self._icon_home = _draw_nav_icon(_draw_home)
        self._icon_progress = _draw_nav_icon(_draw_progress)
        self._icon_settings = _draw_nav_icon(_draw_settings)

    def _setup_animations(self):
        # Pulse animation for status dot
        self._pulse_eff = QGraphicsOpacityEffect(self.status_dot)
        self.status_dot.setGraphicsEffect(self._pulse_eff)
        self.pulse_anim = QPropertyAnimation(self._pulse_eff, b"opacity")
        self.pulse_anim.setDuration(800)
        self.pulse_anim.setStartValue(0.3)
        self.pulse_anim.setEndValue(1.0)
        self.pulse_anim.setLoopCount(-1)
        self.pulse_anim.setEasingCurve(QEasingCurve.Type.InOutSine)

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

        # Stacked pages: Home (0) / Progress (1) / Settings (2)
        self.stack = QStackedWidget()
        self.stack.setObjectName("pageStack")
        self.stack.addWidget(self._build_home_page())       # index 0
        self.stack.addWidget(self._build_progress_page())    # index 1
        self.stack.addWidget(self._build_settings_page())    # index 2
        root_layout.addWidget(self.stack, 1)

        # Bottom action bar
        root_layout.addWidget(self._build_action_bar())

    # ── TOPBAR ─────────────────────────────────────────────────────────
    def _build_topbar(self):
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(56)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(32, 0, 32, 0)

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
        nav = QFrame()
        nav.setObjectName("navContainer")
        nav.setFrameShape(QFrame.Shape.NoFrame)
        nav_lay = QHBoxLayout(nav)
        nav_lay.setContentsMargins(4, 4, 4, 4)
        nav_lay.setSpacing(8)

        self.btn_home = QPushButton("  Home")
        self.btn_home.setIcon(self._icon_home)
        self.btn_home.setIconSize(QSize(16, 16))
        self.btn_home.setObjectName("navBtn")
        self.btn_home.setProperty("active", True)
        self.btn_home.setMinimumHeight(36)
        self.btn_home.setMinimumWidth(110)
        self.btn_home.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_home.clicked.connect(lambda: self._switch_page(0))

        self.btn_progress = QPushButton("  Progress")
        self.btn_progress.setIcon(self._icon_progress)
        self.btn_progress.setIconSize(QSize(16, 16))
        self.btn_progress.setObjectName("navBtn")
        self.btn_progress.setProperty("active", False)
        self.btn_progress.setMinimumHeight(36)
        self.btn_progress.setMinimumWidth(110)
        self.btn_progress.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_progress.clicked.connect(lambda: self._switch_page(1))

        self.btn_settings_nav = QPushButton("  Settings")
        self.btn_settings_nav.setIcon(self._icon_settings)
        self.btn_settings_nav.setIconSize(QSize(16, 16))
        self.btn_settings_nav.setObjectName("navBtn")
        self.btn_settings_nav.setProperty("active", False)
        self.btn_settings_nav.setMinimumHeight(36)
        self.btn_settings_nav.setMinimumWidth(110)
        self.btn_settings_nav.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings_nav.clicked.connect(lambda: self._switch_page(2))

        nav_lay.addWidget(self.btn_home)
        nav_lay.addWidget(self.btn_progress)
        nav_lay.addWidget(self.btn_settings_nav)

        lay.addWidget(nav)
        lay.addStretch()

        # Right: Version + Status
        ver = QLabel("v3.0")
        ver.setObjectName("appVersion")

        self.status_pill = QFrame()
        self.status_pill.setObjectName("statusPill")
        self.status_pill.setProperty("status", "ready")
        status_lay = QHBoxLayout(self.status_pill)
        status_lay.setContentsMargins(12, 0, 12, 0)
        status_lay.setSpacing(8)

        self.status_dot = QLabel("")
        self.status_dot.setObjectName("statusDot")
        self.status_dot.setFixedSize(6, 6)

        self.status_text = QLabel("Ready")
        self.status_text.setObjectName("statusText")

        status_lay.addWidget(self.status_dot)
        status_lay.addWidget(self.status_text)

        lay.addWidget(ver)
        lay.addWidget(self.status_pill)

        return bar

    # ── PAGE SWITCHING ─────────────────────────────────────────────────
    def _switch_page(self, idx):
        if self.stack.currentIndex() == idx:
            return
        # Reload settings data when entering the settings page
        if idx == 2:
            self._load_settings_page()

        self.stack.setCurrentIndex(idx)

        # Smooth fade transition
        effect = QGraphicsOpacityEffect(self.stack.currentWidget())
        self.stack.currentWidget().setGraphicsEffect(effect)
        self.anim = QPropertyAnimation(effect, b"opacity")
        self.anim.setDuration(200)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.anim.start()

        self.btn_home.setProperty("active", idx == 0)
        self.btn_progress.setProperty("active", idx == 1)
        self.btn_settings_nav.setProperty("active", idx == 2)
        for btn in [self.btn_home, self.btn_progress, self.btn_settings_nav]:
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
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(16)

        # ── Page heading ────────────────────────────────────────────
        heading_sub = QLabel("AUTOMATION ENGINE")
        heading_sub.setObjectName("pageHeadingSub")
        heading = QLabel("Claim Processing")
        heading.setObjectName("pageHeading")
        lay.addWidget(heading_sub)
        lay.addWidget(heading)
        lay.addSpacing(4)

        # ── Full-width Folder + Claim card ──────────────────────────
        lay.addWidget(self._build_folder_card())

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
        lay.setContentsMargins(32, 28, 32, 28)
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
    # SETTINGS PAGE (in-app, index 2)
    # ══════════════════════════════════════════════════════════════════
    def _build_settings_page(self):
        page = QWidget()
        page.setObjectName("settingsPageRoot")
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────
        header = QFrame()
        header.setObjectName("settingsHeader")
        header.setFixedHeight(56)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(32, 0, 32, 0)

        title = QLabel("\u2699  Settings")
        title.setStyleSheet(
            "font-size:15pt; font-weight:700; color:#1E293B; background:transparent;"
        )
        h_lay.addWidget(title)
        h_lay.addStretch()
        root.addWidget(header)

        # ── Sub-tab bar ───────────────────────────────────────────
        tab_bar = QFrame()
        tab_bar.setObjectName("settingsTabBar")
        tab_bar_lay = QHBoxLayout(tab_bar)
        tab_bar_lay.setContentsMargins(32, 10, 32, 0)
        tab_bar_lay.setSpacing(6)

        self._stab_general = QPushButton("General")
        self._stab_general.setObjectName("settingsTabBtn")
        self._stab_general.setProperty("active", True)
        self._stab_general.setMinimumHeight(38)
        self._stab_general.setMinimumWidth(150)
        self._stab_general.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stab_general.clicked.connect(lambda: self._switch_settings_tab(0))

        self._stab_field = QPushButton("Field Mapping")
        self._stab_field.setObjectName("settingsTabBtn")
        self._stab_field.setProperty("active", False)
        self._stab_field.setMinimumHeight(38)
        self._stab_field.setMinimumWidth(150)
        self._stab_field.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stab_field.clicked.connect(lambda: self._switch_settings_tab(1))

        self._stab_doc = QPushButton("Document Mapping")
        self._stab_doc.setObjectName("settingsTabBtn")
        self._stab_doc.setProperty("active", False)
        self._stab_doc.setMinimumHeight(38)
        self._stab_doc.setMinimumWidth(150)
        self._stab_doc.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stab_doc.clicked.connect(lambda: self._switch_settings_tab(2))

        self._stab_pdf = QPushButton("PDF Mapping")
        self._stab_pdf.setObjectName("settingsTabBtn")
        self._stab_pdf.setProperty("active", False)
        self._stab_pdf.setMinimumHeight(38)
        self._stab_pdf.setMinimumWidth(150)
        self._stab_pdf.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stab_pdf.clicked.connect(lambda: self._switch_settings_tab(3))

        tab_bar_lay.addWidget(self._stab_general)
        tab_bar_lay.addWidget(self._stab_field)
        tab_bar_lay.addWidget(self._stab_doc)
        tab_bar_lay.addWidget(self._stab_pdf)
        tab_bar_lay.addStretch()
        root.addWidget(tab_bar)

        # ── Sub-stack ─────────────────────────────────────────────
        self._settings_stack = QStackedWidget()
        self._settings_stack.addWidget(self._build_general_settings())   # 0
        self._settings_stack.addWidget(self._build_field_mapping_tab())  # 1
        self._settings_stack.addWidget(self._build_doc_mapping_tab())    # 2
        self._settings_stack.addWidget(self._build_pdf_mapping_tab())    # 3
        root.addWidget(self._settings_stack, 1)

        # ── Footer ────────────────────────────────────────────────
        footer = QFrame()
        footer.setObjectName("settingsFooter")
        footer.setFixedHeight(68)
        f_lay = QHBoxLayout(footer)
        f_lay.setContentsMargins(32, 0, 32, 0)
        f_lay.setSpacing(12)

        btn_reset = QPushButton("  Reset to Defaults  ")
        btn_reset.setObjectName("btnSettingsReset")
        btn_reset.setMinimumHeight(42)
        btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reset.clicked.connect(self._reset_settings_defaults)
        f_lay.addWidget(btn_reset)
        f_lay.addStretch()

        btn_save = QPushButton("  Save All Settings  ")
        btn_save.setObjectName("btnSettingsSave")
        btn_save.setMinimumHeight(42)
        btn_save.setMinimumWidth(180)
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.clicked.connect(self._save_settings_all)
        f_lay.addWidget(btn_save)
        root.addWidget(footer)

        return page

    def _switch_settings_tab(self, idx: int):
        self._settings_stack.setCurrentIndex(idx)
        for i, btn in enumerate([self._stab_general, self._stab_field, self._stab_doc, self._stab_pdf]):
            btn.setProperty("active", i == idx)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # ── General Settings sub-tab ──────────────────────────────────
    def _build_general_settings(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setObjectName("settingsPage")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(16)

        def _sec(text):
            lbl = QLabel(text)
            lbl.setStyleSheet(
                "color:#64748B; font-size:8.5pt; font-weight:700; "
                "letter-spacing:1.5px; padding:8px 0 2px 0; background:transparent;"
            )
            return lbl

        def _flbl(text):
            lbl = QLabel(text)
            lbl.setStyleSheet(
                "color:#475569; font-size:9.5pt; font-weight:600; background:transparent;"
            )
            return lbl

        # ── Credentials ───────────────────────
        lay.addWidget(_sec("PORTAL CREDENTIALS"))
        cred_w = QWidget()
        cg = QGridLayout(cred_w)
        cg.setContentsMargins(0, 0, 0, 0)
        cg.setHorizontalSpacing(16)
        cg.setVerticalSpacing(8)
        cg.setColumnStretch(0, 1)
        cg.setColumnStretch(1, 1)

        cg.addWidget(_flbl("Username"), 0, 0)
        self._set_inp_username = QLineEdit()
        self._set_inp_username.setMinimumHeight(40)
        self._set_inp_username.setPlaceholderText("Portal username / ID")
        self._set_inp_username.setObjectName("settingsInput")
        cg.addWidget(self._set_inp_username, 1, 0)

        cg.addWidget(_flbl("Password"), 0, 1)
        pwd_row = QWidget()
        pw_lay = QHBoxLayout(pwd_row)
        pw_lay.setContentsMargins(0, 0, 0, 0)
        pw_lay.setSpacing(6)
        self._set_inp_password = QLineEdit()
        self._set_inp_password.setMinimumHeight(40)
        self._set_inp_password.setPlaceholderText("Portal password")
        self._set_inp_password.setEchoMode(QLineEdit.EchoMode.Password)
        self._set_inp_password.setObjectName("settingsInput")

        self._set_btn_eye = QPushButton()
        self._set_btn_eye.setIcon(self._icon_eye_closed)
        self._set_btn_eye.setIconSize(QSize(22, 22))
        self._set_btn_eye.setFixedSize(40, 40)
        self._set_btn_eye.setCheckable(True)
        self._set_btn_eye.setCursor(Qt.CursorShape.PointingHandCursor)
        self._set_btn_eye.setToolTip("Show / Hide password")
        self._set_btn_eye.setStyleSheet("""
            QPushButton { background:transparent; border:1px solid #E2E8F0; border-radius:10px; }
            QPushButton:hover { background:#F1F5F9; border-color:#CBD5E1; }
            QPushButton:checked { background:#EEF2FF; border-color:#A5B4FC; }
        """)
        self._set_btn_eye.clicked.connect(self._toggle_settings_pwd)
        pw_lay.addWidget(self._set_inp_password)
        pw_lay.addWidget(self._set_btn_eye)
        cg.addWidget(pwd_row, 1, 1)

        lay.addWidget(cred_w)

        # ── Portal URL ────────────────────────
        lay.addWidget(_sec("PORTAL"))
        url_w = QWidget()
        ul = QVBoxLayout(url_w)
        ul.setContentsMargins(0, 0, 0, 0)
        ul.setSpacing(6)
        ul.addWidget(_flbl("Portal URL"))
        self._set_inp_url = QLineEdit()
        self._set_inp_url.setMinimumHeight(40)
        self._set_inp_url.setPlaceholderText("https://portal.uiic.in/...")
        self._set_inp_url.setObjectName("settingsInput")
        ul.addWidget(self._set_inp_url)
        lay.addWidget(url_w)

        # ── Browser ───────────────────────────
        lay.addWidget(_sec("BROWSER"))
        brow_w = QWidget()
        bg = QGridLayout(brow_w)
        bg.setContentsMargins(0, 0, 0, 0)
        bg.setHorizontalSpacing(16)
        bg.setVerticalSpacing(8)
        bg.setColumnStretch(0, 1)
        bg.setColumnStretch(1, 1)

        bg.addWidget(_flbl("Headless Mode"), 0, 0)
        self._set_inp_headless = QComboBox()
        self._set_inp_headless.addItems(["No (Show Browser)", "Yes (Hidden)"])
        self._set_inp_headless.setMinimumHeight(40)
        bg.addWidget(self._set_inp_headless, 1, 0)

        bg.addWidget(_flbl("Slow-Mo (ms)"), 0, 1)
        self._set_inp_slowmo = QLineEdit()
        self._set_inp_slowmo.setMinimumHeight(40)
        self._set_inp_slowmo.setPlaceholderText("400")
        self._set_inp_slowmo.setObjectName("settingsInput")
        bg.addWidget(self._set_inp_slowmo, 1, 1)
        lay.addWidget(brow_w)

        # ── Timing ────────────────────────────
        lay.addWidget(_sec("TIMING & RETRIES"))
        time_w = QWidget()
        tg = QGridLayout(time_w)
        tg.setContentsMargins(0, 0, 0, 0)
        tg.setHorizontalSpacing(16)
        tg.setVerticalSpacing(8)
        tg.setColumnStretch(0, 1)
        tg.setColumnStretch(1, 1)
        tg.setColumnStretch(2, 1)

        tg.addWidget(_flbl("Timeout (ms)"), 0, 0)
        self._set_inp_timeout = QLineEdit()
        self._set_inp_timeout.setMinimumHeight(40)
        self._set_inp_timeout.setPlaceholderText("4000")
        self._set_inp_timeout.setObjectName("settingsInput")
        tg.addWidget(self._set_inp_timeout, 1, 0)

        tg.addWidget(_flbl("CAPTCHA Retries"), 0, 1)
        self._set_inp_captcha = QLineEdit()
        self._set_inp_captcha.setMinimumHeight(40)
        self._set_inp_captcha.setPlaceholderText("2")
        self._set_inp_captcha.setObjectName("settingsInput")
        tg.addWidget(self._set_inp_captcha, 1, 1)

        tg.addWidget(_flbl("Upload Wait (ms)"), 0, 2)
        self._set_inp_upload = QLineEdit()
        self._set_inp_upload.setMinimumHeight(40)
        self._set_inp_upload.setPlaceholderText("3000")
        self._set_inp_upload.setObjectName("settingsInput")
        tg.addWidget(self._set_inp_upload, 1, 2)

        tg.addWidget(_flbl("Field Wait (ms)"), 2, 0)
        self._set_inp_fieldwait = QLineEdit()
        self._set_inp_fieldwait.setMinimumHeight(40)
        self._set_inp_fieldwait.setPlaceholderText("600")
        self._set_inp_fieldwait.setObjectName("settingsInput")
        tg.addWidget(self._set_inp_fieldwait, 3, 0)
        lay.addWidget(time_w)

        lay.addWidget(time_w)

        note = QLabel(
            "\u2139  Settings are saved to your AppData folder and persist across updates."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            "color:#64748B; font-size:8.5pt; font-style:italic; padding:8px 0; background:transparent;"
        )
        lay.addWidget(note)
        lay.addStretch()
        scroll.setWidget(inner)
        return scroll

    def _toggle_settings_pwd(self, checked):
        if checked:
            self._set_inp_password.setEchoMode(QLineEdit.EchoMode.Normal)
            self._set_btn_eye.setIcon(self._icon_eye_open)
        else:
            self._set_inp_password.setEchoMode(QLineEdit.EchoMode.Password)
            self._set_btn_eye.setIcon(self._icon_eye_closed)

    # ── Field Mapping sub-tab ─────────────────────────────────────
    def _build_field_mapping_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setObjectName("settingsPage")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(12)

        desc = QLabel(
            "Each row maps a ClaimData field to an Excel search label. "
            "The reader scans for the label text, then reads the value "
            "to its right using the offsets."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#64748B; font-size:9pt; padding:4px 0; background:transparent;")
        lay.addWidget(desc)

        self._mapping_table = QTableWidget(0, 4)
        self._mapping_table.setHorizontalHeaderLabels(["FIELD NAME", "SEARCH LABEL", "SHEET", "COL OFFSET"])
        self._mapping_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._mapping_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._mapping_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._mapping_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._mapping_table.verticalHeader().setVisible(False)
        self._mapping_table.verticalHeader().setDefaultSectionSize(38)
        self._mapping_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._mapping_table.setShowGrid(False)
        self._mapping_table.setAlternatingRowColors(True)
        self._mapping_table.setMinimumHeight(400)
        self._mapping_table.setObjectName("settingsTable")
        lay.addWidget(self._mapping_table, 1)

        scroll.setWidget(inner)
        return scroll

    # ── Document Mapping sub-tab ──────────────────────────────────
    def _build_doc_mapping_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setObjectName("settingsPage")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(12)

        desc = QLabel(
            "Maps filename keywords to document types on the UIIC portal. "
            "The scanner checks if the keyword appears in the filename (case-insensitive) "
            "and assigns the matching portal document type."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#64748B; font-size:9pt; padding:4px 0; background:transparent;")
        lay.addWidget(desc)

        self._doc_mapping_table = QTableWidget(0, 3)
        self._doc_mapping_table.setHorizontalHeaderLabels(["SECTION", "PORTAL DOC TYPE", "FILENAME KEYWORDS"])
        self._doc_mapping_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._doc_mapping_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._doc_mapping_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._doc_mapping_table.verticalHeader().setVisible(False)
        self._doc_mapping_table.verticalHeader().setDefaultSectionSize(38)
        self._doc_mapping_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._doc_mapping_table.setShowGrid(False)
        self._doc_mapping_table.setAlternatingRowColors(True)
        self._doc_mapping_table.setMinimumHeight(400)
        self._doc_mapping_table.setObjectName("settingsTable")
        lay.addWidget(self._doc_mapping_table, 1)

        scroll.setWidget(inner)
        return scroll

    # ── PDF Mapping sub-tab ──────────────────────────────────
    def _build_pdf_mapping_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setObjectName("settingsPage")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(12)

        def _sec(text):
            lbl = QLabel(text)
            lbl.setStyleSheet(
                "color:#64748B; font-size:8.5pt; font-weight:700; "
                "letter-spacing:1.5px; padding:8px 0 2px 0; background:transparent;"
            )
            return lbl

        def _flbl(text):
            lbl = QLabel(text)
            lbl.setObjectName("fieldLabel")
            return lbl

        desc = QLabel(
            "Configure how data is extracted from uploaded PDF documents. "
            "These labels are searched inside the PDF text to find specific values."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#64748B; font-size:9pt; padding:4px 0; background:transparent;")
        lay.addWidget(desc)

        # ── PDF Extraction (Strict) ──────────────────────────
        lay.addWidget(_sec("WORKSHOP INVOICE EXTRACTION"))
        pdf_w = QWidget()
        pg = QGridLayout(pdf_w)
        pg.setContentsMargins(0, 0, 0, 0)
        pg.setHorizontalSpacing(16)
        pg.setVerticalSpacing(8)
        pg.setColumnStretch(0, 1)
        pg.setColumnStretch(1, 1)

        pg.addWidget(_flbl("Invoice No Labels (use | to separate)"), 0, 0)
        self._set_inp_pdf_inv = QLineEdit()
        self._set_inp_pdf_inv.setMinimumHeight(40)
        self._set_inp_pdf_inv.setObjectName("settingsInput")
        pg.addWidget(self._set_inp_pdf_inv, 1, 0)

        pg.addWidget(_flbl("Invoice Date Labels (use | to separate)"), 0, 1)
        self._set_inp_pdf_date = QLineEdit()
        self._set_inp_pdf_date.setMinimumHeight(40)
        self._set_inp_pdf_date.setObjectName("settingsInput")
        pg.addWidget(self._set_inp_pdf_date, 1, 1)
        lay.addWidget(pdf_w)

        lay.addStretch()
        scroll.setWidget(inner)
        return scroll

    # ── Settings Load / Save / Reset ──────────────────────────────
    def _load_settings_page(self):
        """Populate the settings page widgets from current saved data."""
        s = load_settings()
        self._set_inp_username.setText(s.get("username", ""))
        self._set_inp_password.setText(s.get("password", ""))
        self._set_inp_url.setText(s.get("portal_url", ""))
        self._set_inp_headless.setCurrentIndex(1 if s.get("browser_headless") else 0)
        self._set_inp_slowmo.setText(str(s.get("browser_slow_mo_ms", 400)))
        self._set_inp_timeout.setText(str(s.get("timeout_ms", 4000)))
        self._set_inp_captcha.setText(str(s.get("captcha_max_retries", 2)))
        self._set_inp_upload.setText(str(s.get("upload_wait_ms", 3000)))
        self._set_inp_fieldwait.setText(str(s.get("field_wait_ms", 600)))
        
        pdf_inv = s.get("pdf_invoice_no_labels", ["Tax Invoice No.", "Invoice No", "Bill No"])
        self._set_inp_pdf_inv.setText(" | ".join(pdf_inv) if isinstance(pdf_inv, list) else str(pdf_inv))
        
        pdf_date = s.get("pdf_invoice_date_labels", ["Invoice Date and Time", "Bill Date", "Invoice Date"])
        self._set_inp_pdf_date.setText(" | ".join(pdf_date) if isinstance(pdf_date, list) else str(pdf_date))

        # Field mapping table
        mapping = load_field_mapping()
        entries = [(k, v) for k, v in mapping.items() if not k.startswith("_")]
        self._mapping_table.setRowCount(len(entries))
        for i, (field_name, cfg) in enumerate(entries):
            name_item = QTableWidgetItem(field_name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setForeground(QColor("#94A3B8"))
            self._mapping_table.setItem(i, 0, name_item)
            labels = cfg.get("search_labels") or [cfg.get("search_label", "")]
            self._mapping_table.setItem(i, 1, QTableWidgetItem(" | ".join(labels)))
            self._mapping_table.setItem(i, 2, QTableWidgetItem(cfg.get("sheet", "ALL")))
            self._mapping_table.setItem(i, 3, QTableWidgetItem(str(cfg.get("col_offset", 1))))

        # Document mapping table
        dm = load_doc_mapping()
        rows = []
        for section_key in ("claim_documents_tab", "claim_assessment_tab"):
            section = dm.get(section_key, {})
            label = "Claim Docs" if "claim_doc" in section_key else "Assessment"
            for doc_type, keywords in section.items():
                if isinstance(keywords, list):
                    kw_str = " | ".join(keywords)
                else:
                    kw_str = keywords
                rows.append((label, doc_type, kw_str))
        self._doc_mapping_table.setRowCount(len(rows))
        for i, (section, dtype, kws) in enumerate(rows):
            sec_item = QTableWidgetItem(section)
            sec_item.setFlags(sec_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            sec_item.setForeground(QColor("#94A3B8"))
            dtype_item = QTableWidgetItem(dtype)
            dtype_item.setFlags(dtype_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            dtype_item.setForeground(QColor("#64748B"))
            self._doc_mapping_table.setItem(i, 0, sec_item)
            self._doc_mapping_table.setItem(i, 1, dtype_item)
            self._doc_mapping_table.setItem(i, 2, QTableWidgetItem(kws))

    def _save_settings_all(self):
        """Save all settings tabs to AppData."""
        # General settings
        try:
            overrides = {
                "username": self._set_inp_username.text().strip(),
                "password": self._set_inp_password.text().strip(),
                "portal_url": self._set_inp_url.text().strip(),
                "browser_headless": self._set_inp_headless.currentIndex() == 1,
                "browser_slow_mo_ms": int(self._set_inp_slowmo.text() or 400),
                "timeout_ms": int(self._set_inp_timeout.text() or 4000),
                "captcha_max_retries": int(self._set_inp_captcha.text() or 2),
                "upload_wait_ms": int(self._set_inp_upload.text() or 3000),
                "field_wait_ms": int(self._set_inp_fieldwait.text() or 600),
                "pdf_invoice_no_labels": [l.strip() for l in self._set_inp_pdf_inv.text().split("|") if l.strip()],
                "pdf_invoice_date_labels": [l.strip() for l in self._set_inp_pdf_date.text().split("|") if l.strip()],
            }
            save_settings(overrides)
        except ValueError:
            QMessageBox.warning(self, "Invalid Input", "Numeric fields must contain valid numbers.")
            return

        # Field mapping
        mapping = load_field_mapping()
        new_mapping = {k: v for k, v in mapping.items() if k.startswith("_")}
        for row in range(self._mapping_table.rowCount()):
            fn = self._mapping_table.item(row, 0).text()
            lt = self._mapping_table.item(row, 1).text().strip()
            sh = self._mapping_table.item(row, 2).text().strip() or "ALL"
            try:
                co = int(self._mapping_table.item(row, 3).text())
            except (ValueError, TypeError):
                co = 1
            old = mapping.get(fn, {})
            labels = [l.strip() for l in lt.split("|") if l.strip()]
            if len(labels) > 1:
                new_mapping[fn] = {"sheet": sh, "search_labels": labels, "row_offset": old.get("row_offset", 0), "col_offset": co}
            else:
                new_mapping[fn] = {"sheet": sh, "search_label": labels[0] if labels else "", "row_offset": old.get("row_offset", 0), "col_offset": co}
        save_field_mapping(new_mapping)

        # Document mapping
        dm = load_doc_mapping()
        new_dm = {k: v for k, v in dm.items() if k.startswith("_")}
        new_dm["other_slots"] = dm.get("other_slots", [])
        claim_docs = {}
        assess_docs = {}
        for row in range(self._doc_mapping_table.rowCount()):
            sec = self._doc_mapping_table.item(row, 0).text()
            dtype = self._doc_mapping_table.item(row, 1).text().strip()
            kws = self._doc_mapping_table.item(row, 2).text().strip()
            if dtype and kws:
                kw_list = [k.strip() for k in kws.split("|") if k.strip()]
                if kw_list:
                    if "Claim" in sec:
                        claim_docs[dtype] = kw_list
                    else:
                        assess_docs[dtype] = kw_list
        new_dm["claim_documents_tab"] = claim_docs
        new_dm["claim_assessment_tab"] = assess_docs
        save_doc_mapping(new_dm)

        self._append_log("\u2699  All settings saved to AppData.")
        QMessageBox.information(
            self, "Settings Saved",
            "All settings have been saved.\n\nChanges take effect on the next automation run."
        )

    def _reset_settings_defaults(self):
        reply = QMessageBox.question(
            self, "Reset to Defaults",
            "Discard all custom settings and revert to bundled defaults?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        reset_field_mapping()
        reset_doc_mapping()
        try:
            sp = settings_paths()
            if os.path.exists(sp["user"]):
                os.remove(sp["user"])
        except OSError:
            pass
        self._load_settings_page()
        QMessageBox.information(self, "Reset Complete", "All settings reverted to defaults.")

    # ══════════════════════════════════════════════════════════════════
    # CARD BUILDERS
    # ══════════════════════════════════════════════════════════════════
    def _build_folder_card(self):
        """Full-width card: Folder Browse."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(10)

        lay.addWidget(_field_label("CLAIM FOLDER PATH"))

        folder_row = QWidget()
        fr_lay = QHBoxLayout(folder_row)
        fr_lay.setContentsMargins(0, 0, 0, 0)
        fr_lay.setSpacing(10)

        self.inp_folder = _input("Click Browse to select the claim folder...")
        self.inp_folder.setObjectName("folderPathInput")
        self.inp_folder.setReadOnly(True)
        self.inp_folder.setMinimumHeight(40)

        btn = QPushButton("Browse...")
        btn.setObjectName("btnBrowse")
        btn.setFixedWidth(120)
        btn.setMinimumHeight(40)
        btn.clicked.connect(self._browse_folder)

        fr_lay.addWidget(self.inp_folder, 1)
        fr_lay.addWidget(btn)
        lay.addWidget(folder_row)

        # Document status
        self.doc_status_label = QLabel("No folder selected \u2014 click Browse to begin.")
        self.doc_status_label.setObjectName("helperTextItalic")
        self.doc_status_label.setWordWrap(True)
        lay.addWidget(self.doc_status_label)

        return _card(w, title="\U0001F4C2  Claim Folder",
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
        self.preview_table.verticalHeader().setDefaultSectionSize(40)  # Taller, breathable rows
        self.preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.preview_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.preview_table.setShowGrid(False)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setMinimumHeight(400)

        # Custom styling for a modern, clean table design
        self.preview_table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                background-color: #FFFFFF;
                alternate-background-color: #F8FAFC;
                color: #334155;
            }
            QHeaderView::section {
                background-color: #F1F5F9;
                color: #64748B;
                font-weight: bold;
                font-size: 8pt;
                letter-spacing: 1px;
                padding: 12px 10px;
                border: none;
                border-bottom: 2px solid #E2E8F0;
                text-transform: uppercase;
            }
            QTableWidget::item {
                padding: 0 10px;
                border-bottom: 1px solid #F1F5F9;
            }
        """)
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
        self.progress_label.setObjectName("helperText")
        vlay.addWidget(self.progress_label)

        return _card(container, title="📈  Progress")

    def _build_log_card(self):
        self.log_panel = QTextEdit()
        self.log_panel.setObjectName("logPanel")
        self.log_panel.setReadOnly(True)
        self.log_panel.setMinimumHeight(450)
        # Max height removed to allow expanding

        return _card(self.log_panel, title="🖥  Live Log",
                     subtitle="Real-time automation output")

    # ── ACTION BAR ─────────────────────────────────────────────────────
    def _build_action_bar(self):
        bar = QFrame()
        bar.setObjectName("actionBar")
        bar.setMinimumHeight(84)
        bar.setMaximumHeight(84)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(32, 0, 32, 0)
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
            # Production reliability: always write logs to a user-writable directory.
            log_dir = ensure_dir(user_data_dir("logs"))
            
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
            path = _SETTINGS_PATHS["user"] if os.path.exists(_SETTINGS_PATHS["user"]) else _SETTINGS_PATHS["default"]
            with open(path, "r", encoding="utf-8") as f:
                s = json.load(f)
            self.inp_claim_type.setCurrentText(s.get("claim_type", "Non Maruti"))
        except Exception:
            pass

    def _save_settings(self, overrides: dict):
        try:
            save_settings(overrides)
        except Exception as exc:
            self._append_log(f"\u26a0\ufe0f  Could not save settings: {exc}")

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
            self._scan_result = scan_folder(folder)

            # ── UI Document Scan Summary ──────────────────────────────────
            claim_docs = self._scan_result.claim_doc_files
            assess_docs = self._scan_result.assessment_files

            if claim_docs:
                self._append_log("📎 Claim Documents (matched):")
                for doc_type, fpath in claim_docs.items():
                    mb = os.path.getsize(fpath) / (1024 * 1024) if os.path.isfile(fpath) else 0
                    self._append_log(f"  ✅ [{doc_type}] → {Path(fpath).name} ({mb:.1f}MB)")
            else:
                self._append_log("⚠️  No claim documents matched from folder")

            if assess_docs:
                self._append_log("📎 Assessment Files (matched):")
                for doc_type, fpath in assess_docs.items():
                    self._append_log(f"  ✅ [{doc_type}] → {Path(fpath).name}")

            # Show missing expected documents
            from app.data.folder_scanner import _EXPECTED_CLAIM_DOCS
            matched_types = set(claim_docs.keys())
            missing_docs = [d for d in _EXPECTED_CLAIM_DOCS if d not in matched_types]
            if missing_docs:
                self._append_log("⚠️  Missing expected documents:")
                for doc in missing_docs:
                    self._append_log(f"  ❌ {doc}")

            if self._scan_result.skipped_files:
                self._append_log("⚠️  Skipped Files:")
                for path, reason in self._scan_result.skipped_files:
                    self._append_log(f"  • {Path(path).name} — {reason}")

            if self._scan_result.unknown_files:
                self._append_log("❓ Unrecognized Files (No Mapping):")
                for path in self._scan_result.unknown_files:
                    self._append_log(f"  • {Path(path).name}")
                self._append_log("  ℹ️  Tip: rename files to include keywords like pan, aadhaar, vehicle_photo_1, claim_form, ckyc, csr, etc.")

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
                                # Load dynamic labels from settings
                                s = load_settings()
                                inv_labels = s.get("pdf_invoice_no_labels", ["Tax Invoice No.", "Invoice No", "Bill No"])
                                date_labels = s.get("pdf_invoice_date_labels", ["Invoice Date and Time", "Bill Date", "Invoice Date"])
                                
                                inv_match = None
                                for label in inv_labels:
                                    pattern = re.escape(label) + r'(.*?)\('
                                    inv_match = re.search(pattern, text, re.IGNORECASE)
                                    if inv_match: break
                                    pattern = re.escape(label) + r'?\s*([A-Za-z0-9-]+)'
                                    inv_match = re.search(pattern, text, re.IGNORECASE)
                                    if inv_match: break
                                
                                date_match = None
                                for label in date_labels:
                                    pattern = re.escape(label) + r'\s*(\d{2}/\d{2}/\d{4})'
                                    date_match = re.search(pattern, text, re.IGNORECASE)
                                    if date_match: break
                                
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
                
                if not self._claim.claim_no:
                    self._append_log("\u26a0\ufe0f  Claim No not found in Excel.")
                
                self._update_preview()
                self._set_status("ready", "Folder scanned \u2014 ready to start")
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

        # Run validation and show errors/warnings
        errors, warnings = self._claim.validate()
        if errors:
            err_text = "⚠  MISSING FIELDS — Review before starting:\n" + \
                       "\n".join(f"  • {e}" for e in errors)
            if warnings:
                err_text += "\n   Also: " + " | ".join(warnings)
            self.validation_bar.setStyleSheet(
                "background:#FFF7ED; color:#C2410C; "
                "border:1px solid #FED7AA; "
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
                v_item.setForeground(QColor("#0F172A"))
                font = v_item.font()
                font.setWeight(QFont.Weight.DemiBold)
                v_item.setFont(font)
            elif is_critical:
                v_item.setForeground(QColor("#EF4444"))
                font = v_item.font()
                font.setItalic(True)
                v_item.setFont(font)
            else:
                v_item.setForeground(QColor("#94A3B8"))
                font = v_item.font()
                font.setItalic(True)
                v_item.setFont(font)
            self.preview_table.setItem(i, 1, v_item)

            # Source column
            src_display = source_coord if source_coord else "—"
            src_item = QTableWidgetItem(src_display)
            if source_coord:
                src_item.setForeground(QColor("#6366F1"))
                font = src_item.font()
                font.setPixelSize(11)
                src_item.setFont(font)
            else:
                src_item.setForeground(QColor("#CBD5E1"))
            src_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.preview_table.setItem(i, 2, src_item)

            # Status column
            if has_value:
                status = "✓  OK"
                s_item = QTableWidgetItem(status)
                s_item.setForeground(QColor("#059669"))  # Emerald
                font = s_item.font()
                font.setWeight(QFont.Weight.Bold)
                s_item.setFont(font)
            elif is_critical:
                status = "⚠  CRITICAL"
                s_item = QTableWidgetItem(status)
                s_item.setForeground(QColor("#DC2626"))  # Red
                font = s_item.font()
                font.setWeight(QFont.Weight.Bold)
                s_item.setFont(font)
            else:
                status = "○  OPTIONAL"
                s_item = QTableWidgetItem(status)
                s_item.setForeground(QColor("#94A3B8"))  # Slate
            
            s_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
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
        self.status_text.setText(text)
        self.status_pill.setProperty("status", status)
        self.status_pill.style().unpolish(self.status_pill)
        self.status_pill.style().polish(self.status_pill)
        self.status_dot.style().unpolish(self.status_dot)
        self.status_dot.style().polish(self.status_dot)

    def _start_automation(self):
        if not self._claim:
            QMessageBox.warning(self, "No Folder", "Please select a claim folder first.")
            return

        # Read credentials from saved settings (configured in Settings page)
        saved = load_settings()
        username = saved.get("username", "").strip()
        password = saved.get("password", "").strip()
        if not username or not password:
            QMessageBox.warning(
                self, "Credentials Required",
                "Portal username and password are not configured.\n\n"
                "Go to Settings \u2192 General to enter your credentials first."
            )
            self._switch_page(2)  # Navigate to Settings
            return

        if not self._claim.claim_no:
            QMessageBox.warning(self, "Claim No Required", "Could not auto-detect Claim Number from folder. Please rename folder or check contents.")
            return

        # \u2500\u2500 Validation gate \u2014 warn (but allow) if critical fields missing \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        errors, warnings = self._claim.validate()
        if errors:
            error_list = "\n".join(f"  \u2022 {e}" for e in errors)
            reply = QMessageBox.warning(
                self, "Critical Fields Missing",
                f"The following fields are missing from Excel:\n\n"
                f"{error_list}\n\n"
                f"The portal may reject the submission.\n"
                f"Do you still want to proceed?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        if warnings:
            warn_list = "\n".join(f"  \u2022 {w}" for w in warnings)
            reply = QMessageBox.question(
                self, "Optional Fields Missing",
                f"Some optional fields are missing:\n\n{warn_list}\n\n"
                f"These fields will be skipped. Continue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        settings_override = {
            "username":   username,
            "password":   password,
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
        is_bold = False

        # ── Box-drawing banners (╔═╗║╚╝) ─────────────────────────────────
        if any(c in raw_message for c in ("╔", "╗", "╚", "╝", "╠", "╣")):
            color = "#FBBF24"   # gold for box borders
            is_bold = True
        elif "║" in raw_message:
            if any(x in raw_message for x in ("🎉", "COMPLETE")):
                color = "#4ADE80"   # green for completion banner content
            elif any(x in raw_message for x in ("🚀", "AUTOMATION")):
                color = "#7C83FF"   # indigo for startup banner
            else:
                color = "#E2E8F0"   # white for banner data
        # ── Step headers (━━━ lines and STEP X/Y) ────────────────────────
        elif "━" in raw_message:
            color = "#A78BFA"   # purple for step separators
            is_bold = True
        elif "STEP" in raw_message and "/" in raw_message:
            color = "#E2E8F0"   # bright white for step titles
            is_bold = True
        # ── Status colors ────────────────────────────────────────────────
        elif any(x in raw_message for x in ("✅", "successful", "complete", "found")):
            color = "#4ADE80"   # green
        elif any(x in raw_message for x in ("❌", "ERROR", "FAILED", "failed")):
            color = "#F87171"   # red
        elif any(x in raw_message for x in ("⚠️", "warning", "⚠", "MISS")):
            color = "#FBBF24"   # yellow
        elif any(x in raw_message for x in ("⏭️", "skipped", "SKIPPED")):
            color = "#94A3B8"   # muted gray for skips
        elif any(x in raw_message for x in ("⏱️", "Duration")):
            color = "#38BDF8"   # sky blue for timing
        elif any(x in raw_message for x in ("🎉", "COMPLETE")):
            color = "#4ADE80"   # green
        elif any(x in raw_message for x in ("📤", "📊", "📁", "🔩", "🔧", "🚀", "📋", "📎", "📌", "🔎", "✏️", "💰", "💼", "🧾", "👷", "✍️", "📝")):
            color = "#7C83FF"   # indigo for section headers
        elif any(x in raw_message for x in ("🔄", "🔑", "📷", "🌐", "🔘")):
            color = "#94A3B8"   # muted for process steps
        elif "═" in raw_message:
            color = "#FBBF24"   # gold for summary borders
            is_bold = True
        else:
            color = "#CBD5E1"   # light slate

        display_message = html.escape(raw_message)
        if is_bold:
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
