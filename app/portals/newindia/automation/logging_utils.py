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

_TECHNICAL_MARKERS = re.compile(
    r"Locator\.|Page\.|Call log:|Traceback|PlaywrightError|TimeoutError|"
    r"RuntimeError|ValueError|TypeError|AttributeError|KeyError|Exception|"
    r"\bselector\b|\bxpath\b|ng-model|data-ng-|\b0x[0-9a-f]+\b|"
    r"waiting for |stacktrace|dom\b",
    re.I,
)


def newindia_operator_reason(
    raw_error: str,
    fallback: str = "Could not complete this step. Check Chrome.",
) -> str:
    """Convert raw Playwright/Python errors into clear plain-English reasons."""
    text = " ".join(str(raw_error or "").split()).strip()
    if not text:
        return fallback

    for pattern, friendly in _REASON_PATTERNS:
        if re.search(pattern, text, re.I):
            return friendly

    # If the text already reads cleanly in plain English, keep it as-is.
    if not _TECHNICAL_MARKERS.search(text) and len(text) <= 180:
        return text

    # Strip any trailing raw exception after a clean prefix like "FIR Date field error: Locator.click..."
    if ":" in text:
        prefix = text.split(":", 1)[0].strip()
        if prefix and not _TECHNICAL_MARKERS.search(prefix) and len(prefix) <= 100:
            return f"{prefix} — {fallback}"

    return fallback


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
