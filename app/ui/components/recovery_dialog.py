"""Friendly "automation paused" card shown while a portal run waits for the operator."""

import re

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def _qt_button_text(text: str) -> str:
    """Escape literal '&' characters so Qt displays them instead of shortcut mnemonics."""
    return str(text or "").replace("&", "&&")

_ISSUE_LINE = re.compile(r"^\s*[•\-]\s*(.+?)\s+—\s+(.+?)\s*$")
_VALUE_HINT = re.compile(r"^(.*?)\s*\[Value:\s*(.+?)\]\s*$")

_STYLE = """
QDialog#recoveryCard { background: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 14px; }
QFrame#recoveryHeader { background: %(accent)s; border-top-left-radius: 14px; border-top-right-radius: 14px; }
QLabel#recoveryTitle { color: #FFFFFF; font-size: 17px; font-weight: 700; }
QLabel#recoverySub { color: rgba(255,255,255,0.88); font-size: 12px; }
QLabel#recoveryBadge { color: #FFFFFF; font-size: 24px; }
QPushButton#recoveryChromeBtn { background: rgba(255,255,255,0.18); color: #FFFFFF; border: 1px solid rgba(255,255,255,0.45);
                               font-size: 11px; font-weight: 600; border-radius: 7px; padding: 6px 10px; }
QPushButton#recoveryChromeBtn:hover { background: rgba(255,255,255,0.28); }
QLabel#recoveryIntro { color: #1E293B; font-size: 13px; }
QLabel#recoveryHint { color: #334155; font-size: 12px; background: #F1F5F9; border-radius: 8px; padding: 8px 10px; }
QLabel#recoveryRetry { color: #92400E; font-size: 12px; font-weight: 600; background: #FEF3C7;
                       border: 1px solid #FCD34D; border-radius: 8px; padding: 6px 10px; }
QFrame#issueCard { background: #FFF7ED; border: 1px solid #FED7AA; border-radius: 10px; }
QLabel#issueNo { color: #FFFFFF; background: %(accent)s; border-radius: 11px; font-weight: 700; font-size: 12px; }
QLabel#issueName { color: #0F172A; font-size: 13px; font-weight: 700; }
QLabel#issueWhere { color: #64748B; font-size: 11px; font-weight: 500; }
QLabel#issueValuePill { color: #334155; background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 6px;
                        padding: 2px 7px; font-size: 11px; font-weight: 600; }
QPushButton#issueCopyBtn { color: #475569; background: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 6px;
                           font-size: 10.5px; font-weight: 600; padding: 2px 8px; }
QPushButton#issueCopyBtn:hover { background: #F1F5F9; color: #0F172A; }
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


def split_field_value_hint(field_text: str) -> tuple[str, str, str]:
    """Extract (clean_field, tried_value, source) from '[Value: ... · Source]' tags."""
    raw = str(field_text or "").strip()
    match = _VALUE_HINT.match(raw)
    if not match:
        return raw, "", ""
    clean_field = match.group(1).strip()
    val_part = match.group(2).strip()
    if " · " in val_part:
        val, _, src = val_part.rpartition(" · ")
        return clean_field, val.strip(), src.strip()
    return clean_field, val_part, ""


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
    focus_chrome = pyqtSignal()

    def __init__(self, parent=None, *, portal_name="New India", accent="#EA580C", anchor_screen=None):
        super().__init__(parent)
        self.prompt_id = None
        self._portal_name = portal_name
        self._accent = accent
        self._kind = "pause"
        self._anchor_screen = anchor_screen
        self._busy = False
        self._positioned = False
        self._confirm_text = "Continue"
        self.setObjectName("recoveryCard")
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowTitle(f"{portal_name} — action needed")
        self.setMinimumWidth(500)
        self.setMaximumWidth(600)
        self.setStyleSheet(_STYLE % {"accent": accent})

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 16)
        root.setSpacing(12)

        header = QFrame()
        header.setObjectName("recoveryHeader")
        header.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._header = header
        head_row = QHBoxLayout(header)
        head_row.setContentsMargins(18, 14, 18, 14)
        badge = QLabel("⏸")
        badge.setObjectName("recoveryBadge")
        self._badge = badge
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
        self.chrome_button = QPushButton("Show Chrome")
        self.chrome_button.setObjectName("recoveryChromeBtn")
        self.chrome_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chrome_button.clicked.connect(self.focus_chrome.emit)
        head_row.addWidget(self.chrome_button, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(header, 0)

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
        self.stop_button = QPushButton(_qt_button_text("Stop automation"))
        self.stop_button.setObjectName("recoveryStop")
        self.stop_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.skip_button = QPushButton(_qt_button_text("Skip"))
        self.skip_button.setObjectName("recoverySkip")
        self.skip_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.fixed_button = QPushButton(_qt_button_text("Continue"))
        self.fixed_button.setObjectName("recoveryContinue")
        self.fixed_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.fixed_button.setDefault(True)
        buttons.addWidget(self.stop_button)
        buttons.addStretch(1)
        buttons.addWidget(self.skip_button)
        buttons.addWidget(self.fixed_button)
        root.addLayout(buttons)

        self.fixed_button.clicked.connect(
            lambda: self._emit_decision("done" if self._kind == "complete" else "fixed")
        )
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
            self.fixed_button.setText(_qt_button_text(self._confirm_text))

    def _clear_issues(self):
        while self.issue_layout.count():
            item = self.issue_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_issue(self, number, section, field, why):
        clean_field, raw_value, source = split_field_value_hint(field)
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
        text.setSpacing(3)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        name = QLabel(clean_field or field)
        name.setObjectName("issueName")
        name.setWordWrap(True)
        title_row.addWidget(name)
        if section:
            where = QLabel(f"· {section}")
            where.setObjectName("issueWhere")
            where.setWordWrap(True)
            title_row.addWidget(where, 1)
        else:
            title_row.addStretch(1)
        text.addLayout(title_row)

        if raw_value:
            val_row = QHBoxLayout()
            val_row.setContentsMargins(0, 0, 0, 0)
            val_row.setSpacing(6)
            src_suffix = f" ({source})" if source else ""
            val_pill = QLabel(f"Tried: {raw_value}{src_suffix}")
            val_pill.setObjectName("issueValuePill")
            val_pill.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            val_row.addWidget(val_pill)
            copy_btn = QPushButton("Copy")
            copy_btn.setObjectName("issueCopyBtn")
            copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)

            def _copy_val(_checked=False, v=raw_value, btn=copy_btn):
                QApplication.clipboard().setText(v)
                btn.setText("Copied ✓")
                def _reset():
                    try:
                        btn.setText("Copy")
                    except RuntimeError:
                        pass
                QTimer.singleShot(1400, _reset)

            copy_btn.clicked.connect(_copy_val)
            val_row.addWidget(copy_btn)
            val_row.addStretch(1)
            text.addLayout(val_row)

        reason = QLabel(why)
        reason.setObjectName("issueWhy")
        reason.setWordWrap(True)
        text.addWidget(reason)
        row.addLayout(text, 1)
        self.issue_layout.addWidget(card)

    def show_prompt(self, prompt, *, retry=False, anchor_screen=None):
        """Fill the card from a RecoveryPrompt and float it without stealing Chrome focus."""
        if anchor_screen is not None:
            self._anchor_screen = anchor_screen
        self.prompt_id = prompt.id
        self._busy = False
        self._kind = getattr(prompt, "kind", "pause") or "pause"
        complete = self._kind == "complete"
        active_accent = "#16A34A" if complete else self._accent
        self.setStyleSheet(_STYLE % {"accent": active_accent})
        self._badge.setText("✅" if complete else "⏸")
        self.setWindowTitle(
            f"{self._portal_name} — ready for review" if complete else f"{self._portal_name} — action needed"
        )
        confirm_label = prompt.confirmation_button or ("Done (Keep Chrome Open)" if complete else "Continue")
        self._confirm_text = confirm_label
        self.title_label.setText(prompt.action or ("Ready for Review" if complete else "Action needed"))
        if complete:
            self.sub_label.setText(f"{self._portal_name} · Chrome is ready for your final check")
        else:
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

        show_retry = bool(retry and not prompt.stop_only and not complete)
        if show_retry:
            count = f"{len(issues)} item(s) still need attention" if issues else "Chrome is not ready yet"
            self.retry_label.setText(f"Not finished yet — {count}. Fix them in Chrome, then press Continue again.")
        self.retry_label.setVisible(show_retry)

        default_hint = (
            "Review Chrome and submit manually when ready. Chrome will stay open."
            if complete else
            ("Complete this step in Chrome, then press Continue." if prompt.stop_only is False
             else "Stop this run and review Chrome.")
        )
        self.hint_label.setText(
            "👉 " + (prompt.instruction.strip() if prompt.instruction else default_hint)
        )

        self.fixed_button.setText(_qt_button_text(confirm_label))
        if complete:
            self.stop_button.setVisible(False)
            self.skip_button.setVisible(False)
            self.skip_button.setEnabled(False)
            self.fixed_button.setVisible(True)
            self.fixed_button.setEnabled(True)
        else:
            self.stop_button.setVisible(True)
            self.fixed_button.setVisible(not prompt.stop_only)
            self.fixed_button.setEnabled(not prompt.stop_only)
            self.skip_button.setText(_qt_button_text(prompt.skip_button or "Skip this field"))
            self.skip_button.setVisible(prompt.can_skip)
            self.skip_button.setEnabled(prompt.can_skip)
        self.setMinimumHeight(0)
        self.resize(max(self.minimumWidth(), self.sizeHint().width()), 0)
        self.adjustSize()
        self._position_once()
        self.bring_to_front(activate=False)

    def _position_once(self, anchor_screen=None):
        if self._positioned:
            return
        self._positioned = True
        parent_screen = self.parentWidget().screen() if self.parentWidget() else None
        screen = (
            anchor_screen or self._anchor_screen or parent_screen or self.screen() or QApplication.primaryScreen()
        )
        if screen is None:
            return
        area = screen.availableGeometry()
        card_w = max(self.width(), self.sizeHint().width(), self.minimumWidth())
        x = max(area.left() + 16, area.right() - card_w - 24)
        y = area.top() + 24
        self.move(x, y)

    def bring_to_front(self, *, activate=False):
        self.showNormal()
        self.raise_()
        if activate:
            self.activateWindow()
