# Selector And DOM Strategy

## Purpose

This document captures how selectors are organized, how DOM interactions are performed, and how to modify selectors safely.

## UIIC Selector Registry

Module: `app/automation/selectors.py`

Selectors are grouped by portal area:

- `WORKLIST`
- `TABS`
- `INTERIM`
- `DOCUMENTS`
- `ASSESSMENT`
- `ASSESSMENT_SLOTS`

The file documents that UIIC has no iframe and all elements are on the main page.

## Selector Priority

Preferred selector order:

1. Stable `#id`.
2. Stable `name`.
3. `ng-model` / `data-ng-model`.
4. Specific structural selector inside a known panel/row.
5. Text selector.
6. JS DOM scan fallback.

Avoid using broad selectors as the first strategy if the page has repeated labels.

## AngularJS Interaction Strategy

The portals use Angular-style bindings. Normal DOM value changes often need events.

Required event patterns:

- Text fields: set/fill value plus `input`, `change`, `Tab`.
- Date fields: JS set value plus `input`, `change`, blur, Escape.
- Radios: set `.checked = true`, dispatch `change`, and sometimes `.click()`.
- Selects: select option, then dispatch `change` in JS fallback.
- File inputs: `set_input_files()`, then sometimes dispatch `change`.

## Helper Functions

Module: `app/automation/form_helpers.py`

Key helpers:

- `safe_fill`
- `safe_fill_amount`
- `safe_fill_date`
- `safe_fill_text`
- `safe_fill_portal_text`
- `safe_select`
- `safe_radio`
- `safe_click`
- `click_all_yes_radios`
- `quick_visible`
- `dump_visible_fields`

Important semantics:

- `safe_fill` skips only `None` and empty strings.
- `safe_fill_amount` rounds to nearest rupee and fills `"0"`.
- `safe_fill_date` expects portal input to receive `DD/MM/YYYY`.
- `safe_fill_portal_text` strips special characters aggressively for strict portal fields.

## Tab Strategy

Module: `app/automation/tab_utils.py`

`click_tab()`:

- Finds tab by configured text.
- Falls back to index.
- Waits `_TAB_RENDER_WAIT = 1.2` seconds.
- Brings page to front.
- Scrolls to a stable offset.

Do not duplicate tab-click logic in individual modules.

## Upload DOM Strategy

`DocumentUploadService` scopes upload row locators to the yellow upload panel titled `Upload Document`. It finds rows by `select[name^="docType"]` and related file input ancestors.

Claim documents:

- Reuse first existing row.
- Click plus for additional rows.
- Select document type.
- Attach file.
- Dismiss upload popups.
- Verify the row still shows the expected file.
- Retry visible row if file was lost.

Assessment uploads use label-based row location in `claim_assessment.py`.

## Selector Change Rules

- Add fallbacks, do not remove known working selectors unless proven obsolete.
- Keep UIIC selectors in `app/automation/selectors.py`.
- Keep New India selectors inside New India modules or create a New India selector module.
- Log selector failures with enough detail to diagnose the row/field.
- After changing a selector, test that the same module still skips gracefully when optional fields are absent.

