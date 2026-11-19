"""Upload and verify the prepared OIC invoice workbook."""

import asyncio
from contextlib import suppress
from hashlib import sha256
from pathlib import Path
import re
from uuid import uuid4

from playwright.async_api import Error as PlaywrightError

from app.portals.oic.automation.assessment_upload_excel import prepared_upload_error
from app.portals.oic.automation.recovery import form_step_is_open, wait_until_ready


UPLOAD_TIMEOUT_SECONDS = 75
IMPORT_TIMEOUT_SECONDS = 75
POLL_SECONDS = 0.35


def _upload_button(page, name):
    return page.get_by_role("button", name=name, exact=True).and_(page.locator(":visible"))


async def _button_enabled(button):
    if await button.count() == 1:
        with suppress(PlaywrightError):
            return await button.is_enabled(timeout=1000)
    return None


async def _check_validation(validation, message):
    if await _button_enabled(validation):
        with suppress(PlaywrightError):
            await validation.click(timeout=2000)
        raise RuntimeError(message)


async def _recognizes_upload(page, filename):
    return await page.get_by_text(filename, exact=False).evaluate_all(
        r"""(nodes, filename) => {
            const normalize = text => text.toLowerCase().replace(/\s+/g, ' ').trim();
            const expected = normalize(filename);
            return nodes.some(node => {
                for (let row = node, depth = 0; row && depth < 4; row = row.parentElement, depth++) {
                    if (row.querySelector('input[type="file"]')) break;
                    if (!row.getClientRects().length || getComputedStyle(row).visibility !== 'visible') continue;
                    const text = normalize(row.innerText || '');
                    if (!text.includes(expected)) continue;
                    const status = text.replace(expected, ' ');
                    if (/[\w.-]+\.xlsx?\b/.test(status)) continue;
                    if (/\b(failed|failure|unsuccessful|not|rejected|error)\b/.test(status)) continue;
                    if (/^(?:uploaded|success)\s*$/.test(status.trim()) ||
                        /\bupload(?:ed)? (?:was )?(?:successful(?:ly)?|complete[d]?)\b|\bsuccessfully uploaded\b/.test(status)) {
                        return true;
                    }
                }
                return false;
            });
        }""",
        filename,
    )


async def _invoice_state(page, invoice, items):
    return await page.evaluate(
        r"""({ invoice, items }) => {
            const norm = s => (s || '').trim().toLowerCase().replace(/\s+/g, ' ');
            const tabs = [...document.querySelectorAll('.p-accordion-tab')].filter(tab => {
                const heading = tab.querySelector(':scope > .p-accordion-header h6');
                return heading && /invoice number/i.test(heading.textContent) &&
                    heading.getClientRects().length && norm(heading.querySelector('b')?.textContent) === norm(invoice);
            });
            if (tabs.length !== 1) return { count: tabs.length, expanded: false, missing: items, unexpected: [] };
            const tab = tabs[0];
            const header = tab.querySelector(':scope > .p-accordion-header .p-accordion-header-link');
            const remaining = [...tab.querySelectorAll('.p-accordion-header h6')]
                .filter(heading => /item sub type/i.test(heading.textContent))
                .map(heading => norm(heading.querySelector('b')?.textContent))
                .filter(Boolean);
            const missing = [];
            for (const name of items) {
                const index = remaining.indexOf(norm(name));
                if (index < 0) missing.push(name); else remaining.splice(index, 1);
            }
            return { count: 1, expanded: header?.getAttribute('aria-expanded') === 'true', missing, unexpected: remaining };
        }""",
        {"invoice": invoice, "items": items},
    )


def _items_match(state):
    return state["count"] == 1 and not state["missing"] and not state["unexpected"]


async def _open_invoice(page, invoice):
    heading = page.locator("h6 b").filter(has_text=re.compile(rf"^\s*{re.escape(invoice)}\s*$", re.I))
    header = page.locator(".p-accordion-header-link[aria-expanded='false']:visible").filter(has=heading)
    if await header.count() == 1:
        with suppress(PlaywrightError):
            await header.click(timeout=1500)


async def invoice_import_is_ready(page, invoice, items):
    if not invoice or not items or not await form_step_is_open(page, "loss"):
        return False
    if await _button_enabled(_upload_button(page, "View Validation Errors")):
        return False
    state = await _invoice_state(page, invoice, items)
    if _items_match(state):
        return True
    if state["count"] == 1 and not state["expanded"]:
        await _open_invoice(page, invoice)
    return False


async def import_invoice_workbook(page, claim, log, stop_cb):
    log._section = "Invoice Excel Upload"
    review_error = getattr(claim, "_oic_parts_review_error", "")
    if review_error:
        raise ValueError(f"OIC parts need review: {review_error}")
    if error := prepared_upload_error(claim):
        raise ValueError(error)

    path = Path(claim._oic_upload_path)
    invoice, items = claim._oic_upload_invoice, claim._oic_upload_items
    submit = _upload_button(page, "Submit")
    validation = _upload_button(page, "View Validation Errors")
    await _check_validation(validation, "OIC is showing validation errors for the invoice. Review them in Chrome.")
    state = await _invoice_state(page, invoice, items)
    if state["count"]:
        ready = lambda: invoice_import_is_ready(page, invoice, items)
        if await wait_until_ready(ready, seconds=4, stopped=stop_cb):
            log.info(f"OIC already contains the expected invoice and all {len(items)} items")
            return
        raise RuntimeError("The expected invoice is already on OIC, but its items could not be verified. Review that invoice in Chrome.")

    data = path.read_bytes()
    expected_digest = getattr(claim, "_oic_upload_digest", "")
    if expected_digest and sha256(data).hexdigest() != expected_digest:
        raise ValueError("The generated workbook changed after the folder scan. Stop and rescan the claim folder.")
    file_input = page.locator('input[type="file"][name="excel"]')
    if await file_input.count() != 1 or await submit.count() != 1:
        raise RuntimeError("App3 could not identify the invoice attachment or Submit button on Assessment of Loss.")

    # Use a unique browser filename so a previous upload cannot confirm this attempt.
    filename = f"oic_invoice_{uuid4().hex[:12]}.xlsx"
    was_disabled = (await _button_enabled(submit)) is False
    await submit.scroll_into_view_if_needed(timeout=3000)
    if stop_cb():
        raise asyncio.CancelledError
    await file_input.set_input_files({
        "name": filename,
        "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "buffer": data,
    }, timeout=8000)
    log.info(f"Selected {filename} from {path.name}; waiting for OIC to enable Submit")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + UPLOAD_TIMEOUT_SECONDS
    ready_reads = 0
    acknowledged = False
    while loop.time() < deadline:
        if stop_cb():
            raise asyncio.CancelledError
        if page.is_closed():
            raise RuntimeError("The OIC tab closed while the workbook was uploading.")
        await _check_validation(validation, "OIC reported validation errors for the uploaded workbook.")
        enabled = await _button_enabled(submit)
        was_disabled |= enabled is False
        with suppress(PlaywrightError):
            if not acknowledged:
                acknowledged = await _recognizes_upload(page, filename)
        ready_reads = ready_reads + 1 if enabled and (acknowledged or was_disabled) else 0
        if ready_reads >= 2:
            break
        await asyncio.sleep(POLL_SECONDS)
    else:
        if acknowledged:
            raise RuntimeError("OIC acknowledged the workbook, but Submit stayed unavailable.")
        raise RuntimeError("OIC did not confirm this workbook was ready to submit. Check its upload status in Chrome.")

    if stop_cb():
        raise asyncio.CancelledError
    await _check_validation(validation, "OIC reported validation errors for the uploaded workbook.")
    try:
        await submit.click(timeout=5000)
        log.info("Submitted invoice workbook; checking the invoice and imported items")
    except PlaywrightError:
        # The click may have reached OIC before the control refreshed.
        log.warning("OIC refreshed while submitting the workbook; checking for the invoice before any further action")

    deadline = loop.time() + IMPORT_TIMEOUT_SECONDS
    while loop.time() < deadline:
        if stop_cb():
            raise asyncio.CancelledError
        if page.is_closed():
            raise RuntimeError("The OIC tab closed while importing the invoice.")
        await _check_validation(validation, "OIC rejected the invoice workbook. Review its validation errors in Chrome.")
        try:
            state = await _invoice_state(page, invoice, items)
        except PlaywrightError:
            await asyncio.sleep(POLL_SECONDS)
            continue
        if _items_match(state):
            log.info(f"OIC confirmed invoice and all {len(items)} imported items")
            return
        if state["count"] > 1:
            raise RuntimeError("OIC shows more than one copy of the expected invoice. Review the invoices in Chrome.")
        if state["count"] == 1 and not state["expanded"]:
            await _open_invoice(page, invoice)
        await asyncio.sleep(POLL_SECONDS)
    if not state["count"]:
        raise RuntimeError("OIC did not show the expected invoice after Submit. Check the import result in Chrome.")
    raise RuntimeError(
        f"OIC did not confirm all the invoice items. Missing: {state['missing']}. Unexpected: {state['unexpected']}."
    )
