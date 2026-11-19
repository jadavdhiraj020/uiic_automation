"""Select and confirm a value in an OIC dropdown."""

import asyncio
import json
import re
import unicodedata
from contextlib import suppress

from playwright.async_api import Error as PlaywrightError

from app.portals.oic.automation.recovery import wait_until_ready


_PANELS = (
    ".p-dropdown-panel:visible, .p-select-overlay:visible, "
    "[role=listbox]:visible:not(:is(.p-dropdown-panel, .p-select-overlay) *)"
)
_OPTION = ":is([role=option], .p-dropdown-item, .p-select-option)"
_OPTIONS = f"{_OPTION}:visible:not({_OPTION} *):not(.p-disabled):not([aria-disabled=true])"


def option_key(value):
    return re.sub(r"[\W_]+", " ", unicodedata.normalize("NFKC", str(value or "")).casefold()).strip()


def _is_option(value):
    key = option_key(value)
    return bool(key) and not re.match(
        r"^(?:(?:please )?(?:select|choose)|loading|fetching|no (?:options|records|results|matches|data))\b", key,
    )


def matching_option(expected, options, *, exact=False):
    """Prefer an exact label. Use a partial label only when it is unambiguous."""
    key = option_key(expected)
    if not key:
        return ""
    eligible = [(name, option_key(name)) for name in options]
    for name, candidate in eligible:
        if candidate == key:
            return name
    if exact:
        return ""
    partial = [name for name, candidate in eligible if f" {key} " in f" {candidate} " or f" {candidate} " in f" {key} "]
    if len(partial) == 1:
        return partial[0]
    if partial:
        return ""
    words = {word for word in key.split() if len(word) > 2}
    related = [name for name, candidate in eligible if words.intersection(candidate.split())]
    return related[0] if len(related) == 1 else ""


def _enabled_dropdown(page, selector):
    return page.locator(f":is({selector}):visible:not(.p-disabled, .p-disabled *, [aria-disabled=true], :disabled)").first


async def dropdown_is_available(page, selector):
    return await _enabled_dropdown(page, selector).is_visible()


async def _toggle(dropdown, timeout):
    arrow = dropdown.locator(".p-dropdown-trigger:visible, .p-select-dropdown:visible").first
    await (arrow if await arrow.is_visible() else dropdown).click(timeout=timeout)


async def _selected_text(dropdown):
    text = await dropdown.evaluate("""root => {
        const labelSelector = '.p-dropdown-label, .p-select-label, [data-pc-section="input"]';
        const label = root.matches(labelSelector) ? root : root.querySelector(labelSelector);
        if (label && !label.matches('select')) {
            if (label.matches('.p-placeholder, [data-p-placeholder="true"]')) return '';
            return label.matches('input') ? label.value : label.textContent;
        }
        const select = root.matches('select') ? root : root.querySelector('select');
        const selected = select?.selectedOptions?.[0];
        if (selected) return selected.disabled || !selected.value ? '' : selected.textContent;
        const control = root.matches('[aria-valuetext]') ? root : root.querySelector('[aria-valuetext]');
        return control?.getAttribute('aria-valuetext') || root.querySelector('input[readonly]')?.value || '';
    }""", timeout=800)
    return text.strip() if _is_option(text) else ""


async def _active_panel(page, dropdown, previous_panels=None):
    ids = await dropdown.evaluate("""root => {
        const nodes = [root, ...root.querySelectorAll('[aria-controls], [aria-owns]')];
        return nodes.flatMap(node => ['aria-controls', 'aria-owns'].flatMap(attr =>
            (node.getAttribute(attr) || '').split(/\\s+/).filter(Boolean)));
    }""", timeout=800)
    for panel_id in ids:
        target = page.locator(f"[id={json.dumps(panel_id)}]:visible").first
        if await target.is_visible():
            return target
    if previous_panels is None:
        return None
    panels = page.locator(_PANELS)
    new_panels = await panels.evaluate_all(
        "(nodes, previous) => nodes.flatMap((node, index) => previous.includes(node) ? [] : [index])",
        previous_panels,
    )
    return panels.nth(new_panels[0]) if len(new_panels) == 1 else None


async def select_dropdown_option(page, selector, choose, *, expected="", allow_duplicate=False):
    """Return the displayed selection, including when a click reported an error after committing."""
    dropdown = page.locator(f":is({selector}):visible").first
    selected = ""
    wanted = expected
    panel = None
    opened_panel = None
    previous_panels = []
    matching_reads = 0

    async def has_selection():
        nonlocal selected
        selected = await _selected_text(dropdown)
        return bool(selected and wanted and option_key(selected) == option_key(wanted))

    async def selection_settled():
        nonlocal matching_reads
        matching_reads = matching_reads + 1 if await has_selection() else 0
        return matching_reads >= 2

    try:
        await dropdown.wait_for(state="visible", timeout=8000)
        panel = await _active_panel(page, dropdown)
        if panel is not None:
            opened_panel = await panel.element_handle(timeout=800)
        if expected and await has_selection():
            return selected
        if panel is None:
            previous_panels = await page.locator(_PANELS).element_handles()
            # A rerender can interrupt Click after OIC has already opened the panel.
            with suppress(PlaywrightError):
                await _toggle(_enabled_dropdown(page, selector), timeout=8000)

        deadline = asyncio.get_running_loop().time() + 10
        previous = None
        stable = 0
        chosen = ""
        while asyncio.get_running_loop().time() < deadline:
            with suppress(PlaywrightError):
                panel = await _active_panel(page, dropdown, previous_panels)
                if panel is not None:
                    items = panel.locator(_OPTIONS)
                    options = [label.strip() for label in await items.all_inner_texts() if _is_option(label)]
                    stable = stable + 1 if options == previous else 0
                    previous = options
                    chosen = choose(options)
                    if chosen and stable >= 2:
                        break
            await asyncio.sleep(0.2)
        if panel is not None and opened_panel is None:
            opened_panel = await panel.element_handle(timeout=800)
        if not chosen or panel is None:
            option = f"“{expected}”" if expected else "a matching option"
            raise ValueError(f"OIC did not offer {option}.")

        wanted = chosen
        if not await has_selection():
            pattern = r"^\s*" + r"\s+".join(re.escape(word) for word in chosen.split()) + r"\s*$"
            matches = panel.locator(_OPTIONS).filter(has_text=re.compile(pattern))
            if not allow_duplicate and await matches.count() > 1:
                raise ValueError("OIC showed more than one option with this name.")
            await matches.first.click(timeout=3500)
        if await wait_until_ready(selection_settled, seconds=3):
            return selected
        raise ValueError(f"OIC did not keep the selection “{wanted}”.")
    except Exception:
        if wanted and await wait_until_ready(selection_settled, seconds=2):
            return selected
        raise
    finally:
        # Escape does not reliably dismiss this portal's overlay. Toggle only the
        # control whose menu was opened so later fields never use its options.
        if opened_panel is not None:
            with suppress(Exception):
                await opened_panel.wait_for_element_state("hidden", timeout=300)
            with suppress(Exception):
                if await opened_panel.is_visible():
                    await _toggle(dropdown, timeout=800)
            with suppress(Exception):
                await opened_panel.dispose()
        for previous_panel in previous_panels:
            with suppress(Exception):
                await previous_panel.dispose()
