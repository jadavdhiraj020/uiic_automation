"""
navigation_module.py
Phase 2 implementation of New India Assurance (NIA) portal navigation.

Handles post-login navigation to the Worklist, searching for the specific claim,
and opening the claim details page.
"""

import asyncio
import logging
from typing import Callable, Optional

from app.automation.form_helpers import safe_click, safe_fill, safe_select

logger = logging.getLogger(__name__)

# --- Selectors ---
SEL_NAV_WORKLIST = "li#navlink-worklist a"
SEL_FILTER_DROPDOWN = "select#searchType"
SEL_CLAIM_INPUT = "input#filterWorklistClaimNo"
SEL_FILTER_BTN = "button[data-ng-click*='filterClaims']"
# The claim row edit button based on the provided HTML
SEL_CLAIM_EDIT_BTN = "a.mdlFire[data-ng-click*='nonMarutiClaimCheck'] svg.icon-tabler-edit"


async def navigate_to_claim(
    page,
    claim_no: str,
    settings: dict,
    log_cb: Callable[[str], None] = print,
    stop_cb: Callable[[], bool] = lambda: False,
) -> Optional:
    """
    Navigate from the Dashboard to the Worklist, enter the claim number in the filter, and search.
    Returns the page object if successful, None otherwise.
    """
    log_cb("  🧭 Starting navigation to Worklist...")

    # 1. Click on the Worklist navbar link
    try:
        # Wait for the dashboard navbar to be ready
        await page.locator(SEL_NAV_WORKLIST).wait_for(state="visible", timeout=15000)
        log_cb("  🖱️ Clicking 'Worklist' in navigation bar...")
        await safe_click(page, SEL_NAV_WORKLIST, log_cb=log_cb, label="Worklist Nav Button")
        
        # Wait for Worklist page to load (indicated by Filter dropdown)
        await page.locator(SEL_FILTER_DROPDOWN).wait_for(state="visible", timeout=15000)
        log_cb("  ✅ Worklist page loaded successfully.")
    except Exception as exc:
        log_cb(f"  ❌ Failed to reach Worklist: {exc}")
        return None

    if stop_cb():
        return None

    # 2. Select "Claim No." in the Filter Criteria dropdown
    log_cb("  ⚙️ Selecting 'Claim No.' in filter criteria...")
    try:
        await safe_select(page, SEL_FILTER_DROPDOWN, "Claim No.", "Filter Criteria Dropdown", log_cb=log_cb)
        # Wait for the input field to appear via ng-if
        await page.locator(SEL_CLAIM_INPUT).wait_for(state="visible", timeout=5000)
    except Exception as exc:
        log_cb(f"  ❌ Failed to select filter criteria: {exc}")
        return None

    if stop_cb():
        return None

    # 3. Enter the Claim Number (Dedicated Human-Typing for New India)
    log_cb(f"  ✍️ Entering claim number: '{claim_no}'")
    
    # CRITICAL: Prevent typing an empty string which triggers the Angular Alert
    if not claim_no or not claim_no.strip():
        log_cb("  ❌ CRITICAL: Claim number is completely empty! Please check your Excel file or folder name.")
        return None

    try:
        await asyncio.sleep(1) # Wait for Angular ng-if/ng-model to fully settle
        
        claim_input = page.locator(SEL_CLAIM_INPUT).first
        await claim_input.wait_for(state="visible", timeout=5000)
        
        # 1. Click to ensure focus
        await claim_input.click()
        await asyncio.sleep(0.2)
        
        # 2. Clear field safely using JS to avoid Playwright click-interception issues
        await claim_input.evaluate("node => node.value = ''")
        await asyncio.sleep(0.2)
        
        # 3. Slowly type like a human
        await claim_input.press_sequentially(claim_no, delay=150)
        
        # 4. Force Angular to register the keystrokes
        await claim_input.evaluate("node => { node.dispatchEvent(new Event('input', {bubbles: true})); node.dispatchEvent(new Event('change', {bubbles: true})); }")
        await asyncio.sleep(0.5)
        
        log_cb(f"  ✅ [Filled] Claim Number Input : '{claim_no}'")
    except Exception as exc:
        log_cb(f"  ❌ Failed to enter claim number: {exc}")
        return None

    if stop_cb():
        return None

    # 4. Click the Filter button
    log_cb("  🖱️ Clicking 'Filter' button...")
    try:
        await safe_click(page, SEL_FILTER_BTN, log_cb=log_cb, label="Filter Search Button")
        await asyncio.sleep(2)  # Wait for search results to populate
        log_cb("  ✅ Claim search executed.")
    except Exception as exc:
        log_cb(f"  ❌ Failed to click filter button: {exc}")
        return None

    # 5. Click the Edit icon
    log_cb("  🖱️ Clicking 'Edit' icon to proceed to claim...")
    try:
        # Wait for the search result to render the edit button
        await page.locator(SEL_CLAIM_EDIT_BTN).first.wait_for(state="visible", timeout=10000)
        await safe_click(page, SEL_CLAIM_EDIT_BTN, log_cb=log_cb, label="Edit Claim Icon")
        await asyncio.sleep(3) # Wait for claim details modal or page to load
        log_cb("  ✅ Claim details opened.")
    except Exception as exc:
        log_cb(f"  ❌ Failed to click edit icon: {exc}")
        return None

    # Return the page so the engine knows navigation was successful
    return page
