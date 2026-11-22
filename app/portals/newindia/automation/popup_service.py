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
import re
from typing import Optional, Union

from playwright.async_api import Page

from app.automation.automation_logger import AutomationLogger

logger = logging.getLogger(__name__)

# ── JavaScript helpers (same portal, one set of JS) ───────────────────────────

_JS_VISIBLE_HELPER = r"""
const _visible = el => {
    if (!el || !el.getClientRects().length) return false;
    const style = getComputedStyle(el);
    return style.visibility !== 'hidden' && style.display !== 'none';
};
const _cleanBodyText = bodyEl => {
    if (!bodyEl) return '';
    const clone = bodyEl.cloneNode(true);
    for (const node of clone.querySelectorAll(
        '.modal-footer, button, a.btn, input[type="button"], input[type="submit"], .close, script, style'
    )) {
        node.remove();
    }
    const stripped = (clone.textContent || '').replace(/\s+/g, ' ').trim();
    if (stripped) return stripped;
    return (bodyEl.innerText || bodyEl.textContent || '').replace(/\s+/g, ' ').trim();
};
const _findVisiblePopup = () => {
    const modals = [...document.querySelectorAll(
        '.modal.in, .modal[style*="display: block"], .modal[style*="display:block"]'
    )].reverse();
    const modal = modals.find(_visible);
    if (modal) return { node: modal, type: 'modal' };
    const swal = [...document.querySelectorAll('.swal2-popup, .sweet-alert')].reverse().find(_visible);
    if (swal) return { node: swal, type: 'swal' };
    const ngd = [...document.querySelectorAll('.ngdialog.ngdialog-open')].reverse().find(_visible);
    if (ngd) return { node: ngd, type: 'ngdialog' };
    return null;
};
"""

# Detect any visible Angular-UI modal overlay and return metadata
_JS_DETECT_POPUP = r"fullBody => {" + _JS_VISIBLE_HELPER + r"""
    const found = _findVisiblePopup();
    if (!found) return { found: false };
    const node = found.node;
    const header = node.querySelector('.modal-header, .modal-title, .swal2-title');
    const bodyEl = node.querySelector('.modal-body, .swal2-html-container, .swal2-content, .ngdialog-message') || node;
    const body = _cleanBodyText(bodyEl);
    return {
        found: true,
        type: found.type,
        title: header ? header.innerText.trim() : '',
        body: fullBody ? body : body.substring(0, 200)
    };
}"""

# Dismiss the topmost visible modal by clicking the safest close/OK button inside it
_JS_DISMISS_POPUP = r"() => {" + _JS_VISIBLE_HELPER + r"""
    const found = _findVisiblePopup();
    if (!found) return { ok: false, err: 'no visible popup' };
    const popup = found.node;
    const clickable = btn => btn && !btn.disabled && _visible(btn)
        && !/\bsubmit\b/i.test((btn.innerText || btn.textContent || btn.value || '').trim());

    // Priority 1: NIA-specific coverChangeObj cancel button
    const cancelBtn = popup.querySelector(
        'button[data-ng-click*="coverChangeObj.cancel"], button[ng-click*="coverChangeObj.cancel"]'
    );
    if (clickable(cancelBtn)) {
        cancelBtn.click();
        return { ok: true, via: 'coverCancel' };
    }

    // Priority 2: scoped OK / confirm / close / single footer button inside visible modal
    const selectors = [
        'button[data-ng-click*="ok"]',
        'button[ng-click*="ok"]',
        'button[data-ng-click*="confirm"]',
        'button[ng-click*="confirm"]',
        'button[data-ng-click*="close"]',
        'button[ng-click*="close"]',
        '.modal-footer button:last-child',
        'button.swal2-confirm',
        'button.confirm',
    ];
    for (const sel of selectors) {
        const btn = [...popup.querySelectorAll(sel)].find(clickable);
        if (btn) {
            btn.click();
            return { ok: true, via: sel };
        }
    }

    // Priority 3: X close icon on the visible modal header
    const closeX = [...popup.querySelectorAll('.close, button.close, [data-dismiss="modal"]')].find(clickable);
    if (closeX) {
        closeX.click();
        return { ok: true, via: 'closeX' };
    }

    // Priority 4: safe text fallback inside the visible popup (never blind 'submit')
    const allBtns = popup.querySelectorAll('button, a.btn, input[type="button"]');
    for (const btn of allBtns) {
        const text = (btn.innerText || btn.textContent || btn.value || '').trim().toLowerCase();
        if ((text === 'ok' || text === 'okay' || text === 'yes' || text === 'close') && clickable(btn)) {
            btn.click();
            return { ok: true, via: 'genericText' };
        }
    }

    if (found.type === 'ngdialog') {
        const ngBtn = [...popup.querySelectorAll('button')].find(clickable);
        if (ngBtn) {
            ngBtn.click();
            return { ok: true, via: 'ngdialogButton' };
        }
    }

    return { ok: false, err: 'no dismissible button found' };
}"""


_JS_CLOSE_CONFIRMED_POPUP = r"body => {" + _JS_VISIBLE_HELPER + r"""
    const dialogs = document.querySelectorAll(
        '.modal.in, .modal[style*="display: block"], .modal[style*="display:block"]'
    );
    const dialog = [...dialogs].reverse().find(el => {
        if (!_visible(el)) return false;
        const bodyEl = el.querySelector('.modal-body');
        return _cleanBodyText(bodyEl) === body || (bodyEl?.innerText || '').trim() === body;
    });
    const buttons = dialog ? [...dialog.querySelectorAll('button, a.btn, input[type="button"], input[type="submit"]')].filter(
        btn => !btn.disabled && _visible(btn)
    ) : [];
    const closeButton = buttons.find(btn => /^(?:ok|okay|close|continue)$/i.test((btn.innerText || btn.textContent || btn.value || '').trim())) ||
        buttons.find(btn => btn.matches('button.close, .close, [data-dismiss="modal"], button[data-ng-click*="coverChangeObj.cancel"], button[ng-click*="coverChangeObj.cancel"]'));
    if (!closeButton) return { ok: false };
    closeButton.click();
    return { ok: true, via: 'confirmedDialog' };
}"""


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


def _log_open_popup(log, context, popup):
    text = " ".join((popup.get("body") or popup.get("title") or "").split())
    if re.search(
        r"[@\\]|\b(?:password|credentials?|token|otp|account|policy|claim no|claim number|pan|aadhaar|"
        r"insured|customer|address|mobile|email)\b|\d{4}", text, re.I,
    ):
        text = ""
    message = f"Left a New India message open{context}. Check Chrome."
    _log_msg(log, "info", f"{message} Portal message: {text[:140]}" if text else message)


# ── Public API ─────────────────────────────────────────────────────────────────

async def dismiss_portal_popup(
    page: Page,
    log,
    *,
    max_wait_s: float = 8.0,
    classify: bool = False,
    context: str = "",
    verify_closed: bool = True,
    expected_message: Optional[re.Pattern[str]] = None,
    success_message: Optional[re.Pattern[str]] = None,
    detail_out: Optional[dict] = None,
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
    expected_message : If set, only dismiss a dialog whose body matches this pattern.
    success_message : If set, require this positive confirmation before returning 'success'.

    Returns
    -------
    When classify=False (default): True if popup was dismissed, False if none appeared.
    When classify=True: tag string or None (None means no popup appeared).
    """
    ctx = f" ({context})" if context else ""
    poll_interval = 0.35
    elapsed = 0.0

    logger.debug("Polling for portal popup%s (max %.0fs)...", ctx, max_wait_s)

    while elapsed < max_wait_s:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        try:
            popup_info: dict = await page.evaluate(_JS_DETECT_POPUP, bool(expected_message or success_message))
        except Exception as exc:
            logger.debug("Popup detection error%s: %s", ctx, str(exc)[:80])
            continue

        if not popup_info.get("found"):
            continue

        # ── Popup detected ────────────────────────────────────────────────────
        ptype = popup_info.get("type", "modal")
        title = popup_info.get("title", "")
        body  = popup_info.get("body", "")
        tag   = _classify_popup(body) if body else "other"
        if detail_out is not None:
            detail_out.update({"title": title, "body": body, "tag": tag, "dismissed": False})
        if expected_message is not None and not expected_message.search(body):
            _log_open_popup(log, ctx, popup_info)
            return None if classify else False
        if success_message is not None:
            if success_message.search(body):
                tag = "success"
            elif tag == "success":
                tag = "other"
            if detail_out is not None:
                detail_out["tag"] = tag

        display_body = (body or title or "Notification shown").replace("\n", " ").strip()[:140]
        if tag in ("size_error", "duplicate_error"):
            _log_msg(log, "warning", f"Portal warning{ctx}: {display_body}")
            from app.portals.newindia.automation.logging_utils import capture_newindia_screenshot
            await capture_newindia_screenshot(page, f"popup_{tag}", log, reason=display_body)
        else:
            _log_msg(log, "info", f"Portal message{ctx}: {display_body}")

        # ── Dismiss ───────────────────────────────────────────────────────────
        try:
            from app.web_sync.submission import capture_before_dismiss
            await capture_before_dismiss(page)
            if expected_message is None:
                dismiss_res = await page.evaluate(_JS_DISMISS_POPUP)
            else:
                dismiss_res = await page.evaluate(_JS_CLOSE_CONFIRMED_POPUP, body)
        except Exception as exc:
            _log_msg(log, "warning", f"Could not close portal popup{ctx}. Check Chrome.")
            logger.debug("Popup dismissal JS error%s: %s", ctx, str(exc)[:120])
            return None if classify else False

        if not dismiss_res.get("ok"):
            _log_msg(
                log, "warning",
                f"Could not close portal popup{ctx}. Please close it in Chrome."
            )
            return None if classify else False

        via = dismiss_res.get("via", "?")
        logger.debug("Popup dismissed%s via %s [%s] (%s)", ctx, via, tag, ptype)

        # ── Verify closure (optional retry) ───────────────────────────────────
        if verify_closed:
            want_full = bool(expected_message or success_message)
            still_open: dict = {"found": False}
            for _ in range(6):
                await asyncio.sleep(0.2)
                try:
                    still_open = await page.evaluate(_JS_DETECT_POPUP, want_full)
                except Exception:
                    still_open = {"found": False}
                    break
                if not still_open.get("found"):
                    break
                if expected_message is not None and still_open.get("body") != body:
                    _log_open_popup(log, ctx, still_open)
                    if detail_out is not None:
                        detail_out["dismissed"] = True
                    return tag if classify else True
            try:
                if still_open.get("found"):
                    _log_msg(log, "warning", f"Portal popup still open{ctx} — retrying...")
                    await capture_before_dismiss(page)
                    if expected_message is None:
                        await page.evaluate(_JS_DISMISS_POPUP)
                    else:
                        await page.evaluate(_JS_CLOSE_CONFIRMED_POPUP, body)
                    final_check: dict = {"found": False}
                    for _ in range(4):
                        await asyncio.sleep(0.2)
                        final_check = await page.evaluate(_JS_DETECT_POPUP, want_full)
                        if not final_check.get("found"):
                            break
                    if final_check.get("found"):
                        _log_msg(log, "warning", f"Portal popup stayed open{ctx} — continuing.")
                    else:
                        _log_msg(log, "success", f"Closed portal message{ctx}.")
                else:
                    _log_msg(log, "success", f"Closed portal message{ctx}.")
            except Exception:
                pass  # verification failure is non-fatal
        else:
            _log_msg(log, "success", f"Closed portal message{ctx}.")

        if detail_out is not None:
            detail_out["dismissed"] = True
        return tag if classify else True

    # ── No popup appeared within timeout ──────────────────────────────────────
    logger.debug("No portal popup appeared%s — continuing.", ctx)
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
