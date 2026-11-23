"""AI debug report (step 1): one Markdown file that explains a run to an AI assistant.

What this module is
-------------------
A passive, read-only helper. When "AI debug report" is switched ON in the Logs tab,
the automation logger hands every warning, error and step result to a recorder.
The recorder keeps them (with the exact place in the code that logged them and the
real error behind them) and writes ``<run log name>_ai_debug.md`` next to the normal
``.json`` / ``.txt`` run logs. It also copies in the run settings (secrets hidden),
the claim input check and the end of the readable run log, so one file is enough
to find the cause of a problem.

What it never does
------------------
* It never touches the browser or the portal (no listeners, no page scripts).
* It never raises into automation code: every public method swallows its own errors.
* When the switch is OFF this module is not even instantiated; the only code that
  always runs is the small value-masking helpers below (``mask_sensitive_value``),
  which keep Password / Captcha values out of every log.

This module only uses the standard library so it is safe to import anywhere.
"""

from __future__ import annotations

import collections
import linecache
import logging
import os
import platform
import re
import sys
import tempfile
import threading
import time
import traceback
from datetime import datetime
from typing import Any, Callable, Optional

REPORT_SUFFIX = "_ai_debug.md"
MASK = "********"

_MAX_TIMELINE = 800
_MAX_FAILURES = 60
_FULL_FAILURES_SHOWN = 12
_LOG_TAIL_LINES = 250
_LOG_TAIL_BYTES = 90_000
_SCAN_LINES = 150
_WRITE_GAP_S = 1.0
_HELPER_FILES = ("automation_logger.py", "debug_recorder.py", "run_diagnostics.py")

_py_logger = logging.getLogger(__name__)

# ── Secret masking ────────────────────────────────────────────────────────────

# Portal field labels whose typed value must never reach a log.
_SENSITIVE_LABEL_RE = re.compile(r"pass(?:word|wd|code)|\bpwd\b|captcha|\botp\b|secret", re.I)
# Settings / header / payload keys whose value is a credential.
_SENSITIVE_KEY_RE = re.compile(
    r"pass(?:word|wd)|pwd|secret|token|cookie|authoriz|api[_-]?key|bearer|csrf|credential"
    r"|^user(?:name|_?id)?$|^login(?:_?id)?$",
    re.I,
)
_URL_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|token|api[_-]?key|secret|access_token|session(?:id)?)=([^&\s\"']+)"
)
_BEARER_RE = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+")
_HEADER_RE = re.compile(r"(?i)\b(cookie|set-cookie|authorization)\s*:\s*[^\r\n]+")
# Playwright error text can echo what was typed, e.g.  fill("my-secret")
_TYPED_CALL_RE = re.compile(
    r"""\b(fill|type|press_sequentially|insert_text)\(\s*(["'])(?:\\.|(?!\2).)*\2"""
)


def is_sensitive_label(label: Any) -> bool:
    """True for portal field labels such as "Password" or "Captcha"."""
    return bool(_SENSITIVE_LABEL_RE.search(str(label or "")))


def mask_sensitive_value(label: Any, value: Any) -> Any:
    """Return ``********`` instead of the value when the field label is sensitive.

    Values of every other field are returned untouched (same object), so normal
    field logging is unchanged.
    """
    if not is_sensitive_label(label):
        return value
    try:
        if value is None or str(value) == "":
            return value
    except Exception:
        pass
    return MASK


def scrub_typed_values(text: Any) -> str:
    """Hide the text a Playwright error message echoes back from fill("...")/type("...")."""
    return _TYPED_CALL_RE.sub(lambda m: f"{m.group(1)}({m.group(2)}{MASK}{m.group(2)}", str(text or ""))


def redact_text(text: Any) -> str:
    """Hide bearer tokens, cookie/authorization headers and password-like URL parameters."""
    out = str(text if text is not None else "")
    out = _BEARER_RE.sub(lambda m: f"{m.group(1)} [REDACTED]", out)
    out = _HEADER_RE.sub(lambda m: f"{m.group(1)}: [REDACTED]", out)
    out = _URL_SECRET_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", out)
    return out


def redact_secrets(value: Any, _depth: int = 0) -> Any:
    """Recursively hide credential values in dicts, lists and strings."""
    if _depth > 6:
        return "(nested data omitted)"
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            key_text = str(key)
            if _SENSITIVE_KEY_RE.search(key_text):
                cleaned[key_text] = MASK if item not in (None, "", [], {}) else "(empty)"
            elif key_text.startswith("_"):
                cleaned[key_text] = "(internal value omitted)"
            else:
                cleaned[key_text] = redact_secrets(item, _depth + 1)
        return cleaned
    if isinstance(value, (list, tuple, set)):
        return [redact_secrets(item, _depth + 1) for item in list(value)[:60]]
    if isinstance(value, str):
        text = redact_text(value)
        return text if len(text) <= 300 else text[:297] + "..."
    return value


# ── Code location ─────────────────────────────────────────────────────────────

def _norm(path: Any) -> str:
    return "/" + str(path or "").replace("\\", "/").lstrip("/")


def relative_source_path(filename: Any) -> str:
    """``C:/x/proj/app/automation/engine.py`` -> ``app/automation/engine.py``."""
    norm = _norm(filename)
    idx = norm.rfind("/app/")
    if idx >= 0:
        return norm[idx + 1:]
    parts = [p for p in norm.split("/") if p]
    return "/".join(parts[-2:]) if parts else "(unknown)"


def is_project_file(filename: Any) -> bool:
    norm = _norm(filename).lower()
    return "/app/" in norm and "/site-packages/" not in norm and "/.venv" not in norm


def _source_snippet(filename: str, lineno: int, context: int = 4) -> str:
    """Source lines around ``lineno`` with ``>>>`` on the active line, or "" if unavailable."""
    lines = []
    found_main = False
    for number in range(max(1, lineno - context), lineno + context + 1):
        text = linecache.getline(filename, number)
        if not text:
            continue
        if number == lineno:
            found_main = True
        marker = ">>>" if number == lineno else "   "
        lines.append(f"{marker} {number:5d} | {text.rstrip()}")
    return "\n".join(lines) if found_main else ""


def _location(filename: str, function: str, lineno: int, context: int) -> dict:
    return {
        "file": relative_source_path(filename),
        "function": function,
        "line": int(lineno),
        "snippet": _source_snippet(filename, int(lineno), context),
    }


def capture_code_context(
    exc: Optional[BaseException] = None,
    *,
    context_lines: int = 4,
    max_chain: int = 5,
) -> dict:
    """Find where something was logged (and, for errors, where it was raised).

    Returns ``{"logged_at", "raised_at", "chain", "exc"}``:
      * ``logged_at`` - the first stack frame outside the logging helpers;
      * ``raised_at`` - the deepest app frame of ``exc`` (or of the exception being
        handled right now), i.e. the line that really failed;
      * ``chain``     - up to ``max_chain`` app frames, innermost first.
    Any part that cannot be found is ``None`` / empty; this never raises.
    """
    result: dict = {"logged_at": None, "raised_at": None, "chain": [], "exc": ""}
    try:
        frame = sys._getframe(1)
        hops = 0
        while frame is not None and hops < 80:
            code = frame.f_code
            if os.path.basename(_norm(code.co_filename)) not in _HELPER_FILES:
                if result["logged_at"] is None:
                    result["logged_at"] = _location(code.co_filename, code.co_name, frame.f_lineno, context_lines)
                if is_project_file(code.co_filename) and len(result["chain"]) < max_chain:
                    result["chain"].append(
                        f"{relative_source_path(code.co_filename)}:{frame.f_lineno} in {code.co_name}"
                    )
                if result["logged_at"] is not None and len(result["chain"]) >= max_chain:
                    break
            frame = frame.f_back
            hops += 1
    except Exception:
        pass
    try:
        error = exc if exc is not None else sys.exc_info()[1]
        if error is not None:
            result["exc"] = redact_text(f"{type(error).__name__}: {error}")[:500]
            deepest = None
            tb = error.__traceback__
            while tb is not None:
                code = tb.tb_frame.f_code
                if (
                    is_project_file(code.co_filename)
                    and os.path.basename(_norm(code.co_filename)) not in _HELPER_FILES
                ):
                    deepest = (code.co_filename, code.co_name, tb.tb_lineno)
                tb = tb.tb_next
            if deepest is not None:
                result["raised_at"] = _location(*deepest, context_lines)
    except Exception:
        pass
    return result


# ── Environment / claim descriptions (all read-only) ─────────────────────────

def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _git_head(root: str) -> str:
    """Branch and short commit read straight from .git (no subprocess)."""
    head_file = os.path.join(root, ".git", "HEAD")
    try:
        with open(head_file, "r", encoding="utf-8") as fh:
            head = fh.read().strip()
        if head.startswith("ref:"):
            ref = head.split(":", 1)[1].strip()
            commit = ""
            ref_file = os.path.join(root, ".git", *ref.split("/"))
            if os.path.isfile(ref_file):
                with open(ref_file, "r", encoding="utf-8") as fh:
                    commit = fh.read().strip()
            else:
                packed = os.path.join(root, ".git", "packed-refs")
                if os.path.isfile(packed):
                    with open(packed, "r", encoding="utf-8") as fh:
                        for line in fh:
                            if line.strip().endswith(" " + ref):
                                commit = line.split()[0]
                                break
            return f"{ref.rsplit('/', 1)[-1]} @ {commit[:9] or 'unknown'}"
        return f"detached @ {head[:9]}"
    except Exception:
        return ""


def _app_version(root: str) -> str:
    try:
        with open(os.path.join(root, "pyproject.toml"), "r", encoding="utf-8") as fh:
            match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', fh.read())
        return match.group(1) if match else ""
    except Exception:
        return ""


def describe_environment() -> list[str]:
    frozen = bool(getattr(sys, "frozen", False))
    lines = [
        f"- Runtime: {'Packaged EXE' if frozen else 'Source (python main.py)'}",
        f"- Python: {platform.python_version()} ({platform.machine() or 'unknown cpu'})",
        f"- Operating system: {platform.platform()}",
    ]
    try:
        from importlib import metadata

        lines.append(f"- Playwright: {metadata.version('playwright')}")
    except Exception:
        lines.append("- Playwright: (version not found)")
    if frozen:
        lines.append(
            "- Code lines: this is a packaged build, so source snippets are not available. "
            "Use the file:line values together with the matching app version."
        )
    else:
        root = _project_root()
        version = _app_version(root)
        git = _git_head(root)
        if version:
            lines.append(f"- App version: {version}")
        if git:
            lines.append(f"- Git: {git}")
    lines.append(f"- Report time: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    return lines


def describe_settings(settings: Optional[dict]) -> list[str]:
    if not settings:
        return ["(no settings were passed to this run)"]
    clean = redact_secrets(dict(settings))
    return [f"- `{key}`: {clean[key]!r}" for key in sorted(clean)]


def describe_claim(claim: Any) -> list[str]:
    """Claim input check: validation messages and the mapped documents (no field values)."""
    lines: list[str] = []
    if claim is None:
        return ["(no claim data)"]
    lines.append(f"- Claim number: {getattr(claim, 'claim_no', '') or '(missing)'}")
    report = str(getattr(claim, "source_report_path", "") or "")
    if report:
        lines.append(f"- Main report file: {os.path.basename(report)}")
    try:
        errors, warnings = claim.validate()
    except Exception as exc:  # validation must never break a run
        errors, warnings = [], []
        lines.append(f"- Validation could not be read: {type(exc).__name__}: {exc}")
    lines.append(f"- Blocking issues ({len(errors)}):" + ("" if errors else " none"))
    lines.extend(f"  - {redact_text(item)}" for item in list(errors)[:40])
    lines.append(f"- Warnings ({len(warnings)}):" + ("" if warnings else " none"))
    lines.extend(f"  - {redact_text(item)}" for item in list(warnings)[:40])
    rows = []
    for attr in ("claim_doc_files", "upload_doc_files"):
        docs = getattr(claim, attr, None) or {}
        for doc_type, path in docs.items():
            path = str(path or "")
            exists = os.path.isfile(path)
            size = f"{os.path.getsize(path) / 1024:.0f} KB" if exists else "-"
            rows.append(f"| {attr} | {_cell(doc_type)} | {_cell(os.path.basename(path))} | {'yes' if exists else 'NO'} | {size} |")
    if rows:
        lines += ["", "| List | Document type | File | Exists | Size |", "|:--|:--|:--|:--|:--|", *rows[:80]]
    else:
        lines.append("- Mapped documents: none")
    return lines


def describe_scan(claim: Any) -> list[str]:
    scan = [str(x) for x in (getattr(claim, "_scan_logs", None) or [])]
    warns = [str(x) for x in (getattr(claim, "_scan_output_warnings", None) or [])]
    if not scan and not warns:
        return ["(no folder-scan lines were attached to this claim)"]
    lines = []
    if len(scan) > _SCAN_LINES:
        lines.append(f"(showing the last {_SCAN_LINES} of {len(scan)} lines)")
    lines.extend(redact_text(x.rstrip())[:300] for x in scan[-_SCAN_LINES:])
    lines.extend(f"WARNING: {redact_text(x)[:300]}" for x in warns[:40])
    return lines


def _cell(text: Any) -> str:
    return " ".join(str(text if text is not None else "").split()).replace("|", "\\|")


def _tail_lines(path: Optional[str]) -> tuple[list[str], int]:
    """Last lines of the readable run log. Returns (lines, total_lines_estimate)."""
    if not path or not os.path.isfile(path):
        return [], 0
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > _LOG_TAIL_BYTES:
                fh.seek(size - _LOG_TAIL_BYTES)
                fh.readline()  # drop the partly cut first line
            text = fh.read().decode("utf-8", "replace")
        lines = text.splitlines()
        return lines[-_LOG_TAIL_LINES:], len(lines)
    except Exception:
        return [], 0


# ── The recorder ──────────────────────────────────────────────────────────────

class AIDebugRecorder:
    """Collects key log events and writes ``<run log>_ai_debug.md``."""

    def __init__(
        self,
        portal_id: str,
        claim_no: str,
        log_path: Optional[str],
        *,
        on_report_path: Optional[Callable[[str], None]] = None,
    ):
        self.enabled = True
        self.portal_id = str(portal_id or "uiic").lower()
        self.claim_no = str(claim_no or "unknown_claim")
        if not log_path:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_path = os.path.join(tempfile.gettempdir(), f"{self.claim_no}_run_{stamp}.json")
        self.report_path = os.path.splitext(log_path)[0] + REPORT_SUFFIX
        self.snapshot_fn: Optional[Callable[[], dict]] = None
        self._on_report_path = on_report_path
        self._path_announced = False
        self._lock = threading.RLock()
        self._t0 = time.time()
        self._timeline: collections.deque = collections.deque(maxlen=_MAX_TIMELINE)
        self._failures: list[dict] = []
        self._counts = {"WARNING": 0, "ERROR": 0}
        self._sections: dict[str, list[str]] = {}
        self._final_status = ""
        self._final_message = ""
        self._last_write = 0.0
        self._write_failed = False
        self._step_echo_prefix = ""
        home = os.path.expanduser("~")
        # Shown as "~" in the report so a pasted report does not carry the Windows user name.
        self._home_paths = sorted({home, home.replace("\\", "/")}, key=len, reverse=True) if len(home) > 3 else []

    # -- run context ---------------------------------------------------------

    def set_context(self, settings: Optional[dict] = None, claim: Any = None) -> None:
        """Capture the static parts of the report once, at the start of the run."""
        for name, build in (
            ("environment", describe_environment),
            ("settings", lambda: describe_settings(settings)),
            ("claim", lambda: describe_claim(claim)),
            ("scan", lambda: describe_scan(claim)),
        ):
            try:
                self._sections[name] = build()
            except Exception as exc:
                self._sections[name] = [f"(could not read this part: {type(exc).__name__}: {exc})"]

    # -- events from the logger ----------------------------------------------

    def note_log(
        self,
        level: str,
        icon: str,
        section: str,
        message: str,
        extra: Optional[dict] = None,
        exc: Optional[BaseException] = None,
    ) -> None:
        """Record a WARNING/ERROR log line with its code location and real error."""
        try:
            if str(section or "") == "Summary":
                return  # the run summary is already shown in section 1 of the report
            level = "ERROR" if str(level).upper() in {"ERROR", "CRITICAL"} else "WARNING"
            extra = extra or {}
            text = redact_text(" ".join(str(message or "").split()))
            prefix = self._step_echo_prefix
            if prefix and text.startswith(prefix):
                self._step_echo_prefix = ""
                return  # the "<step> — Failed" line repeats the step result noted just before
            where = capture_code_context(exc)
            raw = extra.get("raw_error") or extra.get("error_message") or ""
            trace = str(extra.get("traceback") or "")
            if not trace and exc is not None and getattr(exc, "__traceback__", None):
                trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            point = where.get("raised_at") or where.get("logged_at")
            with self._lock:
                self._counts[level] += 1
                self._timeline.append(
                    {
                        "t": time.time(),
                        "level": level,
                        "section": str(section or ""),
                        "text": text[:500],
                        "code": f"{point['file']}:{point['line']}" if point else "",
                    }
                )
                keep = level == "ERROR" or bool(raw or trace or extra.get("field"))
                if keep and len(self._failures) < _MAX_FAILURES:
                    self._failures.append(
                        {
                            "t": time.time(),
                            "level": level,
                            "section": str(section or ""),
                            "icon": icon,
                            "text": text[:800],
                            "raw": redact_text(" ".join(str(raw).split()))[:1500],
                            "traceback": redact_text(trace)[:6000],
                            "where": where,
                        }
                    )
            self._write(force=(level == "ERROR"))
        except Exception:
            pass

    def note_step(self, name: str, ok: bool, duration_s: Optional[float], reason: str = "") -> None:
        try:
            dur = f" ({duration_s:.1f}s)" if duration_s is not None else ""
            text = f"Step '{name}' {'finished' if ok else 'FAILED'}{dur}"
            if reason and not ok:
                text += f": {redact_text(' '.join(str(reason).split()))[:300]}"
            with self._lock:
                self._timeline.append(
                    {"t": time.time(), "level": "STEP" if ok else "ERROR", "section": str(name), "text": text, "code": ""}
                )
                self._step_echo_prefix = "" if ok else f"{name} — Failed"
            self._write(force=False)
        except Exception:
            pass

    def note_info(self, section: str, text: str) -> None:
        """Add a plain milestone to the timeline and write the report straight away."""
        try:
            with self._lock:
                self._timeline.append(
                    {"t": time.time(), "level": "INFO", "section": str(section), "text": redact_text(text)[:300], "code": ""}
                )
            self._write(force=True)
        except Exception:
            pass

    def finalize(self, status: str, final_message: str = "") -> None:
        """Write the finished report (called once from the run summary)."""
        try:
            with self._lock:
                self._final_status = str(status or "")
                self._final_message = redact_text(" ".join(str(final_message or "").split()))[:500]
            self._write(force=True)
        except Exception:
            pass

    # -- report ----------------------------------------------------------------

    def _write(self, force: bool = False) -> bool:
        now = time.monotonic()
        if not force and now - self._last_write < _WRITE_GAP_S:
            return False
        try:
            snap = self._snapshot()
            with self._lock:
                text = self.build_markdown(snap)
                self._last_write = now
            for home in self._home_paths:
                text = text.replace(home, "~")
            folder = os.path.dirname(self.report_path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            tmp = self.report_path + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            os.replace(tmp, self.report_path)
        except Exception as exc:
            if not self._write_failed:
                self._write_failed = True
                _py_logger.warning("AI debug report could not be written: %s", exc)
            return False
        if not self._path_announced:
            self._path_announced = True
            if self._on_report_path is not None:
                try:
                    self._on_report_path(self.report_path)
                except Exception:
                    pass
        return True

    def _snapshot(self) -> dict:
        try:
            return dict(self.snapshot_fn()) if self.snapshot_fn else {}
        except Exception:
            return {}

    def build_markdown(self, snap: Optional[dict] = None) -> str:
        """Render the report. Pure text building; safe to call from tests."""
        snap = snap or {}
        status = self._final_status or "In progress"
        portal = {"uiic": "UIIC", "oic": "OIC", "newindia": "New India"}.get(self.portal_id, self.portal_id.upper())
        started = snap.get("run_started_at") or self._t0
        elapsed = max(0.0, time.time() - started)
        out: list[str] = [
            f"# AI Debug Report — {portal} | Claim {self.claim_no} | {status}",
            "",
            "> Made by App3 for AI assistants. It explains one automation run: what failed, where in the code it was",
            "> logged or raised, the real error text, and the run settings. Password and Captcha field values and other",
            "> credentials are hidden (`********` / `[REDACTED]`). Claim values such as names, numbers and amounts are",
            "> kept on purpose so value or format problems can be spotted. Step 1 of the AI debug report is built from",
            "> App3's own logs only: it has no browser console, network or page snapshots yet.",
            "",
            "## 1. Summary",
            f"- Status: **{status}**" + (f" — {self._final_message}" if self._final_message else ""),
            f"- Portal: {portal}",
            f"- {'Run time' if self._final_status else 'Run time so far'}: {elapsed:.0f}s",
            f"- Correlation ID: {snap.get('correlation_id', '')}",
        ]
        steps = snap.get("steps_completed") or []
        out.append(f"- Steps finished ({len(steps)}): " + (", ".join(str(s) for s in steps) if steps else "none"))
        failed_step = snap.get("failed_step")
        if failed_step:
            out.append(f"- Failed step: {failed_step[0]} — {_cell(failed_step[1])}")
        out.append(
            f"- Fields: {snap.get('fields_filled', 0)} filled, {snap.get('fields_skipped', 0)} skipped, "
            f"{snap.get('fields_failed', 0)} failed"
        )
        out.append(f"- Documents: {snap.get('uploads_ok', 0)} uploaded, {snap.get('uploads_failed', 0)} failed")
        out.append(f"- Problems logged: {self._counts['ERROR']} error(s), {self._counts['WARNING']} warning(s)")
        if self._failures:
            first = self._failures[0]
            point = first["where"].get("raised_at") or first["where"].get("logged_at")
            out.append(
                f"- First problem: [{first['section']}] {_cell(first['text'])}"
                + (f" (`{point['file']}:{point['line']}`)" if point else "")
            )
        out.append("")

        out.append("## 2. Problems in detail (start here)")
        if not self._failures:
            out.append("No errors or field problems were logged yet.")
        for number, item in enumerate(self._failures[:_FULL_FAILURES_SHOWN], 1):
            out += self._render_failure(number, item)
        rest = self._failures[_FULL_FAILURES_SHOWN:]
        if rest:
            out += ["", f"Further problems ({len(rest)}, short form):"]
            for number, item in enumerate(rest, _FULL_FAILURES_SHOWN + 1):
                point = item["where"].get("raised_at") or item["where"].get("logged_at")
                out.append(
                    f"- F{number} [{item['section']}] {_cell(item['text'])[:200]}"
                    + (f" (`{point['file']}:{point['line']}`)" if point else "")
                )
        out.append("")

        out += ["## 3. Timeline of steps and problems", "", "| Time | Level | Section | Event | Code |", "|:--|:--|:--|:--|:--|"]
        for row in self._timeline:
            stamp = datetime.fromtimestamp(row["t"]).strftime("%H:%M:%S")
            out.append(
                f"| {stamp} | {row['level']} | {_cell(row['section'])} | {_cell(row['text'])} | {_cell(row['code'])} |"
            )
        if not self._timeline:
            out.append("| - | - | - | nothing recorded yet | - |")
        out.append("")

        out += ["## 4. Environment", *self._sections.get("environment", ["(not captured)"]), ""]
        out += ["## 5. Run settings (credentials hidden)", *self._sections.get("settings", ["(not captured)"]), ""]
        out += ["## 6. Claim input check", *self._sections.get("claim", ["(not captured)"]), ""]
        out += ["## 7. Folder scan and extraction trace", "```text", *self._sections.get("scan", ["(not captured)"]), "```", ""]

        tail, total = _tail_lines(snap.get("readable_log_file"))
        out.append(f"## 8. End of the readable run log (last {len(tail)} lines)")
        if tail:
            out += ["```text", *(redact_text(line)[:400] for line in tail), "```"]
        else:
            out.append("(the readable run log is not available)")
        out.append("")

        out.append("## 9. Files saved for this run")
        for label, key in (("Readable log", "readable_log_file"), ("Structured log (JSON lines)", "json_log_file")):
            if snap.get(key):
                out.append(f"- {label}: `{os.path.basename(str(snap[key]))}`")
        out.append(f"- This report: `{os.path.basename(self.report_path)}`")
        for step_name, shot in (snap.get("screenshots") or [])[-10:]:
            out.append(f"- Screenshot ({_cell(step_name)}): `{os.path.basename(str(shot))}`")
        out.append("")
        return "\n".join(out)

    def _render_failure(self, number: int, item: dict) -> list[str]:
        where = item["where"]
        lines = [
            "",
            f"### F{number} — [{item['section']}] {_cell(item['text'])[:160]}",
            f"- Time: {datetime.fromtimestamp(item['t']).strftime('%H:%M:%S')} · Level: {item['level']}",
        ]
        logged = where.get("logged_at")
        raised = where.get("raised_at")
        if logged:
            lines.append(f"- Logged at: `{logged['file']}:{logged['line']}` in `{logged['function']}`")
        if raised:
            lines.append(f"- Error raised at: `{raised['file']}:{raised['line']}` in `{raised['function']}`")
        if where.get("exc"):
            lines.append(f"- Exception: {_cell(where['exc'])}")
        if where.get("chain"):
            lines.append("- Called through (innermost first): " + " ← ".join(f"`{c}`" for c in where["chain"]))
        if item.get("raw"):
            lines.append(f"- Raw error text: {_cell(item['raw'])}")
        if item["text"] and len(item["text"]) > 160:
            lines.append(f"- Full message: {_cell(item['text'])}")
        shown = False
        for title, loc in (("Code where it was raised", raised), ("Code where it was logged", logged)):
            if loc and loc.get("snippet"):
                lines += [f"- {title}:", "", "```python", loc["snippet"], "```"]
                shown = True
        if not shown and (logged or raised):
            lines.append("- Source snippet: not available (packaged build or source file missing)")
        if item.get("traceback"):
            lines += ["- Python traceback:", "", "```text", item["traceback"].rstrip(), "```"]
        return lines
