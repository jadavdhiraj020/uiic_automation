"""Values shared by New India field extraction, preview, and portal entry."""

import re
from decimal import Decimal
from pathlib import Path


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
