import asyncio
from typing import Callable
from playwright.async_api import Page
import re
from datetime import datetime


from app.automation.automation_logger import AutomationLogger, _ts

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

async def fill_input_with_delay(
    page: Page, selector: str, value: str, label: str,
    log, delay_ms: int = 600
):
    """Angular-aware text fill with configurable post-fill delay."""
    try:
        await page.wait_for_selector(selector, state="visible", timeout=5000)
        res = await page.evaluate(_JS_FILL, [selector, str(value)])
        if res and res.get("ok"):
            if isinstance(log, AutomationLogger):
                log.field_filled(label, value)
            else:
                log(f"[{_ts()}]   ✅ [{label}] filled → '{str(value)[:60]}'")
        else:
            if isinstance(log, AutomationLogger):
                log.field_failed(label, "Element not found in DOM")
            else:
                log(f"[{_ts()}]   ⚠️ [{label}] fill failed (element not found in DOM)")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.field_failed(label, str(e))
        else:
            log(f"[{_ts()}]   ⚠️ [{label}] error: {e}")

    await asyncio.sleep(delay_ms / 1000.0)


async def select_dropdown_with_delay(
    page: Page, selector: str, value: str, label: str,
    log, delay_ms: int = 600
):
    """Standard <select> dropdown helper with 3-pass matching and configurable delay."""
    try:
        await page.wait_for_selector(selector, state="visible", timeout=5000)
        res = await page.evaluate(_JS_SELECT, [selector, str(value)])
        if res and res.get("ok"):
            if isinstance(log, AutomationLogger):
                log.field_selected(label, res.get("text"))
            else:
                log(f"[{_ts()}]   ✅ [{label}] selected → '{res.get('text')}'")
        else:
            err = res.get('err') if res else 'unknown'
            if isinstance(log, AutomationLogger):
                log.field_failed(label, f"No match for '{value}': {err}")
            else:
                log(f"[{_ts()}]   ⚠️ [{label}] select failed (no match for '{value}'): {err}")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.field_failed(label, str(e))
        else:
            log(f"[{_ts()}]   ⚠️ [{label}] error: {e}")

    await asyncio.sleep(delay_ms / 1000.0)


async def click_radio_with_delay(
    page: Page, name: str, value: str, label: str,
    log, delay_ms: int = 600
):
    """Click radio via label with delay."""
    try:
        res = await page.evaluate(_JS_CLICK_RADIO, [name, value])
        if res and res.get("ok"):
            already = res.get("already", False)
            msg = f"'{value}'" + (" (already set)" if already else "")
            if isinstance(log, AutomationLogger):
                log.field_filled(label, msg)
            else:
                log(f"[{_ts()}]   {'✔' if already else '✅'} [{label}] → {msg}")
        else:
            err = res.get('err') if res else 'unknown'
            if isinstance(log, AutomationLogger):
                log.field_failed(label, f"Click failed: {err}")
            else:
                log(f"[{_ts()}]   ⚠️ [{label}] click failed: {err}")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.field_failed(label, str(e))
        else:
            log(f"[{_ts()}]   ⚠️ [{label}] error: {e}")

    await asyncio.sleep(delay_ms / 1000.0)

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


