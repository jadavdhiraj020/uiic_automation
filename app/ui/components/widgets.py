from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QPainter, QColor, QPen, QFontMetrics
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QLineEdit, QPushButton, QSizePolicy,
    QStyledItemDelegate, QStyle
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


def search_row(placeholder: str, on_change):
    """Create the compact search bar used above data lists."""
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 10)
    lay.setSpacing(8)

    inp = QLineEdit()
    inp.setPlaceholderText(placeholder)
    inp.setObjectName("settingsInput")
    inp.textChanged.connect(on_change)

    btn_clear = QPushButton("X")
    btn_clear.setFixedWidth(36)
    btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_clear.clicked.connect(inp.clear)
    btn_clear.setStyleSheet(
        "QPushButton { border-radius: 8px; padding: 0; background: #F1F5F9; "
        "color: #64748B; font-size: 10pt; font-weight: 800; } "
        "QPushButton:hover { background: #E2E8F0; color: #0F172A; }"
    )

    lay.addWidget(inp)
    lay.addWidget(btn_clear)
    return row, inp


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
        "  border:2px solid #0F172A;"
        f" border-left:6px solid {accent_color};"
        "  border-radius:0px;"
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
        f"background-color: {_hex_to_rgba(accent_color, 0.12)}; border:2px solid {accent_color}; border-radius:0px;"
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
                badge.setStyleSheet("background-color: #10B981; color: white; border: 2px solid #065F46; border-radius: 0px;")
            elif i == active_idx:
                state = "active"
                badge.setText(str(i + 1))
                badge.setStyleSheet("background-color: #4F46E5; color: white; border: 3px solid #312E81; border-radius: 0px;")
            else:
                state = "pending"
                badge.setText(str(i + 1))
                badge.setStyleSheet("background-color: #FFFFFF; color: #94A3B8; border: 2px solid #E2E8F0; border-radius: 0px;")

            for w in (card, badge, lbl):
                w.setProperty("state", state)
                w.style().unpolish(w)
                w.style().polish(w)


# Keep backward compatibility
SidebarStepList = StepPipeline


class TagDelegate(QStyledItemDelegate):
    """Renders ' | ' separated strings as distinctive tags/chips."""
    def paint(self, painter: QPainter, option, index):
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if not text or not isinstance(text, str):
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw background (handles selection)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
            text_color = option.palette.highlightedText().color()
            tag_bg = option.palette.highlight().color().lighter(120)
            tag_border = option.palette.highlight().color().darker(110)
        else:
            # Subtle background for the cell itself isn't needed if cards are white
            # but we follow standard painting for non-selected rows.
            # painter.fillRect(option.rect, option.palette.base())
            text_color = QColor("#0F172A")
            tag_bg = QColor("#FFFFFF")
            tag_border = QColor("#0F172A")

        tags = [t.strip() for t in text.split("|") if t.strip()]
        if not tags:
            painter.restore()
            super().paint(painter, option, index)
            return

        margin = 8
        x = option.rect.x() + margin
        # Vertically center tags
        tag_h = 24
        y = option.rect.y() + (option.rect.height() - tag_h) // 2
        
        # Use a slightly smaller font for tags to fit better
        font = painter.font()
        font.setPointSize(9)
        font.setWeight(700) # Bold brutalist look
        painter.setFont(font)
        metrics = QFontMetrics(font)
        
        for tag in tags:
            # Add padding inside the tag
            tw = metrics.horizontalAdvance(tag) + 16
            tag_rect = QRect(x, y, tw, tag_h)
            
            # Skip if we go beyond the column width (simple clipping)
            if x + tw > option.rect.right() - margin:
                break

            # Draw tag box
            painter.setBrush(tag_bg)
            painter.setPen(QPen(tag_border, 1.5))
            painter.drawRect(tag_rect)
            
            # Draw tag text
            painter.setPen(text_color)
            painter.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, tag)
            
            x += tw + 6 # Space between tags
            
        painter.restore()


class ChipLineEdit(QLineEdit):
    """A QLineEdit that renders pipe-separated text as tags when not focused."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(44)
    
    def paintEvent(self, event):
        # Only show chips when NOT focused and has content with pipes
        if self.hasFocus() or not self.text() or "|" not in self.text():
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw frame (matching brutalist lineEdit style)
        painter.setBrush(QColor("#FFFFFF"))
        painter.setPen(QPen(QColor("#0F172A"), 2))
        painter.drawRect(self.rect().adjusted(1, 1, -1, -1))
        
        tags = [t.strip() for t in self.text().split("|") if t.strip()]
        if not tags:
            painter.end()
            super().paintEvent(event)
            return

        margin = 10
        x = margin
        tag_h = 26
        y = (self.height() - tag_h) // 2
        
        font = self.font()
        font.setPointSize(9)
        font.setWeight(800)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        
        for tag in tags:
            tw = metrics.horizontalAdvance(tag) + 16
            tag_rect = QRect(x, y, tw, tag_h)
            
            # Clip if too long
            if x + tw > self.width() - margin:
                break

            # Tag box
            painter.setBrush(QColor("#FFFFFF"))
            painter.setPen(QPen(QColor("#0F172A"), 1.5))
            painter.drawRect(tag_rect)
            
            # Text
            painter.setPen(QColor("#0F172A"))
            painter.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, tag)
            
            x += tw + 8
        
        painter.end()
