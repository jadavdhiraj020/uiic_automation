# ClaimData Model

## Purpose

`ClaimData` in `app/data/data_model.py` is the single source of truth after extraction. The UI preview, validation, and automation modules all consume this object.

## Model Responsibilities

- Store UIIC claim fields.
- Store New India additional fields.
- Store extracted document paths.
- Store extraction logs and source coordinates.
- Validate required fields based on active portal.
- Render portal-aware preview rows.
- Provide a short summary string.

## Data Flow

```text
extract_claim_data()
  -> ClaimData fields
  -> _excel_coords
  -> _excel_logs

scan_folder()
  -> claim.claim_doc_files
  -> claim.assessment_files

HomePage.update_data()
  -> claim.validate()
  -> claim.all_fields_for_preview()

AutomationEngine.run()
  -> portal modules read claim fields
```

## Important Defaults

String fields generally default to `""`.

Amount fields generally default to `"0"`.

Important exceptions:

- `type_of_settlement` defaults to `"Partial Loss"` for UIIC non-total-loss motor claims.
- `odometer` and New India `odometer_reading` default to `"0"`.

Do not treat `"0"` as missing for amount fields. Several helpers and tests exist specifically to preserve zero filling.

## UIIC Field Groups

- Identification: `claim_no`, `payment_to`
- Interim report: survey date/time/place, mobile/email, settlement type, observation, initial loss
- Claim assessment parts: age depreciation, 50 percent depreciation, nil depreciation, GST amount
- Labour and other charges: labour, towing, spot repairs, excesses, salvage
- Invoice/report details
- Surveyor charges
- File paths: `claim_doc_files`, `assessment_files`

## New India Field Groups

- Vehicle details
- Registration Certificate (`reference_no`)
- Accident details
- Driver details
- FIR details
- Bank details (`bank_payment_to` - Single Source of Truth determined during extraction)
- Assessment and invoice (`vendor_invoice_date`, `vendor_invoice_number` from PDF extraction)
- Add-on covers and deductions

These fields are additive and must not change UIIC behavior.

## Validation

`validate()` calls:

```text
active portal == "newindia"
  -> _validate_newindia()
else
  -> _validate_uiic()
```

UIIC critical fields include:

- Date of Survey
- Place of Survey
- Initial Loss Amount
- Final Report No
- Total Claimed Amount

UIIC warnings include missing claim number, survey time, workshop invoice, observation, files, or zero labour.

New India validation uses a mandatory field list covering claim, vehicle, accident, driver, FIR, bank, invoice, and primary assessment fields. Optional fields produce warnings.

## Preview Rows

`all_fields_for_preview()` calls portal-specific preview functions. Each row is:

```python
(display_label, value, is_critical, source_coord)
```

UI uses `is_critical` to color missing rows and count missing critical fields. If a field is added but not included in preview, the user cannot inspect it before automation.

## Source Tracking

`_excel_coords` maps field name to source, for example:

```text
R12C5 (Sheet1)
PDF Source
Calculated
Fixed Value
Fallback Configuration
```

`_excel_logs` contains user-visible extraction history. These logs are appended to the progress UI after folder processing.

## Safe Modification Guidance

- Add fields additively.
- Keep UIIC field names stable.
- Update validation and preview together.
- Update field mappings for every portal that should extract the new field.
- Add automation use only after preview shows the value.
- Never change amount defaults from `"0"` without reviewing tests and portal behavior.

