# app/portals/oic/automation/date_formatter.py
"""
date_formatter.py — OIC Portal Date Formatter Service.

Single responsibility: Convert *any* raw date string (from Excel, OCR, or
user input) to the strict DD-MM-YYYY format expected by all plain <input>
date fields on the OIC portal.

NOTE:
  - MUI DatePickers use format_date_for_mui() in ui_utils.py — DO NOT change.
  - This service is exclusively for plain Angular/PrimeNG text-input date
    fields (e.g., Date of Birth, DL Issue Date, Registration Date, etc.).
  - Returns "" on empty or unrecognisable input so callers can safely skip.

Usage:
    from app.portals.oic.automation.date_formatter import format_oic_date

    dob = format_oic_date(claim.dob_of_driver)   # → "15-01-1990"
"""

import re
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Month name → number map (handles English abbreviations & full names)
# ─────────────────────────────────────────────────────────────────────────────
_MONTH_MAP: dict[str, int] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4,
    "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
}

# Ordered list of strptime format strings to try (most-common first)
_KNOWN_FORMATS: tuple[str, ...] = (
    # ISO / Excel default
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    # Indian common formats
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d.%m.%Y",
    # Short year
    "%d-%m-%y",
    "%d/%m/%y",
    # US format (less common in Indian insurance docs, but possible)
    "%m/%d/%Y",
    # With timestamp
    "%d-%m-%Y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    # Verbose text months
    "%d-%b-%Y",   # 15-Jan-2024
    "%d %b %Y",   # 15 Jan 2024
    "%d %B %Y",   # 15 January 2024
    "%B %d, %Y",  # January 15, 2024
    "%b %d, %Y",  # Jan 15, 2024
)

# Guard: valid year range (avoids Excel serial-number false positives)
_MIN_YEAR = 1920
_MAX_YEAR = 2100


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def format_oic_date(raw_date) -> str:
    """
    Convert any date representation to OIC's required DD-MM-YYYY string.

    Args:
        raw_date: Any value — str, datetime, date, float (Excel serial), or None.

    Returns:
        "DD-MM-YYYY" string, or "" if the input cannot be parsed.
    """
    if raw_date is None:
        return ""

    # ── Handle Python datetime / date objects ─────────────────────────────────
    if isinstance(raw_date, datetime):
        return raw_date.strftime("%d-%m-%Y")

    # datetime.date (not datetime)
    try:
        from datetime import date as _date
        if isinstance(raw_date, _date):
            return raw_date.strftime("%d-%m-%Y")
    except Exception:
        pass

    # ── Handle Excel serial number floats (e.g. 44927.0 = 2023-01-01) ────────
    if isinstance(raw_date, (int, float)):
        result = _from_excel_serial(raw_date)
        if result:
            return result
        # If it's a plain integer that looks like DDMMYYYY or YYYYMMDD, handle below
        raw_date = str(int(raw_date))

    raw = str(raw_date).strip()

    if not raw or raw.lower() in {"", "na", "n/a", "nil", "none", "-", "--", "nat", "nan"}:
        return ""

    # ── Strip trailing timestamp (e.g. "2024-01-15 00:00:00") ────────────────
    raw_clean = raw.split(".")[0].strip()  # also strips microseconds

    # ── Try each known strptime format ────────────────────────────────────────
    for fmt in _KNOWN_FORMATS:
        try:
            dt = datetime.strptime(raw_clean, fmt)
            if _MIN_YEAR <= dt.year <= _MAX_YEAR:
                return dt.strftime("%d-%m-%Y")
        except ValueError:
            continue

    # ── Regex-based fallbacks ─────────────────────────────────────────────────

    # Pattern: DD-MM-YYYY or DD/MM/YYYY or DD.MM.YYYY (4-digit year, numeric)
    m = re.match(
        r'^(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?:\s.*)?$', raw_clean
    )
    if m:
        d, mon, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if _valid_date_parts(d, mon, y):
            return f"{d:02d}-{mon:02d}-{y}"

    # Pattern: YYYY-MM-DD or YYYY/MM/DD (4-digit year first, numeric)
    m = re.match(
        r'^(\d{4})[./-](\d{1,2})[./-](\d{1,2})(?:\s.*)?$', raw_clean
    )
    if m:
        y, mon, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if _valid_date_parts(d, mon, y):
            return f"{d:02d}-{mon:02d}-{y}"

    # Pattern: 2-digit year (e.g. 15-01-24 → 15-01-2024)
    m = re.match(
        r'^(\d{1,2})[./-](\d{1,2})[./-](\d{2})(?!\d)(?:\s.*)?$', raw_clean
    )
    if m:
        d, mon, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3))
        full_year = 2000 + y2 if y2 < 70 else 1900 + y2
        if _valid_date_parts(d, mon, full_year):
            return f"{d:02d}-{mon:02d}-{full_year}"

    # Pattern: text month mixed (e.g. "15 Jan 24", "1-JAN-2024")
    m = re.match(
        r'^(\d{1,2})[.\s/-]([A-Za-z]{3,9})[.\s/-](\d{2,4})$', raw_clean
    )
    if m:
        d_str, mon_str, y_str = m.group(1), m.group(2).lower(), m.group(3)
        mon = _MONTH_MAP.get(mon_str)
        if mon:
            d = int(d_str)
            y = int(y_str)
            if y < 100:
                y = 2000 + y if y < 70 else 1900 + y
            if _valid_date_parts(d, mon, y):
                return f"{d:02d}-{mon:02d}-{y}"

    # Pattern: compact YYYYMMDD (e.g. "20240115")
    m = re.match(r'^(\d{4})(\d{2})(\d{2})$', raw_clean)
    if m:
        y, mon, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if _valid_date_parts(d, mon, y):
            return f"{d:02d}-{mon:02d}-{y}"

    # Pattern: compact DDMMYYYY (e.g. "15012024")
    m = re.match(r'^(\d{2})(\d{2})(\d{4})$', raw_clean)
    if m:
        d, mon, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if _valid_date_parts(d, mon, y):
            return f"{d:02d}-{mon:02d}-{y}"

    # ── Last resort: log and return empty ─────────────────────────────────────
    logger.debug("[OIC DateFormatter] Could not parse '%s' → returning empty", raw)
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────────────────────────────────────

def _valid_date_parts(d: int, m: int, y: int) -> bool:
    """Return True if d/m/y form a plausible real date."""
    if not (_MIN_YEAR <= y <= _MAX_YEAR):
        return False
    if not (1 <= m <= 12):
        return False
    if not (1 <= d <= 31):
        return False
    try:
        datetime(y, m, d)
        return True
    except ValueError:
        return False


def _from_excel_serial(serial) -> Optional[str]:
    """
    Convert an Excel date serial number to DD-MM-YYYY.

    Excel stores dates as integer/float days since 1900-01-01 (with the
    famous Lotus 1-2-3 leap-year bug where day 60 = 29-Feb-1900, which
    never existed — we compensate for this).
    """
    try:
        n = int(float(serial))
        if n < 1 or n > 2958465:  # 1900-01-01 to 9999-12-31
            return None
        # Account for Excel's 1900 leap year bug (skip day 60)
        if n >= 60:
            n -= 1
        from datetime import date, timedelta
        dt = date(1899, 12, 31) + timedelta(days=n)
        if _MIN_YEAR <= dt.year <= _MAX_YEAR:
            return f"{dt.day:02d}-{dt.month:02d}-{dt.year}"
        return None
    except Exception:
        return None
