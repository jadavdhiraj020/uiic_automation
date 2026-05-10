# Extraction Pipeline

## Purpose

The extraction pipeline converts a user-selected claim folder into one populated `ClaimData` instance plus document file mappings. It is intentionally label-driven and folder-driven, not fixed-cell driven.

## Pipeline Flow

```text
Claim folder path
  -> scan_folder(folder)
       - find Excel workbook
       - classify files using doc_mapping.json
       - generate vehicle photo copies when needed
       - resolve reinspection report from PDF/excel sheet
  -> extract_claim_data(excel_path, config_dir)
       - load active portal field mapping
       - scan sheets for labels
       - clean/format values
       - calculate derived values
       - populate ClaimData
  -> ClaimFolderService._extract_pdf_invoice_data()
       - parse invoice PDF using pdfplumber
       - OCR fallback if configured libraries exist
       - override workshop invoice no/date when found
  -> attach scan_result.claim_doc_files and assessment_files
  -> UI preview and validation
```

## Folder Scanner

Module: `app/data/folder_scanner.py`

Responsibilities:

- Find the first `.xls`, `.xlsx`, or `.xlsm` file.
- Classify document files by filename keywords from `load_doc_mapping()`.
- Separate claim document uploads from assessment uploads.
- Track skipped files, unknown files, and expected document gaps.
- Generate 4 vehicle photo copies from files beginning with `vehicle` or misspelled `vehical`.
- Extract Sheet 7 as reinspection report when a user PDF is not already present.
- Generate a cancelled cheque fallback from invoice when configured and missing.

## Document Matching Strategy

The scanner normalizes names to lowercase and treats spaces/hyphens as underscores. Keywords are flattened and sorted longest-first so specific keywords win before broad ones.

Short keywords with length <= 3 use word-boundary matching to prevent false positives, for example `fir` should not match inside `confirm.pdf`.

```text
filename -> normalized filename
  -> assessment mapping first
  -> claim document mapping second
  -> other_* sequential slots
  -> unknown_files
```

Assessment files are matched before claim documents because names like `invoice` have specific assessment meaning.

## Reinspection Report Extraction

Order of preference:

1. User-provided PDF whose name matches reinspection keywords.
2. Existing generated `Re-Inspection Report format.pdf` or `.xlsx`.
3. Excel COM export of Sheet 7 to PDF using multiple strategies.
4. openpyxl fallback that saves only Sheet 7 as `.xlsx`.

This has Windows-specific behavior because PDF export uses Microsoft Excel COM through `win32com`.

## Excel Reader

Module: `app/data/excel_reader.py`

The reader loads active portal field mapping through `load_field_mapping()`. The `config_dir` argument is currently not the actual source of truth; active portal state controls which mapping file is loaded.

For each field:

```text
field_mapping entry
  -> sheet: "ALL" or sheet name
  -> search_labels / search_label
  -> row_offset and col_offset
  -> allow_literal_values / allow_text_values
  -> _search_label()
  -> _extract_value()
  -> set ClaimData.<field>
```

## Label Search Strategy

`_search_label()` scans all cells in the configured sheet(s):

1. Normalize label and cell whitespace.
2. Match label text with word-boundary protection.
3. Try inline values in the same cell, for example `Mobile: 987...`.
4. Move by `row_offset`.
5. Try `col_offset` as a hint.
6. Scan right across the row for first non-junk value.
7. Do not scan down automatically when `row_offset=0`, to avoid capturing unrelated data.

## Value Cleaning

Important behaviors:

- `0` and `0.0` are valid values and must not be discarded.
- Junk includes empty values, `Rs`, separators, common labels, and pure text labels unless text is explicitly allowed.
- Dates are normalized to `DD/MM/YYYY`.
- Excel serial dates are converted for `.xls` paths when possible.
- `allow_text_values` bypasses normal junk text rejection for fields like place, owner, model, bank address, etc.
- `allow_literal_values` accepts literal yes/no values.

## Derived Values

The reader currently derives several values:

- `surveyor_observation` is set to fixed value `"ok"` before generic extraction.
- `date_of_survey` may also produce `time_hh` and `time_mm` by parsing adjacent time text.
- `expected_completion_date` is synchronized to `date_of_survey`.
- `initial_loss_amount` becomes 75 percent of the extracted Excel value, rounded to rupees.
- `total_claimed_amount` is calculated from traveling expenses, professional fee, daily allowance, and photo charges.
- `payment_to` is detected by scanning workbook text for insured/repairer/favour phrases if not directly mapped.

## PDF Invoice Extraction

Module: `app/ui/services/claim_folder_service.py`

After Excel extraction, the service looks for assessment file key `invoice`. If present:

- `pdfplumber` extracts text from all pages.
- If text is missing, optional OCR fallback uses `pdf2image` and `pytesseract`.
- Invoice number and date labels come from settings keys:
  - `pdf_invoice_no_labels`
  - `pdf_invoice_date_labels`
- Successful extraction overrides:
  - `claim.workshop_invoice_no`
  - `claim.workshop_invoice_date`
  - source coordinates become `"PDF Source"`

## Debugging Extraction

Check logs for:

- `DOCUMENT SCAN SUMMARY`
- `Excel read complete`
- `[FOUND]`, `[MISSING]`, `[FALLBACK]`, `[MATH]`
- `Excel Data Sources Map`

Most extraction bugs are mapping bugs, not parser bugs. First inspect active portal, field label, sheet name, offset, and whether the field needs `allow_text_values`.

