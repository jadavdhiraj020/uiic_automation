# Config System

## Purpose

Configuration controls portal URLs, credentials, timing, Excel field extraction, document mapping, and PDF invoice label extraction.

## Config Files

```text
settings.json
  Runtime settings, credentials, timing, PDF labels.

field_mapping.json
  ClaimData field -> Excel label/sheet/offset extraction rules.

doc_mapping.json
  Filename keyword -> portal document type mapping.
```

There are legacy defaults in `app/config/` and portal-specific defaults in `app/portals/<portal_id>/config/`.

## Load/Save Utilities

Module: `app/utils.py`

Important functions:

- `load_settings()`, `save_settings()`
- `load_field_mapping()`, `save_field_mapping()`, `reset_field_mapping()`
- `load_doc_mapping()`, `save_doc_mapping()`, `reset_doc_mapping()`
- `settings_paths()`, `field_mapping_paths()`, `doc_mapping_paths()`
- `resource_path()`, `user_data_dir()`

All path functions become portal-aware if the portal registry is available and an active portal is set.

## Settings Precedence

`load_settings()`:

```text
bundled default settings
  + user settings override
  = runtime settings
```

`save_settings(overrides)` merges overrides into current loaded settings and writes the user settings file.

## Field Mapping Precedence

`load_field_mapping()` deep-merges per field:

```text
bundled field config for each field
  + user field override
  = merged field config
```

This preserves new bundled keys such as `allow_text_values` when older user mappings exist.

## Document Mapping Precedence

`load_doc_mapping()` currently returns the user doc mapping wholesale if it exists, otherwise bundled defaults.

Warning: this is less robust than field mapping. A stale user doc mapping can hide newly added bundled document types, `expected_claim_docs`, or `other_slots`.

## Field Mapping Schema

Typical entry:

```json
{
  "date_of_survey": {
    "sheet": "ALL",
    "search_labels": ["Date and Time of Survey"],
    "row_offset": 0,
    "col_offset": 4
  }
}
```

Supported keys:

- `sheet`: workbook sheet name or `"ALL"`.
- `search_label`: single label or legacy list.
- `search_labels`: preferred list of fallback labels.
- `row_offset`: row movement from matched label.
- `col_offset`: first value hint to try.
- `allow_text_values`: accept text values that would normally look like labels.
- `allow_literal_values`: accept literal yes/no.
- `fallback_value`: set when extraction fails.

## Document Mapping Schema

```json
{
  "claim_documents_tab": {
    "Driving License": ["driving_license", "driving", "dl"]
  },
  "claim_assessment_tab": {
    "invoice": ["final_invoice", "invoice"]
  },
  "expected_claim_docs": ["PAN Card"],
  "other_slots": ["Other 1", "Other 2", "Other 3"]
}
```

Keys in `claim_documents_tab` are portal dropdown labels. Keys in `claim_assessment_tab` are internal assessment slot keys used by upload modules.

## Settings UI Save Behavior

`SettingsPage._save_all()`:

- Loads current settings.
- Updates only known UI-controlled keys.
- Saves merged settings.
- Rebuilds field mapping rows from table values.
- Rebuilds document mapping for the two main mapping sections while preserving other schema keys.

## Security Warning

Settings files currently contain credentials in plaintext. Avoid committing real credentials and prefer user AppData overrides for local secrets. Documentation should never repeat actual credential values from config files.

