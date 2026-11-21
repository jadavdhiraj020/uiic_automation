"""Plain-English error translation and automatic failure screenshots for New India."""

from __future__ import annotations

import glob
import os
import re
from datetime import datetime
from typing import Optional

from app.utils import automation_logs_dir, ensure_dir


_MAX_SCREENSHOTS = 50

_REASON_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(?:timeout|timed out|exceeded)\b", "New India took too long to respond."),
    (
        r"target closed|browser has been closed|page closed|context closed|target page, context or browser",
        "Chrome was closed or disconnected.",
    ),
    (
        r"strict mode violation|resolved to \d+ elements",
        "Multiple matching controls were found on the page.",
    ),
    (
        r"intercepts pointer events|not clickable|element is outside|obscured",
        "A popup or overlay blocked clicking on the page.",
    ),
    (
        r"element is not enabled|\bdisabled\b|\breadonly\b",
        "This button or field is currently locked on the portal.",
    ),
    (
        r"waiting for locator|waiting for selector|not found in dom|no element found",
        "Could not find this field or button on the current screen.",
    ),
    (
        r"no such file|file not found|\benoent\b",
        "The required file was not found in the claim folder.",
    ),
    (
        r"\b1536\b|file size|too large|exceeds the limit|maximum size",
        "The file is too large for New India (max 1.5 MB).",
    ),
    (
        r"\bduplicate\b",
        "This document name is already uploaded on the portal.",
    ),
    (
        r"\b(?:required|mandatory)\b",
        "New India requires a value here.",
    ),
    (
        r"\b(?:invalid|rejected|validation)\b",
        "New India rejected this value. Check the message beside it in Chrome.",
    ),
    (
        r"net::|err_connection|err_internet|connection reset|disconnected",
        "Network connection to New India was interrupted.",
    ),
)

# Signs that a message carries a raw Playwright/Python error instead of App3's
# own plain-English wording. API names are matched case-sensitively so a normal
# sentence ending in "page." is not mistaken for "Page.click(...)".
_TECHNICAL_MARKERS_CS = re.compile(
    r"\b(?:Locator|Page|Frame|ElementHandle|BrowserContext|Browser)\.[a-z_]\w*|"
    r"Call log:|Traceback|\b[A-Z]\w*(?:Error|Exception)\b|\bException\b"
)
_TECHNICAL_MARKERS_CI = re.compile(
    r"\bselector\b|\bxpath\b|ng-model|data-ng-|\b0x[0-9a-f]+\b|stacktrace|\bdom\b|"
    r"waiting for (?:locator|selector|element|navigation|event|load state|url)|"
    r"\btimeout \d+ ?ms\b|net::|\berr_[a-z_]+\b|\berrno\b|winerror|\benoent\b|"
    r"no such file or directory|strict mode violation|intercepts pointer events|"
    r"element is not (?:enabled|visible|attached|editable|stable)|"
    r"target (?:page|closed)|has been closed",
    re.I,
)

_MAX_CLEAN_LEN = 400


def _looks_technical(text: str) -> bool:
    return bool(_TECHNICAL_MARKERS_CS.search(text) or _TECHNICAL_MARKERS_CI.search(text))


def newindia_operator_reason(
    raw_error: str,
    fallback: str = "Could not complete this step. Check Chrome.",
) -> str:
    """Convert raw Playwright/Python errors into clear plain-English reasons.

    Text that already reads as plain English (App3's own wording or the portal's
    popup text) is returned unchanged, so instructions like "manual solve
    required" are never replaced by a generic reason.
    """
    text = " ".join(str(raw_error or "").split()).strip()
    if not text:
        return fallback

    if not _looks_technical(text):
        if len(text) <= _MAX_CLEAN_LEN:
            return text
        return text[: _MAX_CLEAN_LEN - 3].rstrip() + "..."

    # Keep a clean prefix like "FIR Date field error: Locator.click..." and
    # translate only the raw error after it.
    prefix, detail = "", text
    parts = re.split(r":\s", text, maxsplit=1)
    if len(parts) == 2:
        head = parts[0].strip()
        if " " in head and len(head) <= 100 and not _looks_technical(head):
            prefix, detail = head, parts[1].strip()

    friendly = next(
        (reason for pattern, reason in _REASON_PATTERNS if re.search(pattern, detail, re.I)),
        fallback,
    )
    return f"{prefix} — {friendly}" if prefix else friendly


def _safe_slug(value: str, default: str = "step", max_len: int = 40) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").strip()).strip("_")
    return (cleaned[:max_len] or default).lower()


async def capture_newindia_screenshot(
    page,
    step_name: str,
    log,
    *,
    reason: str = "",
    claim_no: str = "",
) -> Optional[str]:
    """Save a PNG screenshot of the live New India page and log it cleanly."""
    if page is None:
        return None
    try:
        if page.is_closed():
            return None
    except Exception:
        return None

    try:
        shots_dir = ensure_dir(automation_logs_dir("newindia", "screenshots"))
        claim_part = _safe_slug(
            claim_no or getattr(log, "_claim_no", None) or "claim",
            default="claim",
            max_len=30,
        )
        step_part = _safe_slug(step_name, default="step", max_len=36)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(shots_dir, f"{claim_part}_{step_part}_{ts}.png")

        await page.screenshot(path=filepath, full_page=False, timeout=8000)

        # Keep the screenshots folder tidy (latest 50 files).
        try:
            existing = sorted(
                glob.glob(os.path.join(shots_dir, "*.png")),
                key=lambda p: (os.path.getmtime(p), p),
            )
            for old_path in existing[:-_MAX_SCREENSHOTS]:
                if os.path.abspath(old_path) != os.path.abspath(filepath):
                    os.remove(old_path)
        except Exception:
            pass

        page_url = ""
        try:
            page_url = str(getattr(page, "url", "") or "")
        except Exception:
            pass

        if hasattr(log, "record_screenshot"):
            log.record_screenshot(step_name, filepath, reason=reason, page_url=page_url)
        elif callable(log):
            log(f"📸 Screenshot saved ({step_name}): {os.path.basename(filepath)}")

        return filepath
    except Exception:
        return None
