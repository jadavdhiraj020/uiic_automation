# Universal Survey Report Reader V1

Base branch: `Feat/pc-lock-up-security`

## Goal

Allow the existing standalone App-3 to accept a main survey report in:

- existing Excel format (.xls/.xlsx/.xlsm)
- text PDF
- scanned PDF through the app's existing local RapidOCR stack

The existing portal automation remains the consumer of the same `ClaimData` object.

## Safety / compatibility

- Existing Excel extraction remains routed to the existing `excel_reader.py`.
- UIIC, OIC, New India, PC-lock/licensing, Web Sync, and portal selectors are not replaced.
- PDF-only cases skip Excel-only background assessment/report generation.
- Missing or uncertain PDF values are left blank unless an existing configured portal fallback applies.
- For UIIC PDF input, missing survey time stays blank; it is not replaced by the legacy Excel-only 11:00 fallback.
- For UIIC PDF input, ordinary missing/manual-review fields are warnings so the visible portal run can continue. Existing Excel hard-validation behavior is unchanged.
- OIC/New India mandatory-field validation is intentionally unchanged in V1.
- A blank PDF label never consumes the following line automatically; V1 prefers a safe blank over a wrong portal value.
- Human final review/submission remains unchanged.

## Important V1 limitation

Variable Parts/Labour/GST table extraction from arbitrary PDF layouts is **not universal in V1**.
Existing Excel-based assessment generation remains unchanged. This should be implemented and tested separately after simple/header field extraction is validated.

## Windows test

Do not merge into the working branch yet.

From an existing local clone:

```powershell
git fetch origin
git switch feature/universal-report-reader-v1
uv pip install -r requirements.txt
uv run python main.py
```

Test first with a copied/dummy claim folder.

### Excel regression test

Use a claim that already works on `Feat/pc-lock-up-security`.

Expected:
- same Excel is selected
- same values are previewed
- existing portal flow behaves the same

### PDF-only test

Use a copied test folder that contains the survey report PDF but no main Excel workbook.

Expected:
- app selects the survey report PDF as the data source
- confidently found values appear in the preview
- missing values remain blank / produce warnings
- scanned PDFs use local OCR when there is no extractable text
- no final insurer submission should be made during the first validation

## Test samples already considered

The V1 parser was designed around:
- current App-3 Excel report structure
- a different surveyor PDF with blank Claim No.
- a different surveyor PDF containing multiple label/value pairs on one line
- combined date/time text such as `11/04/202610:30 AM`

## Do not merge until

1. current Excel regression passes
2. PDF-only preview values are checked manually
3. visible portal fill is checked without Final Submit
4. UIIC visible-portal PDF fill is checked with no Final Submit
5. OIC/New India regressions are run with reports that satisfy their existing mandatory-field rules
