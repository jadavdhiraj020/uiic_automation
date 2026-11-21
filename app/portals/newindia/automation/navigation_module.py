import re
from typing import Callable, Optional
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError

from app.automation.automation_logger import AutomationLogger
from app.portals.oic.automation.recovery import wait_until_ready


SEL_NAV_WORKLIST = "li#navlink-worklist a:visible"
SEL_FILTER_DROPDOWN = "select#searchType:visible"
SEL_CLAIM_INPUT = "input#filterWorklistClaimNo:visible"
SEL_FILTER_BTN = "button[data-ng-click*='filterClaims']:visible"

# Scope the pencil or its tooltip to the card that contains the claim title.
# Maruti and Non-Maruti can use different Angular handlers.
SEL_CLAIM_EDIT_BTN = (
    ':is(a, button, [role="button"]):visible:is('
    ':has(.icon-tabler-edit), [title="Click Here To Proceed" i], '
    '[data-original-title="Click Here To Proceed" i], '
    '[data-bs-original-title="Click Here To Proceed" i], [aria-label="Edit Claim" i])'
)
CLAIM_CARD = (
    "xpath=ancestor::*[contains(translate(normalize-space(.), "
    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'insured name') "
    "and not(.//*[@id='searchType'])][1]"
)
QUICK_UPDATE = 'h4.headerClip:visible'
SEARCH_TIMEOUT_S = 15
EDIT_TIMEOUT_S = 10
FORM_TIMEOUT_S = 20


class ClaimNavigationError(RuntimeError):
    """An operator-facing failure while locating or opening a New India claim."""


def _claim_label(number):
    return re.compile(rf"^Claim\s+(?:Number|No\.?)\s*:?\s*{number}\s*[/★☆]?\s*$", re.I)


async def _search_for_single_claim(page, results, matching, stop_cb):
    origin = urlsplit(page.url)
    pending = set()
    search_failed = False
    consecutive_matches = 0
    search_result = page.get_by_text(re.compile(r"^Search Results?$", re.I)).and_(page.locator(":visible"))

    def request_started(request):
        url = urlsplit(request.url)
        if request.resource_type in {"fetch", "xhr"} and (url.scheme, url.netloc) == (origin.scheme, origin.netloc):
            pending.add(request)

    def request_done(request):
        pending.discard(request)

    def request_failed(request):
        nonlocal search_failed
        search_failed = search_failed or request in pending
        request_done(request)

    def response_received(response):
        nonlocal search_failed
        search_failed = search_failed or (response.request in pending and response.status >= 400)

    async def single_result_ready():
        nonlocal consecutive_matches
        if search_failed:
            return True
        ready = (not pending and await search_result.count() == 1
                 and await results.count() == 1 and await matching.count() == 1)
        consecutive_matches = consecutive_matches + 1 if ready else 0
        return consecutive_matches >= 2

    # Wait for the UI and its search requests to settle before trusting a card
    # that could still be visible from the previous Worklist search.
    listeners = [
        ("request", request_started),
        ("requestfinished", request_done),
        ("requestfailed", request_failed),
        ("response", response_received),
    ]
    for event, handler in listeners:
        page.on(event, handler)
    try:
        await page.locator(SEL_FILTER_BTN).click(timeout=10000)
        if await wait_until_ready(single_result_ready, seconds=SEARCH_TIMEOUT_S, stopped=stop_cb):
            if search_failed:
                raise ClaimNavigationError("New India returned an error during the Worklist search.")
            return True
    finally:
        for event, handler in listeners:
            page.remove_listener(event, handler)

    if stop_cb():
        return False
    count = await results.count()
    if pending:
        raise ClaimNavigationError("The New India Worklist search did not finish in time.")
    if count > 1:
        raise ClaimNavigationError("The Worklist returned multiple claim cards. App3 needs one exact result before clicking Edit.")
    if count == 1 and not await matching.count():
        raise ClaimNavigationError("The Worklist returned a different claim number from the one entered.")
    raise ClaimNavigationError("The Worklist did not show a single search result for the requested claim number.")


async def navigate_to_claim(
    page,
    claim_no: str,
    settings: dict,
    log=print,
    stop_cb: Callable[[], bool] = lambda: False,
) -> Optional:
    """Filter the Worklist and continue only after opening the same claim."""
    claim_no = str(claim_no or "").strip()
    if not claim_no:
        raise ClaimNavigationError("Claim number is missing. Check the extracted claim number in App3.")
    if stop_cb():
        return None

    structured_log = isinstance(log, AutomationLogger)
    info = log.info if structured_log else log
    success = log.success if structured_log else log
    info("Opening the New India Worklist.")
    if structured_log:
        log.indent()

    failure = "The New India Worklist did not open."
    try:
        await page.locator(SEL_NAV_WORKLIST).click(timeout=15000)
        criteria = page.locator(SEL_FILTER_DROPDOWN)
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

        visible = page.locator(":visible")
        expected_label = _claim_label(re.escape(claim_no))
        results = page.get_by_text(_claim_label(r"[A-Z0-9]+")).and_(visible)
        matching = page.get_by_text(expected_label).and_(results)
        failure = "App3 could not run the claim-number filter on the Worklist."
        info("Filtering the Worklist by the full claim number.")
        if not await _search_for_single_claim(page, results, matching, stop_cb):
            return None

        edit = matching.locator(CLAIM_CARD).locator(SEL_CLAIM_EDIT_BTN)

        async def edit_is_ready():
            return await edit.count() == 1

        failure = "The matching claim was found, but App3 could not identify one Edit control on its card."
        if not await wait_until_ready(edit_is_ready, seconds=EDIT_TIMEOUT_S, stopped=stop_cb):
            if stop_cb():
                return None
            raise ClaimNavigationError(failure)
        if await results.count() != 1 or await matching.count() != 1:
            raise ClaimNavigationError("The Worklist result changed before Edit could be clicked.")
        if stop_cb():
            return None

        failure = "The matching claim was found, but App3 could not click its Edit icon."
        await edit.click(timeout=10000)
        info("Clicked Edit on the matching claim. Waiting for Quick Update.")

        async def form_is_ready():
            breadcrumb = page.locator("li:visible").filter(has_text=expected_label)
            heading = page.locator(QUICK_UPDATE).filter(has_text=re.compile(r"^Quick Update Details$", re.I))
            return bool(await breadcrumb.count() and await heading.count())

        failure = "Edit was clicked, but Quick Update did not open for the requested claim."
        if not await wait_until_ready(form_is_ready, seconds=FORM_TIMEOUT_S, stopped=stop_cb):
            if stop_cb():
                return None
            raise ClaimNavigationError(failure)

        success("Quick Update is open for the matching claim.")
        return page
    except PlaywrightError as exc:
        raise ClaimNavigationError(failure) from exc
    finally:
        if structured_log:
            log.outdent()
