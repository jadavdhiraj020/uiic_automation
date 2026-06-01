"""
excel_parts_extractor.py — Shared extraction of Spare Parts & Labour rows from Excel.

Refactored from assessment_generator.py so the same proven header detection
and row extraction logic can be reused by:
  - Website 2 (New India)  → generate_primary_assessment (Excel output)
  - Website 3 (OIC)        → fill portal invoice items directly

PAINTING COLUMN: Intentionally excluded from labour amount columns.
Only RR, Denting, and C/W are valid labour columns.
"""

import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import openpyxl

logger = logging.getLogger(__name__)

_MIN_HEADER_CONFIDENCE = 80


# ══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class HeaderDetection:
    """Result of a header detection scan on a worksheet."""
    row: Optional[int]
    col_map: Dict[str, int]
    score: int
    confidence: int
    matched_keys: List[str]
    missing_keys: List[str]


# ══════════════════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def _clean_numeric(val) -> Optional[float]:
    """
    Strip commas, currency symbols, whitespace, and placeholder text from a cell value.
    Returns a clean float, or None if the value is empty/invalid.

    Handles:
      - Commas in thousands (e.g. "1,500")
      - Indian Rupee symbol variants: '₹ 1,500', 'Rs. 850', 'Rs 200'
    """
    if val is None:
        return None
    cleaned = str(val).strip()
    # Strip currency symbols before any other processing
    cleaned = cleaned.replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    cleaned = cleaned.replace(",", "")
    if not cleaned or cleaned.lower() in ("na", "n.a.", "-", "nil", "none", "n/a", ""):
        return None
    try:
        return float(cleaned)
    except ValueError:
        logger.warning("_clean_numeric: could not parse %r as a number — skipping", val)
        return None


# Pre-compiled word-boundary pattern used by _is_summary_row.
# ALL keywords use \b so partial matches inside legitimate part names are
# never flagged (e.g. 'Total Quartz Oil' → contains 'total' as substring but
# "Total" IS a standalone word here — that row IS a summary row).
# False-positives like 'bonnet' (contains 'net'), 'Xtax' (contains 'tax'),
# 'subtlety' (starts with 'sub') etc. are avoided because \b requires a
# word boundary on BOTH sides of the match.
_SUMMARY_ROW_RE = __import__('re').compile(
    r'\b(?:total|subtotal|sub\s+total|summary|less|add|salvage'
    r'|depreciation|imposed|gst|cgst|sgst|tax|net)\b'
)


def _is_summary_row(text: str) -> bool:
    """Return True if *text* looks like a summary / total row that should be skipped.

    Uses a single pre-compiled word-boundary regex so that ALL keywords are
    matched only as complete words.  This prevents false-positive skips of
    legitimate part names such as:
      - 'Total Quartz Oil'  (contains 'total' but IS a summary row — correct)
      - 'bonnet'            (contains 'net'   — NOT a summary row — correct)
      - 'Xtax bearing'      (contains 'tax'   — NOT a summary row — correct)
      - 'Fuel additive'     (contains 'add'   — NOT a summary row — correct)
    """
    lower = text.lower()
    if "%" in lower:
        return True
    return bool(_SUMMARY_ROW_RE.search(lower))


def _header_confidence(matched_keys: List[str], required_keys: List[str], expected_keys: List[str]) -> int:
    """Calculate confidence score for a detected header row."""
    matched = set(matched_keys)
    required = set(required_keys)
    expected = set(expected_keys)
    required_score = 70 * len(matched & required) / max(len(required), 1)
    optional = expected - required
    optional_score = 30 * len(matched & optional) / max(len(optional), 1)
    return int(round(required_score + optional_score))


def coerce_hsn_code(value, fallback: str):
    """Coerce an HSN code value to int if possible, else return as string."""
    raw = str(value or fallback).strip() or fallback
    return int(raw) if raw.isdigit() else raw


# The set of values that are clearly boolean/disabled config mistakes.
# When the user accidentally sets the boundary keyword to one of these,
# we substitute robust keyword defaults instead of scanning to sheet end.
_INVALID_BOUNDARY_VALUES = frozenset({"no", "none", "false", "true", "yes", "0", ""})
_DEFAULT_BOUNDARY_KEYWORD = "sub total|total|grand total"


def _normalize_boundary_keyword(keyword: str) -> str:
    """Guard against misconfigured table_boundary_keyword values.

    If the value is empty, a boolean-like word, or any other clearly invalid
    keyword (e.g. the user typed 'No' thinking it would disable the feature),
    fall back to a robust multi-keyword default so the scanner stops at the
    correct table boundary.

    Args:
        keyword: Raw value from ``defaults["table_boundary_keyword"]``.

    Returns:
        A clean, valid keyword string safe to pass to the extractor.
    """
    cleaned = str(keyword or "").strip()
    if cleaned.lower() in _INVALID_BOUNDARY_VALUES:
        logger.warning(
            "table_boundary_keyword '%s' looks like a boolean/disabled value "
            "— substituting default '%s' to prevent full-sheet scanning.",
            cleaned, _DEFAULT_BOUNDARY_KEYWORD,
        )
        return _DEFAULT_BOUNDARY_KEYWORD
    return cleaned


# ══════════════════════════════════════════════════════════════════════════════
# DYNAMIC HEADER DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def _detect_parts_header(sheet) -> HeaderDetection:
    """
    Locate the Spare Parts table header row using keyword scoring.
    Strict range: only columns between Serial Number (sn) and Glass are accepted.
    Returns HeaderDetection with (header_row_index, column_map) or (None, {}).
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


def _detect_labour_header(sheet) -> HeaderDetection:
    """
    Locate the Labour Charges table header row using keyword scoring.
    Strict range: only columns between Serial Number (sn) and CW are accepted.
    Columns outside this range (e.g. Painting after CW) are auto-excluded.
    Returns HeaderDetection with (header_row_index, column_map) or (None, {}).
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

    # NOTE: painting and alignment are detected in keyword_schema but excluded
    # by the strict sn→cw boundary guard.  They are intentionally omitted from
    # expected_keys so they do not penalise the confidence score.
    expected_keys = ["sn", "labour_desc", "rr", "denting", "cw", "estimated"]
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


# ══════════════════════════════════════════════════════════════════════════════
# ROW EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def _extract_parts_rows(
    sheet,
    header_row: int,
    col_map: Dict[str, int],
    hsn_code=8512,
    audit_lines: Optional[List[str]] = None,
    boundary_keyword: str = "sub total",
    stop_row: Optional[int] = None,
) -> List[dict]:
    """Extract spare part rows from the sheet using the detected header and column map."""
    rows = []
    desc_col = col_map.get("part_desc")
    est_col = col_map.get("estimated")
    metal_col = col_map.get("metal")
    plastic_col = col_map.get("plastic")
    glass_col = col_map.get("glass")

    # Pre-compute boundary variants for exact-match comparison.
    # Supports multiple pipe-separated keywords (e.g. "sub total|grand total").
    # For each token, both the literal form and the collapsed form (spaces
    # removed) are added so "sub total" also matches "subtotal" in the sheet.
    _boundary_variants: set = set()
    for _token in boundary_keyword.split("|"):
        _t = _token.strip().lower()
        if _t:
            _boundary_variants.add(_t)
            _boundary_variants.add(_t.replace(" ", ""))

    # Determine the last row to scan. If the caller provides a stop_row (e.g.
    # the first row of the Labour header), we stop before it so spare parts
    # can never bleed into the labour section regardless of boundary keywords.
    scan_end = sheet.max_row
    if stop_row is not None and stop_row > header_row:
        scan_end = stop_row - 1
        if audit_lines is not None:
            audit_lines.append(
                f"Parts extraction: bounded by stop_row={stop_row} "
                f"(Labour header) — scanning rows {header_row + 1}..{scan_end}"
            )

    for r in range(header_row + 1, scan_end + 1):
        # Check for subtotal boundary — exact cell text match only
        row_texts = [
            str(sheet.cell(row=r, column=c).value).strip().lower()
            for c in range(1, sheet.max_column + 1)
            if sheet.cell(row=r, column=c).value is not None
        ]
        if any(t in _boundary_variants for t in row_texts):
            logger.debug("Parts extraction: boundary '%s' at row %d", boundary_keyword, r)
            if audit_lines is not None:
                audit_lines.append(f"Parts row {r}: stopped at boundary '{boundary_keyword}'")
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

        # Count how many material columns have values
        material_values = []
        if metal_val is not None:
            material_values.append("metal")
        if plastic_val is not None:
            material_values.append("plastic")
        if glass_val is not None:
            material_values.append("glass")

        if len(material_values) > 1:
            # Multiple materials in one row — skip with log
            if audit_lines is not None:
                audit_lines.append(
                    f"Parts row {r}: skipped — multiple material columns "
                    f"({', '.join(material_values)}) for '{part_name}'"
                )
            logger.warning(
                "Parts row %d: skipped — multiple material columns (%s) for '%s'",
                r, ", ".join(material_values), part_name,
            )
            continue

        # Determine material type and billed amount
        billed_amt = 0.0
        dep_type = "Parts at Cost"
        material_type = None  # "metal", "plastic", or "glass"

        if metal_val is not None:
            dep_type = "Parts at Agewise Depreciation"
            billed_amt = metal_val
            material_type = "metal"
        elif plastic_val is not None:
            dep_type = "Parts at 50% Depreciation"
            billed_amt = plastic_val
            material_type = "plastic"
        elif glass_val is not None:
            dep_type = "Parts at Cost"
            billed_amt = glass_val
            material_type = "glass"
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
            "material_type": material_type,
        })
        if audit_lines is not None:
            audit_lines.append(
                f"Parts row {r}: added '{part_name}' material={material_type} "
                f"billed={billed_amt} assessed={billed_amt} hsn={hsn_code}"
            )
        logger.debug("Parts row %d: %s | amt=%.2f | type=%s | material=%s", r, part_name, billed_amt, dep_type, material_type)

    return rows


def _extract_labour_rows(
    sheet,
    header_row: int,
    col_map: Dict[str, int],
    hsn_code=8729,
    audit_lines: Optional[List[str]] = None,
    boundary_keyword: str = "sub total",
) -> List[dict]:
    """Extract labour charge rows from the sheet using the detected header and column map.

    IMPORTANT: Only RR, Denting, and C/W are valid labour amount columns.
    Painting, Alignment, and other columns are intentionally excluded.
    """
    rows = []
    desc_col = col_map.get("labour_desc")

    # Only these 3 columns are valid labour amount sources
    labour_amount_keys = ["rr", "denting", "cw"]

    # Pre-compute boundary variants for exact-match comparison.
    # Supports multiple pipe-separated keywords (e.g. "sub total|grand total").
    # For each token, both the literal form and the collapsed form (spaces
    # removed) are added so "sub total" also matches "subtotal" in the sheet.
    _boundary_variants: set = set()
    for _token in boundary_keyword.split("|"):
        _t = _token.strip().lower()
        if _t:
            _boundary_variants.add(_t)
            _boundary_variants.add(_t.replace(" ", ""))

    for r in range(header_row + 1, sheet.max_row + 1):
        # Check for subtotal boundary — exact cell text match only
        row_texts = [
            str(sheet.cell(row=r, column=c).value).strip().lower()
            for c in range(1, sheet.max_column + 1)
            if sheet.cell(row=r, column=c).value is not None
        ]
        if any(t in _boundary_variants for t in row_texts):
            logger.debug("Labour extraction: boundary '%s' at row %d", boundary_keyword, r)
            if audit_lines is not None:
                audit_lines.append(f"Labour row {r}: stopped at boundary '{boundary_keyword}'")
            break

        # Read labour description
        name_raw = sheet.cell(row=r, column=desc_col).value if desc_col else None
        if name_raw is None or str(name_raw).strip() == "":
            if audit_lines is not None:
                audit_lines.append(f"Labour row {r}: skipped blank labour name")
            continue

        labour_name = str(name_raw).strip()

        # Skip summary rows
        if _is_summary_row(labour_name):
            if audit_lines is not None:
                audit_lines.append(f"Labour row {r}: skipped summary row '{labour_name}'")
            continue

        # Collect all valid labour amount columns
        found_columns = []
        for key in labour_amount_keys:
            col = col_map.get(key)
            if col is not None:
                val = _clean_numeric(sheet.cell(row=r, column=col).value)
                if val is not None:
                    found_columns.append((key, val))

        if not found_columns:
            if audit_lines is not None:
                audit_lines.append(f"Labour row {r}: skipped no valid labour amount for '{labour_name}'")
            continue

        found_key = found_columns[0][0]
        total_billed = sum(val for _, val in found_columns)
        if len(found_columns) > 1:
            col_names = ", ".join(k for k, _ in found_columns)
            if audit_lines is not None:
                audit_lines.append(
                    f"Labour row {r}: combined multiple labour columns "
                    f"({col_names}) for '{labour_name}' - summed to {total_billed}"
                )
            logger.info(
                "Labour row %d: combined multiple labour columns (%s) for '%s' - summed to %.2f",
                r, col_names, labour_name, total_billed
            )


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
            "labour_column": found_key,
        })
        if audit_lines is not None:
            audit_lines.append(
                f"Labour row {r}: added '{labour_name}' column={found_key} "
                f"billed={total_billed} assessed={total_billed} hsn={hsn_code}"
            )
        logger.debug("Labour row %d: %s | amt=%.2f | col=%s", r, labour_name, total_billed, found_key)

    return rows


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC CONVENIENCE API
# ══════════════════════════════════════════════════════════════════════════════

def extract_parts_and_labour(
    excel_path: str,
    parts_hsn=8512,
    labour_hsn=8729,
    boundary_keyword: str = "sub total",
) -> Tuple[List[dict], List[dict], List[str]]:
    """
    End-to-end extraction of spare parts and labour rows from an Excel file.

    Args:
        excel_path:       Path to the main Excel file.
        parts_hsn:        HSN code for spare parts items.
        labour_hsn:       HSN code for labour items.
        boundary_keyword: Cell text that marks the end of a table.
                          Supports multiple keywords separated by ``|``
                          (e.g. ``"sub total|grand total|total amount"``).
                          For every token, the literal form and the collapsed
                          form (spaces removed) are both matched, so
                          ``"sub total"`` also matches ``"subtotal"``.
                          Values like ``"No"``, ``"None"``, ``"False"``, or
                          blank are treated as misconfiguration and replaced
                          with a robust default automatically.
                          Default: ``"sub total"``.

    Returns:
        (parts_rows, labour_rows, audit_lines)
        - parts_rows:  List of extracted spare part dicts
        - labour_rows: List of extracted labour charge dicts
        - audit_lines: Human-readable audit log for debugging

    Raises:
        FileNotFoundError: If excel_path does not exist.
    """
    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Source Excel not found: {excel_path}")

    # Normalize the boundary keyword — guard against misconfigured values like
    # 'No', 'None', 'False', or blank that would cause a full-sheet scan.
    boundary_keyword = _normalize_boundary_keyword(boundary_keyword)

    audit_lines: List[str] = [
        "Parts & Labour Extraction Audit",
        f"Source Excel: {excel_path}",
        f"Boundary keyword: {boundary_keyword}",
    ]

    logger.info("Parts extractor: loading source Excel %s", excel_path)
    src_wb = openpyxl.load_workbook(excel_path, data_only=True)
    src_ws = src_wb.active

    audit_lines.append(f"Source Sheet: {src_ws.title}")
    audit_lines.append("")

    parts_rows: List[dict] = []
    labour_rows: List[dict] = []

    # ── Phase 1: Spare Parts ──
    parts_detection = _detect_parts_header(src_ws)
    if parts_detection.row:
        parts_header = parts_detection.row
        parts_col_map = parts_detection.col_map
        logger.info(
            "Parts extractor: parts header found at row %d, confidence=%d, columns: %s",
            parts_header, parts_detection.confidence, list(parts_col_map.keys()),
        )
        audit_lines.extend([
            "── Spare Parts ──",
            f"Header row: {parts_header}",
            f"Confidence: {parts_detection.confidence}%",
            f"Matched: {', '.join(parts_detection.matched_keys) or '-'}",
            f"Missing: {', '.join(parts_detection.missing_keys) or '-'}",
        ])

        if parts_detection.confidence < _MIN_HEADER_CONFIDENCE:
            warning = (
                f"Parts header confidence below minimum {_MIN_HEADER_CONFIDENCE}%; "
                "skipping parts extraction."
            )
            logger.warning("Parts extractor: %s", warning)
            audit_lines.append(f"WARNING: {warning}")
        else:
            # Detect labour header first so we can pass its row as a stop_row
            # boundary. This guarantees spare parts never bleed into the labour
            # section even when keyword matching fails.
            _labour_detection_for_stop = _detect_labour_header(src_ws)
            _stop_row = _labour_detection_for_stop.row  # None if not found

            parts_rows = _extract_parts_rows(
                src_ws, parts_header, parts_col_map, hsn_code=parts_hsn,
                audit_lines=audit_lines, boundary_keyword=boundary_keyword,
                stop_row=_stop_row,
            )
            logger.info("Parts extractor: extracted %d spare part rows", len(parts_rows))
    else:
        logger.warning("Parts extractor: no spare parts header found in Excel")
        audit_lines.append("Parts header: not found")

    # ── Phase 2: Labour Charges ──
    labour_detection = _detect_labour_header(src_ws)
    if labour_detection.row:
        labour_header = labour_detection.row
        labour_col_map = labour_detection.col_map
        logger.info(
            "Parts extractor: labour header found at row %d, confidence=%d, columns: %s",
            labour_header, labour_detection.confidence, list(labour_col_map.keys()),
        )
        audit_lines.extend([
            "",
            "── Labour Charges ──",
            f"Header row: {labour_header}",
            f"Confidence: {labour_detection.confidence}%",
            f"Matched: {', '.join(labour_detection.matched_keys) or '-'}",
            f"Missing: {', '.join(labour_detection.missing_keys) or '-'}",
        ])

        if labour_detection.confidence < _MIN_HEADER_CONFIDENCE:
            warning = (
                f"Labour header confidence below minimum {_MIN_HEADER_CONFIDENCE}%; "
                "skipping labour extraction."
            )
            logger.warning("Parts extractor: %s", warning)
            audit_lines.append(f"WARNING: {warning}")
        else:
            labour_rows = _extract_labour_rows(
                src_ws, labour_header, labour_col_map, hsn_code=labour_hsn,
                audit_lines=audit_lines, boundary_keyword=boundary_keyword,
            )
            logger.info("Parts extractor: extracted %d labour rows", len(labour_rows))
    else:
        logger.warning("Parts extractor: no labour header found in Excel")
        audit_lines.append("Labour header: not found")

    src_wb.close()

    audit_lines.extend([
        "",
        "── Summary ──",
        f"Parts rows: {len(parts_rows)}",
        f"Labour rows: {len(labour_rows)}",
        f"Total rows: {len(parts_rows) + len(labour_rows)}",
    ])

    return parts_rows, labour_rows, audit_lines
