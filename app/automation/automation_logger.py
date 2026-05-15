"""
automation_logger.py — Centralized Production-Grade Logging System
for the UIIC Surveyor Automation project. (Refactored)

Architecture:
  ┌────────────────────────────┐
  │   AutomationLogger         │
  │   (per-module instance)    │
  │                            │
  │  ┌──────────┐ ┌──────────┐ │
  │  │ UI log   │ │ Python   │ │
  │  │ (log_cb) │ │ logging  │ │
  │  └──────────┘ └──────────┘ │
  └────────────────────────────┘

Features:
  - Timestamped UI logs (HH:MM:SS.mmm)
  - Portal-aware tagging  [UIIC] / [NEW_INDIA]
  - Section-aware tagging  [LOGIN] / [DRIVER_DETAILS] etc.
  - Structured log levels  INFO / SUCCESS / WARN / ERROR / DEBUG
  - Field-level action logging
  - Upload/extraction/navigation helpers
  - Wait/retry logging with counters
  - Consistent formatting across all modules
  - Zero breaking changes to existing log_cb interface
"""

import logging
import time
from datetime import datetime
from typing import Callable, Optional

# ── Log Level Tags ────────────────────────────────────────────────────────────

class LogLevel:
    """Visual log level indicators for UI display."""
    INFO       = "ℹ️"
    SUCCESS    = "✅"
    WARNING    = "⚠️"
    ERROR      = "❌"
    DEBUG      = "🔍"
    WAIT       = "⏳"
    RETRY      = "🔄"
    NAVIGATION = "🧭"
    EXTRACTION = "📊"
    UPLOAD     = "📤"
    UPLOAD_OK  = "📎"
    VALIDATION = "🔎"
    FILL       = "✏️"
    SELECT     = "📋"
    CLICK      = "🖱️"
    SKIP       = "⏭️"
    POPUP      = "💬"


# ── Portal ID → Display Tag ──────────────────────────────────────────────────

_PORTAL_TAGS = {
    "uiic":      "UIIC",
    "newindia":  "NIA",
}


def _ts() -> str:
    """Current timestamp as HH:MM:SS.mmm"""
    return datetime.now().strftime("%H:%M:%S.") + f"{datetime.now().microsecond // 1000:03d}"


class AutomationLogger:
    """
    Production-grade structured logger for automation modules.

    Usage:
        log = AutomationLogger("DRIVER_DETAILS", log_cb, portal_id="newindia")
        log.info("Starting Driver Details section")
        log.field_filled("Driver Name", "John Doe")
        log.field_skipped("Badge Number", reason="Optional, not in Excel")
        log.section_start("Driver Details")
        log.section_done("Driver Details")
        log.error("License Type dropdown", "Timeout after 5s")
    """

    def __init__(
        self,
        section: str,
        log_cb: Callable[[str], None],
        portal_id: str = "uiic",
        python_logger: Optional[logging.Logger] = None,
    ):
        self._section = section
        self._log_cb = log_cb
        self._portal_tag = _PORTAL_TAGS.get(portal_id.lower(), portal_id.upper())
        self._py_logger = python_logger or logging.getLogger(f"automation.{section.lower()}")
        self._start_time: Optional[float] = None
        self._indent_level = 1

    @property
    def indent_level(self) -> int:
        return self._indent_level

    @indent_level.setter
    def indent_level(self, value: int):
        self._indent_level = max(0, value)

    def indent(self):
        """Increase indentation."""
        self._indent_level += 1

    def outdent(self):
        """Decrease indentation."""
        self._indent_level = max(0, self._indent_level - 1)

    # ── Core emit ─────────────────────────────────────────────────────────────

    def _emit(self, icon: str, message: str, *, indent: Optional[int] = None, py_level: int = logging.INFO):
        """Emit a formatted log line to both UI callback and Python logger."""
        ts = _ts()
        level = indent if indent is not None else self._indent_level
        pad = "  " * level
        line = f"[{ts}] {pad}{icon} {message}"
        self._log_cb(line)
        self._py_logger.log(py_level, f"[{self._portal_tag}][{self._section}] {message}")

    def raw(self, text: str):
        """Emit raw unformatted text (for separators, blank lines, banners)."""
        self._log_cb(text)

    # ── Standard Levels ───────────────────────────────────────────────────────

    def info(self, message: str, indent: Optional[int] = None):
        self._emit(LogLevel.INFO, message, indent=indent)

    def success(self, message: str, indent: Optional[int] = None):
        self._emit(LogLevel.SUCCESS, message, indent=indent)

    def warning(self, message: str, indent: Optional[int] = None):
        self._emit(LogLevel.WARNING, message, indent=indent, py_level=logging.WARNING)

    def error(self, context: str, detail: str = "", indent: Optional[int] = None):
        msg = f"{context}: {detail}" if detail else context
        self._emit(LogLevel.ERROR, msg, indent=indent, py_level=logging.ERROR)

    def debug(self, message: str, indent: Optional[int] = None):
        self._emit(LogLevel.DEBUG, message, indent=indent, py_level=logging.DEBUG)

    # ── Action-Specific Levels ────────────────────────────────────────────────

    def navigation(self, message: str, indent: Optional[int] = None):
        self._emit(LogLevel.NAVIGATION, message, indent=indent)

    def extraction(self, message: str, indent: Optional[int] = None):
        self._emit(LogLevel.EXTRACTION, message, indent=indent)

    def upload(self, message: str, indent: Optional[int] = None):
        self._emit(LogLevel.UPLOAD, message, indent=indent)

    def validation(self, message: str, indent: Optional[int] = None):
        self._emit(LogLevel.VALIDATION, message, indent=indent)

    def click(self, message: str, indent: Optional[int] = None):
        self._emit(LogLevel.CLICK, message, indent=indent)

    def skip(self, message: str, indent: Optional[int] = None):
        self._emit(LogLevel.SKIP, message, indent=indent)

    def popup(self, message: str, indent: Optional[int] = None):
        self._emit(LogLevel.POPUP, message, indent=indent)

    # ── Wait / Retry ──────────────────────────────────────────────────────────

    def wait(self, what: str, detail: str = "", indent: Optional[int] = None):
        msg = f"Waiting for {what}..." + (f" ({detail})" if detail else "")
        self._emit(LogLevel.WAIT, msg, indent=indent)

    def retry(self, what: str, attempt: int, max_attempts: int, indent: Optional[int] = None):
        self._emit(LogLevel.RETRY, f"{what} — retry {attempt}/{max_attempts}", indent=indent)

    # ── Field-Level Actions ───────────────────────────────────────────────────

    def field_filled(self, label: str, value: str, indent: Optional[int] = None):
        """Log a successfully filled form field."""
        display_val = str(value)[:60]
        self._emit(LogLevel.SUCCESS, f"[{label}] filled → '{display_val}'", indent=indent)

    def field_selected(self, label: str, value: str, indent: Optional[int] = None):
        """Log a successfully selected dropdown value."""
        self._emit(LogLevel.SUCCESS, f"[{label}] selected → '{value}'", indent=indent)

    def field_skipped(self, label: str, reason: str = "Missing from Excel", indent: Optional[int] = None):
        """Log a skipped field."""
        self._emit(LogLevel.SKIP, f"[{label}] — {reason}", indent=indent)

    def field_failed(self, label: str, error: str, indent: Optional[int] = None):
        """Log a failed field action."""
        self._emit(LogLevel.WARNING, f"[{label}] failed: {error}", indent=indent, py_level=logging.WARNING)

    # ── Section Boundaries ────────────────────────────────────────────────────

    def section_start(self, name: str, step: Optional[str] = None):
        """Log the start of a major section with visual separator."""
        self._start_time = time.time()
        self.raw("")
        self.raw(f"{'━' * 56}")
        header = f"  {step} — {name}" if step else f"  {name}"
        self.raw(header)
        self.raw(f"{'━' * 56}")

    def section_done(self, name: str, show_duration: bool = True):
        """Log the completion of a section."""
        if show_duration and self._start_time:
            elapsed = time.time() - self._start_time
            self.success(f"{name} completed ({elapsed:.1f}s)")
        else:
            self.success(f"{name} completed")

    def section_failed(self, name: str, reason: str = ""):
        """Log the failure of a section."""
        msg = f"{name} FAILED" + (f": {reason}" if reason else "")
        self.error(msg)

    # ── Phase Boundaries (Engine-level) ───────────────────────────────────────

    def startup_banner(self, claim_no: str, claim_type: str, survey_date: str, loss_amount: str):
        """Display a prominent startup banner with claim details."""
        self.raw(f"╔{'═' * 54}╗")
        self.raw(f"║  🚀 AUTOMATION STARTED                                ║")
        self.raw(f"╠{'═' * 54}╣")
        self.raw(f"║  Claim No:    {claim_no:<38} ║")
        self.raw(f"║  Claim Type:  {claim_type:<38} ║")
        self.raw(f"║  Survey Date: {survey_date:<38} ║")
        self.raw(f"║  Initial Loss:{loss_amount:<38} ║")
        self.raw(f"╚{'═' * 54}╝")

    def phase_banner(self, phase_num: int, total: int, name: str, icon: str = "📝"):
        """Display a prominent phase banner in the engine log."""
        self.raw("")
        self.raw(f"{'━' * 56}")
        self.raw(f"  {icon} STEP {phase_num}/{total} — {name}")
        self.raw(f"{'━' * 56}")

    def phase_done_banner(self, message: str, lines: Optional[list] = None):
        """Display the final completion banner."""
        self.raw(f"╔{'═' * 54}╗")
        self.raw(f"║  {message:<52} ║")
        if lines:
            self.raw(f"╠{'═' * 54}╣")
            for line in lines:
                self.raw(f"║  {line:<52} ║")
        self.raw(f"╚{'═' * 54}╝")

    # ── Upload Helpers ────────────────────────────────────────────────────────

    def upload_start(self, doc_type: str, filename: str, indent: Optional[int] = None):
        self._emit(LogLevel.UPLOAD, f"Uploading [{doc_type}] ← {filename}", indent=indent)

    def upload_attached(self, doc_type: str, filename: str, indent: Optional[int] = None):
        self._emit(LogLevel.UPLOAD_OK, f"[{doc_type}] attached → '{filename}'", indent=indent)

    def upload_failed(self, doc_type: str, reason: str, indent: Optional[int] = None):
        self._emit(LogLevel.WARNING, f"[{doc_type}] upload failed: {reason}", indent=indent, py_level=logging.WARNING)

    def merge_result(self, filename: str, size_mb: float, file_count: int, indent: Optional[int] = None):
        self._emit(LogLevel.SUCCESS, f"Merged PDF: {filename} ({size_mb:.1f}MB, {file_count} files)", indent=indent)

    # ── Accordion/Panel Helpers ───────────────────────────────────────────────

    def accordion_opened(self, name: str, indent: int = 1):
        self.success(f"Expanded '{name}' section", indent=indent)

    def accordion_already_open(self, name: str, indent: int = 1):
        self.info(f"'{name}' already expanded", indent=indent)

    def accordion_failed(self, name: str, error: str, indent: int = 1):
        self.warning(f"Could not expand '{name}': {error}", indent=indent)

    # ── Extraction Helpers ────────────────────────────────────────────────────

    def extracted(self, field: str, value: str, indent: Optional[int] = None):
        display_val = str(value)[:60]
        self._emit(LogLevel.EXTRACTION, f"Extracted [{field}] → '{display_val}'", indent=indent)

    def extraction_failed(self, field: str, reason: str = "", indent: Optional[int] = None):
        msg = f"Could not extract [{field}]" + (f": {reason}" if reason else "")
        self._emit(LogLevel.WARNING, msg, indent=indent, py_level=logging.WARNING)
