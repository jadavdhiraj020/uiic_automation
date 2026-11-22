import re
from typing import Callable

from playwright.async_api import Error as PlaywrightError, Page

from app.automation.automation_logger import AutomationLogger
from app.portals.newindia.automation.ui_utils import (
    CHANNEL_MARUTI,
    CHANNEL_NON_TIE_UP,
    CHANNEL_UNSUPPORTED,
    classify_newindia_channel,
)
from app.portals.oic.automation.recovery import same_origin, wait_until_ready


SEL_NAV_WORKLIST = "li#navlink-worklist a:visible"
SEL_FILTER_DROPDOWN = "select#searchType:visible"
SEL_CLAIM_TYPE_DROPDOWN = "select#claimType:visible"
SEL_CLAIM_INPUT = "input#filterWorklistClaimNo:visible"
SEL_FILTER_BTN = "button[data-ng-click*='filterClaims']:visible"
SEL_CLAIM_CARD = ".card-claim:visible"
SEL_CLAIM_LABEL = ".card-claim-lbl"
SEL_CLAIM_EDIT_BTN = "a:has(svg.icon-tabler-edit):visible"
QUICK_UPDATE = 'h4.headerClip:visible'
SEARCH_TIMEOUT_S = 15
FORM_TIMEOUT_S = 20

_JS_READ_WORKLIST_CHANNEL = """
() => {
    const sel = document.querySelector('select#claimType');
    const opt = sel && sel.selectedIndex >= 0 ? sel.options[sel.selectedIndex] : null;
    let sessionType = '';
    try { sessionType = sessionStorage.getItem('claimTypeNM') || ''; } catch (e) {}
    return {
        present: Boolean(sel),
        value: sel ? (sel.value || '') : '',
        text: opt ? (opt.textContent || '').trim() : '',
        sessionType,
    };
}
"""


class ClaimNavigationError(RuntimeError):
    """An operator-facing failure while locating or opening a New India claim."""


class UnsupportedClaimChannelError(ClaimNavigationError):
    """Raised when New India assigns the claim to an OEM channel not automated yet."""

    def __init__(self, claim_no: str, channel_name: str):
        self.claim_no = claim_no
        self.channel_name = channel_name or "This channel"
        super().__init__(
            f"{self.channel_name} is not supported yet — only Non-Tie-Up and Maruti claims are automated."
        )


async def navigate_to_claim(
    page: Page,
    claim_no: str,
    settings: dict,
    log=print,
    stop_cb: Callable[[], bool] = lambda: False,
    *,
    channel_out: dict | None = None,
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

        raw_channel = {"present": False, "value": "", "text": "", "sessionType": ""}
        try:
            raw_channel = await page.evaluate(_JS_READ_WORKLIST_CHANNEL)
        except Exception:
            pass
        dd_code, dd_label = classify_newindia_channel(raw_channel.get("value", ""), raw_channel.get("text", ""))
        ss_code, ss_label = classify_newindia_channel(raw_channel.get("sessionType", ""))
        if ss_code == CHANNEL_UNSUPPORTED:
            wl_code = CHANNEL_UNSUPPORTED
            wl_label = dd_label if dd_code == CHANNEL_UNSUPPORTED else ss_label
        elif dd_code:
            wl_code, wl_label = dd_code, dd_label
        else:
            wl_code, wl_label = ss_code, ss_label

        if wl_code == CHANNEL_UNSUPPORTED:
            info(f"Worklist channel detected: {wl_label} (not automated yet).")
            raise UnsupportedClaimChannelError(claim_no, wl_label)
        if wl_code:
            info(f"Worklist channel detected: {wl_label}.")

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

        url_code, url_label = classify_newindia_channel(url=getattr(claim_page, "url", "") or "")
        if url_code == CHANNEL_UNSUPPORTED:
            raise UnsupportedClaimChannelError(claim_no, url_label)
        final_code = url_code if url_code in {CHANNEL_NON_TIE_UP, CHANNEL_MARUTI} else (wl_code or CHANNEL_NON_TIE_UP)
        final_label = url_label if url_code in {CHANNEL_NON_TIE_UP, CHANNEL_MARUTI} else (wl_label or "Non-Tie-Up")
        if channel_out is not None:
            channel_out.update({
                "code": final_code,
                "label": final_label,
                "raw": raw_channel.get("text") or raw_channel.get("value") or raw_channel.get("sessionType") or "",
            })

        success(f"Quick Update opened for claim {claim_no} ({final_label}).")
        return claim_page
    except PlaywrightError as exc:
        raise ClaimNavigationError(failure) from exc
    finally:
        if structured_log:
            log.outdent()
