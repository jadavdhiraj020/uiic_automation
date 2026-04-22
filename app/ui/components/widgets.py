from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QLineEdit, QPushButton, QSizePolicy
)

STEPS = [
    ("Login",             "1"),
    ("Navigate to Claim", "2"),
    ("Interim Report",    "3"),
    ("Claim Documents",   "4"),
    ("Claim Assessment",  "5"),
    ("Complete",          "6"),
]

# ── Small helpers ─────────────────────────────────────────────────────
def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert '#RRGGBB' to 'rgba(r,g,b,a)' for Qt stylesheets."""
    h = (hex_color or "").lstrip("#")
    if len(h) != 6:
        return f"rgba(99,102,241,{alpha})"  # indigo fallback
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"

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
    # Match the tighter Tailwind `h-9` control height used in the Figma export.
    inp.setMinimumHeight(36)
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
    """Create a stat KPI card closer to the Figma layout (icon tile + text)."""
    outer = QFrame()
    outer.setObjectName("statCard")
    # QSS can't reliably bind dynamic colors from properties, so we set the accent via inline style.
    outer.setStyleSheet(
        "QFrame#statCard {"
        "  background-color:#FFFFFF;"
        "  border:1px solid #E2E8F0;"
        f" border-left:4px solid {accent_color};"
        "  border-radius:12px;"
        "}"
    )
    outer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    outer.setMinimumHeight(84)

    lay = QHBoxLayout(outer)
    lay.setContentsMargins(20, 18, 20, 18)
    lay.setSpacing(14)

    icon_map = {
        "Fields Extracted": "📄",
        "Documents Found": "✅",
        "Missing Critical": "⚠",
        "Status": "⏱",
    }
    icon_tile = QLabel(icon_map.get(label_text, ""))
    icon_tile.setObjectName("statIconTile")
    icon_tile.setFixedSize(44, 44)
    # Soft tint for the icon tile like Tailwind `*-100`
    icon_tile.setStyleSheet(
        f"background-color: {_hex_to_rgba(accent_color, 0.18)}; border-radius:12px;"
    )
    icon_tile.setAlignment(Qt.AlignmentFlag.AlignCenter)

    text_col = QWidget()
    text_lay = QVBoxLayout(text_col)
    text_lay.setContentsMargins(0, 0, 0, 0)
    text_lay.setSpacing(2)
    text_lay.setAlignment(Qt.AlignmentFlag.AlignVCenter)

    value = QLabel(value_text)
    value.setObjectName("statValue")
    # Value text is neutral in the Figma export except for the Status card;
    # keep accent only for the 4th card (caller can still override later).
    value.setStyleSheet("background:transparent;")

    label = QLabel(label_text.upper())
    label.setObjectName("statLabel")

    text_lay.addWidget(value)
    text_lay.addWidget(label)

    lay.addWidget(icon_tile, 0, Qt.AlignmentFlag.AlignVCenter)
    lay.addWidget(text_col, 1)

    return outer, value


# ── Horizontal Step Pipeline (replaces sidebar) ──────────────────────
class StepPipeline(QWidget):
    """Horizontal step indicators for the Progress page."""
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        self._items: list[tuple[QFrame, QLabel, QLabel]] = []

        for i, (name, number) in enumerate(STEPS):
            card = QFrame()
            card.setObjectName("stepCard")
            card.setProperty("state", "pending")

            v = QVBoxLayout(card)
            v.setContentsMargins(12, 18, 12, 18)
            v.setSpacing(10)
            v.setAlignment(Qt.AlignmentFlag.AlignCenter)

            badge = QLabel(number)
            badge.setObjectName("stepBadge")
            badge.setFixedSize(36, 36)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setProperty("state", "pending")

            lbl = QLabel(name)
            lbl.setObjectName("stepText")
            lbl.setWordWrap(True)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setProperty("state", "pending")

            v.addWidget(badge, 0, Qt.AlignmentFlag.AlignCenter)
            v.addWidget(lbl, 0, Qt.AlignmentFlag.AlignCenter)

            self._items.append((card, badge, lbl))
            lay.addWidget(card, 1)

    def set_step(self, active_idx: int):
        for i, (card, badge, lbl) in enumerate(self._items):
            if i < active_idx:
                state = "done"
                badge.setText("✓")
            elif i == active_idx:
                state = "active"
                badge.setText(str(i + 1))
            else:
                state = "pending"
                badge.setText(str(i + 1))

            for w in (card, badge, lbl):
                w.setProperty("state", state)
                w.style().unpolish(w)
                w.style().polish(w)


# Keep backward compatibility
SidebarStepList = StepPipeline
