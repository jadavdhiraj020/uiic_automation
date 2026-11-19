"""
popup_service.py — OIC portal popup and modal dismissal service.
Handles prompt shields, SweetAlert overlays, warning modals, and custom dialogs.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Union

from playwright.async_api import Page

from app.automation.automation_logger import AutomationLogger

logger = logging.getLogger(__name__)

# Only a visible portal dialog can supply a dismissal button.
_JS_POPUP_SCOPE = r"""
    const visible = node => node.getClientRects().length && getComputedStyle(node).visibility === 'visible';
    const dialogs = document.querySelectorAll(
        '.modal.in, .modal[style*="display"], .swal2-popup, .sweet-alert, .swal-modal, ' +
        '.ngdialog.ngdialog-open, .popup-container, .p-dialog, .p-dynamicdialog, p-dialog'
    );
    const popup = [...dialogs].reverse().find(node => visible(node) &&
        !node.querySelector('.login-formno, #username, #password, .login-wthmobile-box'));
"""

_JS_DETECT_POPUP = r"() => {" + _JS_POPUP_SCOPE + r"""
    if (!popup) return { found: false };
    return {found: true, body: popup.innerText || ''};
}"""

_JS_DISMISS_POPUP = r"() => {" + _JS_POPUP_SCOPE + r"""
    if (!popup) return { ok: false };
    const text = popup.innerText || '';
    // The operator owns the final submission and its confirmation.
    if (/\b(?:are you sure|do you want)\b/i.test(text) ||
        (/\b(?:submit|submission)\b/i.test(text) && /\?|\bconfirm\b/i.test(text))) {
        return { ok: false };
    }
    const buttons = [...popup.querySelectorAll('button, [role=button], a.close, input[type=button]')].filter(visible);
    const label = btn => (btn.getAttribute('aria-label') || btn.innerText || btn.value || '').trim();
    const safe = buttons.filter(btn => !/\bsubmit\b/i.test(label(btn)));
    const button = safe.find(btn => btn.matches('button.p-dialog-header-close, button.close') || /^close$/i.test(label(btn))) ||
        safe.find(btn => /^(?:ok|okay|yes|proceed|accept)$/i.test(label(btn)) || btn.matches('button.swal2-confirm, button.confirm'));
    if (!button) return { ok: false };
    button.click();
    return { ok: true };
}"""


def _classify_popup(body: str) -> str:
    """Classifies OIC alert popups based on content body."""
    body_lower = body.lower()
    if "invalid" in body_lower or "error" in body_lower or "incorrect" in body_lower:
        return "credential_error"
    if "success" in body_lower or "updated" in body_lower or "saved" in body_lower:
        return "success"
    return "other"

def _log_msg(log, level: str, msg: str) -> None:
    if isinstance(log, AutomationLogger):
        getattr(log, level)(msg)
    elif callable(log):
        prefix = {"info": "ℹ️", "success": "✅", "warning": "⚠️", "error": "❌"}.get(level, "")
        log(f"  {prefix} {msg}")

async def dismiss_portal_popup(
    page: Page,
    log,
    *,
    max_wait_s: float = 4.0,
    classify: bool = False,
    context: str = "",
    verify_closed: bool = True,
) -> Union[str, bool]:
    """Universal modal / overlay dismissal helper for OIC."""
    ctx = f" [{context}]" if context else ""
    poll_interval = 0.25
    elapsed = 0.0

    _log_msg(log, "info", f"Scanning for popups/overlays{ctx} (max {max_wait_s:.1f}s)...")

    while elapsed < max_wait_s:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        try:
            popup_info: dict = await page.evaluate(_JS_DETECT_POPUP)
        except Exception:
            continue

        if not popup_info.get("found"):
            continue

        body  = popup_info.get("body", "")
        tag   = _classify_popup(body)

        _log_msg(log, "info", f"OIC is showing a message{ctx}.")

        try:
            from app.web_sync.submission import capture_before_dismiss
            await capture_before_dismiss(page)
            dismiss_res: dict = await page.evaluate(_JS_DISMISS_POPUP)
        except Exception:
            return None if classify else False

        if not dismiss_res.get("ok"):
            return None if classify else False

        if verify_closed:
            await asyncio.sleep(0.5)
            try:
                still_open = await page.evaluate(_JS_DETECT_POPUP)
                if still_open.get("found") and still_open.get("body") == body:
                    return None if classify else False
            except Exception:
                return None if classify else False
        _log_msg(log, "success", f"OIC message acknowledged{ctx}.")

        return tag if classify else True

    return None if classify else False
