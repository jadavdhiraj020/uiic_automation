"""Order remaining claim documents by their filename for PDF merging."""

import re
from pathlib import Path


# The first matching category wins when a filename describes multiple types.
_CATEGORIES = tuple(re.compile(pattern, re.I) for pattern in (
    r"\bsurvey\s+report\b|\bsurveyreport\b|\bfinal\s+survey\b",
    r"\bre\s*inspection\b|\breinspection\b",
    r"\b(?:surveyor?\s+)?fee\s+bill\b|\bsf\s*bill\b|\bsurvey\s+fee\b",
    r"\bestimate\b|\bestimation\b",
    r"\binvoice\b",
    r"\b(?:payment|paid)\s+receipt\b|^receipt$",
    r"\brc\b|\brcbook\b|\brcmerged\b|\bregistration\s+(?:certificate|card|book)\b",
    r"\bdl\b|\bdlmerged\b|\bdriving\s+licen[cs]e\b|\blicen[cs]e\b",
    r"\btax\b",
    r"\bfitness\b",
    r"\bpermit\b",
    r"\bclaim\s+form\b|\bclaimform\b",
    r"\bvoucher\b|\bdischargevoucher\b",
    r"\bcancel(?:led|ed)?\s+(?:cheque|check)\b",
    r"\bpan\b|\bpancard\b",
    r"\b(?:aadhaar|aadhar|adhar|adhaar|uidai)\b",
    r"\b(?:e\s*)?kyc\b|\bknow\s+your\s+customer\b",
))


def _order_key(path):
    name = Path(path).stem.casefold()
    label = re.sub(r"[^a-z0-9]+", " ", name).strip()
    # A re-inspection or fee bill can also say "survey report". Classify the
    # more specific document first, while retaining the requested output order.
    matching_order = (1, 2, 0, *range(3, len(_CATEGORIES)))
    rank = next((index for index in matching_order if _CATEGORIES[index].search(label)), len(_CATEGORIES))
    return rank, label, str(path).casefold()


def order_remaining_documents(paths):
    """Return the same files in the agreed category order, with stable ties."""
    return sorted(paths, key=_order_key)
