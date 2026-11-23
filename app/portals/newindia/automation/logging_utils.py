"""Plain-English error translation and automatic failure screenshots for New India."""

from __future__ import annotations

from typing import Optional

from app.automation.run_diagnostics import (
    capture_portal_screenshot,
    portal_operator_reason,
)


def newindia_operator_reason(
    raw_error: str,
    fallback: str = "Could not complete this step. Check Chrome.",
) -> str:
    """Convert raw Playwright/Python errors into clear plain-English reasons for New India."""
    return portal_operator_reason(raw_error, fallback, portal_name="New India")


async def capture_newindia_screenshot(
    page,
    step_name: str,
    log,
    *,
    reason: str = "",
    claim_no: str = "",
) -> Optional[str]:
    """Save a PNG screenshot of the live New India page and log it cleanly."""
    return await capture_portal_screenshot(
        page,
        "newindia",
        step_name,
        log,
        reason=reason,
        claim_no=claim_no,
    )
