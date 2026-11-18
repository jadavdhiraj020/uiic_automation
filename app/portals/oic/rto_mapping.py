"""Match an Excel RTO name to the names offered by the OIC portal."""

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable, NamedTuple

from app.portals.oic.city_mapping import _licence_cities


# These words describe an authority, rather than identifying its location.
_GENERIC_WORDS = frozenset({
    "and", "authority", "department", "dept", "for", "government", "govt",
    "gnct", "india", "licensing", "motor", "national", "nct", "of", "office",
    "regional", "registering", "registration", "road", "rto", "state", "the",
    "transport", "vehicle", "vehicles",
})


def _words(value: str) -> list[str]:
    return re.findall(r"[^\W_]+", str(value or "").casefold(), flags=re.UNICODE)


@lru_cache(maxsize=1)
def portal_rto_options() -> tuple[str, ...]:
    """Return the static snapshot captured from the portal RTO dropdown."""
    path = Path(__file__).parent / "config" / "rto_options.json"
    with path.open(encoding="utf-8") as stream:
        return tuple(json.load(stream)["options"])


def match_rto_name(value: str, options: Iterable[str] | None = None) -> str:
    """Prefer an exact office name, then the strongest location-word match.

    A location word must match as a whole word; generic authority words alone
    cannot select an unrelated office. Ties retain the portal's option order.
    """
    raw_words = _words(value)
    query = {word for word in raw_words if len(word) >= 3 and word not in _GENERIC_WORDS}
    if not query:
        return ""

    best_name = ""
    best_score = None
    for name in portal_rto_options() if options is None else options:
        option_words = _words(name)
        location = {word for word in option_words if len(word) >= 3 and word not in _GENERIC_WORDS}
        shared = query & location
        if not shared:
            continue
        score = (
            raw_words == option_words,
            bool(location) and location <= query,
            sum(len(word) for word in shared),
            len(shared),
            -len(location - query),
        )
        if best_score is None or score > best_score:
            best_name, best_score = name, score
    return best_name


_DIRECTION_WORDS = frozenset({"north", "south", "east", "west", "central", "new", "old", "city", "district", "zone", "rla", "sta"})
_PLACEHOLDERS = frozenset({"select", "select rto", "select an rto", "choose", "choose rto", "loading", "loading...", "fetching...", "no results found", "no records found", "--", "-"})


class RtoChoice(NamedTuple):
    name: str
    source: str
    registration_code: str
    mapped_location: str
    possible_mismatch: bool


def _distinctive_words(value: str) -> set[str]:
    return {word for word in _words(value)
            if len(word) >= 3 and word not in _GENERIC_WORDS and word not in _DIRECTION_WORDS}


def _is_real_option(value: str) -> bool:
    text = " ".join(str(value or "").split()).casefold()
    if not text or text in _PLACEHOLDERS:
        return False
    return not re.match(r"^(?:(?:please\s+)?(?:select|choose)|loading|fetching|no\s+(?:results|records|options|matches|data))\b", text)


def registration_rto_code(registration_number: str) -> str:
    """Extract a two-letter state and one- or two-digit office prefix."""
    compact = re.sub(r"[\s./-]+", "", str(registration_number or "")).upper()
    match = re.match(r"^([A-Z]{2})(\d{1,2})(?=[A-Z]|$)", compact)
    return match.group(1) + match.group(2).zfill(2) if match else ""


def resolve_rto_choice(registration_number: str, excel_rto: str, options: Iterable[str] | None = None) -> RtoChoice:
    """Prefer the registration code, then the mapped Excel RTO, then first option."""
    names = [str(name).strip() for name in (portal_rto_options() if options is None else options)
             if _is_real_option(name)]
    code = registration_rto_code(registration_number)
    location = _licence_cities().get(code, "") if code else ""

    # The existing directory contains broad entries such as DL01=NORTH.
    # Never use those as a location match: NORTH PAROOR is not North Delhi.
    name = ""
    source = ""
    if location and _distinctive_words(location):
        name = next((item for item in names if _words(item) == _words(location)), "")
        if name:
            source = "registration code"

    if not name and excel_rto:
        candidate = match_rto_name(excel_rto, names)
        # Shared generic words such as CENTRAL must not match Bengaluru to
        # Madurai Central. A specific place word must occur in both values.
        if candidate and _distinctive_words(excel_rto) & _distinctive_words(candidate):
            name, source = candidate, "Excel RTO name"

    if not name and names:
        name, source = names[0], "first available option"

    excel_words = _distinctive_words(excel_rto)
    location_words = _distinctive_words(location)
    mismatch = bool(location_words and excel_words and not (excel_words & location_words))
    directions = {"north", "south", "east", "west", "central"}
    mapped_directions = set(_words(location)) & directions
    selected_directions = set(_words(name)) & directions
    if mapped_directions and selected_directions and mapped_directions.isdisjoint(selected_directions):
        mismatch = True
    return RtoChoice(name, source, code, location, mismatch)
