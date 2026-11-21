import re
from typing import Callable

from playwright.async_api import Error as PlaywrightError, Page

from app.automation.automation_logger import AutomationLogger
from app.portals.oic.automation.recovery import same_origin, wait_until_ready


SEL_NAV_WORKLIST = "li#navlink-worklist a:visible"
SEL_FILTER_DROPDOWN = "select#searchType:visible"
SEL_CLAIM_INPUT = "input#filterWorklistClaimNo:visible"
SEL_FILTER_BTN = "button[data-ng-click*='filterClaims']:visible"
SEL_CLAIM_CARD = ".card-claim:visible"
SEL_CLAIM_LABEL = ".card-claim-lbl"
SEL_CLAIM_EDIT_BTN = "a:has(svg.icon-tabler-edit):visible"
QUICK_UPDATE = 'h4.headerClip:visible'
SEARCH_TIMEOUT_S = 15
FORM_TIMEOUT_S = 20


class ClaimNavigationError(RuntimeError):
    """An operator-facing failure while locating or opening a New India claim."""


async def navigate_to_claim(
    page: Page,
    claim_no: str,
    settings: dict,
    log=print,
    stop_cb: Callable[[], bool] = lambda: False,
) -> Page | None:
    """Filter the Worklist and continue only after opening the same claim."""
    claim_no = str(claim_no or "").strip()
    if not claim_no:
        raise ClaimNavigationError("Claim number is missing. Check the extracted claim number in App3.")
    if stop_cb():
        return None

    structured_log = isinstance(log, AutomationLogger)
    if structured_log:
        log.section = "Worklist Navigation"
    info = log.info if structured_log else log
    success = log.success if structured_log else log
    if structured_log:
        log.indent()

    failure = "The New India Worklist did not open."
    try:
        criteria = page.locator(SEL_FILTER_DROPDOWN)
        if not await criteria.is_visible():
            info("Opening the New India Worklist.")
            await page.locator(SEL_NAV_WORKLIST).click(timeout=15000)
        else:
            info("Worklist is already open.")
        await criteria.wait_for(state="visible", timeout=15000)
        if stop_cb():
            return None

        failure = "App3 could not select Claim No. in the Worklist filter."
        await criteria.select_option(label="Claim No.", timeout=5000)
        failure = "App3 could not enter the full claim number in the Worklist filter."
        claim_input = page.locator(SEL_CLAIM_INPUT)
        await claim_input.fill(claim_no, timeout=5000)
        await claim_input.dispatch_event("change", timeout=5000)
        if await claim_input.input_value(timeout=5000) != claim_no:
            raise ClaimNavigationError(failure)
        if stop_cb():
            return None

        failure = "App3 could not run the claim-number filter on the Worklist."
        info(f"Searching Worklist by Claim No.: {claim_no}")
        await page.locator(SEL_FILTER_BTN).click(timeout=10000)

        number = re.escape(claim_no)
        # The priority star has a literal period inside the claim label.
        card_label = re.compile(rf"^Claim Number\s*:\s*{number}\s*\.?\s*$", re.I)
        cards = page.locator(SEL_CLAIM_CARD)
        matching = cards.filter(has=page.locator(SEL_CLAIM_LABEL).filter(has_text=card_label))

        async def claim_is_ready():
            return await cards.count() == 1 and await matching.count() == 1

        if not await wait_until_ready(claim_is_ready, seconds=SEARCH_TIMEOUT_S, stopped=stop_cb):
            if stop_cb():
                return None
            total_cards = await cards.count()
            if total_cards == 0:
                raise ClaimNavigationError(f"New India found no claim card for {claim_no} in the Worklist.")
            raise ClaimNavigationError(
                f"Worklist showed {total_cards} card(s) instead of 1 exact match for {claim_no}."
            )
        if stop_cb():
            return None

        info(f"Found 1 matching claim card ({claim_no}). Clicking Edit...")
        edit = matching.locator(SEL_CLAIM_EDIT_BTN)
        origin_url = page.url
        popups: list[Page] = []
        claim_page = None
        expected_breadcrumb = re.compile(rf"^\s*Claim\s+(?:Number|No\.?)\s*:?\s*{number}\s*/?\s*$", re.I)

        def record_popup(popup: Page):
            popups.append(popup)

        async def form_is_ready():
            nonlocal claim_page
            for candidate in (page, *popups):
                if candidate.is_closed() or not same_origin(candidate, origin_url):
                    continue
                breadcrumb = candidate.locator("p.surveyorBreadCrumb:visible").filter(has_text=expected_breadcrumb)
                heading = candidate.locator(QUICK_UPDATE).filter(has_text=re.compile(r"^Quick Update Details$", re.I))
                claim_form = candidate.locator('form[name="workListForm"]', has=breadcrumb).filter(has=heading)
                if await claim_form.count() == 1:
                    claim_page = candidate
                    return True
            return False

        # Start listening before the click so an immediately opened tab is included.
        page.on("popup", record_popup)
        try:
            failure = "The matching claim was found, but App3 could not click its Edit icon."
            await edit.click(timeout=10000)

            failure = f"Edit was clicked, but Quick Update did not open for claim {claim_no}."
            if not await wait_until_ready(form_is_ready, seconds=FORM_TIMEOUT_S, stopped=stop_cb):
                if stop_cb():
                    return None
                raise ClaimNavigationError(failure)
        finally:
            page.remove_listener("popup", record_popup)

        success(f"Quick Update opened for claim {claim_no}.")
        return claim_page
    except PlaywrightError as exc:
        raise ClaimNavigationError(failure) from exc
    finally:
        if structured_log:
            log.outdent()
