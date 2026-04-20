"""
excel_reader.py
Reads the Excel file (.xls / .xlsx) from the scanned folder.

SEARCH STRATEGY (position-independent):
  1. Scan all cells in the sheet for the search_label text.
  2. From that label cell, look RIGHT across the same row for the first
     non-junk value (handles any column layout).
  3. If row_offset > 0, move down that many rows first, then scan right.
  4. col_offset is used ONLY as a tiebreaker hint — it no longer causes
     failures when the Excel layout shifts between claims.

This makes the reader robust regardless of where the label or value
appears in any given Excel file.
"""
import os
import re
import json
import logging
from datetime import datetime
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Excel library selection ───────────────────────────────────────────────────
def _open_workbook(path: str):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xls":
        import xlrd
        wb = xlrd.open_workbook(path)
        return _XlrdWrapper(wb)
    else:
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)
        return _OpenpyxlWrapper(wb)


class _XlrdWrapper:
    def __init__(self, wb):
        self._wb = wb

    def sheet_names(self):
        return self._wb.sheet_names()

    def get_sheet(self, name):
        try:
            sh = self._wb.sheet_by_name(name)
            return _XlrdSheetWrapper(sh)
        except Exception:
            return None

    def all_sheets(self):
        return [_XlrdSheetWrapper(self._wb.sheet_by_index(i))
                for i in range(self._wb.nsheets)]


class _XlrdSheetWrapper:
    def __init__(self, sh):
        self._sh = sh
        self.name = sh.name

    def rows(self):
        for r in range(self._sh.nrows):
            yield [self._sh.cell_value(r, c) for c in range(self._sh.ncols)]


class _OpenpyxlWrapper:
    def __init__(self, wb):
        self._wb = wb

    def sheet_names(self):
        return self._wb.sheetnames

    def get_sheet(self, name):
        if name in self._wb:
            return _OpenpyxlSheetWrapper(self._wb[name])
        return None

    def all_sheets(self):
        return [_OpenpyxlSheetWrapper(self._wb[n]) for n in self._wb.sheetnames]


class _OpenpyxlSheetWrapper:
    def __init__(self, sh):
        self._sh = sh
        self.name = sh.title

    def rows(self):
        for row in self._sh.iter_rows(values_only=True):
            yield [v if v is not None else "" for v in row]


# ── Junk values — never returned as a field value ─────────────────────────────
_JUNK_VALUES = {
    ':', 'rs', 'rs.', 'inr', '-', '--', 'n/a', 'nil', 'na',
    'attached', 'yes', 'no', 'period:', 'date:', 'amount',
    'estimated', 'assessed', 'particulars', 'description',
}

# Junk patterns — text that looks like a label, not a value
_JUNK_PATTERNS = [
    re.compile(r'^[a-z\s/&()%,.:]+$'),      # Pure text with no digits
    re.compile(r'^rs\.?\s*$', re.I),         # "Rs" or "Rs."
    re.compile(r'^\s*:\s*$'),                 # Just ":"
]


def _is_junk(val: Any) -> bool:
    """Return True if val should NOT be treated as a field value."""
    # 0 and 0.0 are valid numeric values — never junk
    if val == 0 or val == 0.0:
        return False
    if val in (None, ""):
        return True
    s = str(val).strip()
    if not s:
        return True
    sl = s.lower()
    if sl in _JUNK_VALUES:
        return True
    # Pure alphabetic strings with no digits are junk (they are labels)
    for pat in _JUNK_PATTERNS:
        if pat.match(sl) and not any(c.isdigit() for c in s):
            return True
    return False


# ── Core search — position-independent ───────────────────────────────────────

def _search_label(sheet, label: str, row_offset: int, col_offset: int,
                  is_date: bool = False) -> Optional[str]:
    """
    Find label text anywhere in the sheet. Then:
      1. Move row_offset rows down.
      2. Try col_offset first (exact hint from config).
      3. If that's empty/junk, scan RIGHT from the label column to find
         the first non-junk value.
      4. This makes the search position-independent: the label can be in
         any column; the value just needs to be to the right on the same row.

    Returns cleaned string value or None.
    """
    label_lower = label.lower().strip()
    all_rows = list(sheet.rows())

    for r_idx, row in enumerate(all_rows):
        for c_idx, cell in enumerate(row):
            cell_str = str(cell).strip().lower()
            if label_lower in cell_str and cell_str:
                # Found the label at (r_idx, c_idx)
                target_r = r_idx + row_offset

                if not (0 <= target_r < len(all_rows)):
                    continue

                target_row = all_rows[target_r]

                # ── Strategy 1: Try col_offset hint first ──────────────────
                hint_c = c_idx + col_offset
                if 0 <= hint_c < len(target_row):
                    val = target_row[hint_c]
                    result = _extract_value(val, is_date)
                    if result is not None:
                        logger.info(
                            f"  [{label}] found at R{r_idx}C{c_idx}, "
                            f"value at R{target_r}C{hint_c} = {result}"
                        )
                        return result

                # ── Strategy 2: Scan right from label col to find first value
                for scan_c in range(c_idx + 1, len(target_row)):
                    val = target_row[scan_c]
                    result = _extract_value(val, is_date)
                    if result is not None:
                        logger.info(
                            f"  [{label}] found at R{r_idx}C{c_idx}, "
                            f"value at R{target_r}C{scan_c} (scan right) = {result}"
                        )
                        return result

                # ── Strategy 3: If row_offset=0 and no value found on same row,
                #    try one row below the label (common pattern in Indian Excel reports)
                if row_offset == 0 and target_r + 1 < len(all_rows):
                    next_row = all_rows[target_r + 1]
                    for scan_c in range(max(0, c_idx - 1), min(len(next_row), c_idx + 10)):
                        val = next_row[scan_c]
                        result = _extract_value(val, is_date)
                        if result is not None:
                            logger.info(
                                f"  [{label}] found at R{r_idx}C{c_idx}, "
                                f"value at R{target_r+1}C{scan_c} (scan below) = {result}"
                            )
                            return result

    return None


def _extract_value(val: Any, is_date: bool) -> Optional[str]:
    """
    Convert a raw cell value to a usable string.
    Returns None if the value is empty or junk.
    """
    if val == "" or val is None:
        return None
    if _is_junk(val):
        return None

    # Special case: val == 0 or 0.0 IS a valid value
    if val == 0 or val == 0.0:
        return "0"

    if is_date:
        date_result = _try_date_serial(val)
        if date_result:
            return date_result

    return _clean_value(val)


def _clean_value(val: Any) -> str:
    """Convert Excel cell value to a clean string."""
    if val is None:
        return ""
    if isinstance(val, float):
        if val == int(val):
            return str(int(val))
        return f"{val:.2f}"
    return str(val).strip()


def _try_date_serial(val: Any) -> Optional[str]:
    """Try to convert xlrd float date serial to DD/MM/YYYY."""
    if not isinstance(val, float):
        return None
    # xlrd date serials for years 1990-2040 fall in ~32874-51544
    if 32874 < val < 51544:
        try:
            import xlrd
            t = xlrd.xldate_as_tuple(val, 0)
            if t[0] > 1990:
                return f"{t[2]:02d}/{t[1]:02d}/{t[0]}"
        except Exception:
            pass
    return None


def _format_date(raw: str) -> str:
    """Normalise any date string to DD/MM/YYYY for the portal."""
    if not raw:
        return ""
    if re.match(r"\d{2}/\d{2}/\d{4}", raw):
        return raw
    # L2 FIX: removed duplicate "%d.%m.%Y" that was listed twice
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d.%m.%Y",
                "%Y/%m/%d", "%B %d, %Y"):
        try:
            dt = datetime.strptime(raw.strip(), fmt)
            return dt.strftime("%d/%m/%Y")
        except ValueError:
            continue
    return raw


# ── Public API ────────────────────────────────────────────────────────────────

def read_excel(excel_path: str, config_dir: str):
    """
    Read Excel file and return a fully populated ClaimData instance.

    For each field in field_mapping.json:
      - Finds the label text anywhere in the configured sheet
      - Reads the value to the right of the label (position-independent)
      - Falls back to scanning right and then scanning below
      - Logs exactly which cell was read for each field
    """
    from app.data.data_model import ClaimData

    mapping_path = os.path.join(config_dir, "field_mapping.json")
    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping = json.load(f)

    wb = _open_workbook(excel_path)
    claim = ClaimData()

    found_count = 0
    missing_fields = []

    for field_name, cfg in mapping.items():
        if field_name.startswith("_"):
            continue

        sheet_name = cfg.get("sheet", "ALL")
        label      = cfg.get("search_label", "")
        row_off    = cfg.get("row_offset", 0)
        col_off    = cfg.get("col_offset", 1)
        is_date    = "date" in field_name

        value = None

        if sheet_name == "ALL":
            for sh in wb.all_sheets():
                value = _search_label(sh, label, row_off, col_off, is_date)
                if value:
                    break
        else:
            sh = wb.get_sheet(sheet_name)
            if sh:
                value = _search_label(sh, label, row_off, col_off, is_date)
            else:
                logger.warning(f"  [{field_name}] Sheet '{sheet_name}' not found in workbook")

        if value:
            if is_date:
                value = _format_date(value)
            setattr(claim, field_name, value)
            found_count += 1
            logger.info(f"  [FOUND] {field_name} = {value}")
        else:
            missing_fields.append(f"{field_name} (label: '{label}')")
            logger.warning(f"  [MISSING] {field_name}: label '{label}' not found or value empty")

    logger.info(f"Excel read complete: {found_count} fields found, "
                f"{len(missing_fields)} missing: {missing_fields}")
    return claim
