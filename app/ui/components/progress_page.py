from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QFrame, QLabel, QProgressBar, QTextEdit
)
from app.ui.components.widgets import StepPipeline, card as _card

class ProgressPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
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

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        lay.addWidget(_card(self.progress_bar, "Automation Progress", "Live tracking of current task"))

        # Log
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(350)
        lay.addWidget(_card(self.log_output, "Activity Log", "Detailed execution history"))

        lay.addStretch()
        scroll.setWidget(inner)
        
        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(0,0,0,0)
        main_lay.addWidget(scroll)
        
    def append_log(self, html_text: str):
        self.log_output.append(html_text)
        self.log_output.ensureCursorVisible()

    def set_progress(self, val: int):
        self.progress_bar.setValue(val)
        
    def set_step(self, idx: int):
        self.pipeline.set_step(idx)
