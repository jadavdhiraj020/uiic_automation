"""Build a clean Excel working copy from an OIC survey PDF.

The original PDF is never modified or removed.  The generated workbook uses
the same labels/offsets and assessment-table shape that the existing Excel
reader already understands.
"""

from decimal import Decimal, InvalidOperation
import os
import tempfile
from pathlib import Path

import openpyxl
from openpyxl.styles import Font

from app.portals.oic.generated_files import publish_generated
from app.portals.oic.pdf_report import read_oic_pdf_report
from app.utils import load_field_mapping


_OUTPUT_FILENAME = "auto_oic_pdf_source_current.xlsx"


def output_path_for(folder: str) -> str:
    return os.path.abspath(os.path.join(folder, _OUTPUT_FILENAME))


def _display_value(value):
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value).strip()


def _initial_loss_source_value(value):
    """Undo excel_reader’s 75% transform so re-reading preserves the PDF value."""
    text = str(value or "").strip().replace(",", "")
    if not text:
        return ""
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return value
    return format(amount / Decimal("0.75"), "f").rstrip("0").rstrip(".")


def _write_mapped_fields(ws, claim, mapping):
    """Write one canonical field block using the configured Excel offsets."""
    row = 1
    written = 0

    for field_name, cfg in mapping.items():
        if field_name.startswith("_") or not isinstance(cfg, dict):
            continue
        value = getattr(claim, field_name, "")
        if value is None or str(value).strip() == "":
            continue

        labels = cfg.get("search_labels") or cfg.get("search_label") or []
        if isinstance(labels, str):
            labels = [labels]
        labels = [str(label).strip() for label in labels if str(label).strip()]
        if not labels:
            continue

        # Keep the existing Excel reader's special 75% calculation behavior
        # without changing the value already validated from the PDF.
        if field_name == "initial_loss_amount":
            value = _initial_loss_source_value(value)

        row_offset = int(cfg.get("row_offset", 0) or 0)
        col_offset = int(cfg.get("col_offset", 1) or 0)

        # Negative offsets (paint depreciation) need the label to the right.
        label_col = max(1, 1 - min(col_offset, 0))
        target_row = row + row_offset
        target_col = label_col + col_offset
        if target_row < 1 or target_col < 1:
            continue

        ws.cell(row=row, column=label_col, value=labels[0])
        ws.cell(row=target_row, column=target_col, value=_display_value(value))
        written += 1

        # Leave enough blank space so exact row-offset mappings cannot overlap.
        row += max(2, row_offset + 2)

    return row + 2, written


def _write_parts_table(ws, start_row, parts):
    ws.cell(start_row, 1, "Parts Details")
    header_row = start_row + 1
    headers = ("SN", "Parts Name", "Estimated", "Metal", "Plastic", "Glass")
    for col, header in enumerate(headers, 1):
        ws.cell(header_row, col, header).font = Font(bold=True)

    totals = {"estimate": Decimal(0), "metal": Decimal(0), "plastic": Decimal(0), "glass": Decimal(0)}
    row = header_row + 1
    for serial, part in enumerate(parts or [], 1):
        material = str(part.get("material_type") or "").strip().lower()
        estimate = Decimal(str(part.get("estimated_amount") or 0))
        billed = Decimal(str(part.get("billed_amount") or 0))
        values = {
            "metal": billed if material == "metal" else Decimal(0),
            "plastic": billed if material == "plastic" else Decimal(0),
            "glass": billed if material == "glass" else Decimal(0),
        }
        ws.cell(row, 1, serial)
        ws.cell(row, 2, str(part.get("part_name") or "").strip())
        ws.cell(row, 3, float(estimate))
        ws.cell(row, 4, float(values["metal"]))
        ws.cell(row, 5, float(values["plastic"]))
        ws.cell(row, 6, float(values["glass"]))
        totals["estimate"] += estimate
        for key in ("metal", "plastic", "glass"):
            totals[key] += values[key]
        row += 1

    ws.cell(row, 1, "Sub Total")
    ws.cell(row, 3, float(totals["estimate"]))
    ws.cell(row, 4, float(totals["metal"]))
    ws.cell(row, 5, float(totals["plastic"]))
    ws.cell(row, 6, float(totals["glass"]))
    return row + 3


def _write_labour_table(ws, start_row, labour):
    ws.cell(start_row, 1, "Labour Details")
    header_row = start_row + 1
    headers = ("SN", "Description", "R/R", "Denting", "C/W", "Painting")
    for col, header in enumerate(headers, 1):
        ws.cell(header_row, col, header).font = Font(bold=True)

    keys = (
        ("rr", "R/R", 3),
        ("denting", "DENTING", 4),
        ("cw", "C/W", 5),
        ("painting", "PAINT", 6),
    )
    row = header_row + 1
    serial = 1
    totals = {key: Decimal(str((labour or {}).get(key) or 0)) for key, _, _ in keys}
    for key, label, col in keys:
        amount = totals[key]
        if amount == 0:
            continue
        ws.cell(row, 1, serial)
        ws.cell(row, 2, label)
        ws.cell(row, col, float(amount))
        serial += 1
        row += 1

    ws.cell(row, 1, "Sub Total")
    for key, _, col in keys:
        ws.cell(row, col, float(totals[key]))
    return row + 2


def convert_oic_pdf_to_excel(pdf_path: str, output_folder: str, *, stop_cb=None) -> str:
    """Create a canonical Excel source from an OIC survey PDF.

    This is deliberately NOT a visual PDF-to-Excel conversion.  The PDF is
    first interpreted by the OIC PDF reader, then rewritten into the stable
    Excel schema that App-3 already knows how to scan.
    """
    source = Path(pdf_path)
    if not source.is_file() or source.suffix.lower() != ".pdf":
        raise FileNotFoundError(f"OIC survey PDF not found: {pdf_path}")

    if stop_cb and stop_cb():
        raise InterruptedError("PDF to Excel conversion cancelled")

    claim = read_oic_pdf_report(str(source), stop_cb=stop_cb)
    mapping = load_field_mapping(portal_id="oic")
    parts, labour = getattr(claim, "_oic_pdf_assessment", ([], {}))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Survey Report"

    next_row, field_count = _write_mapped_fields(ws, claim, mapping)
    next_row = _write_parts_table(ws, next_row, parts)
    _write_labour_table(ws, next_row, labour)

    if not field_count:
        wb.close()
        raise ValueError("No readable OIC survey fields could be converted to Excel")

    ws.freeze_panes = "A1"
    for column_letter, width in {"A": 34, "B": 42, "C": 18, "D": 18, "E": 18, "F": 18}.items():
        ws.column_dimensions[column_letter].width = width

    os.makedirs(output_folder, exist_ok=True)
    target = output_path_for(output_folder)
    fd, staged = tempfile.mkstemp(prefix="oic-pdf-source-", suffix=".xlsx", dir=output_folder)
    os.close(fd)
    try:
        wb.save(staged)
        wb.close()
        return publish_generated(staged, target)
    finally:
        try:
            wb.close()
        except Exception:
            pass
        if os.path.exists(staged):
            os.unlink(staged)
