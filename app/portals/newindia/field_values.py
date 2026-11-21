"""Values shared by New India field extraction, preview, and portal entry."""

import re
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path


_SURVEY_TIME_PATTERN = (
    r"(?P<hour>\d{1,2})"
    r"(?:(?::(?P<minute>\d{1,2})|\.(?P<dot_minute>\d{2}|0)|[ \t]+(?P<space_minute>\d{2}))"
    r"(?::(?P<second>\d{1,2})(?:\.\d+)?)?)?"
    r"(?:\s*(?P<period>[ap]\.?m\.?))?"
)
_EMBEDDED_SURVEY_TIME = re.compile(rf"(?<![\d:./-]){_SURVEY_TIME_PATTERN}(?![\w:./-])", re.I)
_DATED_SURVEY_TIME = re.compile(
    r"(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4})"
    r"(?:T|\s+(?:at\s+)?)(?P<time>.+)", re.I,
)


def parse_survey_time(value, *, embedded=False):
    """Read a New India survey time as HH:MM:SS, filling omitted parts with zero."""
    if isinstance(value, datetime):
        return value.time().isoformat(timespec="seconds")
    if isinstance(value, time):
        return value.isoformat(timespec="seconds")

    text = "" if value is None else str(value).strip()
    if re.search(r"\b(?:GMT|UTC)\b|standard time", text, re.I):
        return None
    if dated := _DATED_SURVEY_TIME.fullmatch(text):
        text = dated["time"].strip()
        embedded = False
    if embedded:
        matches = _EMBEDDED_SURVEY_TIME.finditer(text)
    else:
        matches = (re.fullmatch(_SURVEY_TIME_PATTERN, text, re.I),)
    for match in matches:
        if not match:
            continue
        hour = int(match["hour"])
        minutes = match["minute"] or match["dot_minute"] or match["space_minute"]
        period = match["period"]
        if embedded and minutes is None and period is None:
            continue
        if period:
            if not 1 <= hour <= 12:
                continue
            hour = hour % 12 + (12 if period[0].lower() == "p" else 0)
        try:
            return time(hour, int(minutes or 0), int(match["second"] or 0)).isoformat(timespec="seconds")
        except ValueError:
            continue
    return None


def parse_amount(value):
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        number = Decimal(str(value))
        return number if number.is_finite() else None
    text = re.sub(r"^(?:₹|INR\s*|Rs\.?\s*)", "", str(value or "").strip(), flags=re.I)
    if re.fullmatch(r"[+-]?(?:\d+(?:,\d+)*(?:\.\d+)?|\.\d+)", text.strip()):
        return Decimal(text.replace(",", "").strip())
    return None


def workshop_gst_registered(amount):
    parsed = parse_amount(amount)
    return "Yes" if parsed is not None and parsed > 0 else "No"


def reinspection_document(claim):
    path = getattr(getattr(claim, "_scan_result", None), "source_reinspection_path", None)
    return Path(path).name if path and Path(path).is_file() else ""
