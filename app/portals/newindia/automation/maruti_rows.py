"""Enter and verify assessor-added rows in New India's Maruti assessment."""

import re
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
        if (field && !field.disabled &&
            (model?.$invalid || model?.$pending || !field.validity.valid ||
             (key === 'hsn' && model && !model.$modelValue))) invalid.push(key);
    }
    return {values, invalid, added: Boolean(probe('input[id="vPartDesc"]')),
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


def row_problems(state, item):
    if state is None:
        return ["the row is missing"]
    errors = ["Part No. should be blank"] if state["part"] else []
    for key, expected in item.values().items():
        shown = state["values"][key]
        if key in _NUMBER_FIELDS:
            valid = parse_amount(shown) == parse_amount(expected)
        elif key == "service":
            valid = _word(shown) in {"allow", "allowed"} if expected == "Allow" else _word(shown) == _word(expected)
        else:
            valid = _word(shown) == _word(expected)
        if not valid:
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


async def _fill_item(row, item, stop_cb):
    for key, value in item.values().items():
        if stop_cb():
            return
        field = row.locator(f"{_FIELDS[key]}:visible")
        if await field.count() != 1 or not await field.is_enabled():
            continue
        try:
            if key in {"item", "service"}:
                await field.select_option(value=value, timeout=1800)
            elif key == "hsn":
                await field.fill(value, timeout=1800)
                options = row.locator('ul[typeahead-popup] li a:visible').filter(
                    has_text=re.compile(rf"(?<!\w){re.escape(value)}(?!\w)"),
                )

                async def one_match():
                    return await options.count() == 1

                if await wait_until_ready(one_match, seconds=2.5, stopped=stop_cb):
                    await options.click(timeout=1800)
                    gst = row.locator(f'{_FIELDS["gst"]}:visible')

                    async def gst_loaded():
                        return await gst.count() == 1 and bool((await gst.input_value(timeout=400)).strip())

                    await wait_until_ready(gst_loaded, seconds=2.5, stopped=stop_cb)
                else:
                    await field.blur(timeout=1000)
            elif await field.is_editable():
                await field.fill(value, timeout=1800)
                await field.blur(timeout=1000)
        except Exception:
            # The checkpoint reports the exact field if Angular did not retain it.
            continue


async def add_and_fill_row(body, rows, index, item, stop_cb):
    """Click once and wait for a single new editable row before entering anything."""
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

    if not await wait_until_ready(added_one, seconds=4, stopped=stop_cb):
        return False
    await _fill_item(rows.nth(index), item, stop_cb)
    return True


async def fill_blank_row(rows, index, item, stop_cb):
    await _fill_item(rows.nth(index), item, stop_cb)
