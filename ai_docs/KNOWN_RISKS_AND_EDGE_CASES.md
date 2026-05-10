# Known Risks And Edge Cases

## Current Known Risks

### New India Phase 3 DOM Validation

`app/portals/newindia/automation/quick_update_module.py` now imports successfully, but the Quick Update selectors and required-field behavior still need live portal validation.

### Plaintext Credentials

Bundled `settings.json` files contain credentials. Treat them as secrets and avoid including actual values in docs, logs, screenshots, or commits.

### Stale User Config Overrides

User AppData config can override bundled defaults. Field mapping deep-merges, but doc mapping does not. A stale user doc mapping may hide new bundled document mapping keys.

### Portal DOM Drift

Both UIIC and New India are external portals. IDs, names, Angular models, modal behavior, and upload row structure can change without code changes here.

## Extraction Edge Cases

- Excel with multiple workbooks: first Excel file wins, later Excel files are skipped.
- Text values may be rejected as junk unless `allow_text_values` is set.
- Pure labels with no nearby value will not scan downward automatically.
- Date cells with time text need regex extraction.
- Excel stores phone numbers as floats; mobile cleaning handles trailing `.0`.
- `initial_loss_amount` is transformed to 75 percent.
- `total_claimed_amount` is calculated, not directly trusted.
- Payment target may be inferred from workbook text if not mapped.

## Document Edge Cases

- Files over 2 MB are not skipped, but portal may show alert popups.
- Short keywords like `fir`, `rc`, `pan` require word-boundary matching.
- Files beginning with `other` are assigned only up to configured `other_slots`.
- Duplicate document mapping keeps the first file and skips later duplicates.
- Vehicle photo source file can generate four copies if directional photos are missing.
- Reinspection extraction depends on Excel COM for best PDF output.

## Automation Edge Cases

- UIIC login may open a new tab and close/rerender the login tab.
- Worklist rows may appear before action buttons render.
- Angular inputs may look filled but not update model unless events are dispatched.
- Datepickers may open overlays and intercept input.
- Upload file inputs may lose selected file after portal scripts process it.
- Modals and alerts may block subsequent clicks.
- Readonly fields like UIIC odometer should be skipped.
- Some fields are optional and should fail soft.

## Regression Edge Cases

- `"0"` values must remain valid.
- Empty string is missing; `"0"` is not.
- Changing text sanitization can cause portal validation errors or remove meaningful addresses.
- Changing date formatting can break Angular date fields.
- Changing `safe_select` can break Angular `number:` and `string:` option prefixes.
- Changing `click_tab` wait can race render timing.
- Changing thread cleanup can freeze or crash UI after automation.

## Build Edge Cases

- Frozen mode uses `sys._MEIPASS` for packaged resources.
- Writable files must go under AppData through `user_data_dir()`.
- Playwright browser path is set in frozen mode if bundled.
- PaddleOCR requires Paddle 2.x and model/DLL packaging care.
- Windows Excel COM is only available where Microsoft Excel is installed.
