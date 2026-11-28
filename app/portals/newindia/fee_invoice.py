"""Read the Survey Fee Bill reference and date from their configured cells."""

from datetime import datetime
import re

from app.portals.newindia.fee_charges import _normalise_label, _sheets


def _invoice_value(field, raw):
    if raw is None or not str(raw).strip():
        return ""
    if field.endswith("_date"):
        from app.data.excel_reader import _format_date, _try_date_serial

        value = _format_date(_try_date_serial(raw) or raw)
        try:
            return datetime.strptime(value, "%d/%m/%Y").strftime("%d/%m/%Y")
        except ValueError:
            return ""
    if isinstance(raw, datetime):
        return ""
    from app.data.excel_reader import _clean_value

    value = _clean_value(raw)
    if value.casefold() in {"date", "ref", "reference", "invoice", "number", "no", "na", "n/a"}:
        return ""
    return value if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ./_-]{0,99}", value) else ""


def read_invoice_field(workbook, field, settings, *, formula_workbook=None):
    labels = {_normalise_label(value) for value in settings.get("search_labels", []) if value}
    sheets = _sheets(workbook, settings.get("sheet", "Sheet2"))
    if not sheets:
        return "", "", "The configured fee-bill sheet is missing."
    matches = []
    for sheet in sheets:
        rows = list(sheet.rows())
        for row_index, row in enumerate(rows):
            for column_index, cell in enumerate(row):
                if _normalise_label(cell) not in labels:
                    continue
                target_row = row_index + int(settings.get("row_offset", 0))
                target_col = column_index + int(settings.get("col_offset", 1))
                raw = ""
                if 0 <= target_row < len(rows) and 0 <= target_col < len(rows[target_row]):
                    raw = rows[target_row][target_col]
                source = f"R{target_row + 1}C{target_col + 1} ({sheet.name})"
                uncached_formula = False
                if raw in (None, "") and formula_workbook is not None and target_row >= 0 and target_col >= 0:
                    original = formula_workbook[sheet.name].cell(target_row + 1, target_col + 1)
                    uncached_formula = original.data_type == "f"
                matches.append((row_index, raw, source, uncached_formula))
    if not matches:
        return "", "", "The label was not found on the configured sheet."
    # The fee bill's top Ref and Date are the intended labels.  If two
    # matching labels share that row, their meaning is ambiguous.
    first_row = min(item[0] for item in matches)
    first = [item for item in matches if item[0] == first_row]
    if len(first) != 1:
        return "", "", "More than one matching label appears on the top row."
    _, raw, source, uncached_formula = first[0]
    if uncached_formula:
        return "", source, f"The formula at {source} has no saved result."
    value = _invoice_value(field, raw)
    return (value, source, "") if value else ("", source, f"The value at {source} is missing or invalid.")


def read_invoice_fields(workbook, mapping, source_path):
    formula_workbook = None
    fields = ("sfb_invoice_number", "sfb_invoice_date")
    try:
        if str(source_path).lower().endswith((".xlsx", ".xlsm")):
            import openpyxl
            try:
                formula_workbook = openpyxl.load_workbook(source_path, read_only=True, data_only=False)
            except (OSError, ValueError):
                return {field: ("", "", "Could not verify the fee-bill cells.") for field in fields}
        return {field: read_invoice_field(workbook, field, mapping.get(field, {}),
                                          formula_workbook=formula_workbook)
                for field in fields}
    finally:
        if formula_workbook is not None:
            formula_workbook.close()
