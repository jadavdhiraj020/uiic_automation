"""Read the two fee-bill charges without picking up unrelated amounts."""

import re
from decimal import Decimal, InvalidOperation


def _normalise_label(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _sheets(workbook, setting):
    setting = str(setting or "Sheet2").strip()
    if setting.upper() == "ALL":
        return [workbook.get_sheet(name) for name in workbook.sheet_names()]
    match = re.fullmatch(r"Sheet(\d+)", setting, re.I)
    if match:
        names = workbook.sheet_names()
        index = int(match.group(1)) - 1
        return [workbook.get_sheet(names[index])] if 0 <= index < len(names) else []
    sheet = workbook.get_sheet(setting)
    return [sheet] if sheet is not None else []


def _amount(raw):
    if raw is None or not str(raw).strip():
        return Decimal(0)
    text = str(raw).strip()
    text = re.sub(r"^(?:₹|Rs\.?|INR)\s*", "", text, flags=re.I).replace(",", "")
    try:
        result = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() and result >= 0 else None


def read_charge(workbook, settings, *, formula_workbook=None):
    """Return (amount, source, problem); blank cells and missing labels are zero."""
    labels = {_normalise_label(label) for label in settings.get("search_labels", []) if label}
    sheets = _sheets(workbook, settings.get("sheet", "Sheet2"))
    if not sheets:
        return None, "", "The configured fee-bill sheet is missing."
    matches = []
    for sheet in sheets:
        rows = list(sheet.rows())
        for row_index, row in enumerate(rows):
            for column_index, cell in enumerate(row):
                if _normalise_label(cell) not in labels:
                    continue
                target_row = row_index + int(settings.get("row_offset", 0))
                target_col = column_index + int(settings.get("col_offset", 5))
                raw = ""
                if 0 <= target_row < len(rows) and 0 <= target_col < len(rows[target_row]):
                    raw = rows[target_row][target_col]
                source = f"R{target_row + 1}C{target_col + 1} ({sheet.name})"
                if raw in (None, "") and formula_workbook is not None and target_row >= 0 and target_col >= 0:
                    original = formula_workbook[sheet.name].cell(target_row + 1, target_col + 1)
                    if original.data_type == "f":
                        return None, source, f"The amount at {source} is a formula without a saved result."
                matches.append((raw, source))
    if not matches:
        return Decimal(0), "", ""
    if len(matches) > 1:
        return None, "", "The charge label appears more than once."
    raw, source = matches[0]
    value = _amount(raw)
    if value is None:
        return None, source, f"The amount at {source} is unreadable."
    return value, source, ""


def read_fee_charges(workbook, mapping, source_path):
    """Read both configured charges and retain any error for manual review."""
    formula_workbook = None
    try:
        if str(source_path).lower().endswith((".xlsx", ".xlsm")):
            import openpyxl
            try:
                formula_workbook = openpyxl.load_workbook(source_path, read_only=True, data_only=False)
            except (OSError, ValueError):
                issue = "Could not verify the fee-bill cells."
                return {field: (None, "", issue) for field in
                        ("sfb_reinspection_charges", "sfb_misc_charge")}
        result = {}
        for field in ("sfb_reinspection_charges", "sfb_misc_charge"):
            result[field] = read_charge(workbook, mapping.get(field, {}), formula_workbook=formula_workbook)
        return result
    finally:
        if formula_workbook is not None:
            formula_workbook.close()
