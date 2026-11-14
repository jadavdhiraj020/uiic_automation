"""Resolve OIC licence type from the extracted vehicle class."""

import re


_MOTORCYCLE = "MOTOR CYCLE WITH GEAR"
_LIGHT_GOODS = "LIGHT MOTOR VEHICLE - GOODS"
_LIGHT_PASSENGER = "LIGHT MOTOR VEHICLE - PASSENGER"
_LIGHT_PRIVATE = "LIGHT MOTOR VEHICLE - NON TRANSPORT"


def resolve_license_type(vehicle_class: str, excel_license_type: str = "") -> tuple[str, str]:
    """Return the portal value and its source, or an ambiguous/missing reason.

    The class may contain extra descriptive text. Whole-word matching avoids
    treating words such as "cargo" or "carriage" as the vehicle class "car".
    """
    text = re.sub(r"[^a-z0-9]+", " ", str(vehicle_class or "").casefold()).strip()
    words = set(text.split())
    motorcycle = bool(re.search(r"\b(?:motor\s*cycle|m\s*cycle|scooter|(?:two|2)\s*wheel(?:er)?s?)\b", text))
    heavy_goods = "hgv" in words or ("heavy" in words and bool(words & {"goods", "good"}))
    heavy_passenger = "hpv" in words or ("heavy" in words and bool(words & {"passenger", "passanger"}))
    heavy_unspecified = "heavy" in words and not (heavy_goods or heavy_passenger) and bool(
        words & {"transport", "vehicle", "motor"}
    )
    light = bool(words & {"lmv", "lgv"}) or ("light" in words and bool(
        words & {"motor", "goods", "good", "passenger", "passanger"}
    ))
    light_goods = light and bool(words & {"lgv", "goods", "good"})
    light_passenger = light and bool(words & {"passenger", "passanger"})
    private = (light or bool(words & {"car", "jeep"})) and not (light_goods or light_passenger)

    choices = set()
    if motorcycle:
        choices.add(_MOTORCYCLE)
    if heavy_goods:
        choices.add("HGV")
    if heavy_passenger:
        choices.add("HPV")
    if light_goods:
        choices.add(_LIGHT_GOODS)
    if light_passenger:
        choices.add(_LIGHT_PASSENGER)
    if private:
        choices.add(_LIGHT_PRIVATE)

    if heavy_unspecified or len(choices) > 1:
        return "", "ambiguous"
    if choices:
        return choices.pop(), "class"

    # Preserve the existing Excel licence-type flow for an unmapped class.
    fallback = str(excel_license_type or "").strip()
    if fallback.casefold() == "lmv":
        return _LIGHT_PRIVATE, "excel"
    return (fallback, "excel") if fallback else ("", "missing")
