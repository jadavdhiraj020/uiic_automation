"""Build and validate the OIC bulk invoice/item import workbook."""

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path
import os
import re
import tempfile
from zipfile import ZipFile

import openpyxl
from openpyxl.worksheet.datavalidation import DataValidation

from app.data.excel_parts_extractor import (
    _detect_labour_header, _is_summary_row, _normalize_boundary_keyword, _MIN_HEADER_CONFIDENCE,
    extract_parts_and_labour, select_oic_survey_sheet,
)
from app.portals.oic.generated_files import publish_generated
from app.utils import ensure_dir, user_data_dir


SUPPORTED_DEPRECIATION = frozenset(Decimal(x) for x in (0, 5, 10, 15, 20, 25, 30, 35, 40, 50))
PAINT_SPLIT_RATE = Decimal("12.5")
INVOICE_HEADERS = ("Invoice Number", "Invoice Date (DD-MM-YYYY)", "Invoice GST Type", "Invoice Amount", "Invoice GST Amount")
ITEM_HEADERS = ("Invoice Number", "Item Description", "Item Sub Type", "Side Description", "Item Amount", "Depreciation Rate", "GST Rate", "Estimated Amount", "Estimated Amount Remarks", "HSN Code", "GST Amount")


def _number(value, label):
    text = str(value if value is not None else "").strip().replace(",", "").rstrip("%").strip()
    try:
        result = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{label} is missing or is not a number") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"{label} must be a non-negative number")
    return result


def _nil_depreciation(claim):
    """Return True/False only when the mapped Excel value is unambiguous."""
    raw = getattr(claim, "nil_depreciation", "")
    value = str(raw if raw is not None else "").strip().casefold()
    if value in {"yes", "y", "true", "1", "nil dep", "nil depreciation"}:
        return True
    if value in {"no", "n", "false", "0"}:
        return False
    return None


def depreciation_errors(claim):
    """Return specific OIC upload blockers before launching the browser."""
    nil_depreciation = _nil_depreciation(claim)
    if nil_depreciation is None:
        return ["Nil Depreciation must be Yes or No; check OIC Field Mapping and rescan the folder"]
    if nil_depreciation:
        return []
    errors = []
    for field, label in (("metal_depreciation_rate", "Metal"), ("paint_depreciation_rate", "Paint")):
        try:
            rate = _number(getattr(claim, field, ""), f"{label} depreciation rate")
        except ValueError as exc:
            errors.append(str(exc) + "; check OIC Field Mapping and rescan the folder")
            continue
        if rate not in SUPPORTED_DEPRECIATION and not (field == "paint_depreciation_rate" and rate == PAINT_SPLIT_RATE):
            allowed = "0, 5, 10, 15, 20, 25, 30, 35, 40, 50"
            if field == "paint_depreciation_rate":
                allowed += ", 12.5 (split into material and labour)"
            errors.append(f"{label} depreciation rate {rate}% is not supported by the OIC upload template (allowed: {allowed}). Check the source Excel and mapping.")
    return errors


def prepared_upload_error(claim):
    """Require the workbook produced for the current folder scan."""
    error = str(getattr(claim, "_oic_upload_error", "") or "").strip()
    if error:
        return f"OIC upload Excel could not be prepared: {error}"
    path = str(getattr(claim, "_oic_upload_path", "") or "").strip()
    invoice = str(getattr(claim, "_oic_upload_invoice", "") or "").strip()
    items = getattr(claim, "_oic_upload_items", None)
    if not path or not Path(path).is_file() or not invoice or not items:
        return "OIC upload Excel is missing. Rescan the claim folder before starting."
    return ""


def _labour_totals(path, boundary_keyword):
    wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    try:
        ws = select_oic_survey_sheet(wb)
        detected = _detect_labour_header(ws)
        if not detected.row or detected.confidence < _MIN_HEADER_CONFIDENCE:
            raise ValueError("OIC labour table could not be identified reliably")
        columns = dict(detected.col_map)
        for cell in ws[detected.row]:
            if re.fullmatch(r"\s*paint(?:ing)?\s*", str(cell.value or ""), re.I):
                columns["painting"] = cell.column
                break
        keys = ("rr", "denting", "cw", "painting")
        missing = [key for key in keys if key not in columns]
        if missing:
            raise ValueError("OIC labour columns missing: " + ", ".join(missing))
        boundaries = {x.strip().casefold().replace(" ", "") for x in _normalize_boundary_keyword(boundary_keyword).split("|") if x.strip()}
        totals = {key: Decimal(0) for key in keys}
        for row in ws.iter_rows(min_row=detected.row + 1):
            if any(str(c.value or "").strip().casefold().replace(" ", "") in boundaries for c in row):
                break
            name = ws.cell(row[0].row, columns["labour_desc"]).value
            if not name or _is_summary_row(str(name)):
                continue
            for key in keys:
                raw = ws.cell(row[0].row, columns[key]).value
                if raw is None or str(raw).strip().casefold() in ("", "-", "na", "n/a", "nil"):
                    continue
                totals[key] += _number(raw, f"Labour {key} row {row[0].row}")
        return totals
    finally:
        wb.close()


def _date(value):
    if isinstance(value, datetime):
        return value.strftime("%d-%m-%Y")
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(str(value).strip(), fmt).strftime("%d-%m-%Y")
        except ValueError:
            pass
    raise ValueError("Workshop invoice date is missing or invalid")


def build_upload_workbook(claim, defaults, output_folder=None):
    """Create a fresh OIC import workbook and return its path and item names."""
    errors = depreciation_errors(claim)
    if errors:
        raise ValueError("; ".join(errors))
    source = Path(str(getattr(claim, "source_excel_path", "") or ""))
    if not source.is_file():
        raise ValueError("Source survey Excel is missing; rescan the claim folder")
    invoice = str(getattr(claim, "workshop_invoice_no", "") or getattr(claim, "invoice_no", "") or "").strip()
    if not invoice:
        raise ValueError("Workshop invoice number is missing")
    invoice_date = _date(getattr(claim, "workshop_invoice_date", "") or getattr(claim, "invoice_date", ""))
    invoice_gst = _number(getattr(claim, "invoice_gst_amount", ""), "Invoice GST amount")
    gst_type = str(defaults.get("gst_type", "IGST")).strip().upper()
    if gst_type not in ("IGST", "CGST/SGST"):
        raise ValueError(f"Unsupported invoice GST type: {gst_type}")
    nil_depreciation = _nil_depreciation(claim)
    metal_rate = Decimal(0) if nil_depreciation else _number(claim.metal_depreciation_rate, "Metal depreciation rate")
    paint_rate = Decimal(0) if nil_depreciation else _number(claim.paint_depreciation_rate, "Paint depreciation rate")
    boundary = defaults.get("table_boundary_keyword", "sub total|total|grand total")
    parts, _, _ = extract_parts_and_labour(str(source), boundary_keyword=boundary, oic_flexible_parts=True)
    totals = _labour_totals(str(source), boundary)
    if not parts and not any(totals.values()):
        raise ValueError("No non-zero OIC spare parts or labour amounts were found in the source Excel")
    part_hsn = str(defaults.get("item_hsn_code") or "8512").strip()
    labour_hsn = str(defaults.get("labour_hsn_code") or "8729").strip()
    rows = []
    for part in parts:
        material = part["material_type"]
        category, rate = {"metal": ("Metallic Parts", metal_rate), "plastic": ("Plastic", Decimal(0) if nil_depreciation else Decimal(50)), "glass": ("Glass", Decimal(0))}[material]
        rows.append((category, str(part["part_name"]), _number(part["billed_amount"], "Part amount"), rate, _number(part["estimated_amount"], "Part estimated amount"), part_hsn))
    labour_rows = [
        ("Labour Charge", name, totals[key], Decimal(0), totals[key], labour_hsn)
        for key, name in (("rr", "R/R"), ("denting", "DENTING"), ("cw", "C/W"))
    ]
    paint_total = totals["painting"]
    if nil_depreciation or paint_rate == PAINT_SPLIT_RATE:
        material_amount = (paint_total * Decimal("0.25")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        labour_amount = paint_total - material_amount
        labour_rows.append(("Plastic", "Painting material", material_amount, Decimal(0) if nil_depreciation else Decimal(50), material_amount, part_hsn))
        labour_rows.append(("Labour Charge", "Painting labour", labour_amount, Decimal(0), labour_amount, labour_hsn))
    else:
        labour_rows.append(("Labour Charge", "PAINT", paint_total, paint_rate, paint_total, labour_hsn))
    rows.extend(row for row in labour_rows if row[2] != 0)

    # OIC compares this field against the sum of the uploaded item amounts.
    # Derive it from the same rows rather than from the separate GST summary.
    invoice_amount = sum((row[2] for row in rows), Decimal(0))
    wb = openpyxl.Workbook()
    inv = wb.active
    inv.title = "Invoice"
    inv.append(INVOICE_HEADERS)
    inv.append((invoice, invoice_date, gst_type, float(invoice_amount), float(invoice_gst)))
    ws = wb.create_sheet("Items")
    ws.append(ITEM_HEADERS)
    cached = {}
    for r, (category, name, amount, rate, estimate, hsn) in enumerate(rows, 2):
        ws.append((invoice, category, name, "Front", float(amount), float(rate), 18, float(estimate), None, hsn, f"=ROUND((E{r}-(E{r}*F{r}/100))*(G{r}/100),2)"))
        cached[f"K{r}"] = (amount * (1 - rate / 100) * Decimal("0.18")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    for sheet, target, options in (
        (inv, "C2:C1048576", "IGST,CGST/SGST"),
        (ws, "B2:B1048576", "Non-Metallic Parts,Metallic Parts,Plastic,Glass,Labour Charge,Others"),
        (ws, "D2:D1048576", "Left,Right,Bottom,Top,Rear,Front,Vertex"),
        (ws, "F2:F1048576", "0,5,10,15,20,25,30,35,40,50"),
        (ws, "G2:G1048576", "0,5,12,18,28"),
    ):
        validation = DataValidation(type="list", formula1=f'"{options}"', allow_blank=True)
        sheet.add_data_validation(validation)
        validation.add(target)
    # Excel formulas need cached values for portal importers that do not recalculate.
    buffer = BytesIO()
    wb.save(buffer)
    wb.close()
    # A scan may request the claim folder; the scanner excludes these generated
    # workbooks from source and document selection on subsequent scans.
    output_dir = ensure_dir(str(output_folder or user_data_dir("oic", "assessment_uploads")))
    output = os.path.join(output_dir, "auto_oic_upload_current.xlsx")
    buffer.seek(0)
    fd, staged = tempfile.mkstemp(prefix=".oic-upload-", suffix=".tmp", dir=output_dir)
    try:
        with os.fdopen(fd, "wb") as output_file:
            with ZipFile(buffer, "r") as src, ZipFile(output_file, "w") as dest:
                for info in src.infolist():
                    data = src.read(info.filename)
                    if info.filename == "xl/worksheets/sheet2.xml":
                        xml = data.decode("utf-8")
                        for cell, value in cached.items():
                            pattern = rf'(<c r="{cell}"[^>]*>\s*<f[^>]*>.*?</f>\s*<v>).*?(</v>)'
                            xml, count = re.subn(pattern, lambda m: m.group(1) + str(value) + m.group(2), xml, count=1)
                            if count != 1:
                                raise ValueError(f"Unable to cache GST formula in {cell}")
                        data = xml.encode("utf-8")
                    dest.writestr(info, data)
        publish_generated(staged, output)
    finally:
        if os.path.exists(staged):
            os.remove(staged)
    claim._oic_upload_invoice_amount = format(invoice_amount, "f")
    return output, invoice, [row[1] for row in rows]


def upload_amount_warning(path):
    """Warn before starting if the portal's known invoice check will fail."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        invoice_amount = _number(wb["Invoice"]["D2"].value, "Invoice amount")
        total = sum(
            (_number(row[4], "Item amount") for row in wb["Items"].iter_rows(min_row=2, values_only=True) if row[0] is not None),
            Decimal(0),
        )
        if invoice_amount < total:
            return (f"OIC upload invoice amount {invoice_amount:.2f} is less than the item total {total:.2f}; "
                    "OIC has rejected this mismatch. Review the source amounts before starting.")
        return ""
    finally:
        wb.close()
