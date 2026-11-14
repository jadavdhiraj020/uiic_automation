"""Find the OIC district associated with a driver's licence prefix."""

import json
import re
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _licence_cities() -> dict[str, str]:
    path = Path(__file__).parent / "config" / "licence_city_codes.json"
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)["codes"]


def city_from_licence(licence_number: str) -> str:
    """Return the district for a known two-letter, two-digit licence prefix."""
    # A directly attached letter can be part of a three-character area code;
    # the first four characters alone do not identify those offices reliably.
    match = re.match(r"^\s*([A-Za-z]{2})[\s/\-]*(\d{2})(?![A-Za-z])", str(licence_number or ""))
    if not match:
        return ""
    code = match.group(1).upper() + match.group(2)
    return _licence_cities().get(code, "")
