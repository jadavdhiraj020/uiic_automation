"""
navigation_module.py
After login, navigates to Worklist, selects claim type, finds claim, clicks Action.
Strategy:
  1. Try clicking the Worklist link in sidebar
  2. Fallback: navigate directly to the known Worklist URL
  3. Select claim type dropdown
  4. Search for claim number and click Action
"""
import asyncio
import logging
from typing import Callable

logger = logging.getLogger(__name__)

# Known working URL from live portal observation
WORKLIST_URL = "https://portal.uiic.in/surveyor/data/Surveyor.html?v=62486#/Worklist"

SEL_WORKLIST_MENU = (
    "a:has-text('Worklist'), "
    "li a[href*='Worklist'], "
    "li:has-text('Worklist') a, "
    ".sidebar a:has-text('Worklist'), "
    "ul.nav a:has-text('Worklist')"
)
SEL_CLAIM_TYPE_DD  = "select[ng-model*='claimType'], select[ng-model*='ClaimType'], #claimType, select[ng-model*='claim_type']"
SEL_RESULT_TABLE   = ".table tbody tr, table tbody tr, [ng-repeat] tr, .worklist-table tr"
SEL_ACTION_BTN     = "button:has-text('Click Here'), a:has-text('Click Here'), td button, td a"
SEL_PAGE_NEXT      = "a:has-text('Next'), li.next a, .pagination .next a, li.next:not(.disabled) a"


async def navigate_to_claim(
    page,
    claim_no: str,
    claim_type: str = "Non Maruti",
    log_cb: Callable[[str], None] = print,
) -> bool:
    """
    Navigate to Worklist → select claim type → find claim → click Action.
    Returns True if claim found and clicked.
    """
    log_cb(f"📌 Current URL before navigation: {page.url}")

    # ── Navigate to Worklist ──────────────────────────────────────────────────
    worklist_reached = False

    # Strategy 1: Click sidebar Worklist link
    try:
        worklist_link = page.locator(SEL_WORKLIST_MENU).first
        await worklist_link.wait_for(state="visible", timeout=6000)
        await worklist_link.click()
        await asyncio.sleep(2)
        log_cb("📋 Clicked Worklist sidebar link.")
        worklist_reached = True
    except Exception as e:
        log_cb(f"⚠️  Sidebar click failed ({e.__class__.__name__}) — trying direct URL...")

    # Strategy 2: Direct URL navigation
    if not worklist_reached or "Worklist" not in page.url:
        log_cb(f"🔗 Navigating directly to Worklist URL...")
        await page.goto(WORKLIST_URL, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(3)
        log_cb(f"📌 URL after navigation: {page.url}")

    await page.wait_for_load_state("domcontentloaded", timeout=10000)
    await asyncio.sleep(2)

    # ── Select Claim Type ─────────────────────────────────────────────────────
    log_cb(f"📌 Selecting Claim Type: {claim_type}")
    for sel in SEL_CLAIM_TYPE_DD.split(", "):
        try:
            dd = page.locator(sel.strip()).first
            await dd.wait_for(state="visible", timeout=4000)
            try:
                await dd.select_option(label=claim_type)
            except Exception:
                await dd.select_option(value=claim_type)
            await asyncio.sleep(2)
            log_cb(f"  ✅ Claim type set to: {claim_type}")
            break
        except Exception:
            continue
    else:
        log_cb(f"  ⚠️  Claim type dropdown not found — proceeding anyway")

    # ── Scan all pages for claim number ──────────────────────────────────────
    page_num = 1
    while True:
        log_cb(f"🔎 Scanning page {page_num} for claim: {claim_no}")
        found = await _find_and_click_claim(page, claim_no, log_cb)
        if found:
            await asyncio.sleep(2)
            log_cb(f"✅ Claim {claim_no} found and action clicked!")
            return True

        # Try next pagination page
        next_btn = page.locator(SEL_PAGE_NEXT).first
        try:
            visible = await next_btn.is_visible(timeout=1500)
            if not visible:
                break
            enabled = not await next_btn.locator("xpath=..").evaluate(
                "el => el.classList.contains('disabled')"
            )
            if not enabled:
                break
            await next_btn.click()
            await asyncio.sleep(2)
            page_num += 1
        except Exception:
            break

    log_cb(f"❌ Claim {claim_no} not found in worklist.")
    return False


async def _find_and_click_claim(page, claim_no: str, log_cb: Callable) -> bool:
    """Search current table page for claim_no; click its Action button."""
    try:
        rows = page.locator(SEL_RESULT_TABLE)
        count = await rows.count()
        if count == 0:
            log_cb("  ⚠️  No rows found in table yet — waiting...")
            await asyncio.sleep(2)
            count = await rows.count()

        log_cb(f"  📊 Found {count} rows in table")
        for i in range(count):
            row = rows.nth(i)
            try:
                text = await row.inner_text()
                if claim_no in text:
                    log_cb(f"  ✅ Claim found in row {i + 1}")
                    action_btn = row.locator(SEL_ACTION_BTN).first
                    await action_btn.click()
                    return True
            except Exception:
                continue
    except Exception as e:
        log_cb(f"  ⚠️  Row scan error: {e}")
    return False
