# Debugging And Regression Guide

## Purpose

This guide gives future developers and AI sessions a fast path for diagnosing extraction, UI, and portal automation failures without rediscovering the whole project.

## First Questions

1. Which portal is active?
2. Did folder scan find the correct Excel file?
3. Did field mapping load from bundled defaults or AppData override?
4. Did preview show the expected value and source coordinate?
5. Did automation fail during login, navigation, field fill, upload, or manual review?
6. Is the issue portal-specific or shared-helper related?

## Log Locations

- Startup log: AppData `UIIC_Surveyor_Automation/logs/startup.log`
- Automation log: AppData `UIIC_Surveyor_Automation/logs/automation.log`
- Debug DOM dumps: local `logs/dom_<tab>.html` when `dump_visible_fields()` is called.
- Existing form dumps may appear under local `logs/`.

## Extraction Debugging

Symptoms and likely causes:

| Symptom | Likely Cause | Check |
| --- | --- | --- |
| Field missing in preview | Label mismatch, wrong active portal, wrong sheet, stale user mapping | Settings -> Field Mapping, `_excel_logs` |
| Text field skipped as junk | Missing `allow_text_values` | field mapping entry |
| Amount `0` missing | Bug introduced by falsy check | helper/tests |
| Wrong document type | Keyword collision or stale doc mapping | `doc_mapping.json`, scan summary |
| Reinspection missing | no user PDF, COM export failed, workbook lacks Sheet 7 | scanner logs |
| Invoice no/date wrong | PDF text pattern mismatch | PDF labels in settings |

## Automation Debugging

| Stage | Module | Common Failure |
| --- | --- | --- |
| Login UIIC | `login_module.py` | OCR failed, CAPTCHA changed, selector changed, modal blocks |
| Active page after login | `engine.py` | portal opens/closes tabs, session not ready |
| Worklist UIIC | `navigation_module.py` | claim type selector, claim input, table render delay |
| Interim | `interim_report.py` | datepicker, Angular radios, strict text sanitation |
| Claim documents | `claim_documents.py`, `DocumentUploadService` | plus row not added, dropdown label mismatch, file attach not retained |
| Claim assessment | `claim_assessment.py` | selector drift, readonly/conditional fields, upload label mismatch |
| New India | `app/portals/newindia/*` | incomplete phases, selector drift, unverified DOM behavior |

## DOM Debug Strategy

Use `dump_visible_fields(page, tab_name, log_cb)` from `form_helpers.py` only when diagnosing. It writes full page HTML to `logs/`.

When selectors fail:

1. Inspect live DOM or dump.
2. Prefer stable IDs or `name`/`ng-model`.
3. Add selector alternatives in the portal-specific selector area.
4. Preserve existing selectors when adding fallbacks.
5. Avoid broad text selectors that can click wrong elements.

## Regression Risks

- Changing shared `safe_fill*` helpers can break both UIIC and New India.
- Changing `load_field_mapping()` merge behavior can invalidate user overrides.
- Changing `ClaimData` defaults can alter automation output.
- Changing tab wait duration can race Angular rendering.
- Changing file upload row logic can break large file alert handling.
- Changing document mapping load semantics can hide user mappings or bundled defaults.

## Tests

Tests live in `tests/test_automation.py`. They cover many low-level behaviors:

- junk detection
- value cleaning
- date formatting
- ClaimData defaults/validation/preview
- text sanitization
- amount rounding
- mobile cleaning
- field/doc mapping integrity
- selectors and cross-module consistency
- folder scanner and upload labels

Recommended command:

```bash
uv run pytest
```

If `uv` is unavailable, use the repo's Python environment. In this environment `python` may not exist while `python3` does.

## Known Current Caution

New India Phase 3 imports and compiles, but its selectors and required-field behavior still need live portal validation before the phase is considered stable.
