"""
table_clipboard.py – Double-click → Copy Row to Clipboard
==========================================================
Attach to ANY QTableWidget with a single call:

    from app.ui.components.table_clipboard import attach_row_copy_on_double_click
    attach_row_copy_on_double_click(my_table)

• Copies the entire row (all visible columns) as tab-separated text.
• Shows a lightweight toast notification that auto-fades after 1.5 s.
• 100 % portal/website independent – works on any QTableWidget.
"""

from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QLabel, QTableWidget, QGraphicsOpacityEffect,
)


# ── Toast Notification ──────────────────────────────────────────────────

class _CopyToast(QLabel):
    """Tiny notification that appears near the bottom-center of a parent widget."""

    _STYLE = (
        "background: rgba(15, 23, 42, 0.92);"   # near-black
        "color: #F0FDF4;"                         # soft green-white
        "border: 1px solid #334155;"
        "border-radius: 8px;"
        "padding: 8px 18px;"
        "font-size: 9.5pt;"
        "font-weight: 700;"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(self._STYLE)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.setVisible(False)
        self.setFixedHeight(38)

        # Make toast fully click-through so it never blocks table interactions
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # Opacity effect for fade-out animation
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity)

        self._fade_anim = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade_anim.setDuration(400)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_anim.finished.connect(self._on_fade_done)

        # Persistent timer — avoids race conditions from overlapping singleShot calls
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self._start_fade)

    def show_message(self, text: str, duration_ms: int = 1500):
        """Show *text* for *duration_ms* then fade out."""
        # Cancel any pending fade-out from a previous rapid double-click
        self._dismiss_timer.stop()
        self._fade_anim.stop()
        self._opacity.setOpacity(1.0)
        self.setText(text)
        self.adjustSize()
        self._reposition()
        self.setVisible(True)
        self.raise_()
        self._dismiss_timer.start(duration_ms)

    def _reposition(self):
        """Center-bottom of the parent widget."""
        p = self.parentWidget()
        if not p:
            return
        x = (p.width() - self.width()) // 2
        y = p.height() - self.height() - 16
        self.move(max(x, 4), max(y, 4))

    def _start_fade(self):
        self._fade_anim.start()

    def _on_fade_done(self):
        self.setVisible(False)
        self._opacity.setOpacity(1.0)


# ── Public API ──────────────────────────────────────────────────────────

def attach_row_copy_on_double_click(table: QTableWidget) -> None:
    """
    Wire double-click on any cell → copy the **entire row** to clipboard.

    Parameters
    ----------
    table : QTableWidget
        The table to enhance.  Must already be added to the widget tree
        (or will be before the user double-clicks).

    Notes
    -----
    • The row text is tab-separated (``\\t``) so it pastes cleanly into
      Excel / Google Sheets / Notepad.
    • A small toast appears at the bottom-center of the table confirming
      the copy.
    • Calling this function multiple times on the same table is safe –
      it will NOT attach duplicate handlers.
    """
    # Guard against duplicate attachment
    if getattr(table, "_row_copy_attached", False):
        return
    table._row_copy_attached = True

    # Create toast (parented to the table so it floats on top of rows)
    toast = _CopyToast(table)

    def _on_double_click(row: int, _col: int):
        col_count = table.columnCount()
        parts = []
        for c in range(col_count):
            if table.isColumnHidden(c):
                continue
            item = table.item(row, c)
            parts.append(item.text() if item else "")

        row_text = "\t".join(parts)
        QApplication.clipboard().setText(row_text)

        # Truncate preview for the toast (keep it short)
        preview = row_text.replace("\t", "  |  ")
        if len(preview) > 80:
            preview = preview[:77] + "..."
        toast.show_message(f"✓  Row copied: {preview}")

    table.cellDoubleClicked.connect(_on_double_click)
