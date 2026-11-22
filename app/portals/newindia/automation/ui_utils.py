import asyncio
import json
from typing import Callable, Optional
from playwright.async_api import Page
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation


from app.automation.automation_logger import AutomationLogger, _ts
from app.portals.newindia.automation.recovery import current_recovery
from app.portals.oic.automation.recovery import wait_until_ready


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
    if (!select) return { ok: false, err: 'not_found' };

    select.scrollIntoView({ behavior: 'auto', block: 'center' });

    const search = txt.trim().toLowerCase();
    const options = [...select.options].filter(option => option.value && !option.disabled);
    const label = option => option.text.trim().toLowerCase();
    const words = search.split(/\s+/).filter(word => word.length > 2);
    const matches = options.filter(option => label(option) === search);
    if (!matches.length && search) {
        matches.push(...options.filter(option => label(option) && (label(option).includes(search) || search.includes(label(option)))));
    }
    if (!matches.length) {
        matches.push(...options.filter(option => words.some(word => label(option).includes(word))));
    }
    if (matches.length !== 1) return {ok: false, err: matches.length ? 'ambiguous' : 'no_match'};
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
    return {ok: true, text: matchedText, value: matchedValue};
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

# ── Python Helpers ────────────────────────────────────────────────────────────

_JS_FIELD_STATE = """
el => {
    const visible = node => node && node.getClientRects().length && !node.closest('[aria-hidden=true], [hidden]');
    if (el.type === 'radio' && !visible(el) && ![...el.labels].some(visible)) return null;
    const model = window.angular?.element(el)?.controller('ngModel');
    const errors = Object.keys(model?.$error || {}).filter(code => model.$error[code]);
    const selected = el.selectedOptions?.[0];
    return {
        value: el.value,
        identity: [el.type === 'radio' ? '' : el.id, el.name],
        type: el.type,
        viewValue: ['string', 'number'].includes(typeof model?.$viewValue) ? String(model.$viewValue) : null,
        checked: ['radio', 'checkbox'].includes(el.type) ? el.checked : null,
        editable: !el.readOnly && !el.matches(':disabled'),
        valid: (!el.willValidate || el.validity.valid) && !errors.length && !model?.$pending &&
               (Boolean(model) || el.getAttribute('aria-invalid') !== 'true'),
        missing: el.validity?.valueMissing || errors.includes('required'),
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
    selected_value = str(value)
    shown = str(value)
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
    reason = "App3 could not find this field in the current section."
    if recovery is not None and recovery.stopped():
        raise asyncio.CancelledError
    try:
        ready_state = "attached" if kind in {"radio", "checkbox"} else "visible"
        await target.wait_for(state=ready_state, timeout=5000)
        reason = "New India did not keep this value."
        valid = await matches()
        if not valid and state and state["editable"]:
            result = await target.evaluate(script, str(value), timeout=5000)
            if result and result.get("value") is not None:
                selected_value = result["value"]
                shown = result["text"]
                option_set = True
            if result and result.get("err") == "no_match":
                reason = "The supplied value does not match an available option."
            elif result and result.get("err") == "ambiguous":
                reason = "More than one option matches. Select the correct one in Chrome."
            await asyncio.sleep(max(delay_ms / 1000, 0.12))
            valid = await wait_until_ready(
                matches, seconds=1, stopped=recovery.stopped if recovery else lambda: False,
            )
        if valid:
            log_verified()
            return
        if state and reason == "New India did not keep this value.":
            if state["missing"] and not str(state["value"]).strip():
                reason = "New India requires a value for this field."
            elif not state["valid"]:
                reason = "New India marked this field invalid. Check the message beside it in Chrome."
            elif not state["editable"]:
                reason = "This field is read-only and needs review in Chrome."
    except Exception:
        # A portal rerender can interrupt the write after accepting it.
        if reason != "App3 could not find this field in the current section.":
            if await wait_until_ready(matches, seconds=0.6):
                log_verified()
                return
    if recovery is not None:
        rejected_value = (state["value"], state["checked"]) if state else None
        recovery.record_field_issue(
            log, label, reason, matches=matches, manual_value=verified_manual_value,
            identity=tuple(state["identity"]) if state else None,
        )
    elif isinstance(log, AutomationLogger):
        log.field_failed(label, reason)
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


