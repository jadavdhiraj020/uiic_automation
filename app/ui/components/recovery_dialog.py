"""Friendly "automation paused" card shown while a portal run waits for the operator."""

import re

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

_ISSUE_LINE = re.compile(r"^\s*[•\-]\s*(.+?)\s+—\s+(.+?)\s*$")

_STYLE = """
QDialog#recoveryCard { background: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 14px; }
QFrame#recoveryHeader { background: %(accent)s; border-top-left-radius: 14px; border-top-right-radius: 14px; }
QLabel#recoveryTitle { color: #FFFFFF; font-size: 17px; font-weight: 700; }
QLabel#recoverySub { color: rgba(255,255,255,0.88); font-size: 12px; }
QLabel#recoveryBadge { color: #FFFFFF; font-size: 24px; }
QLabel#recoveryIntro { color: #1E293B; font-size: 13px; }
QLabel#recoveryHint { color: #334155; font-size: 12px; background: #F1F5F9; border-radius: 8px; padding: 8px 10px; }
QLabel#recoveryRetry { color: #92400E; font-size: 12px; font-weight: 600; background: #FEF3C7;
                       border: 1px solid #FCD34D; border-radius: 8px; padding: 6px 10px; }
QFrame#issueCard { background: #FFF7ED; border: 1px solid #FED7AA; border-radius: 10px; }
QLabel#issueNo { color: #FFFFFF; background: #EA580C; border-radius: 11px; font-weight: 700; font-size: 12px; }
QLabel#issueName { color: #0F172A; font-size: 13px; font-weight: 700; }
QLabel#issueWhere { color: #64748B; font-size: 11px; }
QLabel#issueWhy { color: #9A3412; font-size: 12px; }
QPushButton { font-size: 13px; font-weight: 600; border-radius: 9px; padding: 10px 18px; }
QPushButton#recoveryContinue { background: #16A34A; color: #FFFFFF; border: none; }
QPushButton#recoveryContinue:hover { background: #15803D; }
QPushButton#recoveryContinue:disabled { background: #94A3B8; }
QPushButton#recoverySkip { background: #FFFFFF; color: #1D4ED8; border: 1px solid #93C5FD; }
QPushButton#recoverySkip:hover { background: #EFF6FF; }
QPushButton#recoverySkip:disabled { color: #94A3B8; border-color: #E2E8F0; }
QPushButton#recoveryStop { background: #FFFFFF; color: #B91C1C; border: 1px solid #FCA5A5; }
QPushButton#recoveryStop:hover { background: #FEF2F2; }
QScrollArea { border: none; background: transparent; }
"""


def parse_prompt_text(text):
    """Split a pause reason into plain intro text and (section, field, why) issue rows."""
    intro, issues = [], []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _ISSUE_LINE.match(line)
        if not match:
            intro.append(line)
            continue
        title, why = match.groups()
        section, _, field = title.rpartition(" / ")
        issues.append((section.strip(), (field or title).strip(), why.strip()))
    return " ".join(intro), issues


class RecoveryDialog(QDialog):
    """Always-on-top, non-blocking card. Buttons only emit signals; the worker decides what happens."""

    decision = pyqtSignal(str)
    stop = pyqtSignal()

    def __init__(self, parent=None, *, portal_name="New India", accent="#EA580C"):
        super().__init__(parent)
        self.prompt_id = None
        self._portal_name = portal_name
        self._busy = False
        self._positioned = False
        self._confirm_text = "Continue"
        self.setObjectName("recoveryCard")
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
        )
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowTitle(f"{portal_name} — action needed")
        self.setMinimumWidth(500)
        self.setMaximumWidth(560)
        self.setStyleSheet(_STYLE % {"accent": accent})

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 16)
        root.setSpacing(12)

        header = QFrame()
        header.setObjectName("recoveryHeader")
        head_row = QHBoxLayout(header)
        head_row.setContentsMargins(18, 14, 18, 14)
        badge = QLabel("⏸")
        badge.setObjectName("recoveryBadge")
        head_row.addWidget(badge)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title_label = QLabel()
        self.title_label.setObjectName("recoveryTitle")
        self.sub_label = QLabel()
        self.sub_label.setObjectName("recoverySub")
        titles.addWidget(self.title_label)
        titles.addWidget(self.sub_label)
        head_row.addLayout(titles, 1)
        root.addWidget(header)

        body = QVBoxLayout()
        body.setContentsMargins(18, 0, 18, 0)
        body.setSpacing(10)
        self.retry_label = QLabel()
        self.retry_label.setObjectName("recoveryRetry")
        self.retry_label.setWordWrap(True)
        self.retry_label.hide()
        body.addWidget(self.retry_label)
        self.intro_label = QLabel()
        self.intro_label.setObjectName("recoveryIntro")
        self.intro_label.setWordWrap(True)
        body.addWidget(self.intro_label)

        self.issue_host = QWidget()
        self.issue_layout = QVBoxLayout(self.issue_host)
        self.issue_layout.setContentsMargins(0, 0, 0, 0)
        self.issue_layout.setSpacing(8)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.issue_host)
        self.scroll.setMaximumHeight(270)
        body.addWidget(self.scroll)

        self.hint_label = QLabel()
        self.hint_label.setObjectName("recoveryHint")
        self.hint_label.setWordWrap(True)
        body.addWidget(self.hint_label)
        root.addLayout(body)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(18, 0, 18, 0)
        buttons.setSpacing(8)
        self.stop_button = QPushButton("Stop automation")
        self.stop_button.setObjectName("recoveryStop")
        self.skip_button = QPushButton("Skip")
        self.skip_button.setObjectName("recoverySkip")
        self.fixed_button = QPushButton("Continue")
        self.fixed_button.setObjectName("recoveryContinue")
        self.fixed_button.setDefault(True)
        buttons.addWidget(self.stop_button)
        buttons.addStretch(1)
        buttons.addWidget(self.skip_button)
        buttons.addWidget(self.fixed_button)
        root.addLayout(buttons)

        self.fixed_button.clicked.connect(lambda: self._emit_decision("fixed"))
        self.skip_button.clicked.connect(lambda: self._emit_decision("skip"))
        self.stop_button.clicked.connect(self.stop.emit)

    # The worker alone closes this card; ESC / close must not silently dismiss a pause.
    def reject(self):
        pass

    def closeEvent(self, event):
        event.ignore()

    def _emit_decision(self, choice):
        if self._busy:
            return
        self.decision.emit(choice)

    def set_busy(self, busy):
        self._busy = bool(busy)
        self.fixed_button.setEnabled(not self._busy)
        self.skip_button.setEnabled(not self._busy and self.skip_button.isVisible())
        if self._busy:
            self.fixed_button.setText("Checking Chrome…")
        else:
            self.fixed_button.setText(self._confirm_text)

    def _clear_issues(self):
        while self.issue_layout.count():
            item = self.issue_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_issue(self, number, section, field, why):
        card = QFrame()
        card.setObjectName("issueCard")
        row = QHBoxLayout(card)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(10)
        badge = QLabel(str(number))
        badge.setObjectName("issueNo")
        badge.setFixedSize(22, 22)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(1)
        name = QLabel(field)
        name.setObjectName("issueName")
        name.setWordWrap(True)
        text.addWidget(name)
        if section:
            where = QLabel(section)
            where.setObjectName("issueWhere")
            where.setWordWrap(True)
            text.addWidget(where)
        reason = QLabel(why)
        reason.setObjectName("issueWhy")
        reason.setWordWrap(True)
        text.addWidget(reason)
        row.addLayout(text, 1)
        self.issue_layout.addWidget(card)

    def show_prompt(self, prompt, *, retry=False):
        """Fill the card from a RecoveryPrompt and bring it in front of Chrome."""
        self.prompt_id = prompt.id
        self._busy = False
        self._confirm_text = prompt.confirmation_button or "Continue"
        self.title_label.setText(prompt.action or "Action needed")
        self.sub_label.setText(
            f"{self._portal_name} · {prompt.section}" if prompt.section and prompt.section != prompt.action
            else f"{self._portal_name} automation is waiting for you"
        )

        intro, issues = parse_prompt_text(prompt.reason)
        self.intro_label.setText(intro)
        self.intro_label.setVisible(bool(intro))
        self._clear_issues()
        for number, (section, field, why) in enumerate(issues, 1):
            self._add_issue(number, section, field, why)
        self.scroll.setVisible(bool(issues))
        if issues:
            self.issue_layout.activate()
            self.issue_host.adjustSize()
            content_height = max(self.issue_host.sizeHint().height(), self.issue_layout.sizeHint().height())
            self.scroll.setFixedHeight(min(270, max(76, content_height + 8)))

        if retry:
            count = f"{len(issues)} item(s) still need attention" if issues else "Chrome is not ready yet"
            self.retry_label.setText(f"Not finished yet — {count}. Fix them in Chrome, then press Continue again.")
        self.retry_label.setVisible(retry)

        default_hint = (
            "Complete this step in Chrome, then press Continue." if prompt.stop_only is False
            else "Stop this run and review Chrome."
        )
        self.hint_label.setText(
            "👉 " + (prompt.instruction.strip() if prompt.instruction else default_hint)
        )

        self.fixed_button.setText(self._confirm_text)
        self.fixed_button.setVisible(not prompt.stop_only)
        self.fixed_button.setEnabled(not prompt.stop_only)
        self.skip_button.setText(prompt.skip_button or "Skip this field")
        self.skip_button.setVisible(prompt.can_skip)
        self.skip_button.setEnabled(prompt.can_skip)
        self.adjustSize()
        self._position_once()
        self.bring_to_front()

    def _position_once(self):
        if self._positioned:
            return
        self._positioned = True
        parent_screen = self.parentWidget().screen() if self.parentWidget() else None
        screen = parent_screen or self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        card_w = max(self.width(), self.sizeHint().width(), self.minimumWidth())
        x = max(area.left() + 16, area.right() - card_w - 24)
        y = area.top() + 24
        self.move(x, y)

    def bring_to_front(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
