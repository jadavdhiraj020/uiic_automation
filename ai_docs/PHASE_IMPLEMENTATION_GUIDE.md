# Phase Implementation Guide

## Purpose

This guide explains how to safely continue phased development, especially New India, without destabilizing Website 1 UIIC.

## Phase Philosophy

Each phase should be independently reviewable and manually verifiable in the browser. The app should pause at safe boundaries instead of racing into unverified portal sections.

Recommended phase shape:

```text
1. Add/confirm fields and mappings.
2. Show extracted values in preview.
3. Add portal-specific selectors/helper.
4. Implement one portal section.
5. Log every filled field with source.
6. Pause for manual review.
7. Add regression tests for shared helpers.
```

## Existing UIIC Phases

UIIC production flow is already implemented:

1. Login with OCR CAPTCHA.
2. Worklist navigation.
3. Interim Report.
4. Claim Documents.
5. Claim Assessment.
6. Manual review/final submit.

These should be treated as stable baseline behavior.

## New India Current Phases

### Phase 1: Login

Implemented in `app/portals/newindia/automation/login_module.py`.

Behavior:

- Opens New India login page.
- Fills username/password.
- Waits up to 30 seconds for manual CAPTCHA/login.
- Detects success by URL change away from `IntermediaryLogin.html`.

### Phase 2: Navigation

Implemented in `app/portals/newindia/automation/navigation_module.py`.

Behavior:

- Clicks Worklist nav.
- Selects filter criteria `Claim No.`.
- Types claim number with human-like delay.
- Clicks Filter.
- Clicks edit icon.

### Phase 3: Quick Update Details

Draft implemented in `app/portals/newindia/automation/quick_update_module.py`.

Behavior intended:

- Select date of survey radio or Others.
- Fill time/place.
- Set mandatory yes/no radios.
- Fill remarks, mobile, email, expected completion date.
- Pause for manual review.

Current caution:

- The date helper import has been fixed, but Quick Update selectors and required-field behavior still need live portal verification.

## Suggested New India Next Phases

```text
Phase 3a
  Fix date formatter dependency.
  Verify Quick Update selectors against live DOM.
  Add source-aware logging.

Phase 4
  Vehicle Details section.

Phase 5
  Accident and Driver Details.

Phase 6
  FIR and Bank Details.

Phase 7
  Invoice/Assessment/Add-on fields.

Phase 8
  New India document upload.

Phase 9
  End-to-end review pause and regression suite.
```

## Implementation Checklist For Any Phase

- Confirm active portal ID is used.
- Keep selectors portal-specific.
- Avoid modifying UIIC selectors.
- Add new `ClaimData` fields only if needed.
- Add or update `app/portals/newindia/config/field_mapping.json`.
- Update New India preview rows.
- Update New India validation only if the phase truly requires the field.
- Add clear logs for every filled field.
- Check `stop_cb()` between major substeps.
- End with a manual review boundary for early phases.

## No-Large-Rewrite Rule

Do not rewrite the engine or UI to support a phase. Add narrow portal-specific modules and branch at step boundaries. Shared abstractions should come only after at least two portals genuinely use the same behavior.
