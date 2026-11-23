"""Shared Chrome live progress badge, colored field rings, and field progress tracker."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from contextvars import ContextVar
from typing import Optional


_JS_HUD_STYLE_CSS = """
[data-app3-field-state="active"] {
    outline: 2.5px solid #2563EB !important;
    outline-offset: 2px !important;
    box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.22) !important;
    border-radius: 4px !important;
}
[data-app3-field-state="retry"] {
    outline: 2.5px solid #D97706 !important;
    outline-offset: 2px !important;
    box-shadow: 0 0 0 4px rgba(217, 119, 6, 0.22) !important;
    border-radius: 4px !important;
}
[data-app3-field-state="ok"] {
    outline: 2px solid #16A34A !important;
    outline-offset: 2px !important;
    box-shadow: 0 0 0 4px rgba(22, 163, 74, 0.18) !important;
    border-radius: 4px !important;
}
[data-app3-field-state="error"] {
    outline: 2.5px solid #DC2626 !important;
    outline-offset: 2px !important;
    box-shadow: 0 0 0 4px rgba(220, 38, 38, 0.22) !important;
    background-color: #FEF2F2 !important;
    border-radius: 4px !important;
}
#__app3-ni-hud {
    position: fixed !important;
    left: 16px !important;
    bottom: 16px !important;
    z-index: 2147483000 !important;
    pointer-events: none !important;
    max-width: 360px !important;
    background: rgba(15, 23, 42, 0.94) !important;
    color: #F8FAFC !important;
    border: 1px solid rgba(148, 163, 184, 0.35) !important;
    border-radius: 10px !important;
    padding: 8px 12px !important;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
    box-shadow: 0 8px 24px rgba(15, 23, 42, 0.35) !important;
    display: flex !important;
    flex-direction: column !important;
    gap: 2px !important;
}
#__app3-ni-hud .app3-hud-row {
    display: flex !important;
    align-items: center !important;
    gap: 8px !important;
    color: #F8FAFC !important;
    font-size: 12.5px !important;
    font-weight: 600 !important;
    line-height: 1.3 !important;
}
#__app3-ni-hud .app3-hud-dot {
    width: 8px !important;
    height: 8px !important;
    border-radius: 999px !important;
    flex-shrink: 0 !important;
}
#__app3-ni-hud .app3-hud-title {
    color: #F8FAFC !important;
    font-weight: 600 !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
}
#__app3-ni-hud .app3-hud-meta {
    font-size: 11px !important;
    color: #CBD5E1 !important;
    padding-left: 16px !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
}
"""

_JS_UPDATE_HUD = """
(payload) => {
    if (!document.body && !document.documentElement) return;
    if (!document.getElementById('__app3-ni-hud-style')) {
        const style = document.createElement('style');
        style.id = '__app3-ni-hud-style';
        style.textContent = %s;
        (document.head || document.documentElement).appendChild(style);
    }
    let hud = document.getElementById('__app3-ni-hud');
    if (!hud) {
        hud = document.createElement('div');
        hud.id = '__app3-ni-hud';
        hud.setAttribute('aria-hidden', 'true');
        hud.innerHTML = '<div class="app3-hud-row"><span class="app3-hud-dot"></span><span class="app3-hud-title"></span></div><div class="app3-hud-meta"></div>';
        (document.body || document.documentElement).appendChild(hud);
    }
    const colors = { active: '#3B82F6', retrying: '#F59E0B', retry: '#F59E0B', ok: '#22C55E', failed: '#EF4444', paused: '#EA580C' };
    const verbs = { active: 'Filling', retrying: 'Retrying', retry: 'Retrying', ok: 'Filled', failed: 'Needs review', paused: 'Paused' };
    const st = String(payload?.state || 'active');
    const lbl = String(payload?.label || '').trim();
    const verb = verbs[st] || 'Working';
    const title = lbl ? `${verb}: ${lbl}` : verb;
    const dot = hud.querySelector('.app3-hud-dot');
    const titleEl = hud.querySelector('.app3-hud-title');
    const metaEl = hud.querySelector('.app3-hud-meta');
    hud.style.setProperty('color', '#F8FAFC', 'important');
    if (dot) dot.style.background = colors[st] || '#3B82F6';
    if (titleEl) {
        titleEl.style.setProperty('color', '#F8FAFC', 'important');
        titleEl.textContent = title;
    }
    const parts = [];
    if (payload?.section) parts.push(String(payload.section));
    const filled = Number(payload?.filled || 0);
    const failed = Number(payload?.failed || 0);
    parts.push(`✓ ${filled}`);
    if (failed > 0) parts.push(`⚠ ${failed}`);
    if (metaEl) {
        metaEl.style.setProperty('color', '#CBD5E1', 'important');
        metaEl.textContent = parts.join('  ·  ');
    }
}
""" % json.dumps(_JS_HUD_STYLE_CSS)

_JS_MARK_FIELD = """
(el, state) => {
    if (!el) return;
    if (!document.getElementById('__app3-ni-hud-style')) {
        const style = document.createElement('style');
        style.id = '__app3-ni-hud-style';
        style.textContent = %s;
        (document.head || document.documentElement).appendChild(style);
    }
    for (const prev of document.querySelectorAll('[data-app3-field-state]')) {
        const prevState = prev.getAttribute('data-app3-field-state');
        if (prevState === 'active' || prevState === 'retry' || prev === el) {
            prev.removeAttribute('data-app3-field-state');
        }
    }
    if (el.dataset.app3OkTimer) {
        clearTimeout(Number(el.dataset.app3OkTimer));
        delete el.dataset.app3OkTimer;
    }
    const targetNode = (el.type === 'radio' && !el.getClientRects().length)
        ? ([...(el.labels || [])].find(l => l.getClientRects().length) || el)
        : el;
    try {
        targetNode.scrollIntoView({ behavior: 'auto', block: 'center', inline: 'nearest' });
    } catch (e) {}
    el.setAttribute('data-app3-field-state', state);
    if (state === 'ok') {
        const timerId = setTimeout(() => {
            if (el.getAttribute('data-app3-field-state') === 'ok') {
                el.removeAttribute('data-app3-field-state');
            }
            delete el.dataset.app3OkTimer;
        }, 750);
        el.dataset.app3OkTimer = String(timerId);
    } else if (state === 'error' && !el.dataset.app3ErrListener) {
        el.dataset.app3ErrListener = '1';
        const clearOnEdit = () => {
            if (el.getAttribute('data-app3-field-state') === 'error') {
                el.removeAttribute('data-app3-field-state');
            }
        };
        el.addEventListener('input', clearOnEdit);
        el.addEventListener('change', clearOnEdit);
    }
}
""" % json.dumps(_JS_HUD_STYLE_CSS)

_JS_CLEAR_HUD = """
(clearErrors) => {
    const hud = document.getElementById('__app3-ni-hud');
    if (hud) hud.remove();
    for (const node of document.querySelectorAll('[data-app3-field-state]')) {
        const st = node.getAttribute('data-app3-field-state');
        if (clearErrors || st !== 'error') {
            node.removeAttribute('data-app3-field-state');
        }
    }
}
"""


async def update_field_hud(page, section, label, state, *, filled=0, failed=0, skipped=0):
    """Show the current field action and progress pill inside Chrome safely."""
    if not page or page.is_closed():
        return
    with suppress(Exception):
        await asyncio.wait_for(
            page.evaluate(
                _JS_UPDATE_HUD,
                {
                    "section": section or "",
                    "label": label or "",
                    "state": state,
                    "filled": filled,
                    "failed": failed,
                    "skipped": skipped,
                },
            ),
            timeout=1.5,
        )


async def mark_field_state(target, state: str):
    """Apply a transient highlight ring (active/retry/ok/error) to a field locator."""
    if target is None:
        return
    with suppress(Exception):
        if await target.count() >= 1:
            await asyncio.wait_for(target.first.evaluate(_JS_MARK_FIELD, state), timeout=0.8)


async def clear_field_hud(page, *, clear_errors=False):
    """Remove the Chrome progress pill and temporary highlights safely."""
    if not page or page.is_closed():
        return
    with suppress(Exception):
        await asyncio.wait_for(page.evaluate(_JS_CLEAR_HUD, bool(clear_errors)), timeout=1.5)


def _short_val(val, limit: int = 28) -> str:
    text = " ".join(str(val or "").split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 3)] + "..."


class FieldProgressTracker:
    """Track filled/failed/skipped field counts and forward live progress events."""

    def __init__(self, field_progress_cb=None):
        self.fields_filled = 0
        self.fields_failed = 0
        self.fields_skipped = 0
        self.active_section = ""
        self.active_field = ""
        self._cb = field_progress_cb

    def report(self, section: str, field: str, state: str, *, value: str = "") -> None:
        self.active_section = section or ""
        self.active_field = field or ""
        if state == "ok":
            self.fields_filled += 1
        elif state == "failed":
            self.fields_failed += 1
        elif state == "skipped":
            self.fields_skipped += 1
        if self._cb is not None:
            with suppress(Exception):
                self._cb(
                    {
                        "section": self.active_section,
                        "field": self.active_field,
                        "state": state,
                        "value": value,
                        "filled": self.fields_filled,
                        "failed": self.fields_failed,
                        "skipped": self.fields_skipped,
                    }
                )


current_field_tracker: ContextVar[Optional[FieldProgressTracker]] = ContextVar(
    "app3_field_tracker", default=None,
)

_RING_STATE_MAP = {
    "active": "active",
    "retrying": "retry",
    "retry": "retry",
    "ok": "ok",
    "failed": "error",
}


async def emit_field_hud(
    page,
    log,
    label: str,
    state: str,
    *,
    value: str = "",
    target=None,
    selector: str = "",
    section: Optional[str] = None,
) -> None:
    """Non-fatally update the tracker, highlight ring, and Chrome progress badge."""
    with suppress(Exception):
        sec = section or getattr(log, "section", None) or getattr(log, "_section", None) or ""
        tracker = current_field_tracker.get()
        if tracker is not None:
            tracker.report(sec, label, state, value=_short_val(value))
            filled = tracker.fields_filled
            failed = tracker.fields_failed
            skipped = tracker.fields_skipped
        else:
            filled = failed = skipped = 0

        ring_state = _RING_STATE_MAP.get(state, "")
        if ring_state:
            if target is not None:
                await mark_field_state(target, ring_state)
            elif selector and page is not None:
                await mark_field_state(page.locator(selector).first, ring_state)

        await update_field_hud(
            page, sec, label, state, filled=filled, failed=failed, skipped=skipped,
        )

    if state == "failed" and getattr(log, "_debug_recorder", None) is not None:
        # AI debug report only (Logs-tab switch ON): one read-only look at the field and page.
        from app.automation.debug_recorder import debug_snapshot

        sec = ""
        with suppress(Exception):
            sec = section or getattr(log, "section", None) or getattr(log, "_section", None) or ""
        await debug_snapshot(
            log, page, target=target, selector=selector, label=label,
            reason=f"Field failed in {sec}" if sec else "Field failed",
            extra={"Tried value": value, "Section": sec},
        )
