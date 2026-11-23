import asyncio
import json
from contextlib import suppress
from typing import Callable, Optional
from playwright.async_api import Page
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation


from app.automation.automation_logger import AutomationLogger, _ts
from app.portals.newindia.automation.logging_utils import newindia_operator_reason
from app.portals.newindia.automation.recovery import current_recovery
from app.portals.oic.automation.recovery import wait_until_ready


CHANNEL_NON_TIE_UP = "non_tie_up"
CHANNEL_MARUTI = "maruti"
CHANNEL_UNSUPPORTED = "unsupported"

_OEM_ROUTE_LABELS = {
    "worklistsurveyhyundai": "Hyundai",
    "worklistsurveyhyundaihiib": "Hyundai HIIB",
    "worklistsurveytata": "Tata Motors",
    "worklistsurveykia": "Kia",
    "worklistsurveyhero": "Hero MotoCorp",
    "worklistsurveyashokleyland": "Ashok Leyland",
    "worklistsurveyroyalenfield": "Royal Enfield",
    "worklistsurveymorrisgarage": "Morris Garage",
    "worklistsurveymorrisgaragemgd2c": "Morris Garage",
    "worklistsurveymorrisgaragelockton": "Morris Garage",
}


def classify_newindia_channel(raw_value: str = "", label: str = "", url: str = "") -> tuple[str, str]:
    """Classify a New India claim channel from a Worklist selection or route URL."""
    low_url = str(url or "").strip().lower()
    if low_url:
        route_match = re.search(r"#/(worklistsurvey[a-z0-9]*)", low_url)
        if route_match:
            slug = route_match.group(1)
            if slug == "worklistsurveynew":
                return CHANNEL_NON_TIE_UP, "Non-Tie-Up"
            if slug == "worklistsurvey":
                return CHANNEL_MARUTI, "Maruti"
            return CHANNEL_UNSUPPORTED, _OEM_ROUTE_LABELS.get(
                slug, slug.removeprefix("worklistsurvey").strip().title() or "OEM Tie-Up",
            )

    raw = re.sub(r"^(?:string|object|number):", "", str(raw_value or "").strip(), flags=re.I).strip()
    lbl = " ".join(str(label or "").split()).strip()
    combined = f"{raw} {lbl}".lower()
    if not combined.strip():
        return "", ""

    if raw.lower() in {"nonmaruticlaim", "nm", "non_tie_up"} or any(
        token in combined for token in ("non tie", "non-tie", "nontie", "nonmaruti")
    ):
        return CHANNEL_NON_TIE_UP, "Non-Tie-Up"
    if "maruti" in combined:
        return CHANNEL_MARUTI, "Maruti"
    return CHANNEL_UNSUPPORTED, (lbl or raw)


def resolve_newindia_channel(page=None, data=None) -> str:
    """Resolve the active New India channel ('non_tie_up' or 'maruti')."""
    recovery = current_recovery.get()
    for candidate in (
        getattr(data, "_newindia_channel", "") if data is not None else "",
        getattr(recovery, "claim_channel", "") if recovery is not None else "",
    ):
        if candidate in {CHANNEL_NON_TIE_UP, CHANNEL_MARUTI}:
            return candidate
    if page is not None:
        code, _ = classify_newindia_channel(url=getattr(page, "url", "") or "")
        if code in {CHANNEL_NON_TIE_UP, CHANNEL_MARUTI}:
            return code
    return CHANNEL_NON_TIE_UP


def additional_section(page, title):
    return page.locator('form[name="workListForm"] .tab-pane.active a.accordion-toggle:visible').filter(
        has_text=re.compile(rf"^\s*{re.escape(title)}(?:\s+\d+)?\s*$", re.I),
    )


def record_additional_issue(
    log, field, reason="App3 could not fill this field.", *, matches=None, manual_value=None, identity=None,
):
    recovery = current_recovery.get()
    if recovery is not None:
        recovery.record_field_issue(log, field, reason, matches=matches, manual_value=manual_value, identity=identity)
    elif isinstance(log, AutomationLogger):
        log.field_failed(field, reason)
    elif log:
        log(f"{field} — {reason}")


async def open_additional_section(page, title, log, *, optional=False):
    recovery = current_recovery.get()
    if recovery is not None:
        await recovery.wait_if_manually_paused(page, log)
    heading = additional_section(page, title)
    try:
        if optional and not await heading.count():
            return False
        await heading.wait_for(state="visible", timeout=5000)
        panel = heading.locator("xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' panel ')][1]")
        body = panel.locator(":scope > .panel-collapse")
        if not await body.is_visible():
            await heading.click(timeout=5000)
        await body.wait_for(state="visible", timeout=5000)
        return True
    except Exception:
        record_additional_issue(log, title, "App3 could not open this section in Chrome.")
        return False

# ── JavaScript Snippets ───────────────────────────────────────────────────────

_JS_FILL = r"""
(el, val) => {
    if (!el) return { ok: false };
    el.scrollIntoView({ behavior: 'auto', block: 'center' });
    el.value = val;
    el.dispatchEvent(new Event('input',  { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    try {
        const s = angular.element(el).scope();
        if (s && s.$apply) s.$apply();
        else {
            let p = el.parentElement;
            while (p) {
                const ps = angular.element(p).scope();
                if (ps && ps.$apply) { ps.$apply(); break; }
                p = p.parentElement;
            }
        }
    } catch(e) {}
    el.dispatchEvent(new Event('blur', { bubbles: true }));
    return { ok: true };
}
"""

_JS_SELECT = r"""
(select, txt) => {
    if (!select) return { ok: false, err: 'not_found', optionCount: 0, suggestions: [] };

    select.scrollIntoView({ behavior: 'auto', block: 'center' });

    const search = txt.trim().toLowerCase();
    const options = [...select.options].filter(option => option.value && !option.disabled);
    const optionCount = options.length;
    const label = option => option.text.trim().toLowerCase();
    const cleanText = option => option.text.replace(/\s+/g, ' ').trim();
    const words = search.split(/\s+/).filter(word => word.length > 2);
    const matches = options.filter(option => label(option) === search);
    if (!matches.length && search) {
        matches.push(...options.filter(option => label(option) && (label(option).includes(search) || search.includes(label(option)))));
    }
    if (!matches.length) {
        matches.push(...options.filter(option => words.some(word => label(option).includes(word))));
    }
    if (matches.length !== 1) {
        const err = matches.length ? 'ambiguous' : 'no_match';
        const suggestions = err === 'ambiguous'
            ? matches.slice(0, 3).map(cleanText)
            : (optionCount <= 6 ? options.slice(0, 3).map(cleanText) : []);
        return { ok: false, err, optionCount, suggestions };
    }
    const [{value: matchedValue, text: matchedText}] = matches;
    if (select.value !== matchedValue) {
        select.value = matchedValue;
        select.dispatchEvent(new Event('change', { bubbles: true }));
        try {
            const s = angular.element(select).scope();
            if (s && s.$apply) s.$apply();
            else {
                let p = select.parentElement;
                while (p) {
                    const ps = angular.element(p).scope();
                    if (ps && ps.$apply) { ps.$apply(); break; }
                    p = p.parentElement;
                }
            }
        } catch(e) {}
    }
    return {ok: true, text: matchedText, value: matchedValue, optionCount};
}
"""

_JS_CLICK_RADIO = r"""
(radio) => {
    if (!radio) return { ok: false, err: 'not_found' };
    if (radio.checked) return { ok: true, already: true };
    radio.scrollIntoView({ behavior: 'auto', block: 'center' });
    const lbl = [...radio.labels].find(label => label.getClientRects().length);
    if (lbl) { lbl.click(); return { ok: true }; }
    const outer = radio.closest('label');
    if (outer) { outer.click(); return { ok: true, via: 'outer' }; }
    radio.click();
    return { ok: true, via: 'direct' };
}
"""

_JS_TRIGGER_CHANGE = r"""
([sel]) => {
    const el = document.querySelector(sel);
    if (!el) return { ok: false };
    el.dispatchEvent(new Event('change', { bubbles: true }));
    try {
        const s = angular.element(el).scope();
        if (s && s.$apply) s.$apply();
        else {
            let p = el.parentElement;
            while (p) {
                const ps = angular.element(p).scope();
                if (ps && ps.$apply) { ps.$apply(); break; }
                p = p.parentElement;
            }
        }
    } catch(e) {}
    return { ok: true };
}
"""

# ── Chrome Live Field HUD & Highlighting (shared implementation) ─────────────

from app.automation.chrome_hud import (
    clear_field_hud,
    mark_field_state as _mark_field,
    update_field_hud,
)

_JS_TRIGGER_ELEMENT_CHANGE = """
(el) => {
    if (!el) return;
    el.dispatchEvent(new Event('change', { bubbles: true }));
    try {
        const s = angular.element(el).scope();
        if (s && s.$apply) s.$apply();
        else {
            let p = el.parentElement;
            while (p) {
                const ps = angular.element(p).scope();
                if (ps && ps.$apply) { ps.$apply(); break; }
                p = p.parentElement;
            }
        }
    } catch (e) {}
    el.dispatchEvent(new Event('blur', { bubbles: true }));
}
"""


def _short_val(val) -> str:
    text = " ".join(str(val or "").split())
    return text if len(text) <= 36 else text[:33] + "..."


# ── Python Helpers ────────────────────────────────────────────────────────────

_JS_FIELD_STATE = """
el => {
    const visible = node => node && node.getClientRects().length && !node.closest('[aria-hidden=true], [hidden]');
    if (el.type === 'radio' && !visible(el) && ![...el.labels].some(visible)) return null;
    const model = window.angular?.element(el)?.controller('ngModel');
    const errors = Object.keys(model?.$error || {}).filter(code => model.$error[code]);
    const selected = el.selectedOptions?.[0];
    const valid = (!el.willValidate || el.validity.valid) && !errors.length && !model?.$pending &&
                  (Boolean(model) || el.getAttribute('aria-invalid') !== 'true');
    const missing = Boolean(el.validity?.valueMissing || errors.includes('required'));
    const hasInvalidState = !valid || missing || el.classList.contains('ng-invalid') || Boolean(el.closest('.has-error'));
    let portalError = '';
    const box = el.closest('.form-group, td') || el.parentElement;
    if (box) {
        const msgSelectors = hasInvalidState
            ? '.help-block, .text-danger, .error, [ng-message], [data-ng-message], .invalid-feedback, span.err'
            : '.text-danger, .error, [ng-message], [data-ng-message], .invalid-feedback, span.err, .has-error .help-block';
        for (const node of box.querySelectorAll(msgSelectors)) {
            if (!visible(node) || node.querySelector('input, select, textarea')) continue;
            const msg = (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim();
            if (msg && msg !== '*' && !msg.startsWith('http')) {
                portalError = msg.slice(0, 90);
                break;
            }
        }
    }
    return {
        value: el.value,
        identity: [el.type === 'radio' ? '' : el.id, el.name],
        type: el.type,
        viewValue: ['string', 'number'].includes(typeof model?.$viewValue) ? String(model.$viewValue) : null,
        checked: ['radio', 'checkbox'].includes(el.type) ? el.checked : null,
        editable: !el.readOnly && !el.matches(':disabled'),
        valid,
        missing,
        portalError,
        option: selected && !selected.disabled ? selected.text : ''
    };
}
"""


def _field_key(value, input_type=""):
    text = " ".join(str(value or "").split())
    if input_type == "number":
        try:
            return Decimal(text)
        except InvalidOperation:
            return text
    time = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", text)
    if time:
        hour, minute, second = time.groups()
        return f"{int(hour):02d}:{minute}:{second or '00'}"
    if re.fullmatch(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}", text):
        for pattern in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, pattern).date().isoformat()
            except ValueError:
                pass
    return text


def _text_matches_field(state, value, *, numeric=False):
    representation = "number" if numeric else state["type"]
    expected = _field_key(value, representation)
    return (_field_key(state["value"], representation) == expected
            and (state["viewValue"] is None or _field_key(state["viewValue"], representation) == expected))


async def _check_entry(page, target, label, value, script, kind, log, delay_ms, source,
                       radio_group=None, numeric=False):
    recovery = current_recovery.get()
    if recovery is not None:
        await recovery.wait_if_manually_paused(page, log)
    section = getattr(log, "_section", None) or ""
    selected_value = str(value)
    shown = str(value)
    tried_short = _short_val(value) if (str(value or "").strip() and kind != "checkbox") else ""

    async def emit_progress(progress_state: str):
        if recovery is not None and hasattr(recovery, "report_field_progress"):
            recovery.report_field_progress(section, label, progress_state, value=tried_short)
        filled = getattr(recovery, "fields_filled", 0) if recovery is not None else 0
        failed = getattr(recovery, "fields_failed", 0) if recovery is not None else 0
        skipped = getattr(recovery, "fields_skipped", 0) if recovery is not None else 0
        await update_field_hud(page, section, label, progress_state, filled=filled, failed=failed, skipped=skipped)

    async def matches():
        nonlocal state
        if await target.count() != 1:
            return False
        state = await target.evaluate(_JS_FIELD_STATE, timeout=1000)
        if not state or not state["valid"]:
            return False
        if kind in {"radio", "checkbox"}:
            return state["checked"]
        if kind == "dropdown":
            return bool(state["value"] and (option_set and state["value"] == selected_value
                                           or state["option"].strip().casefold() == str(value).strip().casefold()))
        return _text_matches_field(state, value, numeric=numeric)

    def log_verified():
        if recovery is not None:
            recovery.clear_field_issue(log, label)
        if isinstance(log, AutomationLogger):
            write = log.field_selected if kind == "dropdown" else log.field_filled
            write(label, shown, **({"source": source} if source is not None else {}))
        elif log:
            log(f"[{_ts()}] {label} verified.")

    async def verified_manual_value():
        if await matches():
            return True
        if kind == "radio":
            group = radio_group if radio_group is not None else target
            states = await group.evaluate_all(f"els => els.map({_JS_FIELD_STATE.strip()})")
            return any(state and state["valid"] and not state.get("missing") and state["checked"] for state in states)
        if await target.count() != 1:
            return False
        current = await target.evaluate(_JS_FIELD_STATE, timeout=1000)
        value_text = str(current["value"]).strip() if current else ""
        return bool(current and current["valid"] and not current.get("missing") and value_text
                    and not value_text.startswith("?")
                    and (kind != "checkbox" or current["checked"])
                    and (kind != "text" or current["viewValue"] is None
                         or _field_key(current["viewValue"], current["type"]) == _field_key(current["value"], current["type"])))

    state = None
    option_set = False
    err = ""
    suggestions = []
    option_count = None
    reason = "Could not find this field on this page."
    if recovery is not None and recovery.stopped():
        raise asyncio.CancelledError
    await emit_progress("active")
    try:
        ready_state = "attached" if kind in {"radio", "checkbox"} else "visible"
        await target.wait_for(state=ready_state, timeout=5000)
        reason = "New India did not keep this value."
        await _mark_field(target, "active")
        valid = await matches()
        if not valid and state and state["editable"]:
            result = await target.evaluate(script, str(value), timeout=5000)
            if result and result.get("value") is not None:
                selected_value = result["value"]
                shown = result["text"]
                option_set = True
            err = (result or {}).get("err", "")
            suggestions = (result or {}).get("suggestions") or []
            option_count = (result or {}).get("optionCount")
            await asyncio.sleep(max(delay_ms / 1000, 0.12))
            valid = await wait_until_ready(
                matches, seconds=0.9, stopped=recovery.stopped if recovery else lambda: False,
            )

            retryable = bool(
                not valid and state and state["editable"]
                and (err not in ("no_match", "ambiguous") or (kind == "dropdown" and option_count == 0))
            )
            if retryable:
                await _mark_field(target, "retry")
                await emit_progress("retrying")
                await asyncio.sleep(0.4)
                if recovery is not None and recovery.stopped():
                    raise asyncio.CancelledError
                if kind == "text":
                    try:
                        await target.click(timeout=1500)
                        await target.fill(str(value), timeout=2000)
                        await target.evaluate(_JS_TRIGGER_ELEMENT_CHANGE, timeout=1500)
                    except Exception:
                        await target.evaluate(script, str(value), timeout=5000)
                else:
                    result = await target.evaluate(script, str(value), timeout=5000)
                    if result and result.get("value") is not None:
                        selected_value = result["value"]
                        shown = result["text"]
                        option_set = True
                    err = (result or {}).get("err", "")
                    suggestions = (result or {}).get("suggestions") or []
                    option_count = (result or {}).get("optionCount")
                valid = await wait_until_ready(
                    matches, seconds=1.0, stopped=recovery.stopped if recovery else lambda: False,
                )
        if valid:
            await _mark_field(target, "ok")
            await emit_progress("ok")
            log_verified()
            return
    except asyncio.CancelledError:
        raise
    except Exception:
        # A portal rerender can interrupt the write after accepting it.
        if reason != "Could not find this field on this page.":
            if await wait_until_ready(matches, seconds=0.6):
                await _mark_field(target, "ok")
                await emit_progress("ok")
                log_verified()
                return

    await _mark_field(target, "error")
    if err == "no_match":
        opts = ", ".join(s for s in suggestions if s)
        base = "Not in dropdown list"
        reason = f"{base} (options: {opts})" if opts and len(f"{base} (options: {opts})") <= 85 else base
    elif err == "ambiguous":
        opts = ", ".join(s for s in suggestions if s)
        base = "Multiple matches — pick one"
        reason = f"{base} ({opts})" if opts and len(f"{base} ({opts})") <= 85 else base
    elif state and state.get("portalError"):
        reason = newindia_operator_reason(state["portalError"], "New India marked this field invalid.")
    elif state:
        if state["missing"] and not str(state["value"]).strip():
            reason = "New India requires a value for this field."
        elif not state["valid"]:
            reason = "New India marked this field invalid."
        elif not state["editable"]:
            reason = "Field is locked (read-only)."
        else:
            reason = "New India did not keep this value."

    await emit_progress("failed")
    if recovery is not None:
        recovery.record_field_issue(
            log, label, reason, matches=matches, manual_value=verified_manual_value,
            identity=tuple(state["identity"]) if state else None,
            attempted_value=tried_short, source=source or "",
        )
    elif isinstance(log, AutomationLogger):
        log.field_failed(label, f"{reason} (tried '{tried_short}')" if tried_short else reason)
    elif log:
        log(f"[{_ts()}] {label}: {reason}")


def _visible_field(page, selector):
    return page.locator(f":is({selector}):visible")


async def check_checkbox_with_delay(page, selector, label, log, delay_ms=600, source=None):
    await _check_entry(page, page.locator(selector), label, "Y", _JS_CLICK_RADIO,
                       "checkbox", log, delay_ms, source)


async def fill_input_with_delay(
    page: Page, selector: str, value: str, label: str,
    log, delay_ms: int = 600, source: Optional[str] = None, *, numeric=False,
):
    """Angular-aware text fill with configurable post-fill delay."""
    await _check_entry(page, _visible_field(page, selector), label, value, _JS_FILL,
                       "text", log, delay_ms, source, numeric=numeric)


async def select_dropdown_with_delay(
    page: Page, selector: str, value: str, label: str,
    log, delay_ms: int = 600, source: Optional[str] = None, *, index: int | None = None,
):
    """Standard <select> dropdown helper with 3-pass matching and configurable delay."""
    target = _visible_field(page, selector)
    if index is not None:
        target = target.nth(index)
    await _check_entry(page, target, label, value, _JS_SELECT,
                       "dropdown", log, delay_ms, source)


async def click_radio_with_delay(
    page: Page, name: str, value: str, label: str,
    log, delay_ms: int = 600, source: Optional[str] = None, *, scope=None,
):
    """Click radio via label with delay."""
    group = f'input[type="radio"][name={json.dumps(name)}]'
    root = page if scope is None else scope
    target = root.locator(f'{group}[value={json.dumps(str(value))}]')
    await _check_entry(page, target, label, value, _JS_CLICK_RADIO, "radio", log, delay_ms,
                       source, radio_group=root.locator(f"{group}:checked"))

def format_date_ddmmyyyy(raw_date) -> str:
    """Safely format any date string from Excel to DD/MM/YYYY."""
    if not raw_date:
        return ""
    
    val = str(raw_date).strip()
    
    # Try parsing common formats, particularly timestamps from Excel
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(val, fmt)
            return dt.strftime("%d/%m/%Y")
        except ValueError:
            pass
            
    # Regex fallback if formats above fail
    m = re.search(r'(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})', val)
    if m:
        d, mon, y = m.groups()
        return f"{int(d):02d}/{int(mon):02d}/{y}"
        
    m2 = re.search(r'(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})', val)
    if m2:
        y, mon, d = m2.groups()
        return f"{int(d):02d}/{int(mon):02d}/{y}"
        
    # Final fallback, just return the date portion
    return val.split(" ")[0]


async def upload_file_via_input(
    page: Page, file_input_selector: str, file_path: str,
    label: str, log: Callable, delay_ms: int = 1500
) -> bool:
    """
    Attach a file to an <input type='file'> element.
    ONLY selects/attaches the file — does NOT click Upload or Submit.
    The user will manually verify and submit on the live website.
    Returns True if file was attached successfully, False otherwise.
    """
    import os
    recovery = current_recovery.get()
    if recovery is not None:
        await recovery.wait_if_manually_paused(page, log)
    if not file_path or not os.path.exists(file_path):
        if isinstance(log, AutomationLogger):
            log.upload_failed(label, f"File not found: {file_path}")
        else:
            log(f"[{_ts()}]   ⚠️ [{label}] file not found: {file_path}")
        return False

    try:
        file_input = page.locator(file_input_selector).first
        await file_input.wait_for(state="attached", timeout=5000)
        await file_input.set_input_files(file_path)

        # NOTE: Do NOT manually dispatch a 'change' event here.
        # Playwright's set_input_files() already fires a native 'change' event
        # that Angular processes correctly. Dispatching a second 'change' event
        # causes the portal's ng-change handler to register the file twice,
        # triggering: "X is selected more than once for this claim number."

        if isinstance(log, AutomationLogger):
            log.upload_attached(label, os.path.basename(file_path))
        else:
            log(f"[{_ts()}]   ✅ [{label}] file attached → '{os.path.basename(file_path)}'")
            
        await asyncio.sleep(delay_ms / 1000.0)
        return True
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.upload_failed(label, str(e))
        else:
            log(f"[{_ts()}]   ⚠️ [{label}] attach error: {e}")
        return False


