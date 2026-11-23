"""Enter and verify assessor-added rows in New India's Maruti assessment."""

import re
from contextlib import suppress
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook

from app.portals.newindia.field_values import parse_amount
from app.portals.newindia.scan_outputs import ASSESSMENT_SHEET, ASSESSMENT_WORKBOOK
from app.portals.oic.automation.recovery import wait_until_ready


_ITEM_TYPES = {
    "Parts at Agewise Depreciation": "Metal",
    "Parts at 50% Depreciation": "Plastic",
    "Parts at Cost": "Glass",
}
ROWS = 'table[id="example"]:visible > tbody > tr:visible'
_ADD_ROW = (
    'button[data-ng-click*=".addMarutiAssesment("]:visible, '
    'button[ng-click*=".addMarutiAssesment("]:visible'
)
_FIELDS = {
    "item": 'select[id="vItem"]',
    "description": 'input[id="vPartDesc"]',
    "mrp": 'input[id="vMRP"]',
    "quantity": 'input[id="vQuantity"]',
    "depreciation": 'input[id="deprePercent"]',
    "service": 'select[id="sel1"]',
    "amount": 'input[name="approvalAmount"]',
    "hsn": 'input[id="hsnCode"]',
    "gst": 'input[id="gstPercetage"]',
}
_FIELD_LABELS = {
    "item": "Item", "description": "Part Description", "mrp": "MRP",
    "quantity": "Quantity", "depreciation": "Depreciation",
    "service": "Allowed Service type", "amount": "Amount Allowed (GST Excluded)",
    "hsn": "HSN/SAC Code", "gst": "GST%",
}
_NUMBER_FIELDS = {"mrp", "quantity", "depreciation", "amount", "gst"}
_MARUTI_ITEM_OPTIONS = {"labour", "glass", "painting", "plastic", "metal", "denting", "misc", "spare", "other"}

_EDIT_CONTROL = r"""
(row, selector, value, byLabel = false) => {
    if (!row.isConnected) return;
    const fields = [...row.querySelectorAll(selector)].filter(field => field.getClientRects().length);
    if (fields.length !== 1) return;
    const [field] = fields;
    if (field.matches(':disabled, [readonly]')) return;
    if (field.tagName === 'SELECT') {
        const options = [...field.options].filter(option => !option.matches(':disabled') &&
            (option.value === value || (byLabel && option.textContent.trim() === value)));
        if (options.length !== 1 || field.value === options[0].value) return;
        field.value = options[0].value;
    } else {
        if (field.value === value || (field.maxLength >= 0 && value.length > field.maxLength)) return;
        field.focus({preventScroll: true});
        field.value = value;
    }
    field.dispatchEvent(new Event('input', {bubbles: true, composed: true}));
    field.dispatchEvent(new Event('change', {bubbles: true}));
    if (field.tagName !== 'SELECT') field.blur();
}
"""

_EDIT_DEALERS = r"""
(rows, expected) => {
    const edit = """ + _EDIT_CONTROL + r""";
    for (const [index, part, description] of expected) {
        const row = rows[index];
        if (!row || row.querySelector('input[id="vPartDesc"]') ||
            row.cells[2]?.textContent.trim() !== part ||
            row.cells[3]?.textContent.trim() !== description) continue;
        edit(row, 'select[id="sel1"]', 'Not Allowed', true);
    }
}
"""

_EDIT_ITEM_FIELDS = r"""
(row, entries) => {
    const edit = """ + _EDIT_CONTROL + r""";
    for (const [selector, value] of entries) edit(row, selector, value);
}
"""

_SNAPSHOT = r"""
(rows, selectors) => rows.map(row => {
    const probe = selector => [...row.querySelectorAll(selector)].find(el => el.getClientRects().length);
    const cell = index => row.cells[index]?.textContent.trim() || '';
    const read = (selector, index) => probe(selector)?.value.trim() ?? cell(index);
    const indices = {item: 1, description: 3, mrp: 4, depreciation: 5, quantity: 6,
                     service: 10, amount: 11, hsn: 12, gst: 13};
    const values = {};
    const invalid = [];
    for (const [key, selector] of Object.entries(selectors)) {
        const field = probe(selector);
        const model = field && window.angular?.element(field)?.controller('ngModel');
        values[key] = read(selector, indices[key]);
        if (key === 'service' && field?.selectedOptions[0]?.textContent.trim() === 'Not Allowed') {
            values[key] = 'Not Allowed';
        }
        const view = model?.$viewValue;
        if (field && !field.disabled &&
            (model?.$invalid || model?.$pending || !field.validity.valid ||
             (typeof view === 'string' && view.trim() !== field.value.trim()) ||
             (key === 'hsn' && model && !model.$modelValue))) invalid.push(key);
    }
    return {values, invalid, added: Boolean(probe('input[id="vPartDesc"]')),
            itemSelect: Boolean(probe(selectors.item)),
            part: read('input[id="vPartNumber"]', 2), columns: row.cells.length};
})
"""


@dataclass(frozen=True)
class MarutiItem:
    item: str
    description: str
    amount: Decimal
    hsn: str

    def values(self):
        charge = format(self.amount.normalize(), "f")
        return {
            "item": self.item, "description": self.description,
            "mrp": charge, "quantity": "1", "depreciation": "0",
            "service": "Allow" if self.item == "Labour" else "Replace",
            "amount": charge, "hsn": self.hsn, "gst": "0",
        }


def read_maruti_items(path):
    """Use the same rows and amounts prepared by the current folder scan."""
    if not path or Path(path).name.casefold() != ASSESSMENT_WORKBOOK:
        raise ValueError("Scan the claim folder to prepare a fresh Primary Assessment workbook.")
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        rows = workbook[ASSESSMENT_SHEET].values
        if next(rows, None) != (
            "SlNo", "category", "description", "partName", "serviceType",
            "estimatedAmount", "billedAmount", "assessedAmount",
            "depreciationPercentage", "hsnCode", "gstPercentage",
        ):
            raise ValueError("The Primary Assessment workbook has unexpected columns. Rescan the folder.")
        items = []
        for source_row, row in enumerate(rows, 2):
            if all(value is None for value in row):
                continue
            category, description, name, charge, hsn = row[1], row[2], row[3], row[7], row[9]
            kind = _ITEM_TYPES.get(description) if category == "Spare Parts" else None
            if category == "Labor Charges":
                kind = "Labour"
            amount = parse_amount(charge)
            name = str(name or "").strip()
            hsn = str(hsn or "").strip()
            if not kind or not name or amount is None or amount < 0 or not hsn.isascii() or not hsn.isdigit():
                raise ValueError(f"Review the item type, description, amount and HSN on workbook row {source_row}.")
            items.append(MarutiItem(kind, name, amount, hsn))
        if not items:
            raise ValueError("No assessed items were prepared. Check the report and rescan the folder.")
        return items
    finally:
        workbook.close()


def _word(value):
    return " ".join(value.casefold().split())


def _same_field(key, shown, expected):
    if key in _NUMBER_FIELDS:
        return parse_amount(shown) == parse_amount(expected)
    if key == "service" and expected == "Allow":
        return _word(shown) in {"allow", "allowed"}
    return _word(shown) == _word(expected)


def dealer_not_allowed(state):
    return _word(state["values"]["service"]) == "not allowed" and "service" not in state["invalid"]


def dealer_row_problems(state):
    if state is None:
        return ["check the missing row"]
    problems = []
    if not dealer_not_allowed(state):
        problems.append("set Allowed Service type to Not Allowed")
    if state["itemSelect"] and (
        _word(state["values"]["item"]) not in _MARUTI_ITEM_OPTIONS or "item" in state["invalid"]
    ):
        problems.append("select a valid Item")
    # New India validates this value on every row when saving a Maruti draft.
    if not re.fullmatch(r"[0-9]{1,2}(?:\.[0-9]{1,2})?", state["values"]["depreciation"]):
        problems.append("enter Depreciation from 0 to 99.99 with up to two decimal places")
    return problems


def row_problems(state, item):
    if state is None:
        return ["the row is missing"]
    errors = ["Part No. should be blank"] if state["part"] else []
    for key, expected in item.values().items():
        shown = state["values"][key]
        if not _same_field(key, shown, expected):
            errors.append(f"{_FIELD_LABELS[key]} needs {expected}" + (f" (shows {shown})" if shown else ""))
        elif key in state["invalid"]:
            errors.append(f"New India did not accept {_FIELD_LABELS[key]} ({shown})")
    return errors


def assign_existing_rows(states, items):
    """Consume each existing row at most once, including identical report lines."""
    remaining = set(range(len(states)))
    matches = {}
    for number, item in enumerate(items):
        candidates = [
            idx for idx in sorted(remaining)
            if not states[idx]["part"] and _word(states[idx]["values"]["description"]) == _word(item.description)
            and (states[idx]["added"] or (
                _word(states[idx]["values"]["item"]) == _word(item.item)
                and _word(states[idx]["values"]["service"]) not in {"", "not allowed"}
            ))
        ]
        if candidates:
            idx = min(candidates, key=lambda index: (
                _word(states[index]["values"]["item"]) != _word(item.item),
                bool(row_problems(states[index], item)),
            ))
            matches[number] = idx
            remaining.remove(idx)
    dealers = [idx for idx in sorted(remaining) if not states[idx]["added"]]
    blanks = [
        idx for idx in sorted(remaining) if states[idx]["added"] and not states[idx]["part"]
        and not states[idx]["values"]["description"] and not states[idx]["values"]["amount"]
    ]
    return matches, dealers, blanks


async def row_snapshot(rows):
    return await rows.evaluate_all(_SNAPSHOT, _FIELDS)


async def mark_dealer_group(rows, expected):
    await rows.evaluate_all(_EDIT_DEALERS, expected)


async def fill_item(row, item, stop_cb):
    """Enter one row and return whether an HSN lookup was started."""
    values = item.values()
    ordinary = [(key, value) for key, value in values.items() if key not in {"hsn", "gst"}]
    if stop_cb():
        return False
    try:
        await row.evaluate(_EDIT_ITEM_FIELDS, [(_FIELDS[key], value) for key, value in ordinary], timeout=1500)
        state = (await row_snapshot(row))[0]
        ordinary = [
            (key, value) for key, value in ordinary
            if key in state["invalid"] or not _same_field(key, state["values"][key], value)
        ]
    except Exception:
        pass  # Retry with Playwright if the row was rebuilt during fast entry.

    for key, value in ordinary:
        if stop_cb():
            return False
        field = row.locator(f"{_FIELDS[key]}:visible")
        try:
            if await field.count() != 1 or not await field.is_enabled():
                continue
            if key in {"item", "service"}:
                await field.select_option(value=value, timeout=1800)
            elif await field.is_editable():
                await field.fill(value, timeout=1800)
                await field.blur(timeout=1000)
        except Exception:
            # The checkpoint reports the exact field if Angular did not retain it.
            continue

    if stop_cb():
        return False
    field = row.locator(f'{_FIELDS["hsn"]}:visible')
    if await field.count() != 1 or not await field.is_enabled():
        return False
    try:
        await field.fill(item.hsn, timeout=1800)
        options = row.locator('ul[typeahead-popup] li a:visible').filter(
            has_text=re.compile(rf"(?<!\w){re.escape(item.hsn)}(?!\w)"),
        )
        # A strict locator waits for the suggestion and rejects ambiguous matches.
        await options.wait_for(state="visible", timeout=2500)
        if stop_cb():
            return False
        await options.click(timeout=1800)
    except Exception:
        return False
    # Some forms expose GST as an editable box. Keep the normal portal lookup for
    # read-only GST and verify its eventual value at the draft checkpoint.
    if not stop_cb():
        with suppress(Exception):
            await row.evaluate(_EDIT_ITEM_FIELDS, [(_FIELDS["gst"], values["gst"])], timeout=1000)
    return True


async def add_row(body, rows, index, stop_cb):
    """Click once and wait for a single new editable row."""
    add = body.locator(_ADD_ROW).filter(has_text=re.compile(r"^\s*Add Row\s*$", re.I))
    if await add.count() != 1:
        return False
    try:
        await add.click(timeout=2500)
    except Exception:
        # The click may have reached the portal. Observe the table before deciding.
        pass

    async def added_one():
        if await rows.count() != index + 1:
            return False
        return await rows.nth(index).locator(f'{_FIELDS["description"]}:visible').count() == 1

    return await wait_until_ready(added_one, seconds=4, stopped=stop_cb)
