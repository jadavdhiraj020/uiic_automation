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

# Detect visible SweetAlert, Angular-UI modals, or standard dialogs
_JS_DETECT_POPUP = r"""
() => {
    // 1. Angular modal or general display block modal
    const modal = document.querySelector(
        '.modal.in, .modal[style*="display: block"], .modal[style*="display:block"]'
    );
    if (modal) {
        const body = modal.querySelector('.modal-body, p');
        return {
            found: true,
            type:  'modal',
            body:  body ? body.innerText.trim().substring(0, 200) : ''
        };
    }
    // 2. SweetAlert overlay
    const swal = document.querySelector('.swal2-container, .sweet-overlay, .swal-overlay');
    if (swal) {
        const body = swal.querySelector('.swal2-html-container, .swal-text');
        return {
            found: true,
            type: 'swal',
            body: body ? body.innerText.trim().substring(0, 200) : ''
        };
    }
    // 3. ng-dialog or other active popup overlay
    const ngd = document.querySelector('.ngdialog.ngdialog-open, .popup-container');
    if (ngd) {
        return {
            found: true,
            type: 'ngdialog',
            body: ngd.innerText.trim().substring(0, 200)
        };
    }
    // 4. PrimeNG dialog / modal popup covers
    const prime = document.querySelector('.p-dialog, .p-dynamicdialog, p-dialog');
    if (prime) {
        const body = prime.querySelector('.p-dialog-content');
        return {
            found: true,
            type: 'primeng',
            body: body ? body.innerText.trim().substring(0, 200) : ''
        };
    }
    return { found: false };
}
"""

# Dismiss the modal by clicking the best available confirm/OK button
_JS_DISMISS_POPUP = r"""
() => {
    // Priority 1: Common confirmation / generic Close / OK buttons in active dialogs
    const selectors = [
        'button.p-dialog-header-close',
        'button[aria-label="Close"]',
        '.p-dialog-header-close-icon',
        '.modal.in button[data-ng-click*="ok"]',
        '.modal.in button[ng-click*="ok"]',
        '.modal.in button[data-ng-click*="close"]',
        '.modal.in button[ng-click*="close"]',
        '.modal.in .modal-footer button',
        '.modal[style*="display: block"] .modal-footer button',
        '.modal[style*="display:block"] .modal-footer button',
        '.swal2-container button.swal2-confirm',
        '.sweet-alert button.confirm',
        '.swal-overlay button.swal-button--confirm',
        '.ngdialog.ngdialog-open button',
        'button.confirm',
        'button.swal2-confirm',
        'button.close, .close',
    ];
    for (const sel of selectors) {
        const btn = document.querySelector(sel);
        if (btn && btn.offsetParent !== null) {
            btn.click();
            return { ok: true, via: sel };
        }
    }

    // Priority 2: Text search fallback on active popup buttons
    const allBtns = document.querySelectorAll(
        '.modal button, .swal2-container button, .sweet-alert button, .swal-overlay button, .ngdialog button, button'
    );
    for (const btn of allBtns) {
        const text = (btn.innerText || btn.textContent || '').trim().toLowerCase();
        if ((text === 'ok' || text === 'yes' || text === 'close' || text === 'submit' || text === 'proceed' || text === 'accept') &&
            btn.offsetParent !== null) {
            btn.click();
            return { ok: true, via: 'genericTextFallback' };
        }
    }

    return { ok: false, err: 'no dismissible button found' };
}
"""

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

        ptype = popup_info.get("type", "modal")
        body  = popup_info.get("body", "")
        tag   = _classify_popup(body)

        _log_msg(log, "info", f"Popup overlay detected{ctx}: [{ptype}] -> {body[:120]}")

        try:
            dismiss_res: dict = await page.evaluate(_JS_DISMISS_POPUP)
        except Exception:
            return None if classify else False

        if not dismiss_res.get("ok"):
            return None if classify else False

        via = dismiss_res.get("via", "unknown")
        _log_msg(log, "success", f"Popup overlay dismissed{ctx} via {via} [{tag}]")

        if verify_closed:
            await asyncio.sleep(0.5)
            try:
                still_open: dict = await page.evaluate(_JS_DETECT_POPUP)
                if still_open.get("found"):
                    await page.evaluate(_JS_DISMISS_POPUP)
                    await asyncio.sleep(0.5)
            except Exception:
                pass

        return tag if classify else True

    return None if classify else False