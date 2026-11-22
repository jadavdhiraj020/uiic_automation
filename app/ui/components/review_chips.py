"""Compact, wrapping issue labels for Extraction Review."""

import html
import re

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtWidgets import QLabel, QLayout, QVBoxLayout, QWidget


_FIELD_NOTICE = re.compile(
    r"^([^:\r\n]+?)\s+(?:is (?:missing|empty|invalid|not)|not found|missing|must be|cannot be|are zero)\b",
    re.IGNORECASE,
)
_VALUE_SUFFIX = re.compile(
    r"\s+(?:'[^']*'|\([^)]*\)|\d+(?:\.\d+)?%|in the survey PDF)$",
    re.IGNORECASE,
)
_NOTICE_LABELS = (
    ("policy number and claim number are both missing", "Policy Number / Claim Number"),
    ("no claim documents found", "Claim Documents"),
    ("no assessment files found", "Assessment Files"),
    ("oic upload excel", "OIC Upload Workbook"),
    ("the prepared oic upload workbook", "OIC Upload Workbook"),
    ("app3 saved the new upload workbook", "OIC Upload Workbook"),
)


def _group_issues(messages, fallback):
    issues = {}
    for message in dict.fromkeys(messages):
        line = message.strip().split("\n", 1)[0]
        if not line:
            continue
        label = next((label for prefix, label in _NOTICE_LABELS if line.casefold().startswith(prefix)), None)
        if label is None:
            match = _FIELD_NOTICE.match(line)
            field = _VALUE_SUFFIX.sub("", match.group(1)) if match else ""
            label = field.strip() if 0 < len(field.strip()) <= 64 else fallback
        issues.setdefault(label, []).append(message)
    return issues


class _ChipFlowLayout(QLayout):
    """Lay out each label at its natural width and wrap at the panel edge."""

    def __init__(self):
        super().__init__()
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(6)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def minimumSize(self):
        size = QSize(0, 0)
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def sizeHint(self):
        return self.minimumSize()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._flow(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._flow(rect, apply=True)

    def _flow(self, rect, *, apply):
        left = x = rect.x()
        top = y = rect.y()
        row_height = 0
        for item in self._items:
            hint = item.sizeHint()
            width = min(hint.width(), max(1, rect.width()))
            height = hint.height()
            if x > left and x + width > left + rect.width():
                x = left
                y += row_height + self.spacing()
                row_height = 0
            if apply:
                item.setGeometry(QRect(x, y, width, height))
            x += width + self.spacing()
            row_height = max(row_height, height)
        return y - top + row_height


class ReviewChips(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self.hide()

    def set_issues(self, errors=(), warnings=(), *, survey_pdf=False):
        while self._layout.count():
            group = self._layout.takeAt(0).widget()
            group.hide()
            group.deleteLater()

        fallback = "Survey PDF" if survey_pdf else "Review Details"
        critical = _group_issues(errors, fallback)
        optional = _group_issues(warnings, fallback)
        for label in critical.keys() & optional.keys():
            critical[label].extend(optional.pop(label))

        for severity, issues in (("Critical", critical), ("Optional / warnings", optional)):
            if not issues:
                continue
            group = QWidget()
            layout = QVBoxLayout(group)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(4)
            heading = QLabel(severity)
            heading.setObjectName("reviewChipHeading")
            layout.addWidget(heading)
            flow = _ChipFlowLayout()
            layout.addLayout(flow)
            for field, messages in issues.items():
                chip = QLabel(field)
                chip.setObjectName("reviewChip")
                chip.setProperty("critical", severity == "Critical")
                chip.setTextFormat(Qt.TextFormat.PlainText)
                details = "\n".join(dict.fromkeys(messages))
                chip.setToolTip("<p>" + html.escape(details).replace("\n", "<br>") + "</p>")
                chip.setAccessibleDescription(f"{severity}. {details}")
                flow.addWidget(chip)
            self._layout.addWidget(group)

        self.setVisible(bool(critical or optional))
