"""
navigation_module.py
After login, navigates to Worklist, selects claim type, filters by claim
number, and clicks the Action ("Click Here") button for the matching row.

Portal page structure (AngularJS app at #/Worklist):
  ┌──────────────────────────────────────────────┐
  │ Filter Criteria                              │
  │   Claim No:  [__________]                    │
  │   [Filter]  [Reset]                          │
  │   Claim Type:  [ Non Maruti ▾ ]              │
  ├──────────────────────────────────────────────┤
  │ Search Result                                │
  │ S.No | Claim No. | … | Action               │
  │  1   | 12345     | … | [Click Here]          │
  └──────────────────────────────────────────────┘

Key fix: the old code never typed the claim number into the filter
input and never clicked the Filter button — it just tried to scan
an empty table that showed "No Records Found".
"""
import asyncio
import logging
from typing import Callable

logger = logging.getLogger(__name__)

# Known working URL from live portal observation
WORKLIST_URL = "https://portal.uiic.in/surveyor/data/Surveyor.html?v=62486#/Worklist"

# ── Selectors ─────────────────────────────────────────────────────────────────
# Worklist sidebar link
SEL_WORKLIST_MENU = (
    "a:has-text('Worklist'), "
    "li a[href*='Worklist'], "
    "li:has-text('Worklist') a, "
    ".sidebar a:has-text('Worklist'), "
    "ul.nav a:has-text('Worklist')"
)

# Claim No filter input
SEL_CLAIM_NO_INPUT = (
    "input[ng-model*='claimNo'], "
    "input[ng-model*='ClaimNo'], "
    "input[ng-model*='claim_no'], "
    "input[placeholder*='Claim No'], "
    "input[placeholder*='Claim no'], "
    "input[placeholder*='claim no']"
)

# Filter & Reset buttons
SEL_FILTER_BTN = (
    "button:has-text('Filter'), "
    "input[value='Filter'], "
    "a:has-text('Filter'), "
    "button.btn-primary:has-text('Filter')"
)
SEL_RESET_BTN = (
    "button:has-text('Reset'), "
    "input[value='Reset'], "
    "a:has-text('Reset')"
)

# Claim Type dropdown
SEL_CLAIM_TYPE_DD = (
    "select[ng-model*='claimType'], "
    "select[ng-model*='ClaimType'], "
    "select[ng-model*='claim_type'], "
    "#claimType"
)

# Search result table
SEL_RESULT_TABLE = "table tbody tr"
SEL_ACTION_BTN = (
    "button:has-text('Click Here'), "
    "a:has-text('Click Here'), "
    "td button:has-text('Click'), "
    "td a:has-text('Click')"
)
SEL_PAGE_NEXT = (
    "a:has-text('Next'), "
    "li.next:not(.disabled) a, "
    ".pagination .next a"
)
SEL_NO_RECORDS = "td:has-text('No Records Found'), td:has-text('No Record Found'), td:has-text('No records')"


async def _click_first_visible(page, selector_str: str, timeout: int = 4000) -> bool:
    """Try each comma-separated selector; click the first visible one."""
    for sel in selector_str.split(", "):
        try:
            el = page.locator(sel.strip()).first
            await el.wait_for(state="visible", timeout=timeout)
            await el.click()
            return True
        except Exception:
            continue
    return False


async def _fill_first_visible(page, selector_str: str, value: str, timeout: int = 4000) -> bool:
    """Try each comma-separated selector; fill the first visible one."""
    for sel in selector_str.split(", "):
        try:
            el = page.locator(sel.strip()).first
            await el.wait_for(state="visible", timeout=timeout)
            await el.fill("")
            await asyncio.sleep(0.2)
            await el.fill(value)
            return True
        except Exception:
            continue
    return False


async def _select_first_visible(page, selector_str: str, label: str, timeout: int = 4000) -> bool:
    """Try each comma-separated selector; select option by label in the first visible one."""
    for sel in selector_str.split(", "):
        try:
            el = page.locator(sel.strip()).first
            await el.wait_for(state="visible", timeout=timeout)
            try:
                await el.select_option(label=label)
            except Exception:
                await el.select_option(value=label)
            return True
        except Exception:
            continue
    return False


# ── Main entry point ──────────────────────────────────────────────────────────

async def navigate_to_claim(
    page,
    claim_no: str,
    claim_type: str = "Non Maruti",
    log_cb: Callable[[str], None] = print,
) -> bool:
    """
    Navigate to Worklist → select claim type → filter by claim no → click Action.
    Returns True if claim found and clicked.
    """
    log_cb(f"📌 Current URL: {page.url}")

    # ── Step 1: Navigate to Worklist ──────────────────────────────────────────
    worklist_reached = False

    # Strategy A: Click sidebar Worklist link
    try:
        for sel in SEL_WORKLIST_MENU.split(", "):
            try:
                link = page.locator(sel.strip()).first
                if await link.is_visible(timeout=3000):
                    await link.click()
                    await asyncio.sleep(2)
                    log_cb("📋 Clicked Worklist sidebar link.")
                    worklist_reached = True
                    break
            except Exception:
                continue
    except Exception as e:
        log_cb(f"⚠️  Sidebar click failed: {e.__class__.__name__}")

    # Strategy B: Direct URL navigation
    if not worklist_reached or "Worklist" not in page.url:
        log_cb("🔗 Navigating directly to Worklist URL...")
        await page.goto(WORKLIST_URL, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(3)
        log_cb(f"📌 URL after navigation: {page.url}")

    await page.wait_for_load_state("domcontentloaded", timeout=10000)
    await asyncio.sleep(2)

    # ── Step 2: Select Claim Type to "Non Maruti" ─────────────────────────────
    log_cb(f"📌 Selecting Claim Type: {claim_type}")
    if await _select_first_visible(page, SEL_CLAIM_TYPE_DD, claim_type):
        log_cb(f"  ✅ Claim type set to: {claim_type}")
        await asyncio.sleep(1.5)
    else:
        log_cb("  ⚠️  Claim type dropdown not found — proceeding anyway")

    # ── Step 3: Enter claim number and click Filter ───────────────────────────
    if claim_no:
        log_cb(f"📌 Entering Claim No: {claim_no}")
        if await _fill_first_visible(page, SEL_CLAIM_NO_INPUT, claim_no):
            log_cb(f"  ✅ Claim number entered: {claim_no}")
            await asyncio.sleep(0.5)
        else:
            log_cb("  ⚠️  Claim No input not found — trying without filter")

        # Click Filter button
        log_cb("📌 Clicking Filter button...")
        if await _click_first_visible(page, SEL_FILTER_BTN):
            log_cb("  ✅ Filter button clicked")
            await asyncio.sleep(3)  # Wait for results to load
        else:
            log_cb("  ⚠️  Filter button not found — results may already be loaded")

    # ── Step 4: Wait for table to populate ────────────────────────────────────
    log_cb("📌 Waiting for search results...")
    await asyncio.sleep(2)

    # Check if "No Records Found" is showing
    try:
        no_records = page.locator(SEL_NO_RECORDS).first
        if await no_records.is_visible(timeout=2000):
            log_cb("  ⚠️  'No Records Found' — table is empty after filter")
            # Try without claim number filter (just claim type)
            if claim_no:
                log_cb("  🔄 Retrying with Reset + just claim type selection...")
                await _click_first_visible(page, SEL_RESET_BTN, timeout=3000)
                await asyncio.sleep(1)
                await _select_first_visible(page, SEL_CLAIM_TYPE_DD, claim_type)
                await asyncio.sleep(3)
    except Exception:
        pass  # "No Records Found" not visible — good, table has data

    # ── Step 5: Scan table pages for claim and click Action ───────────────────
    page_num = 1
    while True:
        log_cb(f"🔎 Scanning table page {page_num} for claim: {claim_no}")
        found = await _find_and_click_claim(page, claim_no, log_cb)
        if found:
            await asyncio.sleep(2)
            log_cb(f"✅ Claim {claim_no} found and Action clicked!")
            return True

        # Try next pagination page
        has_next = False
        for sel in SEL_PAGE_NEXT.split(", "):
            try:
                next_btn = page.locator(sel.strip()).first
                if await next_btn.is_visible(timeout=1500):
                    # Check parent <li> isn't disabled
                    try:
                        disabled = await next_btn.locator("xpath=..").evaluate(
                            "el => el.classList.contains('disabled')"
                        )
                        if disabled:
                            continue
                    except Exception:
                        pass
                    await next_btn.click()
                    await asyncio.sleep(2)
                    page_num += 1
                    has_next = True
                    break
            except Exception:
                continue

        if not has_next:
            break

    log_cb(f"❌ Claim {claim_no} not found in worklist.")
    return False


async def _find_and_click_claim(page, claim_no: str, log_cb: Callable) -> bool:
    """Search current table page for claim_no; click its Action button."""
    try:
        rows = page.locator(SEL_RESULT_TABLE)
        count = await rows.count()

        if count == 0:
            log_cb("  ⚠️  No rows found — waiting 3s for table to load...")
            await asyncio.sleep(3)
            count = await rows.count()

        log_cb(f"  📊 Found {count} rows in table")

        for i in range(count):
            row = rows.nth(i)
            try:
                text = await row.inner_text()

                # Skip "No Records Found" rows
                if "No Record" in text:
                    continue

                if claim_no in text:
                    log_cb(f"  ✅ Claim found in row {i + 1}: {text[:80]}...")

                    # Click "Click Here" button in the Action column
                    for btn_sel in SEL_ACTION_BTN.split(", "):
                        try:
                            btn = row.locator(btn_sel.strip()).first
                            if await btn.is_visible(timeout=2000):
                                await btn.click()
                                log_cb(f"  ✅ Clicked Action button for claim {claim_no}")
                                return True
                        except Exception:
                            continue

                    # Fallback: click any button/link in the last few TDs
                    log_cb("  ⚠️  'Click Here' not found — trying any button in row...")
                    try:
                        any_btn = row.locator("td button, td a").last
                        if await any_btn.is_visible(timeout=1500):
                            await any_btn.click()
                            log_cb(f"  ✅ Clicked fallback button for claim {claim_no}")
                            return True
                    except Exception:
                        pass

                    log_cb(f"  ⚠️  Found claim row but couldn't click Action button")
                    return False

            except Exception:
                continue

    except Exception as e:
        log_cb(f"  ⚠️  Row scan error: {e}")
    return False
