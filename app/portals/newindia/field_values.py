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


VEHICLE_COLOR_MAX_LEN = 9


def configured_pre_accident_condition(defaults):
    """Get the condition used for New India review and portal entry."""
    return str(defaults.get("pre_accident_condition") or "").strip() or "always good"


def configured_quick_update_remarks(defaults):
    """Get the Remarks text shown in review and entered on Quick Update."""
    return str(defaults.get("remarks_default") or "").strip() or "Yes"


def normalize_vehicle_color(value):
    """Trim whitespace and cap New India Vehicle Color* to 9 characters."""
    if value is None:
        return ""
    return str(value).strip()[:VEHICLE_COLOR_MAX_LEN]


def normalize_driver_license_number(value):
    """Strip spaces and special characters from New India Driver Driving License Number."""
    if value is None:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", str(value)).upper()


def workshop_gst_registered(amount):
    parsed = parse_amount(amount)
    return "Yes" if parsed is not None and parsed > 0 else "No"


def reinspection_document(claim):
    path = getattr(getattr(claim, "_scan_result", None), "source_reinspection_path", None)
    return Path(path).name if path and Path(path).is_file() else ""


DEFAULT_TYPE_OF_BODY = "Saloon"

_TWO_WHEELER_RE = re.compile(
    r"\b(?:motor\s*cycles?|m\s*cycles?|scooters?|(?:two|2)\s*wheel(?:er)?s?|2w|mcwg|mcwog)\b"
)
_LMV_RE = re.compile(r"\b(?:lmv|l\s*m\s*v|light\s*motor\s*veh(?:icle)?s?)\b")
_CAR_CLASS_RE = re.compile(
    r"\b(?:private\s*cars?|pvt\s*cars?|motor\s*cars?|cars?|jeeps?|suvs?|lmv|l\s*m\s*v|light\s*motor\s*veh(?:icle)?s?)\b"
)
_GOODS_OR_TRANS_RE = re.compile(
    r"\b(?:hgv|lgv|heavy\s*goods?(?:\s*motor)?\s*veh(?:icle)?s?|goods?\s*carr(?:ier|ying)|"
    r"goods?\s*veh(?:icle)?s?|trucks?|trans|transport|gcv|(?:lmv|light|heavy)\s+goods?|goods?\s+(?:lmv|light|heavy))\b"
)
_HEAVY_PASSENGER_RE = re.compile(
    r"\b(?:hpv|heavy\s*pass[ae]nger(?:\s*motor)?\s*veh(?:icle)?s?|heavy\s*pass[ae]nger)\b"
)


def _normalize_vehicle_class_text(class_of_vehicle: str) -> tuple[str, str]:
    """Return normalized class text and a version with 'non transport' stripped."""
    text = re.sub(r"[^a-z0-9]+", " ", str(class_of_vehicle or "").casefold()).strip()
    cleaned_for_goods = re.sub(r"\bnon\s*transport\b", " ", text)
    return text, cleaned_for_goods


def resolve_newindia_vehicle_type(
    class_of_vehicle: str,
    registered_laden_weight: str = "",
    excel_type_of_vehicle: str = "",
) -> tuple[str, str]:
    """Resolve New India Type of Vehicle from Class of Vehicle, then Laden Weight fallback."""
    text, cleaned_for_goods = _normalize_vehicle_class_text(class_of_vehicle)
    if text:
        if _TWO_WHEELER_RE.search(text):
            return "Standard Two Wheeler", "Mapped from Class of Vehicle"
        has_goods = bool(_GOODS_OR_TRANS_RE.search(cleaned_for_goods))
        if _LMV_RE.search(text) and has_goods:
            return "Goods Carrying (A)", "Mapped from Class of Vehicle (LMV Goods/Transport)"
        if _CAR_CLASS_RE.search(text) and not has_goods:
            return "Private Car", "Mapped from Class of Vehicle"

    cleaned_wt = re.sub(r"(?i)\bkg\b|\bkilograms?\b|[\s,]", "", str(registered_laden_weight or "")).strip()
    match = re.search(r"\d+", cleaned_wt)
    if match:
        if int(match.group(0)) > 3000:
            return "Goods Carrying (A)", "Derived from Registered Laden Weight"
        return "Passenger Carrying (C)", "Derived from Registered Laden Weight"

    raw_excel = str(excel_type_of_vehicle or "").strip()
    return (raw_excel, "") if raw_excel else ("", "")


def resolve_newindia_license_type(class_of_vehicle: str, excel_license_type: str = "") -> tuple[str, str]:
    """Resolve New India License Type of Driver from Class of Vehicle, with Excel fallback."""
    text, cleaned_for_goods = _normalize_vehicle_class_text(class_of_vehicle)
    if text:
        if _HEAVY_PASSENGER_RE.search(text):
            return "Heavy Passenger Motor vehicle", "Mapped from Class of Vehicle"
        if _GOODS_OR_TRANS_RE.search(cleaned_for_goods):
            return "Heavy Goods vehicle", "Mapped from Class of Vehicle"
        if _TWO_WHEELER_RE.search(text):
            return "Motor Cycle with Gear", "Mapped from Class of Vehicle"
        if _CAR_CLASS_RE.search(text):
            return "Light Motor Vehicle", "Mapped from Class of Vehicle"

    raw_excel = str(excel_license_type or "").strip()
    return (raw_excel, "") if raw_excel else ("", "")

