"""AI debug report: one Markdown file that explains a run to an AI assistant.

What this module is
-------------------
A passive, read-only helper. When "AI debug report" is switched ON in the Logs tab,
the automation logger hands every warning, error and step result to a recorder.
The recorder keeps them (with the exact place in the code that logged them and the
real error behind them) and writes ``<run log name>_ai_debug.md`` next to the normal
``.json`` / ``.txt`` run logs. It also copies in the run settings (secrets hidden),
the claim input check and the end of the readable run log, so one file is enough
to find the cause of a problem.

Browser side (only while the switch is ON):

* ``attach_browser`` listens to Chrome's own events: console errors and warnings,
  page script crashes, failed requests and 4xx/5xx replies (with the first 600
  characters of the reply). These listeners only receive events; they never answer,
  block or change anything. There is deliberately **no** ``dialog`` listener: App3's
  own dialog handlers must stay the only ones (an extra one would stop Playwright's
  automatic dismiss, or be wiped by ``remove_all_listeners("dialog")``).
* ``debug_snapshot`` takes one quick, read-only look at the page when a field, a step
  or a pause has a problem (matching elements, their state, dropdown options,
  visible messages, a short piece of HTML). It never clicks, types, focuses or
  scrolls, and it gives up after about one second.

What it never does
------------------
* It never raises into automation code: every public method swallows its own errors
  (only a cancelled run's ``CancelledError`` is passed on).
* When the switch is OFF this module is not even instantiated; the only code that
  always runs is the small value-masking helpers below (``mask_sensitive_value``),
  which keep Password / Captcha values out of every log.

This module only uses the standard library so it is safe to import anywhere.
"""

from __future__ import annotations

import asyncio
import collections
import html as html_lib
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

# Browser capture (step 2)
_MAX_BROWSER_EVENTS = 300          # unique events kept (oldest dropped first)
_MAX_NAVIGATIONS = 60
_MAX_BODY_TASKS = 20               # replies read at the same time
_BODY_TIMEOUT_S = 2.0
_BODY_CHARS = 600
_BROWSER_WRITE_GAP_S = 3.0         # browser events rewrite the report at most every 3 s
_EVENTS_BEFORE_PROBLEM_S = 12.0
_SKIP_URL_PREFIXES = ("data:", "blob:", "chrome-extension:", "devtools:", "about:", "chrome:")
_BODY_CONTENT_TYPES = ("json", "text", "html", "xml", "javascript")
_BODY_RESOURCE_TYPES = ("xhr", "fetch", "document", "")
_QUIET_ABORT_TYPES = ("image", "font", "media", "stylesheet", "ping", "manifest", "other", "texttrack")

# Page snapshots (step 3)
_MAX_SNAPSHOTS = 25
_SNAPSHOT_TIMEOUT_S = 1.0
_ELEMENT_EVAL_TIMEOUT_MS = 600
_SNAPSHOT_MERGE_S = 2.0
_SNAPSHOT_LINK_BEFORE_S = 4.0      # a snapshot may be taken just before the problem is logged
_SNAPSHOT_LINK_AFTER_S = 10.0      # ... or after it (step failures save a screenshot first)

# Report size (step 4)
_MAX_REPORT_BYTES = 1_500_000

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
# JSON / form pairs such as  "password":"x"  or  captcha=1234  inside browser text.
_PAIR_SECRET_RE = re.compile(
    r"""(?i)(["']?\b(?:pass(?:word|wd|code)|pwd|captcha\w*|otp|secret|token|access_token|authorization"""
    r"""|auth_?token|api_?key)["']?\s*[:=]\s*)"""
    r"""("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,&;}"']+)"""
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
    out = _PAIR_SECRET_RE.sub(lambda m: f"{m.group(1)}[REDACTED]", out)
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


# ── Browser and page helpers (steps 2 and 3, all read-only) ──────────────────

def short_url(url: Any, limit: int = 160) -> str:
    """Secrets hidden, long URLs shortened in the middle."""
    text = redact_text(" ".join(str(url or "").split()))
    if len(text) <= limit:
        return text
    return text[: limit - 40] + "…" + text[-39:]


def _url_key(url: Any) -> str:
    """URL without query/fragment, used to group repeated browser events."""
    text = str(url or "")
    for mark in ("?", "#"):
        if mark in text:
            text = text.split(mark, 1)[0]
    return text[:300]


_TAG_BLOCK_RE = re.compile(r"(?is)<(script|style|svg|noscript)\b.*?</\1\s*>")
_COMMENT_RE = re.compile(r"(?s)<!--.*?-->")
_TAG_RE = re.compile(r"(?s)<[^>]+>")
_LONG_ATTR_RE = re.compile(r'''(\s[\w:-]+=)(["'])([^"']{160,})\2''')
_APP3_ATTR_RE = re.compile(r'''\sdata-app3-field-state=(["'])[^"']*\1''')
_INPUT_TAG_RE = re.compile(r"(?is)<(?:input|textarea)\b[^>]*>")
_VALUE_ATTR_RE = re.compile(r'''(?i)(\svalue=)(["'])(?:(?!\2).)*\2''')
_SECRET_INPUT_RE = re.compile(
    r'''(?i)type=["']?password|(?:name|id|placeholder|formcontrolname|ng-model|data-ng-model|aria-label)=["'][^"']*'''
    r'''(?:pass(?:word|wd|code)|pwd|captcha|otp|secret)'''
)


def _mask_secret_inputs(html_text: str) -> str:
    def fix(match: "re.Match[str]") -> str:
        tag = match.group(0)
        if _SECRET_INPUT_RE.search(tag):
            return _VALUE_ATTR_RE.sub(lambda v: f"{v.group(1)}{v.group(2)}{MASK}{v.group(2)}", tag)
        return tag
    return _INPUT_TAG_RE.sub(fix, html_text)


def clean_html(html_text: Any, limit: int) -> str:
    """Short, safe piece of page HTML: no scripts/styles/svg, App3 marks removed, secrets masked."""
    text = str(html_text or "")
    text = _TAG_BLOCK_RE.sub("", text)
    text = _COMMENT_RE.sub("", text)
    text = _APP3_ATTR_RE.sub("", text)
    text = _LONG_ATTR_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)[:60]}…{m.group(2)}", text)
    text = _mask_secret_inputs(text)
    text = redact_text(" ".join(text.split()))
    return text if len(text) <= limit else text[: limit - 1] + "…"


def html_to_text(text: Any) -> str:
    """Visible text of an HTML reply (error pages from the portal or a gateway)."""
    raw = _TAG_BLOCK_RE.sub(" ", str(text or ""))
    raw = _COMMENT_RE.sub(" ", raw)
    raw = _TAG_RE.sub(" ", raw)
    return " ".join(html_lib.unescape(raw).split())


def clean_reply_body(text: Any, content_type: str = "") -> str:
    body = str(text or "")
    if "html" in str(content_type or "").lower() or body.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        body = html_to_text(body)
    body = redact_text(" ".join(body.split()))
    return body if len(body) <= _BODY_CHARS else body[: _BODY_CHARS - 1] + "…"


def _plain(value: Any, limit: int = 300) -> str:
    return redact_text(" ".join(str(value if value is not None else "").split()))[:limit]


# Read-only page scripts. They only read the DOM: no clicks, focus, scroll, typing,
# cloning or attribute changes. Values of password-type or Password/Captcha/OTP-like
# fields are replaced with ******** before they leave the page.
_JS_SNAPSHOT_COMMON = r"""
const clean = (s, n) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim().slice(0, n || 200);
const SENS = /pass(word|wd|code)|\bpwd\b|captcha|\botp\b|secret/i;
const shown = (n) => {
  try {
    if (!n || !n.getClientRects || !n.getClientRects().length) return false;
    const st = window.getComputedStyle(n);
    if (st.visibility === 'hidden' || st.display === 'none') return false;
    return !n.closest('[aria-hidden="true"], [hidden], #__app3-ni-hud');
  } catch (e) { return false; }
};
const labelOf = (el) => {
  try {
    if (el.labels && el.labels.length) return clean(el.labels[0].innerText, 120);
    const aria = el.getAttribute('aria-label');
    if (aria) return clean(aria, 120);
    const by = el.getAttribute('aria-labelledby');
    if (by) { const n = document.getElementById(by.split(' ')[0]); if (n) return clean(n.innerText, 120); }
    const box = el.closest('.form-group, .mat-form-field, .p-field, td, tr');
    const lab = box && box.querySelector('label');
    if (lab) return clean(lab.innerText, 120);
    if (box && box.tagName === 'TD' && box.previousElementSibling) return clean(box.previousElementSibling.innerText, 120);
  } catch (e) {}
  return clean(el.getAttribute && el.getAttribute('placeholder'), 120);
};
const isSecret = (el, label) => {
  const ident = [el.id, el.getAttribute('name'), el.getAttribute('placeholder'), el.getAttribute('formcontrolname'),
                 el.getAttribute('ng-model'), el.getAttribute('data-ng-model'), label].join(' ');
  return String(el.type || '').toLowerCase() === 'password' || SENS.test(ident);
};
"""

_JS_PAGE_STATE = "() => {" + _JS_SNAPSHOT_COMMON + r"""
const out = {url: location.href, title: clean(document.title, 150), ready: document.readyState,
             popups: [], messages: [], headings: [], invalid: [], invalid_total: 0, active: ''};
const seen = [];
const known = (t) => seen.some(s => s === t || s.includes(t));
const dialogs = '.modal.show, .modal.in, .modal[style*="display: block"], [role="dialog"], [role="alertdialog"], ' +
  '.swal2-popup, .sweet-alert, .bootbox, .ui-dialog, .p-dialog, .mat-dialog-container, .mat-mdc-dialog-container';
for (const n of document.querySelectorAll(dialogs)) {
  if (out.popups.length >= 5) break;
  if (!shown(n)) continue;
  const t = clean(n.innerText, 400);
  if (!t || known(t)) continue;
  seen.push(t); out.popups.push(t);
}
const msgs = '.alert, .toast, .toast-message, #toast-container > div, .text-danger, .error, .help-block, ' +
  '.invalid-feedback, [ng-message], [data-ng-message], .p-message, .p-toast-message, .p-inline-message, ' +
  '.mat-error, .mat-mdc-form-field-error, .mat-snack-bar-container, .ui-messages-error, span.err, ' +
  '.validation-message, .field-validation-error';
for (const n of document.querySelectorAll(msgs)) {
  if (out.messages.length >= 20) break;
  if (!shown(n) || n.querySelector('input, select, textarea')) continue;
  const t = clean(n.innerText, 200);
  if (!t || t === '*' || t.length < 2 || known(t)) continue;
  seen.push(t); out.messages.push(t);
}
for (const n of document.querySelectorAll('h1, h2, h3, h4, legend, .panel-title, .card-title, .page-title, .modal-title, .breadcrumb')) {
  if (out.headings.length >= 8) break;
  if (!shown(n)) continue;
  const t = clean(n.innerText, 80);
  if (t && !out.headings.includes(t)) out.headings.push(t);
}
const bad = new Set();
const badSel = 'input.ng-invalid, select.ng-invalid, textarea.ng-invalid, [aria-invalid="true"], .has-error input, ' +
  '.has-error select, .has-error textarea, input:invalid, select:invalid, textarea:invalid';
for (const n of document.querySelectorAll(badSel)) {
  if (bad.has(n) || n.type === 'hidden' || !shown(n)) continue;
  bad.add(n);
  out.invalid_total += 1;
  if (out.invalid.length >= 15) continue;
  const label = labelOf(n);
  const value = n.tagName === 'SELECT' ? (n.selectedOptions && n.selectedOptions[0] ? n.selectedOptions[0].text : '') : n.value;
  out.invalid.push({label, tag: n.tagName.toLowerCase(), id: n.id || '', name: n.getAttribute('name') || '',
                    value: isSecret(n, label) && value ? '********' : clean(value, 80),
                    message: clean(n.validationMessage, 120)});
}
const a = document.activeElement;
if (a && a !== document.body && a !== document.documentElement) {
  out.active = clean(a.tagName.toLowerCase() + (a.id ? '#' + a.id : '') +
                     (a.getAttribute('name') ? '[name=' + a.getAttribute('name') + ']' : ''), 120);
}
return out;
}"""

_JS_ELEMENT_STATE = "(el) => {" + _JS_SNAPSHOT_COMMON + r"""
const label = labelOf(el);
const secret = isSecret(el, label);
const val = (v) => (secret && v) ? '********' : clean(v, 300);
let st = null;
try { st = window.getComputedStyle(el); } catch (e) {}
const out = {
  tag: el.tagName.toLowerCase(), type: el.type || '', id: el.id || '', name: el.getAttribute('name') || '',
  model: el.getAttribute('ng-model') || el.getAttribute('data-ng-model') || el.getAttribute('formcontrolname') || '',
  label, classes: clean(typeof el.className === 'string' ? el.className : '', 200),
  visible: shown(el), display: st ? st.display : '',
  disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
  readonly: !!el.readOnly, required: !!el.required || el.getAttribute('aria-required') === 'true',
  value: ('value' in el) ? val(el.value) : '',
  checked: (['checkbox', 'radio'].includes(String(el.type || '').toLowerCase())) ? !!el.checked : null,
  validation: clean(el.validationMessage, 200), aria_invalid: el.getAttribute('aria-invalid') || '',
  app3_mark: el.getAttribute('data-app3-field-state') || '', secret,
};
if (el.tagName === 'SELECT') {
  const opts = Array.from(el.options || []);
  out.options_total = opts.length;
  out.options = opts.slice(0, 40).map(o => ({text: clean(o.text, 80), value: clean(o.value, 80),
                                            selected: !!o.selected, disabled: !!o.disabled}));
  const chosen = el.selectedOptions && el.selectedOptions[0];
  out.selected_text = chosen ? clean(chosen.text, 120) : '';
}
try {
  const ng = window.angular && window.angular.element(el).controller('ngModel');
  if (ng) {
    out.angular = {errors: Object.keys(ng.$error || {}).filter(k => ng.$error[k]),
                   view_value: ['string', 'number'].includes(typeof ng.$viewValue) ? val(String(ng.$viewValue)) : null,
                   invalid: !!ng.$invalid, pristine: !!ng.$pristine};
  }
} catch (e) {}
try { out.html = String(el.outerHTML || '').slice(0, 4000); } catch (e) {}
try {
  const box = el.closest('.form-group, .mat-form-field, .p-field, td, tr, fieldset, .row');
  if (box && box !== el) out.container_html = String(box.outerHTML || '').slice(0, 8000);
} catch (e) {}
return out;
}"""


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
        # Browser capture (step 2)
        self._browser: collections.deque = collections.deque()
        self._browser_index: dict = {}
        self._browser_seq = 0
        self._browser_dropped = 0
        self._browser_counts: collections.Counter = collections.Counter()
        self._navigations: collections.deque = collections.deque(maxlen=_MAX_NAVIGATIONS)
        self._last_nav: dict[str, str] = {}
        self._tabs: dict[int, str] = {}
        self._context_ids: set[int] = set()
        self._contexts: list = []
        self._page_ids: set[int] = set()
        self._attached: list = []
        self._body_tasks: set = set()
        self._browser_started = False
        self._browser_stopped = False
        self._page_handler = self._attach_page
        # Page snapshots (step 3)
        self._snapshots: list[dict] = []
        self._snapshots_skipped = 0
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
                            "field": str(extra.get("field") or ""),
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
            # The report covers the automation only, not the manual review that follows.
            self.stop_browser_capture()
            self._write(force=True)
        except Exception:
            pass

    # -- browser capture (step 2) ----------------------------------------------

    def attach_browser(self, context: Any) -> None:
        """Listen (read-only) to console errors, page crashes, failed requests and 4xx/5xx replies.

        Called once per run with the Playwright browser context. Tabs opened later are
        picked up through the context's ``page`` event. There is no ``dialog`` listener.
        """
        try:
            if context is None or self._browser_stopped or self._final_status or id(context) in self._context_ids:
                return
            self._context_ids.add(id(context))
            context.on("page", self._page_handler)
            self._contexts.append(context)
            for page in list(getattr(context, "pages", None) or []):
                self._attach_page(page)
            if not self._browser_started:
                self._browser_started = True
                self.note_info("Browser", "Browser error capture started (console, page errors, failed requests)")
        except Exception:
            pass

    def _tab(self, page: Any) -> str:
        key = id(page)
        with self._lock:
            label = self._tabs.get(key)
            if label is None:
                label = f"Tab {len(self._tabs) + 1}"
                self._tabs[key] = label
            return label

    def _attach_page(self, page: Any) -> None:
        try:
            if page is None or self._browser_stopped or id(page) in self._page_ids:
                return
            self._page_ids.add(id(page))
            tab = self._tab(page)
            handlers = [
                ("console", lambda msg: self._on_console(tab, msg)),
                ("pageerror", lambda err: self._on_page_error(tab, err)),
                ("requestfailed", lambda req: self._on_request_failed(tab, req)),
                ("response", lambda resp: self._on_response(tab, resp)),
                ("framenavigated", lambda frame: self._on_navigated(tab, frame)),
            ]
            added = []
            for event, handler in handlers:
                try:
                    page.on(event, handler)
                    added.append((event, handler))
                except Exception:
                    pass
            with self._lock:
                self._attached.append((page, added))
                if len(self._page_ids) > 1:
                    self._navigations.append({"t": time.time(), "tab": tab, "url": "(new tab opened)"})
        except Exception:
            pass

    def stop_browser_capture(self) -> None:
        """Remove App3's debug listeners and stop reading replies. Safe to call many times."""
        try:
            with self._lock:
                if self._browser_stopped:
                    return
                self._browser_stopped = True
                attached, self._attached = self._attached, []
                contexts, self._contexts = self._contexts, []
                tasks = list(self._body_tasks)
            for page, handlers in attached:
                for event, handler in handlers:
                    try:
                        page.remove_listener(event, handler)
                    except Exception:
                        pass
            for context in contexts:
                try:
                    context.remove_listener("page", self._page_handler)
                except Exception:
                    pass
            for task in tasks:
                try:
                    task.cancel()
                except Exception:
                    pass
        except Exception:
            pass

    def _accepting_browser_events(self) -> bool:
        return self.enabled and not self._browser_stopped and not self._final_status

    def _record_browser(self, kind: str, tab: str, text: str, *, url: str = "", where: str = "", **extra: Any):
        """Add (or count again) one browser event. Returns the entry, or None."""
        if not self._accepting_browser_events():
            return None
        now = time.time()
        text = _plain(text, 400)
        key = (kind, tab, text[:200], _url_key(url), where[:120])
        with self._lock:
            self._browser_counts[kind] += 1
            entry = self._browser_index.get(key)
            if entry is not None:
                entry["count"] += 1
                entry["last_t"] = now
            else:
                if len(self._browser) >= _MAX_BROWSER_EVENTS:
                    old = self._browser.popleft()
                    self._browser_index.pop(old.get("_key"), None)
                    self._browser_dropped += 1
                self._browser_seq += 1
                entry = {
                    "id": f"B{self._browser_seq}",
                    "t": now,
                    "last_t": now,
                    "kind": kind,
                    "tab": tab,
                    "text": text,
                    "url": short_url(url) if url else "",
                    "where": where,
                    "count": 1,
                    "body": "",
                    "_key": key,
                    **extra,
                }
                self._browser.append(entry)
                self._browser_index[key] = entry
        self._write(force=False, gap=_BROWSER_WRITE_GAP_S)
        return entry

    def _on_console(self, tab: str, msg: Any) -> None:
        try:
            kind = str(getattr(msg, "type", "") or "").lower()
            if kind not in ("error", "warning", "assert"):
                return
            location = getattr(msg, "location", None) or {}
            where = ""
            if isinstance(location, dict) and location.get("url"):
                where = f"{short_url(location.get('url'), 120)}:{location.get('lineNumber', '')}"
            label = "Console warning" if kind == "warning" else "Console error"
            self._record_browser(label, tab, getattr(msg, "text", "") or "", where=where)
        except Exception:
            pass

    def _on_page_error(self, tab: str, error: Any) -> None:
        try:
            name = str(getattr(error, "name", "") or "Error")
            message = str(getattr(error, "message", "") or error)
            stack = str(getattr(error, "stack", "") or "")
            frames = [line.strip() for line in stack.splitlines()[1:4] if line.strip()]
            self._record_browser("Page script error", tab, f"{name}: {message}", where=_plain(" | ".join(frames), 300))
        except Exception:
            pass

    def _on_request_failed(self, tab: str, request: Any) -> None:
        try:
            url = str(getattr(request, "url", "") or "")
            if not url or url.startswith(_SKIP_URL_PREFIXES):
                return
            failure = getattr(request, "failure", None)
            if isinstance(failure, dict):
                failure = failure.get("errorText")
            failure = str(failure or "failed")
            resource = str(getattr(request, "resource_type", "") or "")
            if "ERR_ABORTED" in failure.upper() and resource in _QUIET_ABORT_TYPES:
                return  # images/fonts cancelled by a page change are normal
            method = str(getattr(request, "method", "") or "GET")
            self._record_browser("Request failed", tab, f"{method} {failure}", url=url, resource=resource)
        except Exception:
            pass

    def _on_response(self, tab: str, response: Any) -> None:
        try:
            status = int(getattr(response, "status", 0) or 0)
            if status < 400:
                return
            url = str(getattr(response, "url", "") or "")
            if not url or url.startswith(_SKIP_URL_PREFIXES) or "favicon" in url.lower():
                return
            request = getattr(response, "request", None)
            method = str(getattr(request, "method", "") or "GET")
            resource = str(getattr(request, "resource_type", "") or "")
            status_text = str(getattr(response, "status_text", "") or "")
            kind = "HTTP 5xx reply" if status >= 500 else "HTTP 4xx reply"
            entry = self._record_browser(
                kind, tab, f"{method} {status} {status_text}".strip(), url=url, resource=resource, status=status,
            )
            if entry is None or entry["count"] != 1 or resource not in _BODY_RESOURCE_TYPES:
                return
            headers = getattr(response, "headers", None) or {}
            content_type = str(headers.get("content-type", "") if isinstance(headers, dict) else "").lower()
            if any(part in content_type for part in _BODY_CONTENT_TYPES):
                self._read_body_later(entry, response, content_type)
        except Exception:
            pass

    def _read_body_later(self, entry: dict, response: Any, content_type: str) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        with self._lock:
            if len(self._body_tasks) >= _MAX_BODY_TASKS:
                entry["body"] = "(reply not read: too many replies at the same time)"
                return
            task = loop.create_task(self._read_body(entry, response, content_type))
            self._body_tasks.add(task)
        task.add_done_callback(self._body_tasks.discard)

    async def _read_body(self, entry: dict, response: Any, content_type: str) -> None:
        try:
            text = await asyncio.wait_for(response.text(), timeout=_BODY_TIMEOUT_S)
            body = clean_reply_body(text, content_type) or "(empty reply)"
        except asyncio.CancelledError:
            raise
        except Exception:
            body = "(reply could not be read)"
        try:
            with self._lock:
                entry["body"] = body
            self._write(force=False, gap=_BROWSER_WRITE_GAP_S)
        except Exception:
            pass

    def _on_navigated(self, tab: str, frame: Any) -> None:
        try:
            if not self._accepting_browser_events() or getattr(frame, "parent_frame", None) is not None:
                return
            url = str(getattr(frame, "url", "") or "")
            if not url or url.startswith(_SKIP_URL_PREFIXES):
                return
            with self._lock:
                if self._last_nav.get(tab) == url:
                    return
                self._last_nav[tab] = url
                self._navigations.append({"t": time.time(), "tab": tab, "url": short_url(url)})
        except Exception:
            pass

    # -- page snapshots (step 3) -------------------------------------------------

    async def capture_page_snapshot(
        self,
        page: Any,
        *,
        target: Any = None,
        selector: str = "",
        label: str = "",
        reason: str = "",
        extra: Optional[dict] = None,
        screenshot: str = "",
    ) -> tuple[str, bool]:
        """One quick read-only look at the page. Returns (snapshot id, newly taken).

        Never clicks, types, focuses or scrolls. Gives up after about one second and
        keeps whatever it read by then. Only a cancelled run's CancelledError escapes.
        """
        try:
            if not self.enabled or self._final_status or page is None or page.is_closed():
                return "", False
            label = _plain(label, 120)
            reason = _plain(reason, 300)
            tab = self._tab(page)
            now = time.time()
            has_target = target is not None or bool(selector)
            with self._lock:
                last = self._snapshots[-1] if self._snapshots else None
                if (
                    last is not None
                    and last["tab"] == tab
                    and now - last["t"] <= _SNAPSHOT_MERGE_S
                    and (not has_target or last["label"] == label)
                ):
                    note = " — ".join(x for x in (label, reason) if x) or "same moment"
                    if note not in last["also"] and len(last["also"]) < 8:
                        last["also"].append(note)
                    if screenshot and not last.get("screenshot"):
                        last["screenshot"] = os.path.basename(str(screenshot))
                    return last["id"], False
                if len(self._snapshots) >= _MAX_SNAPSHOTS:
                    self._snapshots_skipped += 1
                    return "", False
        except Exception:
            return "", False

        data: dict = {}
        error = ""
        started = time.monotonic()
        try:
            await asyncio.wait_for(self._collect_snapshot(page, target, selector, data), timeout=_SNAPSHOT_TIMEOUT_S)
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            error = f"stopped after {_SNAPSHOT_TIMEOUT_S:.0f} s; only the parts read by then are shown"
        except Exception as exc:
            error = _plain(f"{type(exc).__name__}: {exc}", 200)
        try:
            record = self._build_snapshot_record(
                data, tab=tab, label=label, reason=reason, extra=extra, screenshot=screenshot,
                selector=selector, has_target=has_target, error=error,
                took_ms=int((time.monotonic() - started) * 1000), url_fallback=str(getattr(page, "url", "") or ""),
            )
            with self._lock:
                record["id"] = f"S{len(self._snapshots) + 1}"
                self._snapshots.append(record)
                self._timeline.append(
                    {
                        "t": record["t"],
                        "level": "SNAPSHOT",
                        "section": label or "Page",
                        "text": f"Page snapshot {record['id']} saved" + (f": {reason}" if reason else ""),
                        "code": "",
                    }
                )
            self._write(force=True)
            return record["id"], True
        except Exception:
            return "", False

    async def _collect_snapshot(self, page: Any, target: Any, selector: str, data: dict) -> None:
        """Read element state first (most useful for a failed field), then the page state."""
        locator = target
        if locator is None and selector:
            locator = page.locator(selector)
        if locator is not None:
            if hasattr(locator, "count") and hasattr(locator, "first"):
                data["match_count"] = await locator.count()
                if data["match_count"]:
                    data["element"] = await locator.first.evaluate(_JS_ELEMENT_STATE, timeout=_ELEMENT_EVAL_TIMEOUT_MS)
            else:  # an element handle
                data["match_count"] = 1
                data["element"] = await locator.evaluate(_JS_ELEMENT_STATE)
        data["page"] = await page.evaluate(_JS_PAGE_STATE)

    def _build_snapshot_record(self, data: dict, *, tab: str, label: str, reason: str, extra: Optional[dict],
                               screenshot: str, selector: str, has_target: bool, error: str, took_ms: int,
                               url_fallback: str) -> dict:
        page_state = data.get("page") if isinstance(data.get("page"), dict) else {}
        element = data.get("element") if isinstance(data.get("element"), dict) else None
        sensitive = is_sensitive_label(label)
        if element is not None:
            element = dict(element)
            if sensitive or element.get("secret") or is_sensitive_label(
                f"{element.get('label', '')} {element.get('name', '')} {element.get('id', '')}"
            ):
                if element.get("value"):
                    element["value"] = MASK
                if isinstance(element.get("angular"), dict) and element["angular"].get("view_value"):
                    element["angular"] = dict(element["angular"], view_value=MASK)
            for key in ("label", "classes", "value", "validation", "selected_text", "model", "name", "id"):
                if key in element:
                    element[key] = _plain(element.get(key), 300)
            element["html"] = clean_html(element.get("html"), 1000)
            element["container_html"] = clean_html(element.get("container_html"), 2500)
            options = element.get("options")
            if isinstance(options, list):
                element["options"] = [
                    {k: (_plain(v, 80) if isinstance(v, str) else v) for k, v in dict(o).items()}
                    for o in options[:40]
                    if isinstance(o, dict)
                ]
        invalid = []
        for item in list(page_state.get("invalid") or [])[:15]:
            item = dict(item) if isinstance(item, dict) else {}
            if is_sensitive_label(f"{item.get('label', '')} {item.get('name', '')} {item.get('id', '')}") and item.get("value"):
                item["value"] = MASK
            invalid.append({k: _plain(v, 120) for k, v in item.items()})
        clean_extra = {}
        for key, value in (extra or {}).items():
            if value in (None, "", [], {}):
                continue
            if sensitive and "value" in str(key).lower():
                value = MASK
            if isinstance(value, (list, tuple)):
                value = ", ".join(_plain(v, 60) for v in list(value)[:12])
            clean_extra[_plain(key, 40)] = _plain(redact_secrets(value) if isinstance(value, dict) else value, 300)
        return {
            "t": time.time(),
            "tab": tab,
            "label": label,
            "reason": reason,
            "also": [],
            "screenshot": os.path.basename(str(screenshot)) if screenshot else "",
            "selector": _plain(selector, 200),
            "has_target": has_target,
            "match_count": data.get("match_count"),
            "url": short_url(page_state.get("url") or url_fallback, 200),
            "title": _plain(page_state.get("title"), 150),
            "ready": _plain(page_state.get("ready"), 20),
            "active": _plain(page_state.get("active"), 120),
            "popups": [_plain(x, 400) for x in list(page_state.get("popups") or [])[:5]],
            "messages": [_plain(x, 200) for x in list(page_state.get("messages") or [])[:20]],
            "headings": [_plain(x, 80) for x in list(page_state.get("headings") or [])[:8]],
            "invalid": invalid,
            "invalid_total": int(page_state.get("invalid_total") or len(invalid)),
            "element": element,
            "extra": clean_extra,
            "error": error,
            "took_ms": took_ms,
        }

    # -- report ----------------------------------------------------------------

    def _write(self, force: bool = False, gap: float = _WRITE_GAP_S) -> bool:
        now = time.monotonic()
        if not force and now - self._last_write < gap:
            return False
        try:
            snap = self._snapshot()
            with self._lock:
                text = self.build_markdown(snap)
                if len(text) > _MAX_REPORT_BYTES // 2 and len(text.encode("utf-8")) > _MAX_REPORT_BYTES:
                    text = self.build_markdown(snap, compact=True)
                    raw = text.encode("utf-8")
                    if len(raw) > _MAX_REPORT_BYTES:
                        text = raw[: _MAX_REPORT_BYTES - 200].decode("utf-8", "ignore") + (
                            "\n\n(The report was cut here because it reached the 1.5 MB size limit.)\n"
                        )
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

    def build_markdown(self, snap: Optional[dict] = None, *, compact: bool = False) -> str:
        """Render the report. Pure text building; safe to call from tests.

        ``compact`` is used only when the full report would pass the size limit: it keeps
        every problem but shortens the timeline, browser list, snapshots and log tail.
        """
        snap = snap or {}
        status = self._final_status or "In progress"
        portal = {"uiic": "UIIC", "oic": "OIC", "newindia": "New India"}.get(self.portal_id, self.portal_id.upper())
        started = snap.get("run_started_at") or self._t0
        elapsed = max(0.0, time.time() - started)
        browser_events = list(self._browser)
        out: list[str] = [
            f"# AI Debug Report — {portal} | Claim {self.claim_no} | {status}",
            "",
            "> Made by App3 for AI assistants. It explains one automation run: what failed, where in the code it was",
            "> logged or raised, the real error text, browser errors and failed portal calls, and a read-only snapshot",
            "> of the page at each problem. Password and Captcha field values and other credentials are hidden",
            "> (`********` / `[REDACTED]`). Claim values such as names, numbers and amounts are kept on purpose so",
            "> value or format problems can be spotted. App3 only listened to the browser and read the page; it",
            "> did not click, type or change anything for this report.",
        ]
        if compact:
            out.append("> This is the shortened form of the report (the full one passed the 1.5 MB size limit).")
        out += [
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
        out.append("- Browser: " + self._browser_count_text())
        out.append(f"- Page snapshots: {len(self._snapshots)}" + (
            f" ({self._snapshots_skipped} more skipped: limit {_MAX_SNAPSHOTS})" if self._snapshots_skipped else ""
        ))
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
            out += self._render_failure(number, item, browser_events, compact=compact)
        rest = self._failures[_FULL_FAILURES_SHOWN:]
        if rest:
            out += ["", f"Further problems ({len(rest)}, short form):"]
            for number, item in enumerate(rest, _FULL_FAILURES_SHOWN + 1):
                point = item["where"].get("raised_at") or item["where"].get("logged_at")
                snap_id = self._snapshot_for(item)
                out.append(
                    f"- F{number} [{item['section']}] {_cell(item['text'])[:200]}"
                    + (f" (`{point['file']}:{point['line']}`)" if point else "")
                    + (f" · snapshot {snap_id}" if snap_id else "")
                )
        out.append("")

        out += self._render_browser(browser_events, compact=compact)
        out += self._render_snapshots(compact=compact)

        timeline = list(self._timeline)
        if compact and len(timeline) > 200:
            timeline = timeline[-200:]
        out += ["## 5. Timeline of steps and problems", "", "| Time | Level | Section | Event | Code |", "|:--|:--|:--|:--|:--|"]
        for row in timeline:
            stamp = datetime.fromtimestamp(row["t"]).strftime("%H:%M:%S")
            out.append(
                f"| {stamp} | {row['level']} | {_cell(row['section'])} | {_cell(row['text'])} | {_cell(row['code'])} |"
            )
        if not timeline:
            out.append("| - | - | - | nothing recorded yet | - |")
        out.append("")

        out += ["## 6. Environment", *self._sections.get("environment", ["(not captured)"]), ""]
        out += ["## 7. Run settings (credentials hidden)", *self._sections.get("settings", ["(not captured)"]), ""]
        out += ["## 8. Claim input check", *self._sections.get("claim", ["(not captured)"]), ""]
        out += ["## 9. Folder scan and extraction trace", "```text", *self._sections.get("scan", ["(not captured)"]), "```", ""]

        tail, total = _tail_lines(snap.get("readable_log_file"))
        if compact:
            tail = tail[-60:]
        out.append(f"## 10. End of the readable run log (last {len(tail)} lines)")
        if tail:
            out += ["```text", *(redact_text(line)[:400] for line in tail), "```"]
        else:
            out.append("(the readable run log is not available)")
        out.append("")

        out.append("## 11. Files saved for this run")
        for label, key in (("Readable log", "readable_log_file"), ("Structured log (JSON lines)", "json_log_file")):
            if snap.get(key):
                out.append(f"- {label}: `{os.path.basename(str(snap[key]))}`")
        out.append(f"- This report: `{os.path.basename(self.report_path)}`")
        for step_name, shot in (snap.get("screenshots") or [])[-10:]:
            out.append(f"- Screenshot ({_cell(step_name)}): `{os.path.basename(str(shot))}`")
        out.append("")
        return "\n".join(out)

    def _browser_count_text(self) -> str:
        counts = self._browser_counts
        if not self._browser_started and not counts:
            return "not connected yet"
        parts = [
            f"{counts.get('Console error', 0) + counts.get('Console assert', 0)} console error(s)",
            f"{counts.get('Console warning', 0)} console warning(s)",
            f"{counts.get('Page script error', 0)} page script error(s)",
            f"{counts.get('Request failed', 0)} failed request(s)",
            f"{counts.get('HTTP 4xx reply', 0) + counts.get('HTTP 5xx reply', 0)} error reply(ies) (4xx/5xx)",
        ]
        return ", ".join(parts)

    def _render_browser(self, events: list, *, compact: bool) -> list[str]:
        out = ["## 3. Browser errors and failed portal calls"]
        if not self._browser_started and not events:
            out += ["Browser capture had not started (the run stopped before Chrome opened).", ""]
            return out
        out.append(
            "Read-only: App3 only listened to Chrome's console, page errors and network replies. "
            "Repeated events are counted once (`x3`)."
        )
        shown = events[-80:] if compact else events
        if self._browser_dropped or len(shown) < len(events):
            out.append(f"(older events not shown: {self._browser_dropped + len(events) - len(shown)})")
        if not shown:
            out += ["", "No console errors, page errors, failed requests or 4xx/5xx replies were seen.", ""]
        else:
            out += ["", "| # | Time | Tab | Type | What happened | Where | Seen |", "|:--|:--|:--|:--|:--|:--|:--|"]
            for e in shown:
                stamp = datetime.fromtimestamp(e["t"]).strftime("%H:%M:%S")
                where = e.get("url") or e.get("where") or ""
                if e.get("url") and e.get("where"):
                    where = f"{e['url']} ({e['where']})"
                out.append(
                    f"| {e['id']} | {stamp} | {e['tab']} | {e['kind']} | {_cell(e['text'])} | {_cell(where)} | x{e['count']} |"
                )
            replies = [e for e in shown if e.get("body")]
            if replies:
                out += ["", f"Portal replies (first {_BODY_CHARS} characters, secrets hidden):"]
                for e in replies:
                    out.append(f"- {e['id']} {_cell(e['text'])} `{_cell(e.get('url', ''))}`: {_cell(e['body'])}")
            out.append("")
        navs = list(self._navigations)
        if compact:
            navs = navs[-20:]
        out.append("### Pages visited")
        if navs:
            for row in navs:
                out.append(f"- {datetime.fromtimestamp(row['t']).strftime('%H:%M:%S')} · {row['tab']} · {_cell(row['url'])}")
        else:
            out.append("- (no page changes recorded)")
        out.append("")
        return out

    def _render_snapshots(self, *, compact: bool) -> list[str]:
        out = ["## 4. Page snapshots (read-only, taken when something failed or paused)"]
        if not self._snapshots:
            out += ["No page snapshots were needed.", ""]
            return out
        for snap in self._snapshots:
            stamp = datetime.fromtimestamp(snap["t"]).strftime("%H:%M:%S")
            title = " — ".join(x for x in (snap["label"], snap["reason"]) if x) or "Page"
            out += ["", f"### {snap['id']} — {stamp} · {snap['tab']} · {_cell(title)[:160]}"]
            page_line = " — ".join(x for x in (snap.get("title"), snap.get("url")) if x)
            if page_line:
                out.append(f"- Page: {_cell(page_line)}")
            details = []
            if snap.get("ready"):
                details.append(f"page state `{snap['ready']}`")
            if snap.get("active"):
                details.append(f"focused element `{_cell(snap['active'])}`")
            details.append(f"read in {snap.get('took_ms', 0)} ms")
            out.append("- " + ", ".join(details))
            if snap.get("also"):
                out.append("- Also used for: " + "; ".join(_cell(x) for x in snap["also"]))
            if snap.get("screenshot"):
                out.append(f"- Screenshot: `{snap['screenshot']}`")
            for key, value in (snap.get("extra") or {}).items():
                out.append(f"- {key}: {_cell(value)}")
            if snap.get("error"):
                out.append(f"- Note: snapshot {snap['error']}")
            if snap.get("popups"):
                out.append("- Popups on screen:")
                out += [f"  - {_cell(x)}" for x in snap["popups"]]
            if snap.get("messages"):
                out.append("- Messages on screen:")
                out += [f"  - {_cell(x)}" for x in snap["messages"][: 8 if compact else 20]]
            if snap.get("headings"):
                out.append("- Headings: " + " · ".join(_cell(x) for x in snap["headings"]))
            if snap.get("invalid"):
                out += [
                    f"- Fields the page marks invalid ({snap.get('invalid_total', len(snap['invalid']))}):",
                    "",
                    "| Field | Element | Value | Browser message |",
                    "|:--|:--|:--|:--|",
                ]
                for item in snap["invalid"][: 6 if compact else 15]:
                    element = item.get("tag", "") + (f"#{item['id']}" if item.get("id") else "") + (
                        f"[name={item['name']}]" if item.get("name") else ""
                    )
                    out.append(
                        f"| {_cell(item.get('label'))} | `{_cell(element)}` | {_cell(item.get('value'))} | {_cell(item.get('message'))} |"
                    )
                out.append("")
            out += self._render_element(snap, compact=compact)
        if self._snapshots_skipped:
            out += ["", f"({self._snapshots_skipped} more snapshot(s) were skipped: limit {_MAX_SNAPSHOTS} per run)"]
        out.append("")
        return out

    def _render_element(self, snap: dict, *, compact: bool) -> list[str]:
        if not snap.get("has_target"):
            return []
        count = snap.get("match_count")
        selector = f" for `{_cell(snap['selector'])}`" if snap.get("selector") else ""
        element = snap.get("element")
        if count is None and element is None:
            return [f"- Target field{selector}: not read in time"]
        lines = [f"- Target field{selector}: {count if count is not None else '?'} element(s) matched"]
        if not element:
            return lines
        flags = [
            name for name, on in (
                ("visible", element.get("visible")), ("hidden", not element.get("visible")),
                ("disabled", element.get("disabled")), ("read-only", element.get("readonly")),
                ("required", element.get("required")),
            ) if on
        ]
        ident = element.get("tag", "") + (f"#{element['id']}" if element.get("id") else "") + (
            f"[name={element['name']}]" if element.get("name") else ""
        )
        lines.append(f"  - Element: `{_cell(ident)}`" + (f" type `{element['type']}`" if element.get("type") else "")
                     + (f", label \"{_cell(element['label'])}\"" if element.get("label") else ""))
        lines.append("  - State: " + (", ".join(flags) or "-") + (
            f"; App3 mark `{element['app3_mark']}`" if element.get("app3_mark") else ""
        ))
        if element.get("model"):
            lines.append(f"  - Model / form control: `{_cell(element['model'])}`")
        if "value" in element and element.get("tag") != "select":
            lines.append(f"  - Current value: \"{_cell(element.get('value'))}\"")
        if element.get("checked") is not None:
            lines.append(f"  - Checked: {'yes' if element['checked'] else 'no'}")
        if element.get("classes"):
            lines.append(f"  - Classes: `{_cell(element['classes'])}`")
        if element.get("validation") or element.get("aria_invalid"):
            lines.append(
                "  - Browser validation: " + _cell(element.get("validation") or "-")
                + (f" (aria-invalid={element['aria_invalid']})" if element.get("aria_invalid") else "")
            )
        angular = element.get("angular")
        if isinstance(angular, dict):
            errors = ", ".join(str(x) for x in angular.get("errors") or []) or "none"
            lines.append(
                f"  - Angular model: errors {errors}; view value \"{_cell(angular.get('view_value'))}\"; "
                f"{'invalid' if angular.get('invalid') else 'valid'}"
            )
        if element.get("tag") == "select":
            options = element.get("options") or []
            total = element.get("options_total", len(options))
            lines.append(f"  - Selected option: \"{_cell(element.get('selected_text'))}\" (value \"{_cell(element.get('value'))}\")")
            limit = 10 if compact else 40
            listed = ", ".join(
                f"`{_cell(o.get('text'))}`" + (" (selected)" if o.get("selected") else "") + (" (disabled)" if o.get("disabled") else "")
                for o in options[:limit]
            )
            lines.append(f"  - Options ({min(limit, len(options))} of {total} shown): {listed or 'none'}")
        if not compact:
            if element.get("html"):
                lines += ["  - Element HTML:", "", "```html", element["html"], "```"]
            if element.get("container_html"):
                lines += ["  - Surrounding HTML:", "", "```html", element["container_html"], "```"]
        return lines

    def _snapshot_for(self, item: dict) -> str:
        """The page snapshot that belongs to a problem (same field preferred, then nearest in time)."""
        best = None
        for snap in self._snapshots:
            delta = snap["t"] - item["t"]
            if delta < -_SNAPSHOT_LINK_BEFORE_S or delta > _SNAPSHOT_LINK_AFTER_S:
                continue
            names = " ".join([snap["label"], *snap.get("also", [])]).casefold()
            field = str(item.get("field") or "").casefold()
            same_field = bool(field and field in names) or bool(snap["label"] and snap["label"].casefold() in item["text"].casefold())
            score = (0 if same_field else 1, abs(delta))
            if best is None or score < best[0]:
                best = (score, snap["id"])
        return best[1] if best else ""

    def _render_failure(self, number: int, item: dict, browser_events: Optional[list] = None, *, compact: bool = False) -> list[str]:
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
        snap_id = self._snapshot_for(item)
        if snap_id:
            lines.append(f"- Page snapshot: {snap_id} (section 4)")
        near = [
            e for e in (browser_events or [])
            if item["t"] - _EVENTS_BEFORE_PROBLEM_S <= e.get("last_t", e["t"]) and e["t"] <= item["t"] + 1.0
        ]
        if near:
            lines.append(f"- Browser events in the {_EVENTS_BEFORE_PROBLEM_S:.0f} s before (section 3):")
            for e in near[-6:]:
                target = f" `{_cell(e['url'])}`" if e.get("url") else ""
                body = f" — reply: {_cell(e['body'])[:200]}" if e.get("body") else ""
                lines.append(f"  - {e['id']} {e['kind']}: {_cell(e['text'])[:200]}{target}{body}")
        shown = False
        for title, loc in (("Code where it was raised", raised), ("Code where it was logged", logged)):
            if loc and loc.get("snippet"):
                lines += [f"- {title}:", "", "```python", loc["snippet"], "```"]
                shown = True
        if not shown and (logged or raised):
            lines.append("- Source snippet: not available (packaged build or source file missing)")
        if item.get("traceback"):
            trace = item["traceback"].rstrip()
            if compact and len(trace) > 1500:
                trace = "…\n" + trace[-1500:]
            lines += ["- Python traceback:", "", "```text", trace, "```"]
        return lines


# ── Entry point for page snapshots (step 3) ───────────────────────────────────

async def debug_snapshot(
    log: Any,
    page: Any,
    *,
    target: Any = None,
    selector: str = "",
    label: str = "",
    reason: str = "",
    extra: Optional[dict] = None,
    screenshot: str = "",
) -> str:
    """Take a read-only page snapshot for the AI debug report, if the report is ON.

    Does nothing (and touches nothing) when the switch is OFF. Never raises, except
    a cancelled run's CancelledError. Returns the snapshot id ("S3") or "".
    """
    recorder = getattr(log, "_debug_recorder", None)
    if recorder is None or page is None:
        return ""
    try:
        snap_id, is_new = await recorder.capture_page_snapshot(
            page, target=target, selector=selector, label=label, reason=reason, extra=extra, screenshot=screenshot,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        return ""
    if snap_id and is_new and hasattr(log, "info"):
        try:
            log.info(
                f"AI debug report: page snapshot {snap_id} saved" + (f" ({_plain(label, 60)})" if label else ""),
                ui_detail=True,
            )
        except Exception:
            pass
    return snap_id
