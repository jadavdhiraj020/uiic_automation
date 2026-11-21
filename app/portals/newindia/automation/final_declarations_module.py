"""Check the New India declaration list before the operator completes the survey."""

import re
from contextlib import suppress

from playwright.async_api import Page

from app.portals.newindia.automation.recovery import _BLOCKING_DIALOGS, _TAB_STATE, current_recovery


_DECLARATIONS = (
    ("a", "engChaVerified"),
    ("b", "damage"),
    ("c", "supEstimate"),
    ("d", "repaisReplace"),
    ("e", "reinspected"),
    ("f", "ncbVerified"),
    ("g", "dlVerified"),
    ("h", "rcVerified"),
    ("i", "dlVerifiedPar"),
    ("j", "rcVerifiedPar"),
    ("k", "permitVerifiedPar"),
    ("l", "fitnessCertVerifiedPar"),
)


async def check_final_declarations(page: Page, claim_number: str, log, stop_cb) -> None:
    log.section = "Final Declarations"
    recovery = current_recovery.get()
    claim_number = str(claim_number or "").strip()
    claim_label = re.compile(rf"^\s*Claim\s+No\.?\s*:?\s*{re.escape(claim_number)}\s*/?\s*$", re.I)
    claim_heading = page.locator("li:visible").filter(has_text=claim_label)
    form = page.locator('form[name="workListForm"]')

    async def ready():
        with suppress(Exception):
            if not claim_number or await page.locator(_BLOCKING_DIALOGS).count():
                return False
            if recovery is not None:
                return recovery.claim_number == claim_number and await recovery._same_step(page, "four")
            return bool(await claim_heading.count()) and await page.evaluate(_TAB_STATE) == "four"
        return False

    declarations = form.locator('input[type="checkbox"][name]:visible')
    for _, name in _DECLARATIONS:
        if stop_cb():
            return
        if not await ready():
            log.warning("App3 could not verify the claim or the Document Upload page. Review the declarations in Chrome.")
            return
        checkbox = form.locator(f'input[type="checkbox"][name="{name}"]:visible')
        with suppress(Exception):
            if await checkbox.count() == 1 and await checkbox.is_enabled(timeout=1000):
                await checkbox.check(timeout=3000)

    if stop_cb() or not await ready():
        return
    try:
        checked_names = await declarations.evaluate_all(
            """(fields, names) => names.filter(name => {
                const matches = fields.filter(field => field.name === name);
                return matches.length === 1 && matches[0].checked;
            })""",
            [name for _, name in _DECLARATIONS],
        )
    except Exception:
        log.warning("App3 could not confirm the final declarations. Review them in Chrome.")
        return

    review = [letter for letter, name in _DECLARATIONS if name not in checked_names]
    log.info(f"{len(checked_names)} of {len(_DECLARATIONS)} final declarations are checked.")
    if review:
        log.warning(f"Review these declarations in Chrome before completing the survey: {', '.join(review)}.")
