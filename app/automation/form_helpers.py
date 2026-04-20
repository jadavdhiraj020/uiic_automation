"""
form_helpers.py — Shared low-level helpers for all form modules.
CONFIRMED: No iframe. All elements on main page.

STABILITY FIXES 2026-04-18:
  - safe_fill: now only skips None/empty (not "0" — "0" is a valid value)
  - safe_fill_amount: calls _raw_fill directly (bypasses the "0" skip)
  - safe_fill_date: SIMPLIFIED JS — removes nativeInputValueSetter that crashed Chrome.
    Now uses simple el.value = iso + ONE input event. No more freeze/crash.
"""
import asyncio
import logging
import os
import re
from typing import Callable

logger = logging.getLogger(__name__)


# ── Value converters ──────────────────────────────────────────────────────────

def _clean_text_for_portal(value: str) -> str:
    """Strip characters the portal rejects: @ # $ ! ' etc.
    NOTE: commas (,) are intentionally preserved here — used by safe_fill_text for general fields.
    For fields with strict portal restriction (Place, Observation), use _clean_text_strict().
    """
    return re.sub(r"[@#$!'`]", "", str(value)).strip()


def _clean_text_strict(value: str) -> str:
    """Strip ALL portal-forbidden special chars including commas.
    Portal message: 'Please do not enter Special Symbols such as @ # $ ! \' , etc.'
    Use for: Place of Survey, Surveyor Observation, Remarks.
    """
    # Strip: @ # $ ! ' ` , and other portal-rejected chars
    cleaned = re.sub(r"[@#$!'`,\.\(\)\[\]\{\}\*\^\&\%\~\|\\<>\"]", " ", str(value))
    # Collapse multiple spaces
    cleaned = re.sub(r" +", " ", cleaned).strip()
    return cleaned


def _to_int_amount(value: str) -> str:
    """
    Round decimal rupee amount to nearest integer.
    Portal requirement: 'Please enter amount in rounded value near to rupee.'
    141262.52 → '141263'  |  100818.02 → '100818'  |  '0' → '0'
    """
    try:
        return str(round(float(str(value).replace(",", ""))))
    except Exception:
        return str(value)


def _to_iso_date(value: str) -> str:
    """
    Convert any date format to ISO YYYY-MM-DD (required by input[type='date']).
    Handles: DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY, YYYY-MM-DD
    Returns empty string if unparseable.
    """
    v = str(value).strip()
    if not v:
        return ""
    # Already ISO
    if re.match(r"^\d{4}-\d{2}-\d{2}$", v):
        return v
    # DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
    m = re.match(r"^(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})$", v)
    if m:
        d, mo, y = m.group(1), m.group(2), m.group(3)
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    # YYYY/MM/DD
    m = re.match(r"^(\d{4})[/\-\.](\d{1,2})[/\-\.](\d{1,2})$", v)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3)
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    return ""


# ── Internal raw fill (no value filtering) ───────────────────────────────────

async def _raw_fill(page, sel: str, value_str: str, label: str,
                    log_cb: Callable, timeout_ms: int = 5000,
                    retries: int = 1) -> bool:
    """
    Core fill operation with one automatic retry on failure.
    No value filtering — fills whatever string is passed.
    """
    for attempt in range(retries + 1):
        try:
            el = page.locator(sel).first
            await el.wait_for(state="visible", timeout=timeout_ms)
            await el.click(click_count=3)
            await el.fill(value_str)
            await el.press("Tab")
            await asyncio.sleep(0.1)
            log_cb(f"  ✅ {label}: {value_str[:60]}")
            return True
        except Exception as e:
            if attempt < retries:
                log_cb(f"  🔄 {label}: retry {attempt+1} ({str(e)[:60]})")
                await asyncio.sleep(0.5)
            else:
                log_cb(f"  ⚠️  {label}: {str(e)[:100]}")
    return False


# ── Public fill helpers ───────────────────────────────────────────────────────

async def safe_fill(page, sel: str, value, label: str,
                    log_cb: Callable, timeout_ms: int = 5000) -> bool:
    """
    Fill a text / number input.
    Skips only if value is None or empty string.
    NOTE: '0' is NOT skipped — it's a valid value.
    """
    if value is None or str(value).strip() == "":
        return False
    return await _raw_fill(page, sel, str(value).strip(), label, log_cb, timeout_ms)


async def safe_fill_amount(page, sel: str, value, label: str,
                           log_cb: Callable, timeout_ms: int = 5000) -> bool:
    """
    Fill a monetary field (rounds to nearest integer).
    Fills even when value is '0' — these are mandatory portal fields.
    Only skips when value is None or empty string.
    """
    if value is None or str(value).strip() == "":
        return False
    int_val = _to_int_amount(str(value))
    # Use _raw_fill directly (not safe_fill) so "0" is NOT filtered out
    return await _raw_fill(page, sel, int_val, label, log_cb, timeout_ms)


async def safe_fill_date(page, sel: str, value, label: str,
                         log_cb: Callable, timeout_ms: int = 5000) -> bool:
    """
    Fill an Angular custom datepicker field (text input with calendar icon).

    STRATEGY (most reliable for AngularJS datepickers):
      1. Wait for element to be visible.
      2. Use JS to set value directly on the element AND fire Angular-compatible
         events (input + change) so the model updates.
      3. Press Escape to close any calendar popup that may have opened.
      4. Press Tab to confirm and move to next field.

    Portal expects: DD/MM/YYYY format in these text inputs.
    """
    if not value or str(value).strip() == "":
        log_cb(f"  ⏭️  {label}: skipped (empty)")
        return False

    iso_date = _to_iso_date(str(value).strip())
    if not iso_date:
        log_cb(f"  ⚠️  {label}: bad date '{value}'")
        return False

    # Portal text fields expect DD/MM/YYYY
    parts = iso_date.split("-")                          # ['2026', '03', '16']
    display = f"{parts[2]}/{parts[1]}/{parts[0]}"       # '16/03/2026'

    # ── Strategy 1: JS value injection (most reliable for Angular) ────────────
    try:
        el = page.locator(sel).first
        await el.wait_for(state="visible", timeout=timeout_ms)

        set_ok = await page.evaluate(f"""
            (function() {{
                var el = document.querySelector('{sel}');
                if (!el) return false;

                // Close any open datepicker by pressing Escape first
                el.dispatchEvent(new KeyboardEvent('keydown', {{
                    bubbles: true, cancelable: true, keyCode: 27, key: 'Escape'
                }}));

                // Set the value
                el.value = '{display}';

                // Fire events Angular needs to register the change
                el.dispatchEvent(new Event('input',  {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                el.dispatchEvent(new KeyboardEvent('keydown', {{
                    bubbles: true, cancelable: true, keyCode: 9, key: 'Tab'
                }}));
                el.blur();
                return true;
            }})();
        """)

        if set_ok:
            # Verify the value was actually set
            await asyncio.sleep(0.15)
            actual = await page.evaluate(f"""
                (function() {{
                    var el = document.querySelector('{sel}');
                    return el ? el.value : '';
                }})();
            """)
            if actual and actual.strip():
                await page.keyboard.press("Escape")  # close any stray popup
                await asyncio.sleep(0.1)
                log_cb(f"  ✅ {label}: {actual} (JS)")
                return True

    except Exception as e1:
        log_cb(f"  🔄 {label}: JS strategy failed ({str(e1)[:60]}), trying keyboard...")

    # ── Strategy 2: Triple-click select-all, then type (keyboard fallback) ────
    try:
        el = page.locator(sel).first
        await el.wait_for(state="visible", timeout=2000)

        # Triple-click to select all existing text WITHOUT opening picker
        await el.click(click_count=3)
        await asyncio.sleep(0.1)
        await page.keyboard.press("Escape")   # close calendar if opened
        await asyncio.sleep(0.1)
        await page.keyboard.press("Control+a")  # select all
        await page.keyboard.type(display, delay=25)
        await asyncio.sleep(0.1)
        await page.keyboard.press("Escape")   # close calendar
        await asyncio.sleep(0.05)
        await page.keyboard.press("Tab")
        await asyncio.sleep(0.15)

        log_cb(f"  ✅ {label}: {display} (keyboard)")
        return True

    except Exception as e2:
        log_cb(f"  ⚠️  {label}: all strategies failed. JS err: {str(e2)[:80]}")
        return False


async def safe_fill_text(page, sel: str, value, label: str,
                         log_cb: Callable, timeout_ms: int = 5000) -> bool:
    """Fill a general text/textarea — strips portal-rejected chars (NOT commas)."""
    if not value or str(value).strip() == "":
        return False
    clean = _clean_text_for_portal(str(value))
    if not clean:
        return False
    return await _raw_fill(page, sel, clean, label, log_cb, timeout_ms)


async def safe_fill_portal_text(page, sel: str, value, label: str,
                                log_cb: Callable, timeout_ms: int = 5000) -> bool:
    """Fill a portal text field with STRICT char stripping (commas, dots, special chars).
    Use for: Place of Survey, Surveyor Observation, Remarks.
    Portal warning: 'Please do not enter Special Symbols such as @ # $ ! , etc.'
    """
    if not value or str(value).strip() == "":
        return False
    clean = _clean_text_strict(str(value))
    if not clean:
        return False
    return await _raw_fill(page, sel, clean, label, log_cb, timeout_ms)


async def safe_select(page, sel: str, value: str, label: str,
                      log_cb: Callable, timeout_ms: int = 5000) -> bool:
    """
    Select a dropdown option by label, value, or partial text match.
    Handles both plain <select> and AngularJS selects where option values
    are prefixed with 'number:' or 'string:' (e.g. 'number:10').
    """
    if not value or str(value).strip() == "":
        return False
    try:
        el = page.locator(sel).first
        await el.wait_for(state="visible", timeout=timeout_ms)

        # ── Strategy 1: Try exact label match ─────────────────────────────────
        try:
            await el.select_option(label=value)
            await asyncio.sleep(0.1)
            log_cb(f"  ✅ {label}: {value}")
            return True
        except Exception:
            pass

        # ── Strategy 2: Try exact value match ─────────────────────────────────
        try:
            await el.select_option(value=value)
            await asyncio.sleep(0.1)
            log_cb(f"  ✅ {label}: {value}")
            return True
        except Exception:
            pass

        # ── Strategy 3: Scan all options — handles Angular 'number:X' prefixes
        opts = await el.locator("option").all()
        val_lower = value.strip().lower()
        for opt in opts:
            txt = (await opt.inner_text()).strip()
            opt_val = await opt.get_attribute("value") or ""
            # Match by visible text (exact or partial)
            txt_lower = txt.lower()
            if val_lower == txt_lower or val_lower in txt_lower or txt_lower in val_lower:
                await el.select_option(value=opt_val)
                await asyncio.sleep(0.1)
                log_cb(f"  ✅ {label}: '{txt}' (text match)")
                return True
            # Match by stripping Angular prefixes from option value
            # e.g. 'number:10' → '10', 'string:HH' → 'HH'
            stripped = re.sub(r'^(number|string):', '', opt_val).strip().lower()
            if val_lower == stripped:
                await el.select_option(value=opt_val)
                await asyncio.sleep(0.1)
                log_cb(f"  ✅ {label}: '{txt}' (angular value match)")
                return True

        # ── Strategy 4: JS fallback for AngularJS select ──────────────────────
        set_ok = await page.evaluate(f"""
            (function() {{
                var el = document.querySelector('{sel}');
                if (!el) return false;
                var search = '{value.strip().lower()}';
                var opts = Array.from(el.options);
                // Match by text
                var match = opts.find(o =>
                    o.text.trim().toLowerCase() === search ||
                    o.text.trim().toLowerCase().includes(search) ||
                    search.includes(o.text.trim().toLowerCase())
                );
                // Match by value stripping Angular prefixes
                if (!match) {{
                    match = opts.find(o => {{
                        var v = o.value.replace(/^(number|string):/, '').trim().toLowerCase();
                        return v === search;
                    }});
                }}
                if (match) {{
                    el.value = match.value;
                    el.dispatchEvent(new Event('change', {{bubbles: true}}));
                    return match.text;
                }}
                return false;
            }})();
        """)
        if set_ok:
            await asyncio.sleep(0.1)
            log_cb(f"  ✅ {label}: '{set_ok}' (JS fallback)")
            return True

        log_cb(f"  ⚠️  {label}: no match for '{value}'")
        return False
    except Exception as e:
        log_cb(f"  ⚠️  {label}: {str(e)[:100]}")
        return False


async def safe_radio(page, sel: str, label: str,
                     log_cb: Callable, timeout_ms: int = 3000) -> bool:
    """Click a radio button."""
    try:
        el = page.locator(sel).first
        await el.wait_for(state="visible", timeout=timeout_ms)
        await el.click()
        await asyncio.sleep(0.1)
        log_cb(f"  ✅ {label}: Yes")
        return True
    except Exception as e:
        log_cb(f"  ⚠️  {label}: {str(e)[:100]}")
        return False


async def click_all_yes_radios(page, radio_names: list, log_cb: Callable) -> int:
    """
    JS-based click of all Yes (value='Y') radios by ng-model / name attribute.
    Returns count of successfully clicked radios.
    """
    names_js = str(radio_names).replace("'", '"')
    result = await page.evaluate(f"""
        (function() {{
            var names = {names_js};
            var clicked = [];
            names.forEach(function(name) {{
                var selectors = [
                    'input[name="' + name + '"][value="Y"]',
                    'input[ng-model*="' + name + '"][value="Y"]',
                    'input[data-ng-model*="' + name + '"][value="Y"]',
                ];
                for (var s of selectors) {{
                    var r = document.querySelector(s);
                    if (r) {{
                        r.checked = true;
                        r.click();
                        r.dispatchEvent(new Event('change', {{bubbles: true}}));
                        clicked.push(name);
                        break;
                    }}
                }}
            }});
            return clicked;
        }})();
    """)
    clicked = result or []
    log_cb(f"  🔘 Radios: {len(clicked)}/{len(radio_names)} clicked")
    return len(clicked)


async def js_select_option(page, sel_index: int, doc_type: str,
                           ng_model: str, log_cb: Callable) -> bool:
    """JS partial-text dropdown selection for AngularJS selects."""
    result = await page.evaluate(f"""
        (function() {{
            var selects = document.querySelectorAll('select[ng-model="{ng_model}"]');
            var target = selects[{sel_index}];
            if (!target) return null;
            var opts = Array.from(target.options);
            var search = '{doc_type.lower()[:25]}';
            var match = opts.find(o => o.text.toLowerCase().includes(search));
            if (!match) {{
                var words = search.split(' ');
                for (var w of words) {{
                    if (w.length > 3) {{
                        match = opts.find(o => o.text.toLowerCase().includes(w));
                        if (match) break;
                    }}
                }}
            }}
            if (match) {{
                target.value = match.value;
                target.dispatchEvent(new Event('change', {{bubbles: true}}));
                return match.text;
            }}
            return null;
        }})();
    """)
    if result:
        log_cb(f"      ✅ Doc type: '{result}'")
        return True
    log_cb(f"      ⚠️  No match for '{doc_type}'")
    return False


async def quick_visible(locator, timeout_ms: int = 1000) -> bool:
    try:
        return await locator.is_visible(timeout=timeout_ms)
    except Exception:
        return False


async def get_form_frame(page, log_cb: Callable):
    """No iframe on this portal — returns page directly (no delay)."""
    return page


async def dump_visible_fields(page, tab_name: str, log_cb: Callable):
    """Save DOM snapshot for debugging (only call when diagnosing issues)."""
    try:
        os.makedirs("logs", exist_ok=True)
        html = await page.content()
        path = f"logs/dom_{tab_name.replace(' ', '_')}.html"
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        log_cb(f"  💾 DOM saved: {path}")
    except Exception:
        pass
