"""Resolve vehicle registration codes and report RTO names against OIC options."""

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

_STATE_CODE_ALIASES = {"DN": "DD", "OR": "OD", "TS": "TG", "UA": "UK"}

# Office labels that differ from the district labels used in Driver Details.
# Punjab offices: Punjab Transport Department RFP final.pdf, Annexure A, and
# the NIC Sarathi Punjab office directory (28 September 2021).
_REGISTRATION_OFFICES = {
    "PB01": ("STA Punjab", "Punjab STA", "State Transport Authority Punjab"),
    "PB12": ("Ropar", "Rupnagar"),
    "PB18": ("Batala",),
    "PB26": ("Khanna",),
    "PB34": ("Nabha",),
    "PB36": ("Phagwara",),
    "PB39": ("Rajpura",),
    "PB65": ("SASNAGAR", "S.A.S. Nagar", "Mohali"),
    "PB74": ("Nangal",),
    "PB93": ("Lopoke",),
    "PB94": ("Adampur",),
    "PB99": ("Dinanagar",),
    "DL01": ("North Delhi",),
    "DL06": ("Central Delhi",),
    "DL07": ("East Delhi",),
    "AN01": ("Port Blair", "Sri Vijaya Puram", "South Andaman"),
}

# Additional OIC labels with known geography, including names used before
# district or state renames. Used only for validating a same-state fallback.
_STATE_OFFICE_ALIASES = {
    "AN": ("Port Blair", "Sri Vijaya Puram", "South Andaman", "Nicobar"),
    "CH": ("Chandigarh",),
    "DD": ("Dadra & Nagar Haveli", "Silvassa", "Daman", "Diu"),
    "DL": ("Delhi", "North Delhi", "South Delhi", "East Delhi", "West Delhi",
           "Central Delhi", "New Delhi", "Dwarka, Delhi", "Sarai Kale Khan, Delhi"),
    "GA": ("Panaji", "Goa"),
    "GJ": ("Gandhinagar", "Surendranagar", "Ahmedabad"),
    "KA": ("Bangalore", "Bengaluru", "Gulbarga", "Kalaburagi"),
    "LD": ("Kavaratti", "Lakshadweep"),
    "OD": ("Cuttack", "Bhubaneswar", "Balasore", "Odisha", "Orissa"),
    "PB": ("Punjab", "Mohali", "SASNAGAR", "Ropar", "Bathinda", "Bhatinda"),
    "PY": ("Puducherry", "Pondicherry"),
    "SK": ("North Sikkim", "South Sikkim", "East Sikkim", "West Sikkim", "Sikkim"),
    "TG": ("Hyderabad", "Karimnagar", "Telangana"),
}

_OFFICE_CODE_TOKEN = re.compile(r"(?<![A-Z0-9])([A-Z]{2})[ ./-]*(\d{1,2})(?![A-Z0-9])", re.I)


class RtoChoice(NamedTuple):
    name: str
    source: str
    registration_code: str
    mapped_location: str
    possible_mismatch: bool
    state_code: str


def _distinctive_words(value: str) -> set[str]:
    return {word for word in _words(value)
            if len(word) >= 3 and word not in _GENERIC_WORDS and word not in _DIRECTION_WORDS}


def _is_real_option(value: str) -> bool:
    text = " ".join(str(value or "").split()).casefold()
    if not text or text in _PLACEHOLDERS:
        return False
    return not re.match(r"^(?:(?:please\s+)?(?:select|choose)|loading|fetching|no\s+(?:results|records|options|matches|data))\b", text)


def registration_rto_code(registration_number: str) -> str:
    """Recognize a bare code, a registration with a letter series, or a legacy number."""
    compact = re.sub(r"[\s./-]+", "", str(registration_number or "")).upper()
    match = re.fullmatch(r"([A-Z]{2})(\d{1,2})(?:[A-Z]{1,3}\d{0,4})?", compact)
    if not match:
        match = re.fullmatch(r"([A-Z]{2})(\d{2})\d{4}", compact)
    return match.group(1) + match.group(2).zfill(2) if match else ""


def _state_code(code: str) -> str:
    return _STATE_CODE_ALIASES.get(code[:2], code[:2])


def _canonical_office_code(code: str) -> str:
    return _state_code(code) + code[2:]


def _office_key(name: str) -> tuple[str, ...]:
    return tuple(word for word in _words(name) if word not in _GENERIC_WORDS)


@lru_cache(maxsize=1)
def _office_states() -> dict[tuple[str, ...], set[str]]:
    states: dict[tuple[str, ...], set[str]] = {}
    for code, district in _licence_cities().items():
        if _distinctive_words(district):
            states.setdefault(_office_key(district), set()).add(_state_code(code))
    for code, offices in _REGISTRATION_OFFICES.items():
        for office in offices:
            states.setdefault(_office_key(office), set()).add(_state_code(code))
    for state, aliases in _STATE_OFFICE_ALIASES.items():
        for office in aliases:
            states.setdefault(_office_key(office), set()).add(state)
    return states


def _option_state(name: str) -> str:
    codes = {_state_code(match.group(1).upper()) for match in _OFFICE_CODE_TOKEN.finditer(name)}
    states = codes or _office_states().get(_office_key(name), set())
    return next(iter(states)) if len(states) == 1 else ""


def _match_office_labels(labels: Iterable[str], names: list[str], *, district=False) -> str:
    key_for_name = _office_key if district else lambda name: tuple(_words(name))
    by_key = {}
    for name in names:
        by_key.setdefault(key_for_name(name), name)
    return next((by_key[key] for label in labels if (key := key_for_name(label)) in by_key), "")


def resolve_rto_choice(registration_number: str, excel_rto: str, options: Iterable[str] | None = None) -> RtoChoice:
    """Prefer a coded office or report name, then a confirmed same-state option."""
    names = [str(name).strip() for name in (portal_rto_options() if options is None else options)
             if _is_real_option(name)]
    report_code = registration_rto_code(excel_rto)
    registration_code = registration_rto_code(registration_number)
    code = registration_code or report_code
    canonical_code = _canonical_office_code(code)
    state = _state_code(code)
    districts = _licence_cities()
    district = districts.get(code) or districts.get(canonical_code, "")
    offices = _REGISTRATION_OFFICES.get(canonical_code, ())
    location = (offices or (district,))[0]
    compatible_names = [name for name in names if not state or _option_state(name) in ("", state)]
    same_state = [name for name in compatible_names if state and _option_state(name) == state]

    coded_option = next((name for name in names if code and any(
        _canonical_office_code(registration_rto_code(match.group())) == canonical_code
        for match in _OFFICE_CODE_TOKEN.finditer(name)
    )), "")
    exact_office = coded_option or _match_office_labels(offices, compatible_names)
    district_option = (
        _match_office_labels((district,), compatible_names, district=True) if _distinctive_words(district) else ""
    )
    name = exact_office or (district_option if not offices else "")
    source = ("registration code" if registration_code else "report RTO code") if name else ""

    if not name and excel_rto and not report_code:
        candidate = match_rto_name(excel_rto, compatible_names)
        if candidate and _distinctive_words(excel_rto) & _distinctive_words(candidate):
            name, source = candidate, "Excel RTO name"

    if not name and district_option:
        name, source = district_option, "district fallback"
    if not name and same_state:
        name, source = same_state[0], "same-state fallback"

    report_words = _distinctive_words(excel_rto) if not report_code else set()
    place_words = _distinctive_words(" ".join((*offices, district)))
    report_state = _option_state(excel_rto)
    mismatch = bool(registration_code and report_code and canonical_code != _canonical_office_code(report_code))
    if registration_code and state and report_state and state != report_state:
        mismatch = True
    if place_words and report_words and place_words.isdisjoint(report_words):
        mismatch = True
    directions = {"north", "south", "east", "west", "central"}
    mapped_directions = set(_words(location)) & directions
    selected_directions = set(_words(name)) & directions
    if mapped_directions and selected_directions and mapped_directions.isdisjoint(selected_directions):
        mismatch = True
    return RtoChoice(name, source, code, location, mismatch, state)
