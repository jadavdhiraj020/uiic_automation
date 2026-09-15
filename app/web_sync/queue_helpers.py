"""Pure queue identity helpers kept separate from the Qt page controller."""
from .client import ApiError
from .storage import portal_for


def dispatch_id(value):
    if not isinstance(value, dict):
        return ""
    job = value.get("job") if isinstance(value.get("job"), dict) else value
    return str(job.get("automation_dispatch_id") or value.get("automation_dispatch_id") or "").strip()


def is_stale_dispatch_error(error):
    return bool(
        isinstance(error, ApiError)
        and error.status == 409
        and str(getattr(error, "code", "")).strip().lower() == "stale_dispatch"
    )


def short_insurer_label(insurer, portal_id=None):
    if not insurer and not portal_id:
        return ""
    try:
        portal = portal_for(insurer, portal_id=portal_id)
        return {"uiic": "UIIC", "newindia": "New India", "oic": "OIC"}[portal]
    except (KeyError, ValueError):
        return str(insurer).strip() if insurer else ""
