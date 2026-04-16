"""
excel_reader.py
Reads the Excel file (.xls / .xlsx) from the scanned folder.
Uses label-search strategy: scans all cells in the configured sheet for the
search_label text, then reads the value at (row + row_offset, col + col_offset).
Populates and returns a ClaimData instance.
"""
import os
import re
import json
import logging
from datetime import datetime
from typing import Any, Optional, Tuple

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


# ── Junk values that should never be returned as field values ────────────────
_JUNK_VALUES = {':', 'rs', 'rs.', 'inr', '-', '--', 'n/a', 'nil', 'na', 'attached', 'yes', 'no'}


# ── Core search helper ────────────────────────────────────────────────────────
def _search_label(sheet, label: str, row_offset: int, col_offset: int,
                  is_date: bool = False) -> Optional[str]:
    """
    Scan every cell in sheet. If cell text contains label (case-insensitive),
    return the value at (row+row_offset, col+col_offset).
    is_date=True → try xlrd date-serial conversion on the target cell.
    """
    label_lower = label.lower().strip()
    all_rows = list(sheet.rows())
    for r_idx, row in enumerate(all_rows):
        for c_idx, cell in enumerate(row):
            cell_str = str(cell).strip().lower()
            if label_lower in cell_str and cell_str:
                target_r = r_idx + row_offset
                target_c = c_idx + col_offset
                if 0 <= target_r < len(all_rows):
                    target_row = all_rows[target_r]
                    if 0 <= target_c < len(target_row):
                        val = target_row[target_c]
                        if val in (0, 0.0):
                            return '0'
                        if val in (None, ""):
                            return None
                        val_str = str(val).strip()
                        if val_str.lower() in _JUNK_VALUES:
                            return None
                        # For date fields try serial conversion first
                        if is_date:
                            date_str = _try_date_serial(val)
                            if date_str:
                                return date_str
                        return _clean_value(val)
    return None


def _clean_value(val: Any) -> str:
    """Convert Excel cell value to clean string (NO date conversion — handled separately)."""
    if val is None:
        return ""
    if isinstance(val, float):
        if val == int(val):
            return str(int(val))
        return f"{val:.2f}"
    return str(val).strip()


def _try_date_serial(val: Any) -> Optional[str]:
    """Try to convert xlrd float date serial to DD/MM/YYYY. Returns None if not a date."""
    if not isinstance(val, float):
        return None
    # xlrd date serials for years 1990-2040 fall in range ~32874-51544
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
    """Try to normalise date to DD/MM/YYYY for the portal."""
    if not raw:
        return ""
    # Already correct format
    if re.match(r"\d{2}/\d{2}/\d{4}", raw):
        return raw
    # Try common formats
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(raw.strip(), fmt)
            return dt.strftime("%d/%m/%Y")
        except ValueError:
            continue
    return raw  # Return as-is if unparseable


# ── Public API ────────────────────────────────────────────────────────────────
def read_excel(excel_path: str, config_dir: str):
    """
    Read Excel file and return a populated ClaimData instance.
    Imports ClaimData here to avoid circular imports.
    """
    from app.data.data_model import ClaimData

    mapping_path = os.path.join(config_dir, "field_mapping.json")
    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping = json.load(f)

    wb = _open_workbook(excel_path)
    claim = ClaimData()

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

        if value:
            if is_date:
                value = _format_date(value)
            setattr(claim, field_name, value)
            logger.info(f"  [{field_name}] = {value}")
        else:
            logger.warning(f"  [{field_name}] NOT FOUND in Excel (label: '{label}')")

    return claim
