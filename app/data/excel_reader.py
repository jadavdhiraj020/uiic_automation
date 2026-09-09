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
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
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
        self._sheets = {}

    def sheet_names(self):
        return self._wb.sheet_names()

    def get_sheet(self, name):
        clean_name = str(name).strip().lower()
        if clean_name not in self._sheets:
            # 1. Try exact match
            matched_sh = None
            try:
                matched_sh = self._wb.sheet_by_name(name)
            except Exception:
                # 2. Try case-insensitive / trimmed match across sheet names
                for i in range(self._wb.nsheets):
                    sh = self._wb.sheet_by_index(i)
                    if sh.name.strip().lower() == clean_name:
                        matched_sh = sh
                        break

            if matched_sh is not None:
                self._sheets[clean_name] = _XlrdSheetWrapper(matched_sh)
                return self._sheets[clean_name]

            # 3. Fallback: if name is like "Sheet1", "Sheet2", try 1-based index
            import re
            m = re.match(r"^Sheet(\d+)$", clean_name, re.IGNORECASE)
            if m:
                idx = int(m.group(1)) - 1
                if 0 <= idx < self._wb.nsheets:
                    try:
                        sh = self._wb.sheet_by_index(idx)
                        self._sheets[clean_name] = _XlrdSheetWrapper(sh)
                        return self._sheets[clean_name]
                    except Exception:
                        pass
            return None
        return self._sheets[clean_name]

    def all_sheets(self):
        for i in range(self._wb.nsheets):
            sh = self._wb.sheet_by_index(i)
            name = sh.name
            if name not in self._sheets:
                self._sheets[name] = _XlrdSheetWrapper(sh)
        return list(self._sheets.values())


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
        self._sheets = {}

    def sheet_names(self):
        return self._wb.sheetnames

    def get_sheet(self, name):
        clean_name = str(name).strip().lower()
        if clean_name not in self._sheets:
            # 1. Exact match
            if name in self._wb:
                self._sheets[clean_name] = _OpenpyxlSheetWrapper(self._wb[name])
                return self._sheets[clean_name]

            # 2. Case-insensitive / trimmed match
            for real_name in self._wb.sheetnames:
                if real_name.strip().lower() == clean_name:
                    self._sheets[clean_name] = _OpenpyxlSheetWrapper(self._wb[real_name])
                    return self._sheets[clean_name]

            # 3. Fallback: if name is like "Sheet1", "Sheet2", try 1-based index
            import re
            m = re.match(r"^Sheet(\d+)$", clean_name, re.IGNORECASE)
            if m:
                idx = int(m.group(1)) - 1
                names = self._wb.sheetnames
                if 0 <= idx < len(names):
                    real_name = names[idx]
                    self._sheets[clean_name] = _OpenpyxlSheetWrapper(self._wb[real_name])
                    return self._sheets[clean_name]
            return None
        return self._sheets[clean_name]

    def all_sheets(self):
        for n in self._wb.sheetnames:
            if n not in self._sheets:
                self._sheets[n] = _OpenpyxlSheetWrapper(self._wb[n])
        return list(self._sheets.values())


class _OpenpyxlSheetWrapper:
    def __init__(self, sh):
        self._sh = sh
        self.name = sh.title
        
        # Calculate actual non-empty boundaries to avoid scanning massive empty cells.
        self._max_row = sh.max_row or 1
        self._max_col = sh.max_column or 1
        
        # If the sheet is reported as excessively wide or tall, we scan it once
        # to restrict max_row and max_col to the actual bounding box of data.
        if self._max_col > 100 or self._max_row > 1000:
            real_max_row = 1
            real_max_col = 1
            cells_dict = getattr(sh, "_cells", None)
            if isinstance(cells_dict, dict):
                for (r, c), cell in cells_dict.items():
                    if cell.value not in (None, ""):
                        if r > real_max_row:
                            real_max_row = r
                        if c > real_max_col:
                            real_max_col = c
            else:
                for r_idx, row in enumerate(sh.iter_rows(values_only=True)):
                    row_has_data = False
                    for c_idx, val in enumerate(row):
                        if val not in (None, ""):
                            row_has_data = True
                            real_max_col = max(real_max_col, c_idx + 1)
                    if row_has_data:
                        real_max_row = max(real_max_row, r_idx + 1)
            self._max_row = real_max_row
            self._max_col = real_max_col
            logger.info(
                f"Optimized sheet '{self.name}' boundaries: max_row={self._max_row}, max_col={self._max_col} (down from {sh.max_row}x{sh.max_column})"
            )

    def rows(self):
        for row in self._sh.iter_rows(max_row=self._max_row, max_col=self._max_col, values_only=True):
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
                  is_date: bool = False,
                  allow_literal_values: bool = False,
                  allow_text_values: bool = False) -> Tuple[Optional[str], Optional[str]]:
    """
    Find label text anywhere in the sheet. Then:
      1. Move row_offset rows down.
      2. Try col_offset first (exact hint from config).
      3. If that's empty/junk, scan RIGHT from the label column to find
         the first non-junk value.
      4. This makes the search position-independent: the label can be in
         any column; the value just needs to be to the right on the same row.

    Returns tuple (cleaned string value, coordinate info string) or (None, None).
    """
    label_lower = " ".join(label.lower().split())  # normalize whitespace
    all_rows = list(sheet.rows())

    for r_idx, row in enumerate(all_rows):
        for c_idx, cell in enumerate(row):
            cell_str = " ".join(str(cell).strip().lower().split())  # collapse \n, \t, multi-space
            if cell_str and label_lower in cell_str:
                # Prevent matching "time of survey" on a combined date cell like "Date and Time of Survey"
                if "date" in cell_str and "date" not in label_lower:
                    continue
                # Prevent matching "time of survey" on a combined person cell like "Person Present at the Time of Survey"
                if "person" in cell_str and "person" not in label_lower:
                    continue

                # Word-boundary check: prevent "TOTAL" matching "SUBTOTAL"
                idx = cell_str.find(label_lower)
                before_ok = (idx == 0) or not cell_str[idx - 1].isalnum()
                after_end = idx + len(label_lower)
                after_ok = (after_end >= len(cell_str)) or not cell_str[after_end].isalnum()
                if not (before_ok and after_ok):
                    continue
                # Found the label at (r_idx, c_idx)
                
                # ── Strategy 0: Inline value (e.g., "Mobile: 098761-35253" in one cell)
                # Only check inline if:
                # 1) User specified col_offset == 0 (explicitly in the same cell), OR
                # 2) Cell starts with label (e.g. "Ref: XYZ") and is concise, NOT a huge multi-sentence paragraph.
                inline_content = cell_str.replace(label_lower, "").strip(" :-\n\t")
                is_concise_inline = 0 < len(inline_content) <= 120 and len(inline_content.split()) <= 15
                can_try_inline = (col_offset == 0) or (
                    is_concise_inline and (
                        cell_str.startswith(label_lower)
                        or ":" in str(cell)
                    )
                )

                if can_try_inline and len(inline_content) >= 1:
                    orig_cell = str(cell)
                    # Try splitting by colon or just removing the label text
                    if ":" in orig_cell and not allow_text_values:
                        val = orig_cell.split(":", 1)[-1].strip(" -\n\t")
                    else:
                        val = re.sub(re.escape(label), "", orig_cell, flags=re.IGNORECASE).strip(" -:\n\t")
                    
                    if val:
                        result = _extract_value(val, is_date, allow_literal_values, allow_text_values)
                        if result is not None:
                            coord_str = f"R{r_idx+1}C{c_idx+1}"
                            logger.info(
                                f"  [{label}] found inline at {coord_str} = {result}"
                            )
                            return result, coord_str

                target_r = r_idx + row_offset

                if not (0 <= target_r < len(all_rows)):
                    continue

                target_row = all_rows[target_r]

                # ── Strategy 1: Try col_offset hint first ──────────────────
                hint_c = c_idx + col_offset
                if 0 <= hint_c < len(target_row):
                    val = target_row[hint_c]
                    result = _extract_value(val, is_date, allow_literal_values, allow_text_values)
                    if result is not None:
                        coord_str = f"R{target_r+1}C{hint_c+1}"
                        logger.info(
                            f"  [{label}] found at R{r_idx+1}C{c_idx+1}, "
                            f"value at {coord_str} = {result}"
                        )
                        return result, coord_str

                # ── Strategy 2: Scan right from label col to find first value
                for scan_c in range(c_idx + 1, len(target_row)):
                    val = target_row[scan_c]
                    result = _extract_value(val, is_date, allow_literal_values, allow_text_values)
                    if result is not None:
                        coord_str = f"R{target_r+1}C{scan_c+1}"
                        logger.info(
                            f"  [{label}] found at R{r_idx+1}C{c_idx+1}, "
                            f"value at {coord_str} (scan right) = {result}"
                        )
                        return result, coord_str

                # ── Strategy 3: REMOVED FOR SAFETY ─────────────────────────────
                # We no longer drop down to the next row automatically if row_offset=0.
                # If the value is not on the expected row, we stop to prevent grabbing wrong data.

    return None, None


def _extract_value(val: Any, is_date: bool,
                   allow_literal_values: bool = False,
                   allow_text_values: bool = False) -> Optional[str]:
    """
    Convert a raw cell value to a usable string.
    Returns None if the value is empty or junk.
    """
    if val == "" or val is None:
        return None
    if allow_literal_values:
        s = str(val).strip()
        if s and s.lower() in {"yes", "no"}:
            return s
    if allow_text_values:
        # Accept any non-empty text — skip the junk/pattern checks entirely
        # But still reject trivial separators like ":" or "-"
        s = str(val).strip().strip(":- ")
        return s if s else None
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


def _initial_loss_75_percent(value: Any) -> str:
    """
    Use 75% of the Excel "initial loss assessment" amount.

    The portal ultimately wants rounded rupees, so keep UI preview and
    automation aligned by storing the rounded 75% amount in ClaimData.
    """
    raw = str(value).strip()
    if raw == "":
        return raw

    cleaned = raw.replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return raw

    try:
        amount = Decimal(match.group(0))
    except (InvalidOperation, ValueError):
        logger.warning("  [MATH] Could not calculate 75%% initial loss from '%s'", value)
        return raw

    adjusted = (amount * Decimal("0.75")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return str(int(adjusted))


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
    val = str(raw).strip()
    
    # Try parsing common formats, particularly timestamps from Excel
    for fmt in (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y",
        "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%Y/%m/%d", "%B %d, %Y", "%b %d, %Y",
        "%a %b %d %Y", "%b %d %Y"
    ):
        try:
            dt = datetime.strptime(val, fmt)
            return dt.strftime("%d/%m/%Y")
        except ValueError:
            pass

    # Regex for textual month names (e.g. 'Thu Apr 27 2023 ...' or 'Apr 27 2023' or 'April 27, 2023')
    m_text = re.search(r'(?:[A-Za-z]{3,9}\s+)?([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})', val)
    if m_text:
        mon_str, d_str, y_str = m_text.groups()
        for m_fmt in ("%b", "%B"):
            try:
                mon_dt = datetime.strptime(mon_str, m_fmt)
                return f"{int(d_str):02d}/{mon_dt.month:02d}/{y_str}"
            except ValueError:
                pass

    # Regex for '27 Apr 2023' or '27th April 2023'
    m_text2 = re.search(r'(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9}),?\s+(\d{4})', val)
    if m_text2:
        d_str, mon_str, y_str = m_text2.groups()
        for m_fmt in ("%b", "%B"):
            try:
                mon_dt = datetime.strptime(mon_str, m_fmt)
                return f"{int(d_str):02d}/{mon_dt.month:02d}/{y_str}"
            except ValueError:
                pass

    # Regex fallback if formats above fail
    m = re.search(r'(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})', val)
    if m:
        d, mon, y = m.groups()
        return f"{int(d):02d}/{int(mon):02d}/{y}"
        
    m2 = re.search(r'(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})', val)
    if m2:
        y, mon, d = m2.groups()
        return f"{int(d):02d}/{int(mon):02d}/{y}"
        
    # Fallback: if it looks like a timestamp (date + space + time), return normalized date part
    if " " in val and ":" in val:
        candidate = val.split(" ")[0]
        if any(c.isdigit() for c in candidate) and any(c in "-/." for c in candidate):
            return _format_date(candidate)
    return val


def _parse_time_string(val: str) -> Optional[Tuple[str, str]]:
    """
    Parse a string for a valid time, converting to 24-hour (HH, MM).
    Supports:
      - 12h: '11:30 AM', '11.30am', '11 AM', '02:15 PM', '2.30 pm', 'at 11:30 AM'
      - 24h: '14:30', '11:00', '09:15', '2023-04-27 11:30:00'
    Ignores timezone indicators (e.g. GMT+0530, India Standard Time) since those
    represent UTC midnight conversions rather than actual survey times.
    Returns (hh_str, mm_str) or None.
    """
    if not val or not str(val).strip():
        return None
    s = str(val).strip()

    # If the string contains timezone indicators (e.g. JS Date export), do not treat as survey time
    if "gmt" in s.lower() or "utc" in s.lower() or "standard time" in s.lower():
        return None

    # 1. 12-hour AM/PM pattern (e.g. 11:30 AM, 11.30am, 2 PM)
    m_ampm = re.search(r"\b(\d{1,2})[.:](\d{2})\s*([aA]\.?[mM]\.?|[pP]\.?[mM]\.?)\b", s)
    if not m_ampm:
        m_ampm = re.search(r"\b(\d{1,2})\s*([aA]\.?[mM]\.?|[pP]\.?[mM]\.?)\b", s)
    if m_ampm:
        h = int(m_ampm.group(1))
        m = int(m_ampm.group(2)) if (m_ampm.lastindex >= 3 and m_ampm.group(2)) else 0
        ampm = m_ampm.group(m_ampm.lastindex).replace(".", "").lower()
        if 1 <= h <= 12 and 0 <= m <= 59:
            if ampm == "pm" and h < 12:
                h += 12
            elif ampm == "am" and h == 12:
                h = 0
            return f"{h:02d}", f"{m:02d}"

    # 2. 24-hour pattern (HH:MM or HH:MM:SS or HH.MM)
    m_24 = re.search(r"\b([01]?\d|2[0-3])[.:]([0-5]\d)(?::[0-5]\d)?\b", s)
    if m_24:
        h = int(m_24.group(1))
        m = int(m_24.group(2))
        return f"{h:02d}", f"{m:02d}"

    return None


def _extract_time_from_adjacent_cells(wb, sheet_name, found_label, cfg, claim) -> bool:
    """Helper to scan adjacent cells for survey time if missing from main cell."""
    try:
        all_sheets = wb.all_sheets() if sheet_name == "ALL" else [wb.get_sheet(sheet_name)]
        for sh in all_sheets:
            if sh is None:
                continue
            sh_name = sh.name if hasattr(sh, "name") else "Sheet"
            for r_idx, row in enumerate(sh.rows()):
                for c_idx, cell in enumerate(row):
                    cell_lower = str(cell).strip().lower()
                    if found_label.lower() in cell_lower and cell_lower:
                        target_r = r_idx + cfg.get("row_offset", 0)
                        all_row_data = list(sh.rows())
                        if 0 <= target_r < len(all_row_data):
                            target_row = all_row_data[target_r]
                            for tc in range(c_idx + 1, len(target_row)):
                                tc_str = str(target_row[tc]).strip()
                                parsed = _parse_time_string(tc_str)
                                if parsed:
                                    claim.time_hh, claim.time_mm = parsed
                                    coord_str = f"R{target_r+1}C{tc+1} ({sh_name})"
                                    claim._excel_coords["time_hh"] = coord_str
                                    claim._excel_logs.append(
                                        f"  📊 time_of_survey: '{claim.time_hh}:{claim.time_mm}' (Source: {coord_str})"
                                    )
                                    logger.info(f"  [TIME] Extracted from adjacent cell {coord_str}: {claim.time_hh}:{claim.time_mm}")
                                    return True
    except Exception as e:
        logger.warning(f"  [TIME] Adjacent cell scan failed: {e}")
    return False


def _calculate_professional_fee(survey_fee: any, reinspection_fee: any) -> str:
    """
    Calculates professional_fee = survey_fee + reinspection_fee using Decimal arithmetic.
    """
    survey_raw = re.sub(r"[^\d.]", "", str(survey_fee or "0").replace(",", "").strip())
    reinsp_raw = re.sub(r"[^\d.]", "", str(reinspection_fee or "0").replace(",", "").strip())
    try:
        val_survey = Decimal(survey_raw) if survey_raw else Decimal("0")
    except (InvalidOperation, ValueError):
        val_survey = Decimal("0")
    try:
        val_reinsp = Decimal(reinsp_raw) if reinsp_raw else Decimal("0")
    except (InvalidOperation, ValueError):
        val_reinsp = Decimal("0")

    total_prof = val_survey + val_reinsp
    if total_prof == Decimal("0"):
        return "0"
    if total_prof == total_prof.to_integral():
        return str(int(total_prof))
    return f"{total_prof:.2f}"


def _find_email_by_regex(wb, sheet_name: str = "Sheet1") -> Tuple[Optional[str], Optional[str]]:
    """
    Scans the given sheet for a cell containing an email address ending in .com using regex.
    Prioritizes cell I4 (Surveyor letterhead email) if present, then scans row-by-row.
    Returns (clean_email, coord_str) or (None, None).
    """
    EMAIL_COM_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.com\b", re.IGNORECASE)

    sh = wb.get_sheet(sheet_name)
    if not sh:
        all_sh = wb.all_sheets()
        sh = all_sh[0] if all_sh else None
    if not sh:
        return None, None

    sh_name = sh.name if hasattr(sh, "name") else sheet_name
    all_rows = list(sh.rows())
    if not all_rows:
        return None, None

    # Priority 1: Check cell I4 (Row 4, Column I -> 0-based r=3, c=8)
    if len(all_rows) > 3:
        row4 = all_rows[3]
        if len(row4) > 8:
            val_i4 = str(row4[8] or "").strip()
            if ".com" in val_i4.lower() and "@" in val_i4:
                m = EMAIL_COM_REGEX.search(val_i4)
                if m:
                    email_clean = m.group(0).strip()
                    coord_str = f"I4 ({sh_name})"
                    logger.info(f"  [EMAIL REGEX] Found email at cell I4: {email_clean}")
                    return email_clean, coord_str

    # Priority 2: Scan all cells in the sheet for the first regex .com email match
    for r_idx, row in enumerate(all_rows):
        for c_idx, cell in enumerate(row):
            if cell is None or cell == "":
                continue
            cell_str = str(cell).strip()
            if ".com" in cell_str.lower() and "@" in cell_str:
                m = EMAIL_COM_REGEX.search(cell_str)
                if m:
                    email_clean = m.group(0).strip()
                    coord_str = f"R{r_idx+1}C{c_idx+1} ({sh_name})"
                    logger.info(f"  [EMAIL REGEX] Found email at {coord_str}: {email_clean}")
                    return email_clean, coord_str

    return None, None


# ── Public API ────────────────────────────────────────────────────────────────

def extract_claim_data(excel_path: str, portal_id: str = "uiic"):
    """
    Read Excel file and return a fully populated ClaimData instance.

    For each field in field_mapping.json:
      - Finds the label text anywhere in the configured sheet
      - Reads the value to the right of the label (position-independent)
      - Falls back to scanning right and then scanning below
      - Logs exactly which cell was read for each field
    """
    from app.data.data_model import ClaimData
    from app.utils import load_automation_defaults, load_field_mapping

    # Use the user's custom field mapping from AppData if it exists,
    # otherwise fall back to the bundled default.
    mapping = load_field_mapping(portal_id=portal_id)
    automation_defaults = load_automation_defaults(portal_id=portal_id)

    wb = _open_workbook(excel_path)
    claim = ClaimData(portal_id=portal_id or "uiic")

    found_count = 0
    missing_fields = []

    for field_name, cfg in mapping.items():
        if field_name.startswith("_"):
            continue

        if field_name == "surveyor_observation":
            observation_default = str(automation_defaults.get("observation_default", "Ok") or "Ok")
            claim.surveyor_observation = observation_default
            claim._excel_coords["surveyor_observation"] = "Automation Defaults"
            claim._excel_logs.append(
                f"  [DEFAULT] surveyor_observation: '{observation_default}' (Source: Automation Defaults)"
            )
            logger.info("  [DEFAULT] surveyor_observation = %s", observation_default)
            found_count += 1
            continue

        sheet_name = cfg.get("sheet", "ALL")
        
        labels = cfg.get("search_labels")
        if not labels:
            raw_label = cfg.get("search_label", "")
            if isinstance(raw_label, list):
                labels = raw_label
            else:
                labels = [raw_label] if raw_label else []

        row_off    = cfg.get("row_offset", 0)
        col_off    = cfg.get("col_offset", 1)
        is_date    = "date" in field_name or "dob" in field_name
        allow_literal_values = bool(cfg.get("allow_literal_values"))
        allow_text_values    = bool(cfg.get("allow_text_values"))

        value = None
        found_label = ""

        # ── Priority 0 for email_id: Regex .com discovery on Sheet1 ──────────
        if field_name == "email_id":
            regex_email, regex_coord = _find_email_by_regex(wb, sheet_name=sheet_name)
            if regex_email:
                value = regex_email
                claim._excel_coords[field_name] = regex_coord
                claim._excel_logs.append(
                    f"  📊 {field_name}: '{value}' (Source: {regex_coord} - Regex .com match)"
                )
                logger.info(f"  [REGEX FOUND] email_id = {value} at {regex_coord}")

        if not value:
            for current_label in labels:
                if not current_label:
                    continue
                
                if sheet_name == "ALL":
                    for sh in wb.all_sheets():
                        value, coord = _search_label(
                            sh, current_label, row_off, col_off, is_date,
                            allow_literal_values, allow_text_values
                        )
                        if value:
                            sh_name = sh.name if hasattr(sh, 'name') else 'Sheet'
                            src_str = f"{coord} ({sh_name})"
                            claim._excel_coords[field_name] = src_str
                            claim._excel_logs.append(f"  📊 {field_name}: '{value}' (Source: {src_str})")
                            found_label = current_label
                            break
                else:
                    sh = wb.get_sheet(sheet_name)
                    if sh:
                        value, coord = _search_label(
                            sh, current_label, row_off, col_off, is_date,
                            allow_literal_values, allow_text_values
                        )
                        if value:
                            src_str = f"{coord} ({sheet_name})"
                            claim._excel_coords[field_name] = src_str
                            claim._excel_logs.append(f"  📊 {field_name}: '{value}' (Source: {src_str})")
                            found_label = current_label
                    else:
                        if current_label == labels[-1]: # Only warn on the last fallback try
                            logger.warning(f"  [{field_name}] Sheet '{sheet_name}' not found in workbook")

                if value:
                    break  # Found it, stop trying fallback labels

        if value:
            if field_name == "date_of_survey":
                # ── Extract time from the date string, adjacent cells, or fallback ──
                time_found = False

                # 1. Try parsing time from the value itself (e.g. '27/04/2023 11:30 AM', '14:15', '2023-04-27 11:30:00')
                parsed_time = _parse_time_string(value)
                if parsed_time:
                    claim.time_hh, claim.time_mm = parsed_time
                    time_found = True
                    claim._excel_coords["time_hh"] = claim._excel_coords.get("date_of_survey", "")
                    claim._excel_logs.append(
                        f"  📊 time_of_survey: '{claim.time_hh}:{claim.time_mm}' (Source: {claim._excel_coords['time_hh']})"
                    )
                    logger.info(f"  [TIME] Extracted from date cell: {claim.time_hh}:{claim.time_mm}")

                # 2. If no time in value, scan adjacent cells in the row
                if not time_found:
                    time_found = _extract_time_from_adjacent_cells(wb, sheet_name, found_label, cfg, claim)

                # 3. Direct fallback for UIIC: If not found in date or adjacent cells, default to 11 HH and 00 MM
                if not time_found and (portal_id == "uiic" or "date_of_survey" in mapping):
                    def_time = str(automation_defaults.get("survey_time_default", "11:00") or "11:00")
                    if ":" in def_time:
                        parts = def_time.split(":")
                        claim.time_hh = f"{int(parts[0]):02d}"
                        claim.time_mm = f"{int(parts[1]):02d}"
                    else:
                        claim.time_hh = "11"
                        claim.time_mm = "00"
                    claim._excel_coords["time_hh"] = f"Default ({claim.time_hh}:{claim.time_mm})"
                    claim._excel_logs.append(
                        f"  📊 time_of_survey: '{claim.time_hh}:{claim.time_mm}' (Source: Default Fallback)"
                    )
                    logger.info("  [TIME FALLBACK] Survey time not found in Excel, defaulted to %s:%s", claim.time_hh, claim.time_mm)

            if is_date:
                clean_date_val = re.sub(r"at.*$", "", str(value), flags=re.IGNORECASE).strip()
                value = _format_date(clean_date_val)

            if field_name == "initial_loss_amount":
                raw_initial_loss = value
                value = _initial_loss_75_percent(value)
                claim._excel_logs.append(
                    f"  📊 initial_loss_amount_75_percent: '{value}' "
                    f"(Source: 75% of Excel value '{raw_initial_loss}')"
                )
                logger.info(
                    "  [MATH] initial_loss_amount 75%% = %s (Excel value: %s)",
                    value,
                    raw_initial_loss,
                )

            if field_name.lower() in ("gst_summary_parts", "gst_summary_labour"):
                clean_num = re.sub(r"[^\d.]", "", str(value or "0")).strip()
                if clean_num:
                    try:
                        d_val = Decimal(clean_num)
                        if d_val == d_val.to_integral():
                            value = str(int(d_val))
                        else:
                            value = f"{d_val:.2f}"
                    except (InvalidOperation, ValueError):
                        pass

            target_attr = "gst_summary_parts" if field_name.lower() == "gst_summary_parts" else "gst_summary_labour" if field_name.lower() == "gst_summary_labour" else field_name
            setattr(claim, target_attr, value)
            found_count += 1
            logger.info(f"  [FOUND] {target_attr} = {value}")
        else:
            fallback = cfg.get("fallback_value")
            default_key_by_field = {
                "remarks": "remarks_default",
                "fir_number": "missing_text_default",
                "police_station_name": "missing_text_default",
                "charged_us_motor_vehicle_act": "missing_text_default",
                "charged_us_ipc": "missing_text_default",
                "account_type": "account_type",
                "party_payment_method": "payment_method",
                "driver_relationship_with_insured": "relationship_with_insured",
                "re_inspection_required": "reinspection_required",
                "is_gst_applicable": "gst_applicable",
                "payment_invoice_in_name_of_nia": "invoice_in_company_name",
            }
            default_key = default_key_by_field.get(field_name)
            if default_key and automation_defaults.get(default_key) not in (None, ""):
                fallback = automation_defaults.get(default_key)
            if fallback is not None:
                setattr(claim, field_name, fallback)
                logger.info(f"  [FALLBACK] {field_name} = {fallback}")
                claim._excel_logs.append(f"  📊 {field_name}: '{fallback}' (Source: Fallback Configuration)")
            else:
                labels_str = ' | '.join(labels)
                missing_fields.append(f"{field_name} (labels: '{labels_str}')")
                logger.warning(f"  [MISSING] {field_name}: labels '{labels_str}' not found or value empty")

    # ── Calculate Derived Business Logic ──────────────────────────────────────
    # Professional Fee calculation for UIIC: Survey Fee + Re-inspection Fee (Decimal monetary arithmetic).
    # Guard: For New India, OIC, and other portals where professional_fee is directly mapped from Excel,
    # never overwrite the extracted professional_fee with 0.
    should_derive_prof_fee = (
        portal_id == "uiic"
        or ("survey_fee" in mapping or "reinspection_fee" in mapping)
    ) and ("professional_fee" not in mapping or portal_id == "uiic")

    if should_derive_prof_fee:
        claim.professional_fee = _calculate_professional_fee(
            getattr(claim, "survey_fee", "0"),
            getattr(claim, "reinspection_fee", "0"),
        )
        if claim.professional_fee != "0" or getattr(claim, "survey_fee", "") or getattr(claim, "reinspection_fee", ""):
            claim._excel_coords["professional_fee"] = "Calculated (Survey Fee + Reinspection Fee)"
            claim._excel_logs.append(
                f"  📊 professional_fee: '{claim.professional_fee}' "
                f"(Source: Survey Fee '{claim.survey_fee or 0}' + Re-insp Fee '{claim.reinspection_fee or 0}')"
            )
            logger.info(
                "  [CALC] professional_fee = %s (survey_fee=%s, reinspection_fee=%s)",
                claim.professional_fee,
                claim.survey_fee,
                claim.reinspection_fee,
            )

    if portal_id == "newindia" and claim._excel_coords.get("photo_charges") != "Hardcoded":
        photo_charges_default = str(automation_defaults.get("photo_charges_default", "200") or "200")
        claim.photo_charges = photo_charges_default
        claim._excel_coords["photo_charges"] = "Hardcoded"
        claim._excel_logs.append(
            f"  [HARDCODED] photo_charges: '{photo_charges_default}' (Source: Automation Defaults)"
        )
        logger.info("  [HARDCODED] photo_charges = %s", photo_charges_default)

    claim.calculate_derived_fields()

    logger.info(f"Excel read complete: {found_count} fields found, "
                f"{len(missing_fields)} missing: {missing_fields}")

    # ── Payment Type Detection (keyword scan) ────────────────────────────────
    if not claim.payment_to or not claim.bank_payment_to:
        for sh in wb.all_sheets():
            sh_name = sh.name if hasattr(sh, 'name') else 'Sheet'
            for r_idx, row in enumerate(sh.rows()):
                for c_idx, cell in enumerate(row):
                    cell_text = " ".join(str(cell).strip().lower().split())
                    
                    if "payment to insured" in cell_text or "payment to reimbursement" in cell_text:
                        claim.payment_to = "INSURED"
                        claim.bank_payment_to = "Insured"
                        src = f"R{r_idx+1}C{c_idx+1} ({sh_name})"
                        claim._excel_coords["payment_to"] = src
                        claim._excel_coords["bank_payment_to"] = src
                        claim._excel_logs.append(f"  📊 payment_to / bank_payment_to: '{claim.payment_to}' / '{claim.bank_payment_to}' (Source: {src})")
                        logger.info(f"  [FOUND] payment_to = {claim.payment_to}, bank_payment_to = {claim.bank_payment_to} (keyword scan - payment to insured)")
                        break
                    elif "payment to repairer" in cell_text or "payment to dealer" in cell_text:
                        claim.payment_to = "REPAIRER"
                        claim.bank_payment_to = "Dealer"
                        src = f"R{r_idx+1}C{c_idx+1} ({sh_name})"
                        claim._excel_coords["payment_to"] = src
                        claim._excel_coords["bank_payment_to"] = src
                        claim._excel_logs.append(f"  📊 payment_to / bank_payment_to: '{claim.payment_to}' / '{claim.bank_payment_to}' (Source: {src})")
                        logger.info(f"  [FOUND] payment_to = {claim.payment_to}, bank_payment_to = {claim.bank_payment_to} (keyword scan - payment to repairer/dealer)")
                        break

                    if "favour" in cell_text and ("repairer" in cell_text or "insured" in cell_text or "dealer" in cell_text):
                        if "insured" in cell_text:
                            claim.payment_to = "INSURED"
                            claim.bank_payment_to = "Insured"
                        else:
                            claim.payment_to = "REPAIRER"
                            claim.bank_payment_to = "Dealer"
                        src = f"R{r_idx+1}C{c_idx+1} ({sh_name})"
                        claim._excel_coords["payment_to"] = src
                        claim._excel_coords["bank_payment_to"] = src
                        claim._excel_logs.append(f"  📊 payment_to / bank_payment_to: '{claim.payment_to}' / '{claim.bank_payment_to}' (Source: {src})")
                        logger.info(f"  [FOUND] payment_to = {claim.payment_to}, bank_payment_to = {claim.bank_payment_to} (keyword scan)")
                        break
                    if "favour" in cell_text:
                        for nc in range(c_idx + 1, min(c_idx + 5, len(row))):
                            next_text = " ".join(str(row[nc]).strip().lower().split())
                            if "repairer" in next_text or "dealer" in next_text:
                                claim.payment_to = "REPAIRER"
                                claim.bank_payment_to = "Dealer"
                                src = f"R{r_idx+1}C{nc+1} ({sh_name})"
                                claim._excel_coords["payment_to"] = src
                                claim._excel_coords["bank_payment_to"] = src
                                claim._excel_logs.append(f"  📊 payment_to / bank_payment_to: '{claim.payment_to}' / '{claim.bank_payment_to}' (Source: {src})")
                                break
                            elif "insured" in next_text:
                                claim.payment_to = "INSURED"
                                claim.bank_payment_to = "Insured"
                                src = f"R{r_idx+1}C{nc+1} ({sh_name})"
                                claim._excel_coords["payment_to"] = src
                                claim._excel_coords["bank_payment_to"] = src
                                claim._excel_logs.append(f"  📊 payment_to / bank_payment_to: '{claim.payment_to}' / '{claim.bank_payment_to}' (Source: {src})")
                                break
                        if claim.payment_to and claim.bank_payment_to: break
                if claim.payment_to and claim.bank_payment_to: break
            if claim.payment_to and claim.bank_payment_to: break

    # Fallback Defaults
    if not claim.bank_payment_to:
        claim.bank_payment_to = "Insured"
        claim._excel_logs.append(f"  📊 bank_payment_to: '{claim.bank_payment_to}' (Source: Default Fallback)")

    return claim
