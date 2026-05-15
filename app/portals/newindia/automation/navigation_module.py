import asyncio
import logging
from typing import Callable, Optional

from app.automation.form_helpers import safe_click, safe_fill, safe_select
from app.automation.automation_logger import AutomationLogger, _ts

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
    log = print,
    stop_cb: Callable[[], bool] = lambda: False,
) -> Optional:
    """
    Navigate from the Dashboard to the Worklist, enter the claim number in the filter, and search.
    Returns the page object if successful, None otherwise.
    """
    if isinstance(log, AutomationLogger):
        log.info("Starting navigation to Worklist...")
        log.indent()
    else:
        log("🧭 Starting navigation to Worklist...")

    # 1. Click on the Worklist navbar link
    try:
        # Wait for the dashboard navbar to be ready
        await page.locator(SEL_NAV_WORKLIST).wait_for(state="visible", timeout=15000)
        if isinstance(log, AutomationLogger):
            log.info("Opening 'Worklist' section...")
        else:
            log("🖱️ Clicking 'Worklist' in navigation bar...")
        
        await safe_click(page, SEL_NAV_WORKLIST, log=log, label="Worklist Nav Button")
        
        # Wait for Worklist page to load (indicated by Filter dropdown)
        await page.locator(SEL_FILTER_DROPDOWN).wait_for(state="visible", timeout=15000)
        if isinstance(log, AutomationLogger):
            log.success("Worklist page loaded.")
        else:
            log("✅ Worklist page loaded successfully.")
    except Exception as exc:
        if isinstance(log, AutomationLogger):
            log.error(f"Navigation failure: {str(exc)[:100]}")
            log.outdent()
        else:
            log(f"❌ Failed to reach Worklist: {exc}")
        return None

    if stop_cb(): return None

    # 2. Select "Claim No." in the Filter Criteria dropdown
    if isinstance(log, AutomationLogger):
        log.info("Configuring search filter (Claim No.)...")
    else:
        log("⚙️ Selecting 'Claim No.' in filter criteria...")
        
    try:
        await safe_select(page, SEL_FILTER_DROPDOWN, "Claim No.", "Filter Criteria Dropdown", log=log)
        # Wait for the input field to appear via ng-if
        await page.locator(SEL_CLAIM_INPUT).wait_for(state="visible", timeout=5000)
    except Exception as exc:
        if isinstance(log, AutomationLogger):
            log.error(f"Filter configuration failure: {str(exc)[:100]}")
            log.outdent()
        else:
            log(f"❌ Failed to select filter criteria: {exc}")
        return None

    if stop_cb(): return None

    # 3. Enter the Claim Number (Dedicated Human-Typing for New India)
    if isinstance(log, AutomationLogger):
        log.info(f"Populating claim: '{claim_no}'")
    else:
        log(f"✍️ Entering claim number: '{claim_no}'")
    
    # CRITICAL: Prevent typing an empty string which triggers the Angular Alert
    if not claim_no or not claim_no.strip():
        if isinstance(log, AutomationLogger):
            log.error("CRITICAL: Claim number is empty!")
            log.outdent()
        else:
            log("❌ CRITICAL: Claim number is empty! Check Excel or folder name.")
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
        
        if isinstance(log, AutomationLogger):
            log.success(f"Claim populated.")
    except Exception as exc:
        if isinstance(log, AutomationLogger):
            log.error(f"Input failure: {str(exc)[:100]}")
            log.outdent()
        else:
            log(f"❌ Failed to enter claim number: {exc}")
        return None

    if stop_cb(): return None

    # 4. Click the Filter button
    if isinstance(log, AutomationLogger):
        log.info("Executing search...")
    else:
        log("🖱️ Clicking 'Filter' button...")
        
    try:
        await safe_click(page, SEL_FILTER_BTN, log=log, label="Filter Search Button")
        await asyncio.sleep(2)  # Wait for search results to populate
        if isinstance(log, AutomationLogger):
            log.success("Search executed.")
        else:
            log("✅ Claim search executed.")
    except Exception as exc:
        if isinstance(log, AutomationLogger):
            log.error(f"Search trigger failure: {str(exc)[:100]}")
            log.outdent()
        else:
            log(f"❌ Failed to click filter button: {exc}")
        return None

    # 5. Click the Edit icon
    if isinstance(log, AutomationLogger):
        log.info("Opening claim record...")
    else:
        log("🖱️ Clicking 'Edit' icon to open claim...")
        
    try:
        # Wait for the search result to render the edit button
        await page.locator(SEL_CLAIM_EDIT_BTN).first.wait_for(state="visible", timeout=10000)
        await safe_click(page, SEL_CLAIM_EDIT_BTN, log=log, label="Edit Claim Icon")
        await asyncio.sleep(3) # Wait for claim details modal or page to load
        if isinstance(log, AutomationLogger):
            log.success("Claim record accessed.")
        else:
            log("✅ Claim details opened.")
    except Exception as exc:
        if isinstance(log, AutomationLogger):
            log.error(f"Record access failure: {str(exc)[:100]}")
        else:
            log(f"❌ Failed to click edit icon: {exc}")
        return None
    finally:
        if isinstance(log, AutomationLogger):
            log.outdent()

    # Return the page so the engine knows navigation was successful
    return page
