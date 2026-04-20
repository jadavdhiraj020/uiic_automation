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
from typing import Callable, Optional

from playwright.async_api import Page

logger = logging.getLogger(__name__)

# Known working URL from live portal observation
WORKLIST_URL = "https://portal.uiic.in/surveyor/data/Surveyor.html#/Worklist"

# ── Selectors ─────────────────────────────────────────────────────────────────
# B8 FIX: Store selectors as lists instead of comma-joined strings.
# Joining selectors with ', ' then splitting on ', ' breaks selectors that
# themselves contain commas (e.g. inside :has-text() patterns).
SEL_WORKLIST_MENU = [
    "a:has-text('Worklist')",
    "li a[href*='Worklist']",
    "li:has-text('Worklist') a",
    ".sidebar a:has-text('Worklist')",
    "ul.nav a:has-text('Worklist')",
]

SEL_CLAIM_NO_INPUT = [
    "input[name='claimPolicyNo']",
    "input[ng-model*='filterWorklistClaimNo']",
    "input[ng-model*='claimNo']",
    "input[ng-model*='ClaimNo']",
    "input[placeholder*='Claim']",
]

SEL_FILTER_BTN = [
    "button:has-text('Filter')",
    "input[value='Filter']",
    "a:has-text('Filter')",
    "button.btn-primary:has-text('Filter')",
]
SEL_RESET_BTN = [
    "button:has-text('Reset')",
    "input[value='Reset']",
    "a:has-text('Reset')",
]

SEL_CLAIM_TYPE_DD = [
    "select[name='claimType']",
    "select[ng-model*='claimType']",
    "#claimType",
]
CLAIM_TYPE_NONMARUTI_VALUE = "string:NONMARUTI"

SEL_RESULT_TABLE = "table tbody tr"
SEL_ACTION_BTN = [
    "button:has-text('Click Here')",
    "a:has-text('Click Here')",
    "td button:has-text('Click')",
    "td a:has-text('Click')",
]
SEL_PAGE_NEXT = [
    "a:has-text('Next')",
    "li.next:not(.disabled) a",
    ".pagination .next a",
]
SEL_NO_RECORDS = "td:has-text('No Records Found'), td:has-text('No Record Found'), td:has-text('No records')"


async def _click_first_visible(page, selectors, timeout: int = 4000) -> bool:
    """Try each selector (list or comma-string); click the first visible one."""
    if isinstance(selectors, str):
        selectors = [s.strip() for s in selectors.split(",")]
    for sel in selectors:
        try:
            el = page.locator(sel.strip()).first
            await el.wait_for(state="visible", timeout=timeout)
            await el.click()
            return True
        except Exception:
            continue
    return False


async def _fill_first_visible(page, selectors, value: str, timeout: int = 4000) -> bool:
    """Try each selector (list or comma-string); fill the first visible one."""
    if isinstance(selectors, str):
        selectors = [s.strip() for s in selectors.split(",")]
    for sel in selectors:
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


async def _select_first_visible(page, selectors, label: str, timeout: int = 4000) -> bool:
    """Try each selector (list or comma-string); select option by label."""
    if isinstance(selectors, str):
        selectors = [s.strip() for s in selectors.split(",")]
    for sel in selectors:
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
    page: Page,
    claim_no: str,
    claim_type: str = "Non Maruti",
    log_cb: Callable[[str], None] = print,
) -> Optional[Page]:
    """
    Navigate to Worklist → select claim type → filter by claim no → click Action.
    Returns the claim details Page (may be a new tab) if found, or None.
    """
    log_cb(f"📌 Current URL: {page.url}")

    # ── Step 1: Navigate to Worklist ──────────────────────────────────────────
    worklist_reached = False

    # Strategy A: Click sidebar Worklist link
    try:
        for sel in SEL_WORKLIST_MENU:
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
    # Try confirmed value first ('string:NONMARUTI'), then label text
    set_ct = False
    for ct_sel in SEL_CLAIM_TYPE_DD:
        try:
            el = page.locator(ct_sel.strip()).first
            if await el.is_visible(timeout=3000):
                try:
                    await el.select_option(value=CLAIM_TYPE_NONMARUTI_VALUE)
                    set_ct = True
                except Exception:
                    pass
                if not set_ct:
                    try:
                        await el.select_option(label=claim_type)
                        set_ct = True
                    except Exception:
                        pass
                if set_ct:
                    log_cb(f"  ✅ Claim type set to: {claim_type}")
                    await asyncio.sleep(1.5)
                    break
        except Exception:
            continue
    if not set_ct:
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
        claim_page = await _find_and_click_claim(page, claim_no, log_cb)
        if claim_page is not None:
            await asyncio.sleep(2)
            log_cb(f"✅ Claim {claim_no} found and Action clicked!")
            return claim_page

        # Try next pagination page
        has_next = False
        for sel in SEL_PAGE_NEXT:
            try:
                next_btn = page.locator(sel.strip()).first
                if await next_btn.is_visible(timeout=1500):
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
    return None


async def _find_and_click_claim(page: Page, claim_no: str, log_cb: Callable) -> Optional[Page]:
    """
    Search current table page for claim_no; click its Action button.
    Returns the new page (if a new tab opened) or same page, or None if not found.
    """
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
                    # The portal may open a NEW TAB — listen for it
                    context = page.context
                    pages_before = set(id(p) for p in context.pages)

                    for btn_sel in SEL_ACTION_BTN:
                        try:
                            btn = row.locator(btn_sel.strip()).first
                            if await btn.is_visible(timeout=2000):
                                await btn.click()
                                log_cb(f"  ✅ Clicked Action button for claim {claim_no}")
                                return await _detect_new_page(page, context, pages_before, log_cb)
                        except Exception:
                            continue

                    # Fallback: click any button/link in the last few TDs
                    log_cb("  ⚠️  'Click Here' not found — trying any button in row...")
                    try:
                        context = page.context
                        pages_before = set(id(p) for p in context.pages)
                        any_btn = row.locator("td button, td a").last
                        if await any_btn.is_visible(timeout=1500):
                            await any_btn.click()
                            log_cb(f"  ✅ Clicked fallback button for claim {claim_no}")
                            return await _detect_new_page(page, context, pages_before, log_cb)
                    except Exception:
                        pass

                    log_cb(f"  ⚠️  Found claim row but couldn't click Action button")
                    return None

            except Exception:
                continue

    except Exception as e:
        log_cb(f"  ⚠️  Row scan error: {e}")
    return None


async def _detect_new_page(
    original_page: Page,
    context,
    pages_before: set,
    log_cb: Callable,
    timeout: float = 5.0,
) -> Page:
    """
    After clicking 'Click Here', the portal usually opens the claim details
    in a new tab. Wait up to `timeout` seconds for it, then return whichever
    page to use for subsequent steps.
    """
    # Wait for a new tab to appear
    elapsed = 0.0
    while elapsed < timeout:
        await asyncio.sleep(0.5)
        elapsed += 0.5
        for p in context.pages:
            if id(p) not in pages_before and not p.is_closed():
                try:
                    await p.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass
                await p.bring_to_front()
                log_cb(f"  🆕 New tab detected: {p.url}")
                return p

    # No new tab — the page navigated in-place (SPA route change)
    log_cb(f"  📌 No new tab — staying on: {original_page.url}")
    return original_page
