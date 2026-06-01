"""
assessment_generator.py
Auto-generates a standardised primary_assessment.xlsx from the main Excel file.

When the user's folder does NOT contain a pre-made assessment Excel, this module
extracts Spare Parts + Labour data from the main data Excel, formats it into the
portal's required template, and saves it as 'primary_assessment.xlsx'.

The generated file is then seamlessly picked up by claim_assessment_module.py
for upload to the New India Assurance portal.

Extraction logic is delegated to the shared excel_parts_extractor module so that
both Website 2 (generate Excel) and Website 3 (fill portal UI) use identical
header detection and row extraction.
"""

import logging
import os
from typing import List, Optional

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from app.utils import load_automation_defaults

# ── Shared extraction logic (single source of truth) ──────────────────────────
from app.data.excel_parts_extractor import (
    HeaderDetection,
    _clean_numeric,
    coerce_hsn_code,
    _is_summary_row,
    _header_confidence,
    _detect_parts_header,
    _detect_labour_header,
    _extract_parts_rows,
    _extract_labour_rows,
)

logger = logging.getLogger(__name__)

# ── Output filename — includes doc_mapping.json keyword "primary_assessment" ──
_OUTPUT_FILENAME = "auto_primary_assessment.xlsx"
_MIN_HEADER_CONFIDENCE = 80

# Keys added by the shared extractor that are OIC-specific and must be stripped
# before the NIA template writer processes the row dicts.
_OIC_ONLY_KEYS: frozenset = frozenset({"material_type", "labour_column"})


def _next_available_path(output_folder: str, filename: str = _OUTPUT_FILENAME) -> str:
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(output_folder, filename)
    idx = 1
    while os.path.exists(candidate):
        candidate = os.path.join(output_folder, f"{base}_{idx}{ext}")
        idx += 1
    return candidate


def _audit_path_for(output_path: str) -> str:
    root, _ext = os.path.splitext(output_path)
    return f"{root}_audit.txt"


def _write_audit_file(audit_path: str, lines: List[str]) -> None:
    with open(audit_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines).rstrip() + "\n")


# ══════════════════════════════════════════════════════════════════════════════
# TEMPLATE GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def _create_template_workbook(data_rows: List[dict]):
    """
    Create an in-memory workbook with the exact portal template format,
    including dropdown data validations.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Primary_Assessment_Template"
    ws.views.sheetView[0].showGridLines = True

    # ── Headers ──
    headers = [
        "SlNo", "category", "description", "partName", "serviceType",
        "estimatedAmount", "billedAmount", "assessedAmount",
        "depreciationPercentage", "hsnCode", "gstPercentage",
    ]

    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for col_idx, header_text in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header_text)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align

    # ── Data Validation Dropdowns (matching portal template exactly) ──
    formula_category = '"Labor Charges,Spare Parts"'
    formula_description = (
        '"Other Labor Charges,Labor charges for Repairing and Alignment,'
        'Labor charges for Removing and Refitting,Parts at Cost,'
        'Parts at 50% Depreciation,Parts at 30% Depreciation,'
        'Parts at Agewise Depreciation"'
    )
    formula_service_type = '"ALLOW,REPLACE,REPAIR,NOT ALLOWED"'

    # Use a generous range to cover any number of rows
    max_dv_row = max(len(data_rows) + 10, 122)

    dv_category = DataValidation(type="list", formula1=formula_category, allow_blank=True)
    dv_description = DataValidation(type="list", formula1=formula_description, allow_blank=True)
    dv_service_type = DataValidation(type="list", formula1=formula_service_type, allow_blank=True)

    for dv in (dv_category, dv_description, dv_service_type):
        dv.error = "Value must be selected from the validation dropdown list."
        dv.showErrorMessage = True
        ws.add_data_validation(dv)

    dv_category.add(f"B2:B{max_dv_row}")
    dv_description.add(f"C2:C{max_dv_row}")
    dv_service_type.add(f"E2:E{max_dv_row}")

    # ── Column Widths ──
    col_widths = {
        "A": 8, "B": 16, "C": 35, "D": 35, "E": 18,
        "F": 18, "G": 18, "H": 18, "I": 22, "J": 14, "K": 14,
    }
    for col_letter, width in col_widths.items():
        ws.column_dimensions[col_letter].width = width

    # ── Write Data Rows ──
    for idx, row_data in enumerate(data_rows, start=1):
        r = idx + 1  # row 1 is header
        ws.cell(row=r, column=1, value=idx)                            # SlNo
        ws.cell(row=r, column=2, value=row_data["category"])           # category
        ws.cell(row=r, column=3, value=row_data["description"])        # description
        ws.cell(row=r, column=4, value=row_data["part_name"])          # partName
        ws.cell(row=r, column=5, value=row_data["service_type"])       # serviceType
        ws.cell(row=r, column=6, value=row_data["estimated_amount"])   # estimatedAmount
        ws.cell(row=r, column=7, value=row_data["billed_amount"])      # billedAmount
        ws.cell(row=r, column=8, value=row_data["assessed_amount"])    # assessedAmount
        ws.cell(row=r, column=9, value=row_data["depreciation_pct"])   # depreciationPercentage
        ws.cell(row=r, column=10, value=row_data["hsn_code"])          # hsnCode
        ws.cell(row=r, column=11, value=row_data["gst_pct"])           # gstPercentage

    return wb


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def generate_primary_assessment(source_excel_path: str, output_folder: str) -> Optional[str]:
    """
    Generate a standardised primary_assessment.xlsx from the main data Excel.

    Args:
        source_excel_path: Path to the main Excel file (the data source).
        output_folder:     Directory where the generated file will be saved.

    Returns:
        Full path to the generated primary_assessment.xlsx, or None if extraction
        yielded no data rows (both parts and labour tables empty).

    Raises:
        FileNotFoundError: If source_excel_path does not exist.
    """
    if not os.path.exists(source_excel_path):
        raise FileNotFoundError(f"Source Excel not found: {source_excel_path}")

    defaults = load_automation_defaults(portal_id="newindia")
    parts_hsn = coerce_hsn_code(defaults.get("assessment_parts_hsn_code"), "8512")
    labour_hsn = coerce_hsn_code(defaults.get("assessment_labour_hsn_code"), "8729")
    boundary_kw = defaults.get("table_boundary_keyword", "sub total").strip() or "sub total"

    logger.info("Assessment generator: loading source Excel %s", source_excel_path)
    src_wb = openpyxl.load_workbook(source_excel_path, data_only=True)
    src_ws = src_wb.active

    all_rows: List[dict] = []
    audit_lines: List[str] = [
        "Primary Assessment Generation Audit",
        f"Source Excel: {source_excel_path}",
        f"Source Sheet: {src_ws.title}",
        f"Parts HSN: {parts_hsn}",
        f"Labour HSN: {labour_hsn}",
        "",
        "Header Detection",
    ]

    # ── Phase 1: Spare Parts ──
    parts_detection = _detect_parts_header(src_ws)
    parts_rows: List[dict] = []
    if parts_detection.row:
        parts_header, parts_col_map = parts_detection.row, parts_detection.col_map
        logger.info(
            "Assessment generator: parts header found at row %d, confidence=%d, columns: %s",
            parts_header, parts_detection.confidence, list(parts_col_map.keys()),
        )
        audit_lines.extend([
            f"Parts header row: {parts_header}",
            f"Parts confidence: {parts_detection.confidence}%",
            f"Parts matched: {', '.join(parts_detection.matched_keys) or '-'}",
            f"Parts missing: {', '.join(parts_detection.missing_keys) or '-'}",
        ])
        if parts_detection.confidence < _MIN_HEADER_CONFIDENCE:
            warning = (
                f"Parts header confidence below minimum {_MIN_HEADER_CONFIDENCE}%; "
                "skipping parts extraction."
            )
            logger.warning("Assessment generator: %s", warning)
            audit_lines.append(f"Parts warning: {warning}")
        else:
            parts_rows = _extract_parts_rows(
                src_ws, parts_header, parts_col_map, hsn_code=parts_hsn,
                audit_lines=audit_lines, boundary_keyword=boundary_kw,
            )
            logger.info("Assessment generator: extracted %d spare part rows", len(parts_rows))
            all_rows.extend(parts_rows)
    else:
        logger.warning("Assessment generator: no spare parts header found in Excel")
        audit_lines.append("Parts header row: not found")

    # ── Phase 2: Labour Charges ──
    labour_detection = _detect_labour_header(src_ws)
    labour_rows: List[dict] = []
    if labour_detection.row:
        labour_header, labour_col_map = labour_detection.row, labour_detection.col_map
        logger.info(
            "Assessment generator: labour header found at row %d, confidence=%d, columns: %s",
            labour_header, labour_detection.confidence, list(labour_col_map.keys()),
        )
        audit_lines.extend([
            f"Labour header row: {labour_header}",
            f"Labour confidence: {labour_detection.confidence}%",
            f"Labour matched: {', '.join(labour_detection.matched_keys) or '-'}",
            f"Labour missing: {', '.join(labour_detection.missing_keys) or '-'}",
        ])
        if labour_detection.confidence < _MIN_HEADER_CONFIDENCE:
            warning = (
                f"Labour header confidence below minimum {_MIN_HEADER_CONFIDENCE}%; "
                "skipping labour extraction."
            )
            logger.warning("Assessment generator: %s", warning)
            audit_lines.append(f"Labour warning: {warning}")
        else:
            labour_rows = _extract_labour_rows(
                src_ws, labour_header, labour_col_map, hsn_code=labour_hsn,
                audit_lines=audit_lines, boundary_keyword=boundary_kw,
            )
            logger.info("Assessment generator: extracted %d labour rows", len(labour_rows))
            all_rows.extend(labour_rows)
    else:
        logger.warning("Assessment generator: no labour header found in Excel")
        audit_lines.append("Labour header row: not found")

    src_wb.close()

    # ── Guard: no data extracted ──
    if not all_rows:
        logger.warning("Assessment generator: no parts or labour data found — skipping generation")
        # Use a deterministic filename so we don't consume a numbered slot that the
        # actual generator would later claim, avoiding phantom path conflicts.
        audit_path = os.path.join(output_folder, "primary_assessment_skipped_audit.txt")
        audit_lines.extend(["", "Result", "No parts or labour data found. Excel generation skipped."])
        _write_audit_file(audit_path, audit_lines)
        return None

    # ── Sanitise: strip OIC-specific keys that the shared extractor adds ──
    # The template writer only reads the canonical NIA schema keys.
    for row in all_rows:
        for k in _OIC_ONLY_KEYS:
            row.pop(k, None)

    # ── Phase 3: Generate Template ──
    wb = _create_template_workbook(all_rows)

    output_path = _next_available_path(output_folder)
    audit_path = _audit_path_for(output_path)
    _max_save_attempts = 3
    try:
        for _attempt in range(1, _max_save_attempts + 1):
            try:
                wb.save(output_path)
                break
            except PermissionError:
                if _attempt == _max_save_attempts:
                    logger.error(
                        "Assessment generator: all %d save attempts failed (last path: %s)",
                        _max_save_attempts, output_path,
                    )
                    audit_lines.extend([
                        "", "Result",
                        f"FAILED: Could not save after {_max_save_attempts} attempts.",
                        f"Last attempted path: {output_path}",
                    ])
                    _write_audit_file(audit_path, audit_lines)
                    raise
                logger.warning(
                    "Assessment generator: path locked on attempt %d, retrying: %s",
                    _attempt, output_path,
                )
                output_path = _next_available_path(output_folder)
                audit_path = _audit_path_for(output_path)
        # No else needed: loop exits via break (success) or raise (PermissionError).
    finally:
        wb.close()

    parts_total = sum(float(row["assessed_amount"] or 0) for row in parts_rows)
    labour_total = sum(float(row["assessed_amount"] or 0) for row in labour_rows)
    audit_lines.extend([
        "",
        "Result",
        f"Output Excel: {output_path}",
        f"Audit File: {audit_path}",
        f"Parts rows: {len(parts_rows)}",
        f"Labour rows: {len(labour_rows)}",
        f"Total rows: {len(all_rows)}",
        f"Parts assessed total: {parts_total}",
        f"Labour assessed total: {labour_total}",
        f"Grand assessed total: {parts_total + labour_total}",
    ])
    _write_audit_file(audit_path, audit_lines)

    logger.info(
        "Assessment generator: SUCCESS — %d rows (%d parts + %d labour) → %s",
        len(all_rows),
        len(parts_rows),
        len(labour_rows),
        output_path,
    )
    return output_path
