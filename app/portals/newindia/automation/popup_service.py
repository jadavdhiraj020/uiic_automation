"""
popup_service.py — Universal portal popup/modal dismissal service.
New India Assurance portal.

The NIA portal uses a SINGLE Angular-UI modal system for every message type:
  - Upload success banner
  - File-size error ("File size should be less than or equal to 1536 KB")
  - Duplicate document error ("Duplicate Document Name. Please select another")
  - Work Approval confirmation
  - Claim Assessment save confirmation
  - Any other Angular coverChangeObj alert

All modals share the same DOM pattern:
  .modal.in | .modal[style*="display: block"]
  └─ .modal-body           (message text)
  └─ .modal-footer
       └─ button[data-ng-click*="coverChangeObj.cancel"]  ← primary dismiss
       └─ button (generic OK/Close/Yes)                   ← fallback dismiss

This single module replaces all previous duplicate implementations:
  ✗ document_upload_module._dismiss_doc_portal_alert
  ✗ document_upload_module._dismiss_upload_modal
  ✗ document_upload_module._dismiss_initial_document_upload_popup
  ✗ vehicle_photo_module._handle_popup_after_next
  ✗ work_approval_module (inline wait_for block)

Usage:
    from app.portals.newindia.automation.popup_service import dismiss_portal_popup

    # Simple dismiss (bool result):
    dismissed = await dismiss_portal_popup(page, log, max_wait_s=8.0)

    # Classified dismiss (tag string for error-type routing):
    tag = await dismiss_portal_popup(page, log, max_wait_s=3.0, classify=True)
    if tag == "size_error":
        ...  # file was rejected as too large
    elif tag == "duplicate_error":
        ...  # duplicate document name
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Union

from playwright.async_api import Page

from app.automation.automation_logger import AutomationLogger

logger = logging.getLogger(__name__)

# ── JavaScript helpers (same portal, one set of JS) ───────────────────────────

# Detect any visible Angular-UI modal overlay and return metadata
_JS_DETECT_POPUP = r"""
() => {
    // Angular-UI Bootstrap modal (primary NIA pattern)
    const modal = document.querySelector(
        '.modal.in, .modal[style*="display: block"], .modal[style*="display:block"]'
    );
    if (modal) {
        const header = modal.querySelector('.modal-header, .modal-title');
        const body   = modal.querySelector('.modal-body');
        return {
            found: true,
            type:  'modal',
            title: header ? header.innerText.trim() : '',
            body:  body   ? body.innerText.trim().substring(0, 200) : ''
        };
    }
    // SweetAlert / custom overlay (rare but possible)
    const swal = document.querySelector('.swal2-container, .sweet-overlay');
    if (swal) return { found: true, type: 'swal', title: '', body: '' };
    // NG-dialog
    const ngd = document.querySelector('.ngdialog.ngdialog-open');
    if (ngd) return { found: true, type: 'ngdialog', title: '', body: '' };
    return { found: false };
}
"""

# Dismiss the modal by clicking the first available button (priority order)
_JS_DISMISS_POPUP = r"""
() => {
    // Priority 1: NIA-specific coverChangeObj cancel button
    const cancelBtn = document.querySelector(
        'button[data-ng-click*="coverChangeObj.cancel"], button[ng-click*="coverChangeObj.cancel"]'
    );
    if (cancelBtn && cancelBtn.offsetParent !== null) {
        cancelBtn.click();
        return { ok: true, via: 'coverCancel' };
    }

    // Priority 2: generic OK / confirm / close / yes in any visible modal
    const selectors = [
        '.modal.in button[data-ng-click*="ok"]',
        '.modal.in button[ng-click*="ok"]',
        '.modal.in button[data-ng-click*="confirm"]',
        '.modal.in button[ng-click*="confirm"]',
        '.modal.in button[data-ng-click*="close"]',
        '.modal.in button[ng-click*="close"]',
        '.modal.in .modal-footer button:last-child',
        '.modal[style*="display: block"] .modal-footer button:last-child',
        '.modal[style*="display:block"] .modal-footer button:last-child',
    ];
    for (const sel of selectors) {
        const btn = document.querySelector(sel);
        if (btn && btn.offsetParent !== null) {
            btn.click();
            return { ok: true, via: sel };
        }
    }

    // Priority 3: X close icon on any visible modal header
    const closeX = document.querySelector('.modal.in .close, .modal.in button.close');
    if (closeX && closeX.offsetParent !== null) {
        closeX.click();
        return { ok: true, via: 'closeX' };
    }

    return { ok: false, err: 'no dismissible button found' };
}
"""


# ── Popup tag classification ───────────────────────────────────────────────────

def _classify_popup(body: str) -> str:
    """
    Classify a portal popup based on its body text.

    Returns one of:
      'size_error'      — file too large
      'duplicate_error' — duplicate document name
      'success'         — upload/save success banner
      'other'           — anything else
    """
    body_lower = body.lower()
    if "1536" in body_lower or "size" in body_lower:
        return "size_error"
    if "duplicate" in body_lower:
        return "duplicate_error"
    if "success" in body_lower or "uploaded" in body_lower or "updated" in body_lower:
        return "success"
    return "other"


def _log_msg(log, level: str, msg: str) -> None:
    """Dispatch log message to either AutomationLogger or plain callable."""
    if isinstance(log, AutomationLogger):
        getattr(log, level)(msg)
    elif callable(log):
        prefix = {"info": "ℹ️", "success": "✅", "warning": "⚠️", "error": "❌"}.get(level, "")
        log(f"  {prefix} {msg}")


# ── Public API ─────────────────────────────────────────────────────────────────

async def dismiss_portal_popup(
    page: Page,
    log,
    *,
    max_wait_s: float = 8.0,
    classify: bool = False,
    context: str = "",
    verify_closed: bool = True,
) -> Union[str, bool]:
    """
    Poll for and dismiss any visible NIA portal modal.

    Parameters
    ----------
    page        : Playwright Page instance.
    log         : AutomationLogger or plain callable (both supported).
    max_wait_s  : Maximum seconds to poll for a popup before giving up.
    classify    : If True, return a tag string instead of a bool.
                  Useful when the caller needs to react to error type.
                    'size_error'      → file rejected as too large
                    'duplicate_error' → duplicate document name
                    'success'         → upload/save success banner
                    'other'           → unclassified popup dismissed
                    None / False      → no popup appeared
    context     : Optional label for log messages e.g. "after Upload click".
    verify_closed : If True, verify the popup is gone after dismissal and
                    retry once if it is still visible. Default True.

    Returns
    -------
    When classify=False (default): True if popup was dismissed, False if none appeared.
    When classify=True: tag string or None (None means no popup appeared).
    """
    ctx = f" [{context}]" if context else ""
    poll_interval = 0.35
    elapsed = 0.0

    _log_msg(log, "info", f"Polling for portal popup{ctx} (max {max_wait_s:.0f}s)...")

    while elapsed < max_wait_s:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        try:
            popup_info: dict = await page.evaluate(_JS_DETECT_POPUP)
        except Exception as exc:
            _log_msg(log, "warning", f"Popup detection error{ctx}: {str(exc)[:80]}")
            continue

        if not popup_info.get("found"):
            continue

        # ── Popup detected ────────────────────────────────────────────────────
        ptype = popup_info.get("type", "modal")
        title = popup_info.get("title", "")
        body  = popup_info.get("body", "")
        tag   = _classify_popup(body) if body else "other"

        _log_msg(
            log, "info",
            f"Portal popup detected{ctx}: [{ptype}] {title or tag} | {body[:100]}"
        )

        # ── Dismiss ───────────────────────────────────────────────────────────
        try:
            dismiss_res: dict = await page.evaluate(_JS_DISMISS_POPUP)
        except Exception as exc:
            _log_msg(log, "error", f"Popup dismissal JS error{ctx}: {str(exc)[:80]}")
            return None if classify else False

        if not dismiss_res.get("ok"):
            _log_msg(
                log, "warning",
                f"Could not dismiss popup{ctx}: {dismiss_res.get('err', 'unknown')}"
            )
            return None if classify else False

        via = dismiss_res.get("via", "?")
        _log_msg(log, "success", f"Popup dismissed{ctx} via {via} [{tag}]")

        # ── Verify closure (optional retry) ───────────────────────────────────
        if verify_closed:
            await asyncio.sleep(0.8)  # let Angular animate the modal out
            try:
                still_open: dict = await page.evaluate(_JS_DETECT_POPUP)
                if still_open.get("found"):
                    _log_msg(log, "warning", f"Popup still visible{ctx} — retrying once...")
                    await page.evaluate(_JS_DISMISS_POPUP)
                    await asyncio.sleep(0.8)
                    # Check again
                    final_check: dict = await page.evaluate(_JS_DETECT_POPUP)
                    if final_check.get("found"):
                        _log_msg(log, "warning", f"Popup persists{ctx} — continuing anyway.")
                    else:
                        _log_msg(log, "success", f"Popup closed{ctx}.")
                else:
                    _log_msg(log, "success", f"Popup closed{ctx}.")
            except Exception:
                pass  # verification failure is non-fatal

        return tag if classify else True

    # ── No popup appeared within timeout ──────────────────────────────────────
    _log_msg(log, "info", f"No portal popup appeared{ctx} — continuing.")
    return None if classify else False


async def quick_check_and_dismiss(
    page: Page,
    log,
    context: str = "",
) -> Optional[str]:
    """
    Instant (non-polling) popup check — use immediately after attaching a file
    or clicking a button when the portal may show an error synchronously.

    Polls for up to 2 seconds.  Returns tag string or None.
    This is the correct replacement for the inline JS popup checks in
    vehicle_photo_module after each file attachment.
    """
    return await dismiss_portal_popup(
        page, log,
        max_wait_s=2.0,
        classify=True,
        context=context,
        verify_closed=False,  # speed-optimized: no re-verify for instant checks
    )
