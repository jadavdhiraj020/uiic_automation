"""Match an Excel RTO name to the names offered by the OIC portal."""

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable


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
