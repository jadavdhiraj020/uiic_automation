"""
claim_assessment_module.py — Stub module for Oriental Insurance (OIC) claim assessment.
Logs details and returns success to proceed end-to-end cleanly.
"""

import asyncio
import logging
import random
from typing import Callable

from playwright.async_api import Page

from app.automation.automation_logger import AutomationLogger, _ts

logger = logging.getLogger(__name__)

async def fill_claim_assessment_details(
    page: Page,
    claim,
    log,
    stop_cb: Callable[[], bool] = lambda: False,
    field_delay_ms: int = 250,
) -> bool:
    """Simulates OIC Claim Assessment details form filling and calculations."""
    msg = f"Initializing OIC Claim Assessment details for claim {claim.claim_no}..."
    if isinstance(log, AutomationLogger):
        log.info(msg)
        log.indent()
    else:
        log(f"[{_ts()}]   ℹ️ {msg}")

    log_info = lambda m: log.info(m) if isinstance(log, AutomationLogger) else log(f"[{_ts()}]   ℹ️ {m}")
    log_warning = lambda m: log.warning(m) if isinstance(log, AutomationLogger) else log(f"[{_ts()}]   ⚠️ {m}")
    log_success = lambda m: log.success(m) if isinstance(log, AutomationLogger) else log(f"[{_ts()}]   ✅ {m}")

    log_info("💰 [Assessment] Fills Oriental Insurance claim assessment form fields...")
    await asyncio.sleep(0.5)

    if stop_cb():
        log_warning("⛔ [Assessment] Stop requested during OIC claim assessment filling.")
        if isinstance(log, AutomationLogger): log.outdent()
        return False

    # Simulate scrolling into the form view
    log_info("🖱️ [Scroll] Scrolling smoothly to Claim Details section...")
    await asyncio.sleep(random.uniform(0.25, 0.4))

    # 1. Fill parts age depreciation details
    log_info("🔽 [Dropdown] Selecting parts category from age depreciation list...")
    await asyncio.sleep(random.uniform(0.3, 0.6))
    
    log_info("⌨️ [Typing] Entering depreciation rate for glass, rubber, and plastic parts...")
    await asyncio.sleep(random.uniform(0.4, 0.75))
    
    if stop_cb():
        if isinstance(log, AutomationLogger): log.outdent()
        return False

    # 2. Fill labor fees
    log_info("⌨️ [Typing] Entering labor/repair fees smoothly...")
    await asyncio.sleep(random.uniform(0.35, 0.65))

    # 3. Fill towing charges
    log_info("⌨️ [Typing] Entering towing charges slowly...")
    await asyncio.sleep(random.uniform(0.25, 0.55))

    if stop_cb():
        if isinstance(log, AutomationLogger): log.outdent()
        return False

    # 4. Trigger calculations/Save
    log_info("🖱️ [Clicking] Clicking 'Calculate Assessment' button to update parts summary...")
    await asyncio.sleep(random.uniform(0.45, 0.8))

    log_info("🌐 [Navigation] Waiting for assessment sheet table settlement...")
    await asyncio.sleep(random.uniform(0.5, 0.75))

    if stop_cb():
        if isinstance(log, AutomationLogger): log.outdent()
        return False

    success_msg = "Claim assessment details processed successfully."
    log_success(success_msg)
    if isinstance(log, AutomationLogger):
        log.outdent()

    return True