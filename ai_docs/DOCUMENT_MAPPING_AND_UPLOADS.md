# Document Mapping And Uploads

## Purpose

This document explains how files in the claim folder become portal upload rows, how document type labels are selected, and where upload regressions usually occur.

## Data Flow

```text
folder files
  -> scan_folder()
  -> load_doc_mapping()
  -> claim_doc_files
  -> assessment_files
  -> ClaimData
  -> claim_documents.py / claim_assessment.py
  -> Playwright file inputs
```

## Mapping Files

Active portal document mapping is loaded through `app.utils.load_doc_mapping()`.

Locations:

```text
UIIC:
  app/portals/uiic/config/doc_mapping.json

New India:
  app/portals/newindia/config/doc_mapping.json

Legacy fallback:
  app/config/doc_mapping.json
```

User overrides are saved in AppData under the active portal.

## Mapping Schema

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

Important distinction:

- `claim_documents_tab` keys are portal dropdown labels.
- `claim_assessment_tab` keys are internal slot keys used by automation modules.

## Folder Scan Classification

`scan_folder()` uses this order:

1. Ignore known generated system files.
2. Generate vehicle photo copies if source file starts with `vehicle` or `vehical`.
3. Prefer user-provided reinspection PDF.
4. Find first Excel workbook.
5. Resolve generated or extracted reinspection report.
6. Queue files beginning with `other`.
7. Match assessment keywords first.
8. Match claim document keywords second.
9. Put unmatched files in `unknown_files`.
10. Assign queued `other` files to configured Other slots.
11. Generate cancelled cheque fallback from invoice when configured and missing.

## Keyword Matching Rules

- Filename is normalized to lowercase.
- Spaces and hyphens become underscores.
- Longest keyword wins.
- Short keywords with length <= 3 require word boundaries.
- Duplicates keep the first file and skip the later one.

## UIIC Claim Documents Upload

Modules:

- `app/automation/claim_documents.py`
- `app/automation/services/document_upload_service.py`

Workflow:

```text
click Claim Documents tab
  -> set verification radios
  -> set payment option from claim.payment_to
  -> build queue from claim.claim_doc_files
  -> wait for upload panel
  -> row 0 uses existing row
  -> later rows click plus
  -> select doc type
  -> attach file
  -> accept portal popups
  -> verify visible row retained file
  -> retry row if file was lost
  -> upload summary
```

## UIIC Assessment Upload

Module: `app/automation/claim_assessment.py`

Internal assessment slot keys:

```text
assessment_report   -> Upload Assessment Report
survey_report       -> Upload Survey Report
estimate            -> Upload Estimate
invoice             -> Upload Invoice
reinspection_report -> Upload Re-Inspection Report
```

The upload logic finds file inputs by label/row scanning and has several fallbacks:

1. `li.clearfix` row filtered by upload label.
2. JS DOM scan through rows and labels.
3. Playwright filter.
4. Label parent/grandparent traversal.
5. XPath following input fallback.

## New India Upload Status

New India has document mappings, but portal-specific upload automation is not implemented yet. Do not reuse UIIC upload selectors blindly because New India DOM and document upload semantics may differ.

## Common Upload Failures

| Failure | Likely Cause | Fix Direction |
| --- | --- | --- |
| Dropdown type not found | portal label changed or mapping key wrong | update doc mapping key or selection fallback |
| Plus button does not add row | DOM changed, click target hidden | update `DocumentUploadService.click_plus()` |
| File input does not retain file | portal validation/popup/rerender | increase wait, inspect popup, retry strategy |
| Wrong document classified | keyword collision | add longer/specific keyword first |
| Expected doc missing | filename does not match keywords | rename file or update mapping |
| Reinspection not uploaded | Sheet 7 export failed or keyword mismatch | inspect scanner logs |

## Safe Modification Guidance

- Add keywords, do not remove old ones unless proven wrong.
- Keep short keywords rare.
- Preserve upload verification after file attach.
- Preserve dialog/modal dismissal.
- Keep assessment slot keys stable unless all references are updated.
- When adding New India upload, create portal-specific upload service or module.

