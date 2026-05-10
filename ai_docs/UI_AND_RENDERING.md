# UI And Rendering

## Purpose

The UI is a PyQt6 desktop shell for folder selection, extracted-data preview, settings management, progress visualization, and log review.

## Main UI Modules

- `app/ui/main_window.py`: application shell, portal dropdown, navigation tabs, action bar, worker lifecycle.
- `app/ui/components/home_page.py`: folder picker, validation banner, stats, extracted data preview.
- `app/ui/components/progress_page.py`: step pipeline, progress bar, live log panel, log filtering.
- `app/ui/components/settings_page.py`: settings, field mapping, document mapping, PDF mapping.
- `app/ui/components/widgets.py`: shared cards, stat cards, search rows, step pipeline, tag/chip delegates.
- `app/ui/services/log_formatter.py`: maps plain log lines to colored HTML for the progress log.

## UI Flow

```text
main.py
  -> QApplication
  -> load app/ui/styles.qss
  -> MainWindow
     -> topbar with portal selector
     -> QStackedWidget pages
     -> action bar start/stop/log buttons
```

## Portal Selector

The topbar dropdown is populated from `list_portals()` in the registry. On change:

1. `set_active_portal(portal_id)`
2. Log portal switch.
3. Update window title.
4. Reload settings page.
5. Clear currently loaded claim and scan state.
6. Clear preview table and stats.

This prevents a `ClaimData` extracted under one portal mapping from being reused under another portal.

## Home Page Rendering

`HomePage.update_data(claim, scan_result)`:

- Calls `claim.validate()` to build error/warning banner.
- Calls `claim.all_fields_for_preview()` to get portal-aware preview rows.
- Renders rows with columns:
  - Field
  - Value
  - Source
  - Status
- Calculates filled count and missing critical count.
- Counts claim documents plus assessment documents.
- Displays scan summary in `doc_status_label`.

Preview row contract:

```python
(label: str, value: str, is_critical: bool, source_coord: str)
```

## Progress Page Rendering

`ProgressPage` keeps `_log_entries` as formatted HTML strings and uses a search box to filter visible entries. Step updates call `StepPipeline.set_step(idx)`.

The log output is HTML, but exported/copied log text comes from `QTextEdit.toPlainText()`.

## Log Formatting

`format_log_html(raw_message, ts)` colors messages by tokens:

- box borders and separators
- `STEP`
- success/failure/warning/skipped keywords
- activity icons/categories

The formatter is deterministic and does not alter actual log file output. `MainWindow._append_log()` writes raw text to AppData `automation.log`.

## Settings Rendering

Settings page tabs:

1. General
2. Field Mapping
3. Document Mapping
4. PDF Mapping

Field mapping table edits:

- Field name is locked.
- Search labels are pipe-separated in a tag-rendered cell.
- Sheet is a dropdown.
- Col offset is a non-negative spinbox.

Document mapping table edits:

- Section and portal doc type are locked.
- Filename keywords are pipe-separated.

## Rendering Warnings

- The UI uses custom widgets/cards and stylesheet-driven states. Large visual refactors should be avoided unless necessary.
- `settings_page._load_data()` is called directly from `MainWindow`, even though it is a private method by convention.
- The preview table depends on `ClaimData.all_fields_for_preview()`, so adding portal fields without updating preview methods makes data invisible in UI.
- Several labels and UI strings still say UIIC even though portal support is expanding. Be careful when renaming; user familiarity and build identity may rely on existing names.

