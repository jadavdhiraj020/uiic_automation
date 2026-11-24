"""Enter and verify assessor-added rows in New India's Maruti assessment."""

import re
from contextlib import suppress
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from openpyxl import load_workbook

from app.data.excel_parts_extractor import (
    _MIN_HEADER_CONFIDENCE,
    _detect_labour_header,
    extract_painting_rows,
)
from app.portals.newindia.field_values import parse_amount
from app.portals.newindia.scan_outputs import ASSESSMENT_SHEET, ASSESSMENT_WORKBOOK
from app.portals.oic.automation.recovery import wait_until_ready
from app.utils import load_automation_defaults


_ITEM_TYPES = {
    "Parts at Agewise Depreciation": "Metal",
    "Parts at 50% Depreciation": "Plastic",
    "Parts at Cost": "Glass",
}
_MARUTI_PARTS_HSN = "870840"
_MARUTI_LABOUR_HSN = "998714"
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
    "dealer_service": 'input[id="vDealerServiceType"]',
    "service": 'select[id="sel1"]',
    "amount": 'input[name="approvalAmount"]',
    "hsn": 'input[id="hsnCode"]',
    "gst": 'input[id="gstPercetage"]',
}
_FIELD_LABELS = {
    "item": "Item", "description": "Part Description", "mrp": "MRP",
    "quantity": "Quantity", "depreciation": "Depreciation",
    "dealer_service": "Dealer Service Type",
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
        const want = String(value).trim().toLowerCase();
        const options = [...field.options].filter(option => !option.matches(':disabled') &&
            (option.value === value || option.value.trim().toLowerCase() === want ||
             (byLabel && (option.textContent.trim() === value || option.textContent.trim().toLowerCase() === want))));
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
    const validItems = new Set(['labour', 'glass', 'painting', 'plastic', 'metal', 'denting', 'misc', 'spare', 'other']);
    for (const [index, part, description] of expected) {
        const row = rows[index];
        if (!row || row.querySelector('input[id="vPartDesc"]') ||
            row.cells[2]?.textContent.trim() !== part ||
            row.cells[3]?.textContent.trim() !== description) continue;
        edit(row, 'select[id="sel1"]', 'Not Allowed', true);
        const itemSel = [...row.querySelectorAll('select[id="vItem"]')].find(el => el.getClientRects().length);
        if (itemSel && !itemSel.matches(':disabled, [readonly]')) {
            const cur = (itemSel.value || '').trim().toLowerCase();
            if (!validItems.has(cur)) {
                edit(row, 'select[id="vItem"]', 'Spare', true);
            }
        }
    }
}
"""

_EDIT_ITEM_FIELDS = r"""
(row, entries) => {
    const edit = """ + _EDIT_CONTROL + r""";
    for (const [selector, value] of entries) edit(row, selector, value, true);
}
"""

_SNAPSHOT = r"""
(rows, selectors) => rows.map(row => {
    const probe = selector => [...row.querySelectorAll(selector)].find(el => el.getClientRects().length);
    const cell = index => row.cells[index]?.textContent.trim() || '';
    const read = (selector, index) => probe(selector)?.value.trim() ?? (index !== undefined ? cell(index) : '');
    const indices = {item: 1, description: 3, mrp: 4, depreciation: 5, quantity: 6,
                     dealer_service: 9, service: 10, amount: 11, hsn: 12, gst: 13};
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
        const errors = model?.$error ? Object.keys(model.$error) : [];
        // New India's claimAssessmentFormParse() clears $error.parse on 'P'/'S'/'SFB'
        // after typeahead selection, but omits a 'Maruti' branch, leaving $error.parse=true
        // on input#hsnCode even after a valid suggestion is selected and $modelValue is set.
        const modelInvalid = Boolean(
            model?.$invalid && !(key === 'hsn' && model?.$modelValue && errors.length === 1 && errors[0] === 'parse')
        );
        if (field && !field.disabled &&
            (modelInvalid || model?.$pending || !field.validity.valid ||
             (typeof view === 'string' && view.trim() !== field.value.trim()) ||
             (key === 'hsn' && model && !model.$modelValue))) invalid.push(key);
    }
    return {values, invalid, added: Boolean(probe('input[id="vPartDesc"]')),
            itemSelect: Boolean(probe(selectors.item)),
            hasDealerServiceInput: Boolean(probe(selectors.dealer_service)),
            part: read('input[id="vPartNumber"]', 2), columns: row.cells.length};
})
"""


_ZERO = Decimal("0")
_PLASTIC_DEFAULT_PCT = Decimal("50")


def _parse_pct(value) -> Decimal | None:
    """A percentage from 0 to 99.99 (the range New India accepts), else None."""
    text = str(value if value is not None else "").strip().rstrip("%").strip()
    if not text:
        return None
    try:
        pct = Decimal(text)
    except InvalidOperation:
        return None
    if not pct.is_finite():
        return None
    pct = pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)  # New India accepts 2 decimals
    if pct < 0 or pct >= 100:
        return None
    return pct


def _pct_text(pct: Decimal) -> str:
    return format(pct.normalize(), "f")


@dataclass(frozen=True)
class DepreciationRules:
    """Depreciation % App3 enters for each Maruti row.

    Nil Depreciation = Yes: every row 0. Otherwise (No or missing): Plastic uses the
    Automation Defaults value (50), Metal and Painting use the Excel values, and Glass,
    Labour and everything else are 0. A Metal or Painting % that Excel did not give is 0.
    """
    nil_depreciation: bool = False
    metal: Decimal | None = None
    painting: Decimal | None = None
    plastic: Decimal = _PLASTIC_DEFAULT_PCT
    plastic_setting_invalid: bool = False

    def for_item(self, kind: str) -> Decimal:
        if self.nil_depreciation:
            return _ZERO
        if kind == "Plastic":
            return self.plastic
        if kind == "Metal":
            return self.metal if self.metal is not None else _ZERO
        if kind == "Painting":
            return self.painting if self.painting is not None else _ZERO
        return _ZERO

    def missing(self) -> list[str]:
        """Excel percentages that were needed but not found (empty under Nil Depreciation)."""
        if self.nil_depreciation:
            return []
        return [
            name for name, pct in (("Metal", self.metal), ("Painting", self.painting)) if pct is None
        ]

    def summary(self) -> str:
        if self.nil_depreciation:
            return "Nil Depreciation is Yes: Depreciation 0 on every row."
        shown = lambda pct: _pct_text(pct) if pct is not None else "not found (0)"  # noqa: E731
        return (
            f"Nil Depreciation is not Yes: Plastic {_pct_text(self.plastic)}, "
            f"Metal {shown(self.metal)}, Painting {shown(self.painting)}, Glass 0, Labour and others 0."
        )


def build_depreciation_rules(data, defaults) -> DepreciationRules:
    """Rules from the scanned Excel values and the Automation Defaults."""
    nil = str(getattr(data, "nil_depreciation", "") or "").strip().lower() in {"yes", "y"}
    raw_plastic = (defaults or {}).get("plastic_depreciation_pct")
    plastic = _parse_pct(raw_plastic)
    return DepreciationRules(
        nil_depreciation=nil,
        metal=_parse_pct(getattr(data, "metal_depreciation_pct", "")),
        painting=_parse_pct(getattr(data, "paint_depreciation_pct", "")),
        plastic=plastic if plastic is not None else _PLASTIC_DEFAULT_PCT,
        plastic_setting_invalid=plastic is None and str(raw_plastic or "").strip() != "",
    )


@dataclass(frozen=True)
class MarutiItem:
    item: str
    description: str
    amount: Decimal
    hsn: str
    mrp: Decimal | None = None
    depreciation: Decimal = _ZERO

    def values(self):
        charge = format(self.amount.normalize(), "f")
        mrp_val = self.mrp if (self.mrp is not None and self.mrp > 0) else self.amount
        mrp_text = format(mrp_val.normalize(), "f")
        service_val = "Repair" if self.item in {"Labour", "Painting"} else "Replace"
        return {
            "item": self.item, "description": self.description,
            "mrp": mrp_text, "quantity": "1", "depreciation": _pct_text(self.depreciation),
            "dealer_service": service_val, "service": service_val,
            "amount": charge, "hsn": self.hsn,
        }


def _read_excel_painting_items(
    source_excel_path: str | None, rules: DepreciationRules | None = None,
) -> list[MarutiItem]:
    """Extract Painting rows (full Excel PAINT amount) from the source Excel."""
    rules = rules or DepreciationRules(nil_depreciation=True)
    if not source_excel_path or not Path(source_excel_path).is_file():
        return []
    defaults = load_automation_defaults(portal_id="newindia")
    boundary_kw = str(defaults.get("table_boundary_keyword") or "sub total").strip() or "sub total"
    wb = load_workbook(source_excel_path, data_only=True)
    try:
        ws = wb.active
        labour_det = _detect_labour_header(ws)
        if not labour_det.row or labour_det.confidence < _MIN_HEADER_CONFIDENCE:
            return []
        paint_rows = extract_painting_rows(
            ws,
            labour_det.row,
            labour_det.col_map,
            hsn_code=_MARUTI_LABOUR_HSN,
            boundary_keyword=boundary_kw,
        )
        items: list[MarutiItem] = []
        for prow in paint_rows:
            amt = parse_amount(prow.get("assessed_amount"))
            if amt is None or amt <= 0:
                continue
            est = parse_amount(prow.get("estimated_amount"))
            mrp_amt = est if (est is not None and est > 0) else amt
            name = str(prow.get("part_name") or "").strip()
            if name:
                items.append(MarutiItem(
                    "Painting", name, amt, _MARUTI_LABOUR_HSN, mrp=mrp_amt,
                    depreciation=rules.for_item("Painting"),
                ))
        return items
    except Exception:
        return []
    finally:
        wb.close()


def read_maruti_items(path, source_excel_path: str | None = None, rules: DepreciationRules | None = None):
    """Use the same rows and amounts prepared by the current folder scan.

    ``rules`` sets each row's Depreciation; without it every row keeps Depreciation 0.
    """
    rules = rules or DepreciationRules(nil_depreciation=True)
    if not path or Path(path).name.casefold() != ASSESSMENT_WORKBOOK:
        raise ValueError("Scan the claim folder to prepare a fresh Primary Assessment workbook.")
    workbook = load_workbook(path, read_only=True, data_only=True)
    has_painting_in_workbook = False
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
            category, description, name, est_raw, charge, hsn_raw = (
                row[1], row[2], row[3], row[5], row[7], row[9]
            )
            kind = _ITEM_TYPES.get(description) if category == "Spare Parts" else None
            if category == "Labor Charges":
                kind = "Painting" if str(description or "").strip().casefold() == "painting" else "Labour"
            elif str(category or "").strip().casefold() == "painting":
                kind = "Painting"
            if kind == "Painting":
                has_painting_in_workbook = True

            amount = parse_amount(charge)
            if amount is not None and amount == 0 and kind in {"Labour", "Painting"}:
                # Skip zero-amount placeholder lines (e.g. "1 | Labour | Estimate=35000 | R/R=0")
                continue

            est_amount = parse_amount(est_raw)
            mrp_amount = est_amount if (est_amount is not None and est_amount > 0) else amount
            name = str(name or "").strip()

            raw_hsn = str(hsn_raw or "").strip()
            if kind in {"Labour", "Painting"}:
                hsn = _MARUTI_LABOUR_HSN if raw_hsn in {"", "8729", "8512"} else raw_hsn
            else:
                hsn = _MARUTI_PARTS_HSN if raw_hsn in {"", "8512", "8708"} else raw_hsn

            if not kind or not name or amount is None or amount < 0 or not hsn.isascii() or not hsn.isdigit():
                raise ValueError(f"Review the item type, description, amount and HSN on workbook row {source_row}.")
            items.append(MarutiItem(
                kind, name, amount, hsn, mrp=mrp_amount, depreciation=rules.for_item(kind),
            ))
    finally:
        workbook.close()

    if not has_painting_in_workbook:
        candidate_excel = source_excel_path
        if not candidate_excel and path:
            # Look for main Excel in the same claim folder if not passed explicitly
            folder = Path(path).parent
            for entry in sorted(folder.iterdir()):
                if (
                    entry.is_file()
                    and entry.suffix.casefold() in {".xlsx", ".xlsm", ".xls"}
                    and entry.name.casefold() != ASSESSMENT_WORKBOOK
                    and not entry.name.startswith(("~$", "."))
                    and not entry.name.casefold().startswith(("printable_assessment", "reinspection"))
                ):
                    candidate_excel = str(entry)
                    break
        items.extend(_read_excel_painting_items(candidate_excel, rules))

    if not items:
        raise ValueError("No assessed items were prepared. Check the report and rescan the folder.")
    return items


def _word(value):
    return " ".join(str(value or "").casefold().split())


def _same_field(key, shown, expected):
    if key in _NUMBER_FIELDS:
        return parse_amount(shown) == parse_amount(expected)
    if key == "service":
        w_shown = _word(shown)
        w_exp = _word(expected)
        if w_exp in {"allow", "allowed"}:
            return w_shown in {"allow", "allowed"}
        if w_exp == "repair":
            return w_shown in {"repair", "allow", "allowed"}
        return w_shown == w_exp
    return _word(shown) == _word(expected)


def dealer_not_allowed(state):
    if not (_word(state["values"]["service"]) == "not allowed" and "service" not in state["invalid"]):
        return False
    if state.get("itemSelect") and (
        _word(state["values"]["item"]) not in _MARUTI_ITEM_OPTIONS or "item" in state["invalid"]
    ):
        return False
    return True


def dealer_row_problems(state):
    if state is None:
        return ["check the missing row"]
    problems = []
    if not (_word(state["values"]["service"]) == "not allowed" and "service" not in state["invalid"]):
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
        if key == "dealer_service" and not state.get("hasDealerServiceInput"):
            continue
        shown = state["values"].get(key, "")
        if not _same_field(key, shown, expected):
            errors.append(f"{_FIELD_LABELS[key]} needs {expected}" + (f" (shows {shown})" if shown else ""))
        elif key in state["invalid"]:
            errors.append(f"New India did not accept {_FIELD_LABELS[key]} ({shown})")
    # GST% is auto-populated by New India from the selected HSN/SAC code (e.g. 18%).
    gst_shown = state["values"].get("gst", "")
    if parse_amount(gst_shown) is None:
        errors.append("GST% was not populated from HSN/SAC Code")
    elif "gst" in state["invalid"]:
        errors.append(f"New India did not accept GST% ({gst_shown})")
    return errors


def assign_existing_rows(states, items):
    """Consume each existing row at most once, including identical report lines."""
    remaining = set(range(len(states)))
    matches = {}
    for number, item in enumerate(items):
        candidates = [
            idx for idx in sorted(remaining)
            if not states[idx]["part"]
            and _word(states[idx]["values"]["description"]) == _word(item.description)
            and (
                (states[idx]["added"] and _word(states[idx]["values"]["item"]) in {"", _word(item.item)})
                or (
                    _word(states[idx]["values"]["item"]) == _word(item.item)
                    and _word(states[idx]["values"]["service"]) not in {"", "not allowed"}
                )
            )
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
    # Order matters on the live Maruti portal: setting Item and Dealer Service Type
    # first causes Angular's ng-if on Allowed Service type (select#sel1) to render
    # the dropdown containing 'Repair' / 'Replace' before we select #sel1.
    ordered_keys = ("item", "description", "mrp", "quantity", "depreciation", "dealer_service", "service", "amount")
    ordinary = [(key, values[key]) for key in ordered_keys if key in values]
    if stop_cb():
        return False
    state = None
    try:
        await row.evaluate(_EDIT_ITEM_FIELDS, [(_FIELDS[key], value) for key, value in ordinary], timeout=1500)
        state = (await row_snapshot(row))[0]
        ordinary = [
            (key, value) for key, value in ordinary
            if (key != "dealer_service" or state.get("hasDealerServiceInput"))
            and (key in state["invalid"] or not _same_field(key, state["values"][key], value))
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
                try:
                    await field.select_option(value=value, timeout=1800)
                except Exception:
                    if key == "service" and value == "Repair":
                        await field.select_option(value="Allow", timeout=1800)
                    else:
                        await field.select_option(label=value, timeout=1800)
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
    _clear_hsn_parse_js = """el => {
        const model = window.angular?.element(el)?.controller('ngModel');
        if (model && model.$modelValue) {
            model.$setValidity('parse', true);
            el.classList.remove('error-field', 'inperr');
        }
    }"""
    if (
        state is not None
        and _same_field("hsn", state["values"].get("hsn", ""), item.hsn)
        and "hsn" not in state["invalid"]
        and parse_amount(state["values"].get("gst", "")) is not None
    ):
        with suppress(Exception):
            await field.evaluate(_clear_hsn_parse_js, timeout=1000)
        return True
    try:
        if (await field.input_value(timeout=1000)).strip():
            await field.click(timeout=1000)
            await field.fill("", timeout=1500)
        await field.fill(item.hsn, timeout=1800)
        options = row.locator('ul[typeahead-popup] li a:visible').filter(
            has_text=re.compile(rf"(?<!\w){re.escape(item.hsn)}(?!\w)"),
        )
        # A strict locator waits for the suggestion and rejects ambiguous matches.
        await options.wait_for(state="visible", timeout=2500)
        if stop_cb():
            return False
        await options.click(timeout=1800)
        with suppress(Exception):
            await field.evaluate(_clear_hsn_parse_js, timeout=1000)
    except Exception:
        return False
    return True


DEPRECIATION_ROW_KINDS = frozenset({"Metal", "Plastic", "Painting"})


async def fill_existing_depreciation(row, item, stop_cb) -> bool:
    """Type only the Depreciation % on a row the portal already held.

    Rows that came from the portal are matched to Excel items and are not re-entered, so
    their Depreciation stays at the portal's 0 unless it is typed here. Only Metal, Plastic
    and Painting rows are touched, nothing else on the row changes, and a locked or
    read-only box is left alone. Returns True when the row now shows the wanted value
    because of this call.
    """
    if item.item not in DEPRECIATION_ROW_KINDS or stop_cb():
        return False
    wanted = item.values()["depreciation"]

    def accepted(state):
        return (
            _same_field("depreciation", state["values"]["depreciation"], wanted)
            and "depreciation" not in state["invalid"]
        )

    try:
        if accepted((await row_snapshot(row))[0]):
            return False
    except Exception:
        return False
    try:
        await row.evaluate(_EDIT_ITEM_FIELDS, [(_FIELDS["depreciation"], wanted)], timeout=1500)
        if accepted((await row_snapshot(row))[0]):
            return True
    except Exception:
        pass  # Retry with Playwright if the row was rebuilt during fast entry.
    if stop_cb():
        return False
    field = row.locator(f'{_FIELDS["depreciation"]}:visible')
    try:
        if await field.count() != 1 or not await field.is_enabled() or not await field.is_editable():
            return False
        await field.fill(wanted, timeout=1800)
        await field.blur(timeout=1000)
        return accepted((await row_snapshot(row))[0])
    except Exception:
        return False


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
