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
  - Production-grade structured JSON log file output per claim run
  - Unique correlation/session UUID generation
  - Fully thread-safe operations guarded by re-entrant locks
  - Detailed exception logging with automated traceback captures
"""

import json
import logging
import os
import threading
import time
import traceback
import uuid
from datetime import datetime
from typing import Callable, Optional

# ── Log Level Tags ────────────────────────────────────────────────────────────


class LogLevel:
    """Visual log level indicators for UI display."""

    INFO = "ℹ️"
    SUCCESS = "✅"
    WARNING = "⚠️"
    ERROR = "❌"
    DEBUG = "🔍"
    WAIT = "⏳"
    RETRY = "🔄"
    NAVIGATION = "🧭"
    EXTRACTION = "📊"
    UPLOAD = "📤"
    UPLOAD_OK = "📎"
    VALIDATION = "🔎"
    FILL = "✏️"
    SELECT = "📋"
    CLICK = "🖱️"
    SKIP = "⏭️"
    POPUP = "💬"


# ── Portal ID → Display Tag ──────────────────────────────────────────────────

_PORTAL_TAGS = {
    "uiic": "UIIC",
    "newindia": "NEW INDIA",
    "oic": "OIC",
}


def _ts() -> str:
    """Current timestamp as HH:MM:SS.mmm"""
    return (
        datetime.now().strftime("%H:%M:%S.")
        + f"{datetime.now().microsecond // 1000:03d}"
    )


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
        claim_no: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ):
        # 1. Lock initialized first for thread-safe property assignment
        self._lock = threading.RLock()

        # 2. Assign section through the thread-safe property setter
        self.section = section
        self._log_cb = log_cb
        self._portal_id = portal_id
        self._portal_tag = _PORTAL_TAGS.get(portal_id.lower(), portal_id.upper())
        self._py_logger = python_logger or logging.getLogger(
            f"automation.{section.lower()}"
        )
        self._start_time: Optional[float] = None
        self._indent_level = 1

        # Production structured logging enhancements
        self.correlation_id = correlation_id or str(uuid.uuid4())
        self._claim_no = claim_no
        self._json_log_file = None
        if claim_no:
            self.set_claim_context(claim_no, portal_id)

    def set_claim_context(
        self, claim_no: str, portal_id: str, log_file_path: Optional[str] = None
    ):
        """Set the claim and portal context, resolving the structured JSON log path."""
        with self._lock:
            self._claim_no = claim_no
            self._portal_id = portal_id
            self._portal_tag = _PORTAL_TAGS.get(portal_id.lower(), portal_id.upper())

            if log_file_path:
                self._json_log_file = log_file_path
            else:
                # Resolve target path: logs/<portal_id>/<claim_no>_run_<timestamp>.json
                from app.utils import user_data_dir, ensure_dir

                log_dir = ensure_dir(user_data_dir("logs", portal_id.lower()))
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                # PID is appended to make it unique per process execution
                filename = f"{claim_no}_run_{ts}_{os.getpid()}.json"
                self._json_log_file = os.path.join(log_dir, filename)

    def write_historical_logs(self, logs: list[str]):
        """Write pre-existing plain text logs (like scanner logs) to the JSON file retrospectively."""
        if not logs or not self._json_log_file:
            return
        with self._lock:
            try:
                base_time = datetime.now()
                # Open the JSON log file once to write all logs in a single batch
                with open(self._json_log_file, "a", encoding="utf-8") as f:
                    for i, log_line in enumerate(logs):
                        # Add a 1-microsecond sequence offset per line to ensure perfect sorting sequence
                        offset_time = base_time.replace(
                            microsecond=(base_time.microsecond + i) % 1000000
                        )
                        entry = {
                            "timestamp": offset_time.isoformat(),
                            "correlation_id": self.correlation_id,
                            "portal_id": self._portal_id,
                            "claim_no": self._claim_no or "unknown_claim",
                            "section": "SCANNER",
                            "level": "INFO",
                            "icon": "📁",
                            "message": log_line.strip(),
                            "extra": {},
                        }
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception as e:
                self._py_logger.warning(f"Failed to batch write historical logs: {e}")

    def _write_json_log(self, entry: dict):
        if not self._json_log_file:
            return
        try:
            with self._lock:
                with open(self._json_log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            # Safe fallback: do not crash if writing to JSON fails
            self._py_logger.warning(f"Failed to write structured log line to JSON: {e}")

    @property
    def section(self) -> str:
        """Thread-safe getter for the active logging section."""
        with self._lock:
            return self.__dict__.get("_section_val", "SCANNER")

    @section.setter
    def section(self, value: str):
        """Thread-safe setter for the active logging section."""
        with self._lock:
            self.__dict__["_section_val"] = value

    @property
    def _section(self) -> str:
        """Backward compatible thread-safe getter mapping to public property."""
        return self.section

    @_section.setter
    def _section(self, value: str):
        """Backward compatible thread-safe setter mapping to public property."""
        self.section = value

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

    def _emit(
        self,
        icon: str,
        message: str,
        *,
        indent: Optional[int] = None,
        py_level: int = logging.INFO,
        extra: Optional[dict] = None,
    ):
        """Emit a formatted log line to both UI callback and Python logger."""
        with self._lock:
            ts = _ts()
            level = indent if indent is not None else self._indent_level
            pad = "  " * level

            if "\n" in message:
                lines = message.split("\n")
                line = f"[{ts}] {pad}{icon} {lines[0]}"
                for sub in lines[1:]:
                    line += f"\n{pad}{sub}"
            else:
                line = f"[{ts}] {pad}{icon} {message}"

            # Emit to standard visual UI callback (backward compatible plain text)
            self._log_cb(line)

            # Emit to standard Python logger
            py_message = message.replace("\n", " | ")
            self._py_logger.log(
                py_level, f"[{self._portal_tag}][{self.section}] {py_message}"
            )

            # Write to structured JSON log
            level_name = logging.getLevelName(py_level)
            entry = {
                "timestamp": datetime.now().isoformat(),
                "correlation_id": self.correlation_id,
                "portal_id": self._portal_id,
                "claim_no": self._claim_no or "unknown_claim",
                "section": self.section,
                "level": level_name,
                "icon": icon,
                "message": message,
                "extra": extra or {},
            }
            self._write_json_log(entry)

    def raw(self, text: str):
        """Emit raw unformatted text (for separators, blank lines, banners)."""
        with self._lock:
            self._log_cb(text)

            entry = {
                "timestamp": datetime.now().isoformat(),
                "correlation_id": self.correlation_id,
                "portal_id": self._portal_id,
                "claim_no": self._claim_no or "unknown_claim",
                "section": self.section,
                "level": "RAW",
                "icon": "",
                "message": text,
                "extra": {},
            }
            self._write_json_log(entry)

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

    def exception(self, context: str, exc: Exception, indent: Optional[int] = None):
        """Log a detailed traceback and error details for an exception."""
        # Clean robust traceback extraction directly from exception object
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        detail = f"{type(exc).__name__}: {exc}"
        msg = f"{context} FAILED: {detail}"

        extra = {
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback": tb,
        }
        self._emit(
            LogLevel.ERROR, msg, indent=indent, py_level=logging.ERROR, extra=extra
        )
        with self._lock:
            self._py_logger.error(
                f"[{self._portal_tag}][{self.section}] Traceback:\n{tb}"
            )

    def debug(self, message: str, indent: Optional[int] = None):
        self._emit(LogLevel.DEBUG, message, indent=indent, py_level=logging.DEBUG)

    def step(
        self, current: int, total: int, message: str, indent: Optional[int] = None
    ):
        """Log a numbered step within a section (e.g., Step 1/3)."""
        self._emit(LogLevel.INFO, f"Step {current}/{total}: {message}", indent=indent)

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

    def retry(
        self, what: str, attempt: int, max_attempts: int, indent: Optional[int] = None
    ):
        self._emit(
            LogLevel.RETRY, f"{what} — retry {attempt}/{max_attempts}", indent=indent
        )

    # ── Field-Level Actions ───────────────────────────────────────────────────

    def field_filled(
        self,
        label: str,
        value: str,
        indent: Optional[int] = None,
        source: str = "Excel",
    ):
        """Log a successfully filled form field."""
        if self._portal_id == "oic":
            display_val = str(value)
            msg = f"[{self._portal_tag}][{self._section}] — Filling {label}\n    • Source: {source}\n    • Value:  {display_val}"
            extra = {"field": label, "value": value, "source": source}
            self._emit(LogLevel.SUCCESS, msg, indent=indent, extra=extra)
        elif self._portal_id == "newindia":
            display_val = str(value)
            msg = f"[{self._portal_tag}][{self._section}]\nField: {label}\nSource: {source}\nValue:  {display_val}\nStatus: Filled Successfully"
            extra = {
                "field": label,
                "value": value,
                "source": source,
                "status": "Filled Successfully",
            }
            self._emit(LogLevel.SUCCESS, msg, indent=indent, extra=extra)
        elif self._portal_id == "uiic":
            display_val = str(value)
            msg = f"[{self._portal_tag}][Field Mapping]\nUI Field:    {label}\nMapped From: {source}\nValue:       {display_val}"
            extra = {"field": label, "value": value, "source": source}
            self._emit(LogLevel.SUCCESS, msg, indent=indent, extra=extra)
        else:
            display_val = str(value)[:60]
            self._emit(
                LogLevel.SUCCESS, f"[{label}] filled → '{display_val}'", indent=indent
            )

    def field_selected(
        self,
        label: str,
        value: str,
        indent: Optional[int] = None,
        source: str = "Excel",
    ):
        """Log a successfully selected dropdown value."""
        if self._portal_id == "oic":
            display_val = str(value)
            msg = f"[{self._portal_tag}][{self._section}] — Selecting {label}\n    • Source: {source}\n    • Value:  {display_val}"
            extra = {"field": label, "value": value, "source": source}
            self._emit(LogLevel.SUCCESS, msg, indent=indent, extra=extra)
        elif self._portal_id == "newindia":
            display_val = str(value)
            msg = f"[{self._portal_tag}][{self._section}]\nField: {label}\nSource: {source}\nValue:  {display_val}\nStatus: Selected Successfully"
            extra = {
                "field": label,
                "value": value,
                "source": source,
                "status": "Selected Successfully",
            }
            self._emit(LogLevel.SUCCESS, msg, indent=indent, extra=extra)
        elif self._portal_id == "uiic":
            display_val = str(value)
            msg = f"[{self._portal_tag}][Field Mapping]\nUI Field:    {label}\nMapped From: {source}\nValue:       {display_val}"
            extra = {"field": label, "value": value, "source": source}
            self._emit(LogLevel.SUCCESS, msg, indent=indent, extra=extra)
        else:
            self._emit(
                LogLevel.SUCCESS, f"[{label}] selected → '{value}'", indent=indent
            )

    def field_skipped(
        self,
        label: str,
        reason: str = "Missing from Excel",
        indent: Optional[int] = None,
    ):
        """Log a skipped field."""
        if self._portal_id == "oic":
            msg = f"[{self._portal_tag}][{self._section}] — {label} skipped\n    • Reason: {reason}"
            extra = {"field": label, "reason": reason}
            self._emit(LogLevel.SKIP, msg, indent=indent, extra=extra)
        elif self._portal_id == "newindia":
            skip_reason = (
                "No value extracted from source Excel"
                if "excel" in reason.lower() or "missing" in reason.lower()
                else reason
            )
            msg = f"[{self._portal_tag}][{self._section}]\nField: {label}\nStatus: Skipped\nReason: {skip_reason}"
            extra = {"field": label, "status": "Skipped", "reason": skip_reason}
            self._emit(LogLevel.SKIP, msg, indent=indent, extra=extra)
        elif self._portal_id == "uiic":
            msg = f"[{self._portal_tag}][Field Mapping]\nUI Field: {label}\nStatus:   Skipped\nReason:   {reason}"
            extra = {"field": label, "status": "Skipped", "reason": reason}
            self._emit(LogLevel.SKIP, msg, indent=indent, extra=extra)
        else:
            self._emit(LogLevel.SKIP, f"[{label}] — {reason}", indent=indent)

    def field_failed(self, label: str, error: str, indent: Optional[int] = None):
        """Log a failed field action."""
        if self._portal_id == "oic":
            msg = f"[{self._portal_tag}][{self._section}] — {label} failed\n    • Reason: {error}"
            extra = {"field": label, "error": error}
            self._emit(
                LogLevel.WARNING,
                msg,
                indent=indent,
                py_level=logging.WARNING,
                extra=extra,
            )
        elif self._portal_id == "newindia":
            msg = f"[{self._portal_tag}][{self._section}]\nField: {label}\nStatus: Failed\nReason: {error}"
            extra = {"field": label, "status": "Failed", "reason": error}
            self._emit(
                LogLevel.WARNING,
                msg,
                indent=indent,
                py_level=logging.WARNING,
                extra=extra,
            )
        elif self._portal_id == "uiic":
            msg = f"[{self._portal_tag}][Field Mapping]\nUI Field: {label}\nStatus:   Failed\nReason:   {error}"
            extra = {"field": label, "status": "Failed", "error": error}
            self._emit(
                LogLevel.WARNING,
                msg,
                indent=indent,
                py_level=logging.WARNING,
                extra=extra,
            )
        else:
            self._emit(
                LogLevel.WARNING,
                f"[{label}] failed: {error}",
                indent=indent,
                py_level=logging.WARNING,
            )

    def validation_failed(
        self,
        field: str,
        value: str,
        reason: str,
        retry: Optional[str] = None,
        indent: Optional[int] = None,
    ):
        """Log a failed validation on a field/value, optionally with a retry string."""
        if self._portal_id == "oic":
            msg = f"[{self._portal_tag}][{self._section}] — {field} validation failed\n    • Value:  {value}\n    • Reason: {reason}"
            if retry:
                msg += f"\n    • Retry:  {retry}"
            extra = {"field": field, "value": value, "reason": reason, "retry": retry}
            self._emit(
                LogLevel.WARNING,
                msg,
                indent=indent,
                py_level=logging.WARNING,
                extra=extra,
            )
        elif self._portal_id == "newindia":
            msg = f"[{self._portal_tag}][Validation]\nField:  {field}\nResult: Failed\nReason: {reason}"
            if retry:
                msg += f"\nRetry:  {retry}"
            extra = {
                "field": field,
                "value": value,
                "result": "Failed",
                "reason": reason,
                "retry": retry,
            }
            self._emit(
                LogLevel.WARNING,
                msg,
                indent=indent,
                py_level=logging.WARNING,
                extra=extra,
            )
        elif self._portal_id == "uiic":
            msg = f"[{self._portal_tag}][Validation]\n{field} Failed\nReason: {reason}"
            extra = {"field": field, "value": value, "reason": reason, "retry": retry}
            self._emit(
                LogLevel.WARNING,
                msg,
                indent=indent,
                py_level=logging.WARNING,
                extra=extra,
            )
        else:
            retry_suffix = f" (Retry: {retry})" if retry else ""
            self._emit(
                LogLevel.WARNING,
                f"[{field}] validation failed: '{value}' - {reason}{retry_suffix}",
                indent=indent,
                py_level=logging.WARNING,
            )

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

    def startup_banner(
        self, claim_no: str, claim_type: str, survey_date: str, loss_amount: str
    ):
        """Display a prominent startup banner with claim details."""
        self.raw(f"╔{'═' * 54}╗")
        self.raw("║  🚀 AUTOMATION STARTED                                ║")
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
        if self._portal_id == "oic":
            msg = f"[{self._portal_tag}][Document Upload] — Uploading {doc_type}\n    • File:   {filename}\n    • Status: In Progress"
            extra = {
                "doc_type": doc_type,
                "filename": filename,
                "status": "In Progress",
            }
            self._emit(LogLevel.UPLOAD, msg, indent=indent, extra=extra)
        elif self._portal_id == "newindia":
            msg = f"[{self._portal_tag}][Document Upload]\nUploading {doc_type}\nFile:   {filename}\nStatus: In Progress"
            extra = {
                "doc_type": doc_type,
                "filename": filename,
                "status": "In Progress",
            }
            self._emit(LogLevel.UPLOAD, msg, indent=indent, extra=extra)
        elif self._portal_id == "uiic":
            msg = f"[{self._portal_tag}][Document Upload]\nUploading {doc_type}\nFile:   {filename}"
            extra = {
                "doc_type": doc_type,
                "filename": filename,
                "status": "In Progress",
            }
            self._emit(LogLevel.UPLOAD, msg, indent=indent, extra=extra)
        else:
            self._emit(
                LogLevel.UPLOAD, f"Uploading [{doc_type}] ← {filename}", indent=indent
            )

    def upload_attached(
        self, doc_type: str, filename: str, indent: Optional[int] = None
    ):
        if self._portal_id == "oic":
            msg = f"[{self._portal_tag}][Document Upload] — Uploading {doc_type}\n    • File:   {filename}\n    • Status: Success"
            extra = {"doc_type": doc_type, "filename": filename, "status": "Success"}
            self._emit(LogLevel.UPLOAD_OK, msg, indent=indent, extra=extra)
        elif self._portal_id == "newindia":
            msg = f"[{self._portal_tag}][Document Upload]\nUploading {doc_type}\nFile:   {filename}\nStatus: Success"
            extra = {"doc_type": doc_type, "filename": filename, "status": "Success"}
            self._emit(LogLevel.UPLOAD_OK, msg, indent=indent, extra=extra)
        elif self._portal_id == "uiic":
            msg = f"[{self._portal_tag}][Document Upload]\nUpload Successful"
            extra = {"doc_type": doc_type, "filename": filename, "status": "Success"}
            self._emit(LogLevel.UPLOAD_OK, msg, indent=indent, extra=extra)
        else:
            self._emit(
                LogLevel.UPLOAD_OK,
                f"[{doc_type}] attached → '{filename}'",
                indent=indent,
            )

    def upload_failed(self, doc_type: str, reason: str, indent: Optional[int] = None):
        if self._portal_id == "oic":
            msg = f"[{self._portal_tag}][Document Upload] — Uploading {doc_type}\n    • File:   N/A\n    • Status: Failed\n    • Reason: {reason}"
            extra = {"doc_type": doc_type, "status": "Failed", "reason": reason}
            self._emit(
                LogLevel.WARNING,
                msg,
                indent=indent,
                py_level=logging.WARNING,
                extra=extra,
            )
        elif self._portal_id == "newindia":
            msg = f"[{self._portal_tag}][Document Upload]\nUpload Failed\nDocument: {doc_type}\nReason:   {reason}\nRetry:    Exhausted"
            extra = {
                "doc_type": doc_type,
                "status": "Failed",
                "reason": reason,
                "retry": "Exhausted",
            }
            self._emit(
                LogLevel.WARNING,
                msg,
                indent=indent,
                py_level=logging.WARNING,
                extra=extra,
            )
        elif self._portal_id == "uiic":
            msg = f"[{self._portal_tag}][Document Upload]\nUpload Failed\nDocument: {doc_type}\nReason:   {reason}\nRetry:    Exhausted"
            extra = {
                "doc_type": doc_type,
                "status": "Failed",
                "reason": reason,
                "retry": "Exhausted",
            }
            self._emit(
                LogLevel.WARNING,
                msg,
                indent=indent,
                py_level=logging.WARNING,
                extra=extra,
            )
        else:
            self._emit(
                LogLevel.WARNING,
                f"[{doc_type}] upload failed: {reason}",
                indent=indent,
                py_level=logging.WARNING,
            )

    def merge_result(
        self,
        filename: str,
        size_mb: float,
        file_count: int,
        indent: Optional[int] = None,
    ):
        self._emit(
            LogLevel.SUCCESS,
            f"Merged PDF: {filename} ({size_mb:.1f}MB, {file_count} files)",
            indent=indent,
        )

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
        self._emit(
            LogLevel.EXTRACTION, f"Extracted [{field}] → '{display_val}'", indent=indent
        )

    def extraction_failed(
        self, field: str, reason: str = "", indent: Optional[int] = None
    ):
        msg = f"Could not extract [{field}]" + (f": {reason}" if reason else "")
        self._emit(LogLevel.WARNING, msg, indent=indent, py_level=logging.WARNING)

    # ── New India Specialized Helpers ─────────────────────────────────────────

    def excel_extracted(
        self,
        field: str,
        value: str,
        cell: str,
        indent: Optional[int] = None,
        sheet: str = "Summary",
    ):
        """Log a successfully extracted Excel field."""
        if self._portal_id == "newindia":
            msg = f"[{self._portal_tag}][Excel Extraction]\nField: {field}\nValue: {value}\nSource Cell: {cell}"
            extra = {"field": field, "value": value, "source_cell": cell}
            self._emit(LogLevel.EXTRACTION, msg, indent=indent, extra=extra)
        elif self._portal_id == "uiic":
            msg = f"[{self._portal_tag}][Excel Extraction]\nField: {field}\nValue: {value}\nSheet: {sheet}\nCell:  {cell}"
            extra = {"field": field, "value": value, "sheet": sheet, "cell": cell}
            self._emit(LogLevel.EXTRACTION, msg, indent=indent, extra=extra)
        else:
            self._emit(
                LogLevel.EXTRACTION,
                f"Extracted [{field}] from Cell {cell} → '{value}'",
                indent=indent,
            )

    def ocr_processed(
        self, doc_name: str, fields: dict[str, str], indent: Optional[int] = None
    ):
        """Log OCR processing results."""
        if self._portal_id == "newindia":
            lines = [f"[{self._portal_tag}][OCR]", f"Processing {doc_name}"]
            for k, v in fields.items():
                lines.append(f"{k} Extracted: {v}")
            msg = "\n".join(lines)
            extra = {"document": doc_name, "extracted_fields": fields}
            self._emit(LogLevel.EXTRACTION, msg, indent=indent, extra=extra)
        elif self._portal_id == "uiic":
            lines = [f"[{self._portal_tag}][OCR]", f"{doc_name} OCR Started"]
            for k, v in fields.items():
                lines.append(f"  • {k} Extracted: {v}")
            msg = "\n".join(lines)
            extra = {"document": doc_name, "extracted_fields": fields}
            self._emit(LogLevel.EXTRACTION, msg, indent=indent, extra=extra)
        else:
            self._emit(
                LogLevel.EXTRACTION,
                f"OCR complete for [{doc_name}]: {fields}",
                indent=indent,
            )

    def document_mapped(
        self,
        doc_type: str,
        matched_file: str,
        status: str = "Matched Successfully",
        indent: Optional[int] = None,
        source: str = "Folder Scan",
    ):
        """Log document mapping results."""
        if self._portal_id == "newindia":
            msg = f"[{self._portal_tag}][Document Mapping]\nDocument Type: {doc_type}\nMatched File:  {matched_file}\nStatus:        {status}"
            extra = {
                "doc_type": doc_type,
                "matched_file": matched_file,
                "status": status,
            }
            self._emit(LogLevel.INFO, msg, indent=indent, extra=extra)
        elif self._portal_id == "uiic":
            msg = f"[{self._portal_tag}][Document Mapping]\nDocument Type: {doc_type}\nMatched File:  {matched_file}\nSource:        {source}\nStatus:        {status}"
            extra = {
                "doc_type": doc_type,
                "matched_file": matched_file,
                "source": source,
                "status": status,
            }
            self._emit(LogLevel.INFO, msg, indent=indent, extra=extra)
        else:
            self._emit(
                LogLevel.INFO,
                f"Mapped [{doc_type}] → '{matched_file}' ({status})",
                indent=indent,
            )

    def field_mapped(
        self, ui_field: str, source_field: str, value: str, indent: Optional[int] = None
    ):
        """Log field mapping results."""
        if self._portal_id == "newindia":
            msg = f"[{self._portal_tag}][Field Mapping]\nUI Field:     {ui_field}\nMapped From:  {source_field}\nValue:        {value}"
            extra = {"ui_field": ui_field, "source_field": source_field, "value": value}
            self._emit(LogLevel.INFO, msg, indent=indent, extra=extra)
        elif self._portal_id == "uiic":
            msg = f"[{self._portal_tag}][Field Mapping]\nUI Field:     {ui_field}\nMapped From:  {source_field}\nValue:        {value}"
            extra = {"ui_field": ui_field, "source_field": source_field, "value": value}
            self._emit(LogLevel.INFO, msg, indent=indent, extra=extra)
        else:
            self._emit(
                LogLevel.INFO,
                f"Field Mapping [{ui_field}] ← '{source_field}' ({value})",
                indent=indent,
            )

    def retry_failed(
        self,
        operation: str,
        attempt: int,
        max_attempts: int,
        reason: str,
        indent: Optional[int] = None,
    ):
        """Log a failed operation retry attempt."""
        if self._portal_id in ("newindia", "uiic"):
            msg = f"[{self._portal_tag}][Retry]\n{operation} Failed\nAttempt: {attempt}/{max_attempts}\nReason:  {reason}"
            extra = {
                "operation": operation,
                "attempt": attempt,
                "max_attempts": max_attempts,
                "reason": reason,
            }
            self._emit(LogLevel.RETRY, msg, indent=indent, extra=extra)
        else:
            self.retry(
                f"{operation} failed: {reason}", attempt, max_attempts, indent=indent
            )

    def dom_recovery(
        self, issue: str, action: str, status: str, indent: Optional[int] = None
    ):
        """Log DOM Stale or recovery details."""
        if self._portal_id in ("newindia", "uiic"):
            msg = f"[{self._portal_tag}][DOM Recovery]\n{issue}\n{action}\nStatus: {status}"
            extra = {"issue": issue, "action": action, "status": status}
            self._emit(
                LogLevel.WARNING,
                msg,
                indent=indent,
                py_level=logging.WARNING,
                extra=extra,
            )
        else:
            self.warning(
                f"DOM Recovery: {issue} -> {action} -> {status}", indent=indent
            )

    def section_transition(self, completed_sec: str, duration: float, next_sec: str):
        """Log section transitions clearly."""
        if self._portal_id in ("newindia", "uiic"):
            msg = f"[{self._portal_tag}]\nCompleted: {completed_sec}\nDuration:  {duration:.1f} sec\n\nMoving To:\n{next_sec}"
            self.raw(f"\n{LogLevel.NAVIGATION} {msg}\n")
        else:
            self.success(f"{completed_sec} completed ({duration:.1f}s)")
            self.info(f"Moving to {next_sec}")

    def performance_metric(
        self, metric_name: str, duration: float, indent: Optional[int] = None
    ):
        """Log performance timings."""
        if self._portal_id in ("newindia", "uiic"):
            msg = f"[{self._portal_tag}][Performance]\n{metric_name}\nDuration: {duration:.1f} sec"
            extra = {"metric_name": metric_name, "duration": duration}
            self._emit(LogLevel.INFO, msg, indent=indent, extra=extra)
        else:
            self.info(f"Performance: {metric_name} took {duration:.1f}s", indent=indent)
