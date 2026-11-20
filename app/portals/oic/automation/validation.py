"""Read OIC's validation messages with their field labels when available."""

import asyncio
import re
from contextlib import suppress

from app.portals.oic.automation.recovery import BLOCKING_DIALOG, operator_reason, portal_messages


_CONTROLS = 'input:not([type=hidden]), textarea, select, [role=combobox]'

_READ_VALIDATION = r"""
function readValidation(controls, includeUnlinked) {
    const controlSelector = 'input:not([type=hidden]), textarea, select, [role=combobox]';
    const errorSelector = '.p-error, .error-message, .error-messageSeverity, .MuiFormHelperText-root.Mui-error';
    const groupSelector = '.input-section, .p-float-label, .p-field, .form-group, .MuiFormControl-root';
    const clean = value => (value || '').replace(/\s+/g, ' ').trim();
    const visible = node => node && node.getClientRects().length &&
        !node.closest('[hidden], [aria-hidden="true"]') && getComputedStyle(node).visibility === 'visible';
    const references = value => clean(value).split(' ').filter(Boolean).map(id => document.getElementById(id));
    const seen = new Set();
    const issues = [];

    for (const target of controls) {
        const control = target.matches(controlSelector) ? target : target.querySelector(controlSelector);
        if (!visible(control) || control.readOnly || control.matches(':disabled, [aria-disabled=true]')) continue;

        const group = control.closest(groupSelector);
        const singleField = group && [...group.querySelectorAll(controlSelector)].filter(visible).length === 1;
        const labels = [...(control.labels || []), ...references(control.getAttribute('aria-labelledby'))];
        if (singleField && group.querySelectorAll('label').length === 1) labels.push(group.querySelector('label'));
        const label = clean(labels.find(visible)?.innerText || control.getAttribute('aria-label')).replace(/[ *]+$/, '');

        const invalid = control.getAttribute('aria-invalid') === 'true' ||
            Boolean(control.willValidate && !control.validity.valid);
        const linked = references(control.getAttribute('aria-errormessage'));
        if (invalid) {
            // A description can be a placeholder or help text. Only an actual
            // validation element can supply a reason to pause this field.
            linked.push(...references(control.getAttribute('aria-describedby')).filter(node =>
                node?.matches(`${errorSelector}, [role="alert"]`)));
        }
        if (singleField) linked.push(...group.querySelectorAll(errorSelector));
        const errors = linked.filter(visible).filter(node => clean(node.innerText));
        errors.forEach(node => seen.add(node));
        const nativeError = control.validity?.valueMissing ? 'Required.' : control.validationMessage;
        const message = errors[0]?.innerText || nativeError ||
            (invalid && includeUnlinked && label ? 'Check the value.' : '');
        if (message) issues.push([label, clean(message)]);
    }

    if (includeUnlinked) {
        for (const node of document.querySelectorAll(errorSelector)) {
            if (!seen.has(node) && visible(node) && clean(node.innerText)) {
                issues.push(['', clean(node.innerText)]);
            }
        }
    }
    return issues;
}
"""


async def field_validation_message(locator):
    """Check only the field App3 just edited."""
    with suppress(Exception):
        found = await locator.evaluate(f"field => ({_READ_VALIDATION})([field], false)", timeout=500)
        if found:
            # Allow the portal to clear an error from the previous value.
            await asyncio.sleep(0.4)
            found = await locator.evaluate(f"field => ({_READ_VALIDATION})([field], false)", timeout=500)
            if found:
                return operator_reason(found[0][1], "OIC flagged this field. Check its value in Chrome.")
    return ""


async def portal_validation_summary(page, button):
    """Report actual validation evidence when the expected step did not open."""
    issues = await page.locator(_CONTROLS).evaluate_all(f"fields => ({_READ_VALIDATION})(fields, true)")
    for message in await portal_messages(page):
        if re.search(r"\b(error|required|invalid|failed|missing|cannot|not found|no .{1,40} found)\b", message, re.I):
            issues.append(("", message))
    lines = []
    for label, message in issues:
        safe_label = label if re.fullmatch(r"[A-Za-z][A-Za-z .()'/&-]{1,56}(?: [1-9]\d?)?", label or "") else ""
        message = operator_reason(message, "Check this value in Chrome." if safe_label else "")
        if not message:
            continue
        line = f"{safe_label}. {message}" if safe_label else message
        if line not in lines:
            lines.append(line)
    if lines:
        detail = "\n".join(lines[:3])
        if len(lines) > 3:
            detail += "\nSee Chrome for the remaining messages."
        return "Check the OIC form", detail
    dialog = page.locator(BLOCKING_DIALOG).first
    if await dialog.is_visible():
        return "Check the OIC message", "OIC is showing a dialog. Respond to it in Chrome."
    return None
