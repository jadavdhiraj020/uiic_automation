import asyncio
from typing import Callable, Optional
from playwright.async_api import Page
import re
import random
from datetime import datetime

from app.automation.automation_logger import AutomationLogger, _ts
from app.portals.oic.automation.date_formatter import format_oic_date as _format_oic_date
from app.portals.oic.automation.dropdowns import matching_option, select_dropdown_option
from app.portals.oic.automation.recovery import (
    current_recovery, field_decision, field_problem, field_was_handled, form_step_is_open, wait_until_ready,
)
from app.portals.oic.automation.validation import field_validation_message

# ── JavaScript Snippets ───────────────────────────────────────────────────────

_JS_FILL = r"""
([sel, val]) => {
    const el = document.querySelector(sel);
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
([sel, txt]) => {
    const select = document.querySelector(sel);
    if (!select) return { ok: false, err: 'not_found' };

    select.scrollIntoView({ behavior: 'auto', block: 'center' });

    const search = txt.trim().toLowerCase();
    let matchedValue = null;
    let matchedText  = null;

    // Pass 1: exact text match
    for (let i = 0; i < select.options.length; i++) {
        const optText = select.options[i].text.trim().toLowerCase();
        if (optText === search) {
            matchedValue = select.options[i].value;
            matchedText  = select.options[i].text;
            break;
        }
    }

    // Pass 2: substring match (both directions)
    if (matchedValue === null) {
        for (let i = 0; i < select.options.length; i++) {
            const optText = select.options[i].text.trim().toLowerCase();
            if (optText.includes(search) || search.includes(optText)) {
                matchedValue = select.options[i].value;
                matchedText  = select.options[i].text;
                break;
            }
        }
    }

    // Pass 3: word-level fallback
    if (matchedValue === null && search.length > 2) {
        const words = search.split(/\s+/);
        for (let i = 0; i < select.options.length; i++) {
            const optText = select.options[i].text.toLowerCase();
            if (words.some(w => w.length > 2 && optText.includes(w))) {
                matchedValue = select.options[i].value;
                matchedText  = select.options[i].text;
                break;
            }
        }
    }

    if (matchedValue !== null) {
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
        return { ok: true, text: matchedText };
    }
    return { ok: false, err: 'no_match' };
}
"""

_JS_CLICK_RADIO = r"""
([name, value]) => {
    const radio = document.querySelector(`input[name="${name}"][value="${value}"]`);
    if (!radio) return { ok: false, err: 'not_found' };
    if (radio.checked) return { ok: true, already: true };
    radio.scrollIntoView({ behavior: 'auto', block: 'center' });
    const lbl = document.querySelector(`label[for="${radio.id}"]`);
    if (lbl) { lbl.click(); return { ok: true }; }
    const outer = radio.closest('label');
    if (outer) { outer.click(); return { ok: true, via: 'outer' }; }
    radio.click();
    return { ok: true, via: 'direct' };
}
"""

# ── Python Helpers ────────────────────────────────────────────────────────────

async def advance_form(page, log, selector, button_name, destination, stop_cb, screenshot_name):
    recovery = current_recovery.get()

    async def ready():
        if recovery is not None and not await recovery.is_original_document(page):
            return False
        return await form_step_is_open(page, destination)

    if stop_cb():
        return False
    try:
        if recovery is not None:
            if not await recovery.is_original_document(page):
                return False
            recovery.transition_started = True
        if await ready():
            return True
        if recovery is not None and await recovery._field_resume_state(page) != "same":
            return False
        visible_buttons = ", ".join(f"{part.strip()}:visible" for part in selector.split(","))
        await page.locator(visible_buttons).first.click(timeout=6000)
    except Exception:
        message = f"App3 could not confirm that {button_name} was clicked."
        log.warning(message) if isinstance(log, AutomationLogger) else log(message)
    else:
        message = f"Clicked {button_name}. Waiting for OIC to open the next step."
        log.info(message) if isinstance(log, AutomationLogger) else log(message)
    if await wait_until_ready(ready, seconds=12, stopped=stop_cb):
        return True
    if not stop_cb():
        await capture_error_screenshot(page, screenshot_name, log)
    return False


async def _check_field_validation(locator):
    if current_recovery.get() is not None:
        message = await field_validation_message(locator)
        if message:
            raise ValueError(message)


def _get_oic_fill_settings():
    """Retrieve dynamic fill settings (instant fill vs typing speed) from OIC defaults."""
    try:
        from app.utils import load_automation_defaults
        defaults = load_automation_defaults(portal_id="oic")
        instant_fill = str(defaults.get("instant_fill", "Yes")).strip().upper() == "YES"
        try:
            typing_delay = int(str(defaults.get("typing_delay_ms", "25")).strip())
            typing_delay = max(0, min(typing_delay, 1000))  # Sanitize to valid range
        except ValueError:
            typing_delay = 25
        return instant_fill, typing_delay
    except Exception:
        return True, 25


async def fill_input_with_delay(
    page: Page, selector: str, value: str, label: str,
    log, delay_ms: int = 30, source: Optional[str] = None
):
    """Angular-aware instant or typed text fill with configurable inter-field delay."""
    if field_was_handled(page, log, label):
        return
    try:
        await page.wait_for_selector(selector, state="visible", timeout=5000)
        
        locator = page.locator(selector).first
        await locator.focus()
        
        instant_fill, typing_delay = _get_oic_fill_settings()
        if instant_fill:
            await locator.fill(str(value))
        else:
            await locator.fill("")
            for char in str(value):
                await locator.press_sequentially(char, delay=typing_delay)
            
        # Trigger Angular changes and event dispatches to settle state
        result = await page.evaluate(_JS_FILL, [selector, str(value)])
        if not result or not result.get("ok"):
            raise ValueError("OIC could not update this field.")
        await _check_field_validation(locator)
        
        if isinstance(log, AutomationLogger):
            kwargs = {}
            if source is not None:
                kwargs["source"] = source
            log.field_filled(label, value, **kwargs)
        else:
            log(f"[{_ts()}]   ✅ [{label}] filled → '{str(value)[:60]}'")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.field_failed(label, str(e))
        else:
            log(f"[{_ts()}]   ⚠️ [{label}] error: {e}")
        await field_problem(page, log, label, str(e))

    await asyncio.sleep(delay_ms / 1000.0)


async def select_dropdown_with_delay(
    page: Page, selector: str, value: str, label: str,
    log, delay_ms: int = 30, source: Optional[str] = None
):
    """Standard <select> dropdown helper with 3-pass matching and configurable delay."""
    if field_was_handled(page, log, label):
        return
    try:
        await page.wait_for_selector(selector, state="visible", timeout=5000)
        res = await page.evaluate(_JS_SELECT, [selector, str(value)])
        if res and res.get("ok"):
            await _check_field_validation(page.locator(selector).first)
            if isinstance(log, AutomationLogger):
                kwargs = {}
                if source is not None:
                    kwargs["source"] = source
                log.field_selected(label, res.get("text"), **kwargs)
            else:
                log(f"[{_ts()}]   ✅ [{label}] selected → '{res.get('text')}'")
        else:
            err = res.get('err') if res else 'unknown'
            if isinstance(log, AutomationLogger):
                log.field_failed(label, f"No match for '{value}': {err}")
            else:
                log(f"[{_ts()}]   ⚠️ [{label}] select failed (no match for '{value}'): {err}")
            await field_problem(page, log, label, f"No match for '{value}': {err}")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.field_failed(label, str(e))
        else:
            log(f"[{_ts()}]   ⚠️ [{label}] error: {e}")
        await field_problem(page, log, label, str(e))

    await asyncio.sleep(delay_ms / 1000.0)


async def click_radio_with_delay(
    page: Page, name: str, value: str, label: str,
    log, delay_ms: int = 30, source: Optional[str] = None
):
    """Click radio via label with delay."""
    if field_was_handled(page, log, label):
        return
    try:
        res = await page.evaluate(_JS_CLICK_RADIO, [name, value])
        if res and res.get("ok"):
            already = res.get("already", False)
            msg = f"'{value}'" + (" (already set)" if already else "")
            if isinstance(log, AutomationLogger):
                kwargs = {}
                if source is not None:
                    kwargs["source"] = source
                log.field_filled(label, msg, **kwargs)
            else:
                log(f"[{_ts()}]   {'✔' if already else '✅'} [{label}] → {msg}")
        else:
            err = res.get('err') if res else 'unknown'
            if isinstance(log, AutomationLogger):
                log.field_failed(label, f"Click failed: {err}")
            else:
                log(f"[{_ts()}]   ⚠️ [{label}] click failed: {err}")
            await field_problem(page, log, label, f"Click failed: {err}")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.field_failed(label, str(e))
        else:
            log(f"[{_ts()}]   ⚠️ [{label}] error: {e}")
        await field_problem(page, log, label, str(e))

    await asyncio.sleep(delay_ms / 1000.0)


def format_date_ddmmyyyy(raw_date) -> str:
    """Format any date string from Excel to DD/MM/YYYY (slash-separated).

    Delegates to the shared OIC date formatter service (date_formatter.py)
    which is the single source of truth for all date parsing on this portal.
    Output separators are converted from hyphens to slashes to match the
    historic contract of this function (callers expect DD/MM/YYYY).
    Returns "" when the input cannot be parsed.
    """
    # _format_oic_date always returns "DD-MM-YYYY" or "".
    result = _format_oic_date(raw_date)
    return result.replace("-", "/") if result else ""


async def upload_file_via_input(
    page: Page, file_input_selector: str, file_path: str,
    label: str, log: Callable, delay_ms: int = 1000
) -> bool:
    """
    Attach a file to an <input type='file'> element.
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


async def capture_error_screenshot(page: Page, context_name: str, log) -> Optional[str]:
    """
    Captures a screenshot of the current page state, saves it to the logs directory,
    and returns the file path.
    """
    import os
    try:
        logs_dir = os.path.abspath(os.path.join(os.getcwd(), "logs"))
        os.makedirs(logs_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"oic_error_{context_name.replace(' ', '_')}_{timestamp}.png"
        filepath = os.path.join(logs_dir, filename)
        
        await page.screenshot(path=filepath, full_page=False)
        
        msg = f"Captured a screenshot for {context_name.replace('_', ' ')}."
        if isinstance(log, AutomationLogger):
            log.warning(msg)
        elif callable(log):
            log(f"[{_ts()}]   ⚠️ {msg}")
        return filepath
    except Exception:
        msg = "App3 could not capture a screenshot."
        if isinstance(log, AutomationLogger):
            log.warning(msg)
        elif callable(log):
            log(f"[{_ts()}]   ⚠️ {msg}")
        return None


# ── PrimeNG-Specific Helpers ─────────────────────────────────────────────────


async def click_primeng_radio(
    page: Page, radio_selector: str, label: str,
    log, delay_ms: int = 30, source: Optional[str] = None
):
    """Click a PrimeNG radio button using multi-strategy locator matching."""
    if field_was_handled(page, log, label):
        return
    try:
        radio = page.locator(radio_selector).first
        await radio.wait_for(state="attached", timeout=5000)
        
        # 1. Ancestor label (classic PrimeNG)
        ancestor = radio.locator("xpath=ancestor::label")
        # 2. Sibling label (React PrimeNG, uses 'for' attribute)
        radio_id = await radio.get_attribute("id")
        sibling = page.locator(f"label[for='{radio_id}']") if radio_id else None
        # 3. p-radiobutton wrapper (React synthetic event trigger)
        wrapper = radio.locator("xpath=ancestor::div[contains(@class, 'p-radiobutton')]")

        if await ancestor.count() > 0:
            await ancestor.first.click()
        elif sibling and await sibling.count() > 0:
            await sibling.first.click()
        elif await wrapper.count() > 0:
            await wrapper.first.click()
        else:
            await radio.click()

        if isinstance(log, AutomationLogger):
            kwargs = {}
            if source is not None:
                kwargs["source"] = source
            log.field_filled(label, "selected", **kwargs)
        else:
            log(f"[{_ts()}]   ✅ [{label}] → selected")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.field_failed(label, str(e))
        else:
            log(f"[{_ts()}]   ⚠️ [{label}] error: {e}")
        await field_problem(page, log, label, str(e))

    await asyncio.sleep(delay_ms / 1000.0)


async def select_primeng_dropdown(
    page: Page, dropdown_selector: str, value: str, label: str,
    log, delay_ms: int = 80, source: Optional[str] = None, *, exact: bool = False,
) -> bool:
    """Select the requested option and check the value shown in the same field."""
    if field_was_handled(page, log, label):
        return True
    try:
        chosen = await select_dropdown_option(
            page, dropdown_selector, lambda options: matching_option(value, options, exact=exact), expected=value,
        )
        if isinstance(log, AutomationLogger):
            log.field_selected(label, chosen, **({"source": source} if source is not None else {}))
        else:
            log(f"[{_ts()}] [{label}] selected → '{chosen}'")
        return True
    except Exception as exc:
        if isinstance(log, AutomationLogger):
            log.field_failed(label, str(exc))
        else:
            log(f"[{_ts()}] [{label}] selection failed: {exc}")
        return await field_problem(page, log, label, str(exc))
    finally:
        await asyncio.sleep(delay_ms / 1000.0)


async def fill_primeng_inputnumber(
    page: Page, selector: str, value: str, label: str,
    log, delay_ms: int = 30, source: Optional[str] = None
):
    """Fill a PrimeNG <p-inputnumber> component (which nests an <input> inside)."""
    if field_was_handled(page, log, label):
        return
    try:
        # PrimeNG inputnumber has a nested <input> element
        inner_input = page.locator(f"{selector} input").first
        is_visible = await inner_input.is_visible()
        if not is_visible:
            inner_input = page.locator(selector).first

        await inner_input.wait_for(state="visible", timeout=5000)
        await inner_input.scroll_into_view_if_needed()
        await inner_input.focus()

        # PrimeNG components use custom event handlers that do not bind properly
        # with direct page.fill() under instant_fill. We must type character-by-character
        # to trigger all internal value/mask formatting listeners.
        instant_fill, typing_delay = _get_oic_fill_settings()
        delay_to_use = 5 if instant_fill else typing_delay

        await inner_input.fill("")
        for char in str(value):
            await inner_input.press_sequentially(char, delay=delay_to_use)

        # Trigger change events
        await inner_input.evaluate("el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); el.dispatchEvent(new Event('blur', { bubbles: true })); }")
        await _check_field_validation(inner_input)

        if isinstance(log, AutomationLogger):
            kwargs = {}
            if source is not None:
                kwargs["source"] = source
            log.field_filled(label, value, **kwargs)
        else:
            log(f"[{_ts()}]   ✅ [{label}] filled → '{str(value)[:60]}'")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.field_failed(label, str(e))
        else:
            log(f"[{_ts()}]   ⚠️ [{label}] error: {e}")
        await field_problem(page, log, label, str(e))

    await asyncio.sleep(delay_ms / 1000.0)


# ── MUI DatePicker Helpers ───────────────────────────────────────────────────


def format_date_for_mui(raw_date) -> str:
    """Format any date string to DD-MM-YYYY (hyphen-separated) for MUI DatePickers.

    The OIC MUI DatePicker expects DD-MM-YYYY with hyphens (see placeholder).

    Delegates to the shared OIC date formatter service (date_formatter.py) which
    is the single source of truth for all date parsing on this portal.
    All callers of this function remain unchanged — public API is preserved.
    """
    return _format_oic_date(raw_date)


async def fill_mui_datepicker(
    page: Page, label_text: str, value: str, label: str,
    log, delay_ms: int = 30, source: Optional[str] = None
) -> bool:
    """Fill a Material UI DatePicker by locating it via its visible label text.

    MUI DatePickers on the OIC portal use dynamic IDs (e.g., :r0:, :r4:)
    that change on every render.  This helper finds the correct input by:
      1. Locating the `.DatePicker` container whose label contains *label_text*
      2. Finding the `MuiInputBase-input` inside that container
      3. Triple-clicking to select all, then typing the formatted date
      4. Pressing Escape to close any calendar popup, then Tab to blur

    Args:
        label_text: The visible label text (e.g., "Date of Survey").
        value:      Date string — will be formatted to DD-MM-YYYY automatically.
        label:      Human-friendly label for logging.

    Returns:
        True if the date was successfully filled, False otherwise.
    """
    decision = field_decision(page, log, label)
    if decision is not None:
        return decision == "fixed"
    formatted = format_date_for_mui(value)
    if not formatted:
        if isinstance(log, AutomationLogger):
            log.field_failed(label, "empty date value — skipped")
        else:
            log(f"[{_ts()}]   ⚠️ [{label}] empty date value — skipped")
        await field_problem(page, log, label, "empty date value — skipped")
        return False

    try:
        # 1. Locate the DatePicker container by its label text
        container = page.locator(
            f".DatePicker:has(label:has-text('{label_text}'))"
        ).first
        await container.wait_for(state="visible", timeout=8000)

        # 2. Find the MUI input inside that container
        input_el = container.locator("input.MuiInputBase-input").first
        await input_el.wait_for(state="visible", timeout=3000)
        await input_el.scroll_into_view_if_needed()

        # 3. Triple-click and clear any pre-existing value to avoid appending onto pre-filled date masks
        await input_el.click(click_count=3)
        await asyncio.sleep(0.05)
        await input_el.fill("")
        await asyncio.sleep(0.05)

        # 4. Type date at max speed (delay=0) or low delay if typed simulation is preferred
        instant_fill, typing_delay = _get_oic_fill_settings()
        datepicker_delay = 0 if instant_fill else max(5, typing_delay // 2)
        for char in formatted:
            await input_el.press_sequentially(char, delay=datepicker_delay)

        # 4. Close any calendar popup and blur
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.05)
        await page.keyboard.press("Tab")
        await _check_field_validation(input_el)

        if isinstance(log, AutomationLogger):
            kwargs = {}
            if source is not None:
                kwargs["source"] = source
            log.field_filled(label, formatted, **kwargs)
        else:
            log(f"[{_ts()}]   ✅ [{label}] filled → '{formatted}'")
        return True

    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.field_failed(label, str(e))
        else:
            log(f"[{_ts()}]   ⚠️ [{label}] error: {e}")
        await field_problem(page, log, label, str(e))
        return False
    finally:
        await asyncio.sleep(delay_ms / 1000.0)


# ── PrimeNG Textarea Helper ──────────────────────────────────────────────────


async def fill_textarea_primeng(
    page: Page, selector: str, value: str, label: str,
    log, delay_ms: int = 30, source: Optional[str] = None
) -> None:
    """Fill a PrimeNG textarea (<textarea> element) with instant fill or typed simulation.

    PrimeNG textareas are plain <textarea> elements (not <input>).  This helper:
      1. Waits for the element to be visible.
      2. Focuses and clears/fills based on instant vs typed settings.
      3. Dispatches input / change / blur events so the framework registers the
         change (same pattern as fill_input_with_delay for <input> elements).
    """
    if field_was_handled(page, log, label):
        return
    try:
        locator = page.locator(selector).first
        await locator.wait_for(state="visible", timeout=5000)
        await locator.scroll_into_view_if_needed()
        await locator.focus()

        instant_fill, typing_delay = _get_oic_fill_settings()
        if instant_fill:
            await locator.fill(str(value))
        else:
            await locator.fill("")
            for char in str(value):
                await locator.press_sequentially(char, delay=typing_delay)

        # Dispatch change events so the Angular/PrimeNG framework registers the value
        await locator.evaluate(
            "el => { "
            "el.dispatchEvent(new Event('input',  {bubbles: true})); "
            "el.dispatchEvent(new Event('change', {bubbles: true})); "
            "el.dispatchEvent(new Event('blur',   {bubbles: true})); }"
        )
        await _check_field_validation(locator)

        if isinstance(log, AutomationLogger):
            kwargs = {}
            if source is not None:
                kwargs["source"] = source
            log.field_filled(label, str(value)[:60], **kwargs)
        else:
            log(f"[{_ts()}]   ✅ [{label}] filled → '{str(value)[:60]}'")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.field_failed(label, str(e))
        else:
            log(f"[{_ts()}]   ⚠️ [{label}] error: {e}")
        await field_problem(page, log, label, str(e))

    await asyncio.sleep(delay_ms / 1000.0)
