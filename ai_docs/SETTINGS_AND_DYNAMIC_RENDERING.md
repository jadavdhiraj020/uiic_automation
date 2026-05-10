# Settings And Dynamic Rendering

## Purpose

This document explains how settings and mappings are edited dynamically in the UI and how they affect extraction and automation.

## Settings Page Tabs

```text
General
  username/password
  portal URL
  headless
  slow-mo
  timeout
  captcha retries
  upload wait
  field wait

Field Mapping
  ClaimData field -> Excel labels/sheet/offset

Document Mapping
  portal document type -> filename keywords

PDF Mapping
  invoice number/date labels for PDF extraction
```

## Dynamic Portal Settings

Changing the portal dropdown in `MainWindow` changes the active portal. `SettingsPage._load_data()` then reads the settings and mappings for that portal.

The same settings UI therefore edits different AppData files depending on the active portal.

## Dynamic Preview Rendering

After folder scan:

```text
ClaimData.validate()
ClaimData.all_fields_for_preview()
```

Both are portal-aware, so the same Home page can render UIIC or New India field sets.

## Field Mapping UI Details

The table uses:

- pipe-separated labels in a tag-rendered text cell
- fixed field names
- sheet dropdown
- non-negative col offset spinbox

On save, `search_label` is replaced with `search_labels` for edited rows.

## Document Mapping UI Details

The table renders `claim_documents_tab` and `claim_assessment_tab`. On save:

- Only those two sections are replaced.
- Other doc mapping schema keys are preserved.

## Dynamic Rendering Risks

- If active portal is wrong during scan, the wrong mappings populate `ClaimData`.
- If active portal is switched after scan, `MainWindow` clears claim state to avoid cross-portal reuse.
- If a user has stale AppData mappings, the UI will show stale values even if bundled JSON was updated.
- Field mapping deep-merge protects new keys; doc mapping does not.
- New fields require updates in `ClaimData`, config, preview, validation, and automation.

## Safe Settings Changes

- Prefer adding fallback labels to `search_labels` over changing existing labels.
- Use `allow_text_values` for names, addresses, descriptions, makes/models, and bank text fields.
- Keep offsets as hints, not brittle assumptions.
- Add specific document keywords before broad ones.
- Avoid short keywords unless word-boundary behavior is sufficient.

