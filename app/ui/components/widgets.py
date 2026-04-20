from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QLineEdit, QPushButton
)

STEPS = [
    ("Login",             "1"),
    ("Navigate to Claim", "2"),
    ("Interim Report",    "3"),
    ("Claim Documents",   "4"),
    ("Claim Assessment",  "5"),
    ("Complete",          "6"),
]

# ── Reusable Widgets ─────────────────────────────────────────────────
def hline():
    """Thin horizontal separator line."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet("background:#E8ECF0; border:none;")
    return line


def create_label(text, object_name=None, bold=False, secondary=False):
    lbl = QLabel(text)
    if object_name:
        lbl.setObjectName(object_name)
    if bold:
        lbl.setStyleSheet("font-weight:700;")
    if secondary:
        lbl.setStyleSheet("color:#8894A7; font-size:8.5pt;")
    return lbl


def field_label(text):
    lbl = QLabel(text)
    lbl.setObjectName("fieldLabel")
    return lbl


def create_input(placeholder="", echo_password=False):
    inp = QLineEdit()
    inp.setPlaceholderText(placeholder)
    if echo_password:
        inp.setEchoMode(QLineEdit.EchoMode.Password)
    inp.setMinimumHeight(40)
    return inp


def card(content_widget, title=None, subtitle=None, icon=None):
    """Wrap a widget in a clean white card with title header."""
    outer = QWidget()
    outer.setObjectName("card")
    lay = QVBoxLayout(outer)
    lay.setContentsMargins(24, 20, 24, 20)
    lay.setSpacing(8)
    if title:
        header_lay = QHBoxLayout()
        header_lay.setSpacing(8)
        t = QLabel(title)
        t.setObjectName("cardTitle")
        header_lay.addWidget(t)
        header_lay.addStretch()
        lay.addLayout(header_lay)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("cardSubtitle")
            lay.addWidget(s)
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setFixedHeight(1)
        div.setStyleSheet("background:#E8ECF0; border:none;")
        lay.addWidget(div)
        lay.addSpacing(4)
    elif subtitle:
        s = QLabel(subtitle)
        s.setObjectName("cardSubtitle")
        lay.addWidget(s)
    lay.addWidget(content_widget)
    return outer


def stat_card(value_text, label_text, accent_color):
    """Create a single stat KPI card with colored left border."""
    outer = QFrame()
    outer.setStyleSheet(
        f"QFrame {{ background-color: #FFFFFF; border: 1px solid #E8ECF0; "
        f"border-left: 3px solid {accent_color}; border-radius: 14px; }}"
    )
    lay = QVBoxLayout(outer)
    lay.setContentsMargins(20, 16, 20, 16)
    lay.setSpacing(2)

    value = QLabel(value_text)
    value.setStyleSheet(
        f"color: {accent_color}; font-size: 22pt; font-weight: 800; "
        f"background: transparent; border: none;"
    )

    label = QLabel(label_text.upper())
    label.setStyleSheet(
        "color: #8894A7; font-size: 8pt; font-weight: 700; "
        "letter-spacing: 1px; background: transparent; border: none;"
    )

    lay.addWidget(value)
    lay.addWidget(label)

    return outer, value


# ── Horizontal Step Pipeline (replaces sidebar) ──────────────────────
class StepPipeline(QWidget):
    """Horizontal step indicators for the Progress page."""
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self._buttons = []

        for i, (name, icon) in enumerate(STEPS):
            btn = QPushButton(f"  {icon}  {name}")
            btn.setObjectName("stepPill")
            btn.setProperty("state", "pending")
            btn.setMinimumHeight(44)
            btn.setCheckable(False)
            btn.setFlat(True)
            btn.setCursor(Qt.CursorShape.ArrowCursor)
            self._buttons.append(btn)
            lay.addWidget(btn, 1)

    def set_step(self, active_idx: int):
        for i, btn in enumerate(self._buttons):
            if i < active_idx:
                btn.setProperty("state", "done")
                btn.setText(f"  ✓  {STEPS[i][0]}")
            elif i == active_idx:
                btn.setProperty("state", "active")
                btn.setText(f"  ●  {STEPS[i][0]}")
            else:
                btn.setProperty("state", "pending")
                btn.setText(f"  {STEPS[i][1]}  {STEPS[i][0]}")
            btn.style().unpolish(btn)
            btn.style().polish(btn)


# Keep backward compatibility
SidebarStepList = StepPipeline
