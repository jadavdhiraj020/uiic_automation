import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame, QLabel, QProgressBar, QTextEdit,
    QApplication, QPushButton
)
from app.ui.components.widgets import StepPipeline, card as _card, search_row as _search_row

class ProgressPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._log_entries = []
        self._setup_ui()

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        inner = QWidget()
        inner.setObjectName("progressPage")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(24)

        # Pipeline
        self.pipeline = StepPipeline()
        lay.addWidget(self.pipeline)

        # Status Header
        status_w = QWidget()
        status_lay = QVBoxLayout(status_w); status_lay.setContentsMargins(0,0,0,0); status_lay.setSpacing(10)
        self.current_action = QLabel("Waiting to start...")
        self.current_action.setStyleSheet("font-size: 14pt; font-weight: 700; color: #4F46E5; background: transparent;")
        status_lay.addWidget(self.current_action)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        status_lay.addWidget(self.progress_bar)
        
        lay.addWidget(_card(status_w, "Automation Live Status", "Currently executing task and overall progress"))

        # Log
        self.log_output = QTextEdit()
        self.log_output.setObjectName("logPanel")
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(350)
        
        log_header = QWidget()
        log_h_lay = QHBoxLayout(log_header); log_h_lay.setContentsMargins(0,0,0,0)
        btn_copy = QPushButton("📋 Copy Log")
        btn_copy.setFixedWidth(110); btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.log_output.toPlainText()))
        btn_copy.setStyleSheet("QPushButton { border-radius: 0px; padding: 6px 12px; font-size: 8.5pt; font-weight: 800; background: #FFFFFF; color: #0F172A; border: 2px solid #0F172A; } QPushButton:hover { background: #F8FAFC; border-color: #4F46E5; }")
        log_h_lay.addStretch(); log_h_lay.addWidget(btn_copy)

        log_v_w = QWidget()
        log_v_lay = QVBoxLayout(log_v_w); log_v_lay.setContentsMargins(0,0,0,0); log_v_lay.setSpacing(10)
        search, self.log_search_input = _search_row(
            "Filter activity log...",
            self._filter_log,
        )
        log_v_lay.addWidget(search)
        log_v_lay.addWidget(log_header)
        log_v_lay.addWidget(self.log_output)
        
        lay.addWidget(_card(log_v_w, "Activity Log", "Detailed execution history"))

        lay.addStretch()
        scroll.setWidget(inner)
        
        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(0,0,0,0)
        main_lay.addWidget(scroll)
        
    def append_log(self, html_text: str):
        self._log_entries.append(html_text)
        if self._log_matches_filter(html_text, self.log_search_input.text()):
            self.log_output.append(html_text)
        self.log_output.ensureCursorVisible()

    def clear_logs(self):
        self._log_entries.clear()
        self.log_output.clear()

    def _plain_log_text(self, html_text: str) -> str:
        return re.sub(r"<[^>]+>", " ", html_text).lower()

    def _log_matches_filter(self, html_text: str, text: str) -> bool:
        text = (text or "").strip().lower()
        return not text or text in self._plain_log_text(html_text)

    def _filter_log(self, text):
        self.log_output.clear()
        for entry in self._log_entries:
            if self._log_matches_filter(entry, text):
                self.log_output.append(entry)
        self.log_output.ensureCursorVisible()

    def set_progress(self, val: int):
        self.progress_bar.setValue(val)
        
    def set_step(self, idx: int, name: str = ""):
        self.pipeline.set_step(idx)
        if name:
            self.current_action.setText(name)
