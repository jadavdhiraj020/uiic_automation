from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame, QLineEdit, QPushButton
)

STEPS = [
    ("Login",            "1"),
    ("Navigate to Claim","2"),
    ("Interim Report",   "3"),
    ("Claim Documents",  "4"),
    ("Claim Assessment", "5"),
    ("Complete",         "6"),
]

# ── Reusable Widgets ─────────────────────────────────────────────────
def hline():
    """Thin horizontal separator line."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet("background:#E0E0E0; border:none;")
    return line


def create_label(text, object_name=None, bold=False, secondary=False):
    lbl = QLabel(text)
    if object_name:
        lbl.setObjectName(object_name)
    if bold:
        lbl.setStyleSheet("font-weight:700;")
    if secondary:
        lbl.setStyleSheet("color:#888888; font-size:8.5pt;")
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
    inp.setMinimumHeight(38)
    return inp


def card(content_widget, title=None, subtitle=None, icon=None):
    """Wrap a widget in a white card with title header."""
    outer = QWidget()
    outer.setObjectName("card")
    lay = QVBoxLayout(outer)
    lay.setContentsMargins(20, 16, 20, 16)
    lay.setSpacing(6)
    if title:
        t = QLabel(title)
        t.setObjectName("cardTitle")
        lay.addWidget(t)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("cardSubtitle")
            lay.addWidget(s)
        # Divider line under header
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setFixedHeight(1)
        div.setStyleSheet("background:#E0E0E0; border:none;")
        lay.addWidget(div)
        lay.addSpacing(2)
    elif subtitle:
        s = QLabel(subtitle)
        s.setObjectName("cardSubtitle")
        lay.addWidget(s)
    lay.addWidget(content_widget)
    return outer


# ── Sidebar Step Widget ───────────────────────────────────────────────
class SidebarStepList(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._lay    = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(2)
        self._buttons = []

        title = QLabel("PROGRESS")
        title.setObjectName("sidebarTitle")
        self._lay.addWidget(title)
        self._lay.addSpacing(4)

        for i, (name, icon) in enumerate(STEPS):
            btn = QPushButton(f"  {icon}  {name}")
            btn.setObjectName("stepItem")
            btn.setProperty("state", "pending")
            btn.setMinimumHeight(40)
            btn.setCheckable(False)
            btn.setFlat(True)
            btn.setCursor(Qt.CursorShape.ArrowCursor)
            self._buttons.append(btn)
            self._lay.addWidget(btn)

        self._lay.addStretch()

        # Sidebar footer
        footer = QLabel("UIIC Surveyor Tool")
        footer.setStyleSheet("color:#AAAAAA; font-size:7.5pt; padding:12px 16px;")
        self._lay.addWidget(footer)

    def set_step(self, active_idx: int):
        for i, btn in enumerate(self._buttons):
            if i < active_idx:
                btn.setProperty("state", "done")
            elif i == active_idx:
                btn.setProperty("state", "active")
            else:
                btn.setProperty("state", "pending")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
