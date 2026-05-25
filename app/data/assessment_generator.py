"""
assessment_generator.py
Auto-generates a standardised primary_assessment.xlsx from the main Excel file.

When the user's folder does NOT contain a pre-made assessment Excel, this module
extracts Spare Parts + Labour data from the main data Excel, formats it into the
portal's required template, and saves it as 'primary_assessment.xlsx'.

The generated file is then seamlessly picked up by claim_assessment_module.py
for upload to the New India Assurance portal.

Based on the proven extraction logic from excel_mapper.py (reference implementation).
"""

import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from app.utils import load_automation_defaults

logger = logging.getLogger(__name__)

# ── Output filename — includes doc_mapping.json keyword "primary_assessment" ──
_OUTPUT_FILENAME = "auto_primary_assessment.xlsx"
_MIN_HEADER_CONFIDENCE = 80


@dataclass
class HeaderDetection:
    row: Optional[int]
    col_map: Dict[str, int]
    score: int
    confidence: int
    matched_keys: List[str]
    missing_keys: List[str]


def _coerce_hsn_code(value, fallback: str):
    raw = str(value or fallback).strip() or fallback
    return int(raw) if raw.isdigit() else raw


def _header_confidence(matched_keys: List[str], required_keys: List[str], expected_keys: List[str]) -> int:
    matched = set(matched_keys)
    required = set(required_keys)
    expected = set(expected_keys)
    required_score = 70 * len(matched & required) / max(len(required), 1)
    optional = expected - required
    optional_score = 30 * len(matched & optional) / max(len(optional), 1)
    return int(round(required_score + optional_score))


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
# UTILITY FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def _clean_numeric(val) -> Optional[float]:
    """
    Strip commas, whitespace, and placeholder text from a cell value.
    Returns a clean float, or None if the value is empty/invalid.
    """
    if val is None:
        return None
    cleaned = str(val).strip().replace(",", "")
    if not cleaned or cleaned.lower() in ("na", "n.a.", "-", "nil", "none", "n/a", ""):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _is_summary_row(text: str) -> bool:
    """Return True if the text looks like a summary/total row that should be skipped."""
    lower = text.lower()
    skip_keywords = [
        "total", "subtotal", "sub total", "summary", "less:", "add:",
        "salvage", "depreciation", "net", "imposed", "gst", "cgst",
        "sgst", "tax",
    ]
    return any(kw in lower for kw in skip_keywords) or "%" in lower


# ══════════════════════════════════════════════════════════════════════════════
# DYNAMIC HEADER DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def _detect_parts_header(sheet) -> HeaderDetection:
    """
    Locate the Spare Parts table header row using keyword scoring.
    Strict range: only columns between Serial Number (sn) and Glass are accepted.
    Returns (header_row_index, column_map) or (None, {}).
    """
    keyword_schema = {
        "sn":        ["s.n", "sr", "sl", "s.no", "sr.no", "sn", "serial"],
        "part_desc": ["description", "discription", "part name", "particular",
                      "part desc", "item description", "nomenclature", "item"],
        "estimated": ["estimated", "estimate", "est amount", "est amt", "est."],
        "metal":     ["metal"],
        "plastic":   ["plastic"],
        "glass":     ["glass"],
    }

    expected_keys = ["sn", "part_desc", "estimated", "metal", "plastic", "glass"]
    required_keys = ["sn", "part_desc", "glass"]
    best = HeaderDetection(None, {}, 0, 0, [], expected_keys.copy())

    for r in range(1, sheet.max_row + 1):
        temp_map = {}
        score = 0
        for c in range(1, sheet.max_column + 1):
            cell_val = sheet.cell(row=r, column=c).value
            if cell_val is None:
                continue
            norm = str(cell_val).strip().lower()

            for key, keywords in keyword_schema.items():
                if any(kw in norm for kw in keywords):
                    if key not in temp_map:
                        temp_map[key] = c
                        score += 5 if key in ("part_desc", "estimated") else 2

        # Strict boundary guard: 'sn' and 'glass' must be found
        if "sn" in temp_map and "glass" in temp_map:
            idx_start = temp_map["sn"]
            idx_end = temp_map["glass"]
            bounded = {k: v for k, v in temp_map.items() if idx_start <= v <= idx_end}

            if "part_desc" in bounded:
                matched = [key for key in expected_keys if key in bounded]
                confidence = _header_confidence(matched, required_keys, expected_keys)
                if (score, confidence) > (best.score, best.confidence):
                    best = HeaderDetection(
                        row=r,
                        col_map=bounded,
                        score=score,
                        confidence=confidence,
                        matched_keys=matched,
                        missing_keys=[key for key in expected_keys if key not in bounded],
                    )

    return best


def _find_parts_header(sheet) -> Tuple[Optional[int], Dict[str, int]]:
    detection = _detect_parts_header(sheet)
    return detection.row, detection.col_map


def _detect_labour_header(sheet) -> HeaderDetection:
    """
    Locate the Labour Charges table header row using keyword scoring.
    Strict range: only columns between Serial Number (sn) and CW are accepted.
    Columns outside this range (e.g. Painting after CW) are auto-excluded.
    Returns (header_row_index, column_map) or (None, {}).
    """
    keyword_schema = {
        "sn":          ["s.n", "sr", "sl", "s.no", "sr.no", "sn", "serial"],
        "labour_desc": ["description", "particular", "labour description", "item"],
        "rr":          ["r/r", "r.r.", "remove", "refit"],
        "denting":     ["denting", "dent"],
        "cw":          ["c/w", "c.w.", "chassis"],
        "painting":    ["painting", "paint"],
        "alignment":   ["alignment", "align"],
        "estimated":   ["estimated", "estimate"],
    }

    expected_keys = ["sn", "labour_desc", "rr", "denting", "cw", "painting", "alignment", "estimated"]
    required_keys = ["sn", "labour_desc", "cw"]
    best = HeaderDetection(None, {}, 0, 0, [], expected_keys.copy())

    for r in range(1, sheet.max_row + 1):
        temp_map = {}
        score = 0
        for c in range(1, sheet.max_column + 1):
            cell_val = sheet.cell(row=r, column=c).value
            if cell_val is None:
                continue
            norm = str(cell_val).strip().lower()

            for key, keywords in keyword_schema.items():
                if any(kw in norm for kw in keywords):
                    if key not in temp_map:
                        temp_map[key] = c
                        score += 4 if key in ("rr", "denting", "cw") else 2

        # Strict boundary guard: 'sn' and 'cw' must be found
        if "sn" in temp_map and "cw" in temp_map:
            idx_start = temp_map["sn"]
            idx_end = temp_map["cw"]
            bounded = {k: v for k, v in temp_map.items() if idx_start <= v <= idx_end}

            if "labour_desc" in bounded:
                matched = [key for key in expected_keys if key in bounded]
                confidence = _header_confidence(matched, required_keys, expected_keys)
                if (score, confidence) > (best.score, best.confidence):
                    best = HeaderDetection(
                        row=r,
                        col_map=bounded,
                        score=score,
                        confidence=confidence,
                        matched_keys=matched,
                        missing_keys=[key for key in expected_keys if key not in bounded],
                    )

    return best


def _find_labour_header(sheet) -> Tuple[Optional[int], Dict[str, int]]:
    detection = _detect_labour_header(sheet)
    return detection.row, detection.col_map


# ══════════════════════════════════════════════════════════════════════════════
# ROW EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def _extract_parts_rows(
    sheet,
    header_row: int,
    col_map: Dict[str, int],
    hsn_code=8512,
    audit_lines: Optional[List[str]] = None,
) -> List[dict]:
    """Extract spare part rows from the sheet using the detected header and column map."""
    rows = []
    desc_col = col_map.get("part_desc")
    est_col = col_map.get("estimated")
    metal_col = col_map.get("metal")
    plastic_col = col_map.get("plastic")
    glass_col = col_map.get("glass")

    for r in range(header_row + 1, sheet.max_row + 1):
        # Check for subtotal boundary
        row_texts = [
            str(sheet.cell(row=r, column=c).value).strip().lower()
            for c in range(1, sheet.max_column + 1)
            if sheet.cell(row=r, column=c).value is not None
        ]
        if any("sub total" in t or "subtotal" in t or t == "total" for t in row_texts):
            logger.debug("Parts extraction: subtotal boundary at row %d", r)
            if audit_lines is not None:
                audit_lines.append(f"Parts row {r}: stopped at subtotal/total boundary")
            break

        # Read part description
        part_raw = sheet.cell(row=r, column=desc_col).value if desc_col else None
        if part_raw is None or str(part_raw).strip() == "":
            if audit_lines is not None:
                audit_lines.append(f"Parts row {r}: skipped blank part name")
            continue

        part_name = str(part_raw).strip()

        # Skip summary/aggregation rows
        if _is_summary_row(part_name):
            if audit_lines is not None:
                audit_lines.append(f"Parts row {r}: skipped summary row '{part_name}'")
            continue

        # Skip labour rows that accidentally appear in parts section
        if "labour" in part_name.lower() or "labor" in part_name.lower():
            if audit_lines is not None:
                audit_lines.append(f"Parts row {r}: skipped likely labour row '{part_name}'")
            continue

        # Read values (all protected by the SN→Glass boundary)
        est_val = _clean_numeric(sheet.cell(row=r, column=est_col).value) if est_col else 0.0
        metal_val = _clean_numeric(sheet.cell(row=r, column=metal_col).value) if metal_col else None
        plastic_val = _clean_numeric(sheet.cell(row=r, column=plastic_col).value) if plastic_col else None
        glass_val = _clean_numeric(sheet.cell(row=r, column=glass_col).value) if glass_col else None

        # Determine material type and billed amount
        billed_amt = 0.0
        dep_type = "Parts at Cost"

        if metal_val is not None:
            dep_type = "Parts at Agewise Depreciation"
            billed_amt = metal_val
        elif plastic_val is not None:
            dep_type = "Parts at 50% Depreciation"
            billed_amt = plastic_val
        elif glass_val is not None:
            dep_type = "Parts at Cost"
            billed_amt = glass_val
        else:
            # No valid material amount found — skip this row
            if audit_lines is not None:
                audit_lines.append(f"Parts row {r}: skipped no metal/plastic/glass amount for '{part_name}'")
            continue

        rows.append({
            "category": "Spare Parts",
            "description": dep_type,
            "part_name": part_name,
            "service_type": "REPLACE",
            "estimated_amount": est_val if est_val is not None else 0.0,
            "billed_amount": billed_amt,
            "assessed_amount": billed_amt,
            "depreciation_pct": 0,
            "hsn_code": hsn_code,
            "gst_pct": 0,
        })
        if audit_lines is not None:
            audit_lines.append(
                f"Parts row {r}: added '{part_name}' billed={billed_amt} assessed={billed_amt} hsn={hsn_code}"
            )
        logger.debug("Parts row %d: %s | amt=%.2f | type=%s", r, part_name, billed_amt, dep_type)

    return rows


def _extract_labour_rows(
    sheet,
    header_row: int,
    col_map: Dict[str, int],
    hsn_code=8729,
    audit_lines: Optional[List[str]] = None,
) -> List[dict]:
    """Extract labour charge rows from the sheet using the detected header and column map."""
    rows = []
    desc_col = col_map.get("labour_desc")

    # Collect all labour-amount columns within the boundary
    labour_amount_keys = ["rr", "denting", "cw", "painting", "alignment"]

    for r in range(header_row + 1, sheet.max_row + 1):
        # Check for subtotal boundary
        row_texts = [
            str(sheet.cell(row=r, column=c).value).strip().lower()
            for c in range(1, sheet.max_column + 1)
            if sheet.cell(row=r, column=c).value is not None
        ]
        if any("sub total" in t or "subtotal" in t or "total" in t for t in row_texts):
            logger.debug("Labour extraction: subtotal boundary at row %d", r)
            if audit_lines is not None:
                audit_lines.append(f"Labour row {r}: stopped at subtotal/total boundary")
            break

        # Read labour description
        name_raw = sheet.cell(row=r, column=desc_col).value if desc_col else None
        if name_raw is None or str(name_raw).strip() == "":
            if audit_lines is not None:
                audit_lines.append(f"Labour row {r}: skipped blank labour name")
            continue

        labour_name = str(name_raw).strip()

        # Sum all valid labour-amount columns (within the bounded range)
        amounts = []
        for key in labour_amount_keys:
            col = col_map.get(key)
            if col is not None:
                val = _clean_numeric(sheet.cell(row=r, column=col).value)
                if val is not None:
                    amounts.append(val)

        if not amounts:
            if audit_lines is not None:
                audit_lines.append(f"Labour row {r}: skipped no valid labour amount for '{labour_name}'")
            continue

        total_billed = sum(amounts)

        rows.append({
            "category": "Labor Charges",
            "description": "Labor charges for Repairing and Alignment",
            "part_name": labour_name,
            "service_type": "ALLOW",
            "estimated_amount": 0,
            "billed_amount": total_billed,
            "assessed_amount": total_billed,
            "depreciation_pct": 0,
            "hsn_code": hsn_code,
            "gst_pct": 0,
        })
        if audit_lines is not None:
            audit_lines.append(
                f"Labour row {r}: added '{labour_name}' billed={total_billed} assessed={total_billed} hsn={hsn_code}"
            )
        logger.debug("Labour row %d: %s | amt=%.2f", r, labour_name, total_billed)

    return rows


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
    parts_hsn = _coerce_hsn_code(defaults.get("assessment_parts_hsn_code"), "8512")
    labour_hsn = _coerce_hsn_code(defaults.get("assessment_labour_hsn_code"), "8729")

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
                src_ws, parts_header, parts_col_map, hsn_code=parts_hsn, audit_lines=audit_lines
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
                src_ws, labour_header, labour_col_map, hsn_code=labour_hsn, audit_lines=audit_lines
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
        audit_path = _audit_path_for(_next_available_path(output_folder))
        audit_lines.extend(["", "Result", "No parts or labour data found. Excel generation skipped."])
        _write_audit_file(audit_path, audit_lines)
        return None

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
        else:
            return None
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
