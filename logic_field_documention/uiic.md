# UIIC Portal Automation: Complete Field Guide

**App3 · United India Insurance Company (UIIC) · Motor OD Surveyor Portal**

This guide explains, in plain language, every field App3 fills on the UIIC portal: where each value comes from, whether it is copied directly or worked out, what App3 changes before entering it, and what happens when it is missing.

> Based on the `uiic_automation` repository (`main` branch, reviewed on 28 November 2026). Companion to [nia.md](nia.md) and [oic.md](oic.md).

---

## Contents

1. [How to read this guide](#1-how-to-read-this-guide)
2. [Where the data comes from](#2-where-the-data-comes-from)
3. [The journey through the portal](#3-the-journey-through-the-portal)
4. [Login and finding the claim](#4-login-and-finding-the-claim)
5. [Interim Report](#5-interim-report)
6. [Claim Documents](#6-claim-documents)
7. [Claim Assessment](#7-claim-assessment)
8. [All value changes at a glance](#8-all-value-changes-at-a-glance)
9. [Checks before the run starts](#9-checks-before-the-run-starts)
10. [When a field cannot be filled & logs](#10-when-a-field-cannot-be-filled--logs)
11. [Settings you can change](#11-settings-you-can-change)
12. [Points worth checking](#12-points-worth-checking)
13. [Appendix A: Excel labels App3 looks for](#appendix-a-excel-labels-app3-looks-for)
14. [Appendix B: Survey PDF extraction rules](#appendix-b-survey-pdf-extraction-rules)

---

## 1. How to read this guide

Every field is tagged with one method:

| Tag | Method | Meaning |
| --- | --- | --- |
| 📄 | **Direct** | Copied from the survey report as written (extra spaces trimmed). |
| 🔧 | **Cleaned** | Tidied before entry: date format, digits only, whole rupees, suffix extracted, or special symbols stripped. |
| 🧮 | **Calculated** | Worked out by App3 from other values (for example 75% initial loss, or Survey Fee + Re-inspection Fee). |
| 🔍 | **Matched** | App3 picks the matching option from the portal's dropdown list. |
| ⚙️ | **Setting** | A value from App3 **Settings** (`Automation Defaults` or `General`). You can change it. |
| 🔒 | **Fixed** | Always the same value or radio choice, built into App3. |
| 📎 | **File** | A document from the claim folder is attached. |
| ⏭️ | **Skipped** | The portal locks this field or App3 leaves it for manual handling. |

All dates are entered on UIIC as **DD/MM/YYYY** (for example `15/01/2024`), whatever format they had in the report.

---

## 2. Where the data comes from

### 2.1 Two possible sources

| Source | When it is used | How App3 reads it |
| --- | --- | --- |
| **Excel survey report** | Used first whenever the claim folder has an Excel file (`.xlsx`, `.xls`, `.xlsm`). Because UIIC's shipped **Main Excel Keywords** list is empty, App3 automatically picks the **first valid Excel file alphabetically** (skipping `~$` lock files and app-generated workbooks). | App3 searches the configured sheet (`ALL` or `Sheet1`) for each label in [Appendix A](#appendix-a-excel-labels-app3-looks-for). It checks inline text first (for example `"Mobile: 9876543210"`), then `col_offset` to the right, then scans rightward on the same row. See [Excel reader](../app/data/excel_reader.py). |
| **Survey PDF** (final survey report, typed or scanned) | Used when the claim folder has no Excel workbook. | App3 reads text with `pdfplumber` and falls back to local **RapidOCR** if the PDF has no selectable text. Secondary PDFs in the same folder with strong survey/fee/GST markers supplement missing fields only if their Claim No. and Vehicle Registration No. agree. See [PDF reader](../app/data/pdf_report_reader.py). |

**Files prepared automatically on Excel scans**

- **Sheet 1 → `survey_report.pdf`** (and copied to **`assessment_report.pdf`**), formatted with the selected **Print Mode** (`scale_percentage` at `80%` or `column_range` `A:L`).
- **Sheet 2 → `survey_fee_bill.pdf`** using the same Print Mode settings.
- **Sheet 3 → `reinspection_report.pdf`** when no user-provided re-inspection file is already in the folder.
- **Vehicle Photographs:** the first file matching `photo_sheet`, `vehicle`, or `vehical` is copied 4 times as `vehicle_photo_1` through `vehicle_photo_4` (Front, Rear, Left, Right).
- **No merging:** UIIC uploads individual document rows directly (`requires_document_merge = False`), so App3 does **not** create a merged PDF. See [folder scanner](../app/data/folder_scanner.py) and [claim folder service](../app/ui/services/claim_folder_service.py).

### 2.2 Files App3 looks for in the claim folder

| Portal Section | Document / Slot | File name contains (keywords) |
| --- | --- | --- |
| **Claim Documents** | Driving License | `driving_license`, `driving`, `dl` |
| **Claim Documents** | RC Book | `rc_book`, `rc book`, `rcbook`, `registration_certificate`, `registration` |
| **Claim Documents** | Vehicle Photograph (Front / Rear / Left / Right) | `photo_sheet`, `vehicle`, `vehical` (copied into `vehicle_photo_1`–`4`) |
| **Claim Documents** | Road Permit for Commercial Vehicle | `road_permit`, `route_permit`, `permit` |
| **Claim Documents** | Vehicle Fitness Certificate | `fitness_certificate`, `fitness` |
| **Claim Documents** | FIR | `fir`, `police_report` |
| **Claim Documents** | CSR and Certificate | `csr` |
| **Claim Documents** | PAN Card | `pan_card`, `pan` |
| **Claim Documents** | Aadhaar Card | `aadhaar`, `aadhar`, `uid` |
| **Claim Documents** | Cancelled Cheque Or Bank Details | `cancel_check`, `cancel_cheque`, `cancelled_cheque`, `cancelled`, `cheque`, `bank_detail`, `bank` |
| **Claim Documents** | Claim Form | `claim_form`, `claimform` |
| **Claim Documents** | Discharge or Satisfaction Voucher | `discharge_voucher`, `discharge`, `satisfaction_voucher`, `voucher` |
| **Claim Documents** | CKYC Form | `ckyc`, `kyc_form`, `kyc` |
| **Claim Documents** | Investigation Report 1 | `investigation`, `inv_report` |
| **Claim Documents** | Other 1 / Other 2 / Other 3 | Any file whose name **starts with `other`** (assigned in order, up to 3 slots) |
| **Claim Assessment** | Upload Survey Report | `survey_report`, `survey` (or generated `survey_report.pdf`) |
| **Claim Assessment** | Upload Assessment Report | Copy of `survey_report` (`assessment_report.pdf`) |
| **Claim Assessment** | Upload Estimate | `repair_estimate`, `estimate` |
| **Claim Assessment** | Upload Invoice | `final_invoice`, `invoice` |
| **Claim Assessment** | Upload Re-Inspection Report | `re_inspection`, `reinspection` (or generated `reinspection_report.pdf`) |

> Files larger than **2.0 MB** are compressed automatically into temporary files before upload (target ~1.9 MB). See [document utils](../app/automation/services/document_utils.py).

---

## 3. The journey through the portal

App3 opens a visible Chrome window and keeps it open when finished so you can review every tab and click **Final Submit** manually. See [automation engine](../app/automation/engine.py).

| Order | Stage | What happens |
| :---: | --- | --- |
| 1 | **Login** | Username, password, canvas CAPTCHA solved via local RapidOCR |
| 2 | **Navigate to Claim** | Worklist → Claim Type `Non Maruti` → Filter by Claim No. → click Action |
| 3 | **Interim Report** | Settlement type, survey date/time, place, Yes radios, loss amount, contact info, observations & remarks |
| 4 | **Claim Documents** | Verification Yes radios, Cashless/Reimbursement option, add rows and attach each document |
| 5 | **Claim Assessment** | Nil Dep & parts, labour, workshop & fee invoice, other charges, report details, surveyor charges, declaration, remarks, and 5 assessment PDF uploads |
| 6 | **Complete** | Chrome stays open on `READY FOR FINAL SUBMISSION` for your manual review |

---

## 4. Login and finding the claim

### 4.1 Login

| Field | Method | How it is handled | Source |
| --- | --- | --- | --- |
| **Username** | ⚙️ Setting | From UIIC **Settings → General**. | [login_module.py](../app/automation/login_module.py) |
| **Password** | ⚙️ Setting | From UIIC **Settings → General** (masked as `********` in logs). | [login_module.py](../app/automation/login_module.py) |
| **Captcha** | 🧮 Calculated | Captures `canvas#captcha` screenshot in memory and reads it with local RapidOCR (no temp files on disk). Retries up to `Captcha Max Retries` (General setting; falls back to `5` if unset) and stops early if a wrong-password error appears. | [captcha_solver.py](../app/automation/captcha_solver.py) |
| **Post-login alert** | 🔒 Fixed | Dismisses any modal `OK` popup after login succeeds. | [login_module.py](../app/automation/login_module.py) |

### 4.2 Worklist Navigation

1. Clicks **Worklist** in the sidebar (or navigates directly to `https://portal.uiic.in/surveyor/data/Surveyor.html#/Worklist`).
2. Selects **Claim Type** = `Non Maruti` (`string:NONMARUTI`).
3. Enters **Claim Number** and clicks **Filter**.
4. Scans table rows across pagination pages (`Next`) until the Claim Number matches, then clicks **Click Here** (with last-cell and JS fallbacks).
5. Switches to the newly opened claim tab if a new tab opens (or stays on the SPA page if it navigated in place). See [navigation_module.py](../app/automation/navigation_module.py).

---

## 5. Interim Report

App3 switches to the **Interim Report** tab and fills fields in this order. See [interim_report.py](../app/automation/interim_report.py) and [form_helpers.py](../app/automation/form_helpers.py).

| # | Portal field | Method | How the value is decided or changed | If missing |
| --- | --- | --- | --- | --- |
| 1 | **Type of Settlement** | 🔍 Matched | Uses `type_of_settlement` (defaults to `"Partial Loss"` in `ClaimData`). | Uses `"Partial Loss"` |
| 2 | **Date of Survey** | 🔧 Cleaned | Parsed to **DD/MM/YYYY** and injected into AngularJS datepicker (`Escape` + `Tab`). | Excel: **Blocks start** · PDF: Warning & skipped |
| 3 | **Time HH** | 🔍 Matched | 2-digit hour (`"11"`). **Excel:** defaults to `"11"` (`11:00`) if survey date exists and time is missing. **PDF:** stays blank if not found in PDF. | Excel: `"11"` · PDF: Left empty |
| 4 | **Time MM** | 🔍 Matched | 2-digit minute (`"00"`). Same rule as Time HH. | Excel: `"00"` · PDF: Left empty |
| 5 | **Odometer Reading** | ⏭️ Skipped | Always skipped unconditionally because the UIIC portal field is read-only. | Skipped |
| 6 | **Place of Survey** | 🔧 Cleaned | Strict cleaning: removes **all** special symbols including commas and dots (`A-Z`, `a-z`, `0-9`, spaces only). | Excel: **Blocks start** · PDF: Warning & skipped |
| 7 | **Yes/No Radios (5)** | 🔒 Fixed | Sets all 5 radios to **Yes** (`Y`): Vehicle Inspected Personally, Survey Completed, DL Applicable, DL Verified, RC Book Verified. | Always **Yes** |
| 8 | **Initial Loss Assessment Amount** | 🧮 Calculated | **75%** of the extracted Excel/PDF initial loss amount, rounded to whole rupees (`40,000` → `30000`). | Excel: **Blocks start** · PDF: Warning & skipped |
| 9 | **Mobile No** | 🔧 Cleaned | Strips country code/spaces to 10 digits starting with `5–9` (`"+91 98765 43210"` → `9876543210`). | Left empty |
| 10 | **Email ID** | 📄 Direct | Trimmed email address from the report. | Left empty |
| 11 | **Expected Completion Date** | 🧮 Calculated | Automatically calculated as **Date of Survey + 1 calendar month**, clamped to valid month-end (`31/01/2026` → `28/02/2026`), entered as `DD/MM/YYYY`. | Left empty |
| 12 | **Surveyor's Observation** | 🔧 Cleaned | Strict-cleaned (letters, numbers, spaces only). Uses **Observation Default** (`Ok` shipped) when not read from report. | Uses **Observation Default** (`Ok`) |
| 13 | **Remarks** | 🔧 Cleaned | Strict-cleaned **Remarks Default** from Settings (`Done` shipped). | Uses **Remarks Default** (`Done`) |

---

## 6. Claim Documents

App3 switches to the **Claim Documents** tab and handles verification, payment type, and document rows. See [claim_documents.py](../app/automation/claim_documents.py) and [document_upload_service.py](../app/automation/services/document_upload_service.py).

| Step | Portal area | Method | How it works |
| --- | --- | --- | --- |
| 1 | **Verification Radios** | 🔒 Fixed | Sets `ynRCBookVerified`, `ynRelevantDamage`, and `ynDrivingLicense` to **Yes** (`Y`), plus any other visible Yes/No radio rows that are unchecked. |
| 2 | **Payment Option** | 🧮 Calculated | If `payment_to` contains `"insured"` → **Reimbursement**; otherwise → **Cashless**. |
| 3 | **Upload Queue** | 📎 File | Loops through every matched entry in `claim_doc_files` (including the 4 `vehicle_photo_1`–`4` copies and any `Other 1/2/3` files). Uses the first existing row, then clicks `+` to add each subsequent row. |
| 4 | **Compression** | 🔧 Cleaned | Any file larger than **2.0 MB** is automatically compressed (target 1.9 MB) before attaching. |
| 5 | **Missing File Fallback** | 🔍 Matched | If a mapped row's file does not exist on disk, App3 selects dropdown **option index 3** (the 4th dropdown item) and marks it `SKIPPED`. |
| 6 | **Verification & Alerts** | 🔒 Fixed | Auto-accepts browser alert dialogs (`dialog.accept()`) and re-checks each visible row after upload; if a row lost its file name, App3 retries attaching it once. |

---

## 7. Claim Assessment

App3 switches to the **Claim Assessment** tab and fills 4 stages before leaving the browser open for your review. See [claim_assessment.py](../app/automation/claim_assessment.py).

### 7.1 Parts & Labour

| # | Portal field | Method | How the value is decided | Special rules |
| --- | --- | --- | --- | --- |
| 1 | **Nil Depreciation** checkbox | 📄 Direct | Checked if `nil_depreciation` is `Yes`, unchecked if `No`. Skipped if missing/unclear. | Determines Parts GST 18% calculation below |
| 2 | **Age Dep (Metal)** | 🔧 Cleaned | From `parts_age_dep_excl_gst`, rounded to whole rupees. | Unsourced PDF zeros are left blank |
| 3 | **50% Dep (Plastic)** | 🔧 Cleaned | From `parts_50_dep_excl_gst`, rounded to whole rupees. | Unsourced PDF zeros are left blank |
| 4 | **Nil Dep** | 🔧 Cleaned | From `parts_nil_dep_excl_gst`, rounded to whole rupees. | Unsourced PDF zeros are left blank |
| 5 | **Parts GST 18%** | 🧮 / 🔧 | **If Nil Dep = Yes:** `Age Dep + 50% Dep + Nil Dep` (rounded whole rupees). **If Nil Dep = No/blank:** uses `parts_gst18_amount` from Excel/PDF directly. | Unsourced PDF zeros are left blank |
| 6 | **Labour (Excl GST)** | 🔧 Cleaned | From `labour_gst18_amount`, rounded to whole rupees. | Unsourced PDF zeros are left blank |
| 7 | **Labour GST 18%** | 🔧 Cleaned | Same value as Labour (Excl GST), rounded to whole rupees. | Unsourced PDF zeros are left blank |

### 7.2 Workshop Invoice, Other Charges, Invoice & Report Details

| # | Portal field | Method | How the value is decided |
| --- | --- | --- | --- |
| 8 | **WS Invoice No** | 🔧 Cleaned | Takes `workshop_invoice_no`, splits at the first space or `(`, and caps at **20 characters** (`"INV-42 (2026)"` → `"INV-42"`). |
| 9 | **WS Invoice Date** | 🔧 Cleaned | `workshop_invoice_date` formatted to **DD/MM/YYYY**. |
| 10 | **Towing Charges** | 🔧 Cleaned | Rounded to whole rupees (defaults to `0` on Excel; blank if unsourced on PDF). |
| 11 | **Spot Repairs** | 🔧 Cleaned | Rounded to whole rupees. |
| 12 | **Voluntary Excess** | 🔧 Cleaned | Rounded to whole rupees. |
| 13 | **Compulsory Excess** | 🔧 Cleaned | Rounded to whole rupees. |
| 14 | **Imposed Excess** | 🔧 Cleaned | Rounded to whole rupees. |
| 15 | **Salvage Value** | 🔧 Cleaned | Rounded to whole rupees. |
| 16 | **Invoice No** | 🔧 Cleaned | Takes `invoice_no`, splits at the first space or `(`, and caps at **20 characters**. |
| 17 | **Invoice Date** | 🔧 Cleaned | `invoice_date` formatted to **DD/MM/YYYY**. |
| 18 | **Report No** | 🔧 Cleaned | Takes `final_report_no` (or `invoice_no` if blank) and keeps **only the last segment** after `/`, `\`, or `-`, preserving leading zeros (`"SUR/2026-27/0042"` → `"0042"`). |
| 19 | **Report Date** | 🔧 Cleaned | `final_report_date` formatted to **DD/MM/YYYY**. If missing, skipped so the portal keeps today's date. |

### 7.3 Surveyor Charges, Declaration, Remarks & Document Uploads

| # | Portal field | Method | How the value is decided |
| --- | --- | --- | --- |
| 20 | **Travel Expenses** | 🔧 Cleaned | `traveling_expenses` rounded to whole rupees. |
| 21 | **Professional Fee** | 🧮 Calculated | **`survey_fee + reinspection_fee`** (from Excel/PDF fee bill), rounded to whole rupees. |
| 22 | **Daily Allowance** | 🔧 Cleaned | `daily_allowance` rounded to whole rupees. |
| 23 | **Photo Charges** | 🔧 Cleaned | `photo_charges` rounded to whole rupees. |
| 24 | **Total Claimed Amount** | 🧮 Calculated | Sum of `traveling_expenses + professional_fee + daily_allowance + photo_charges + sfb_others` (only entered if the portal field is visible and editable; skipped if unsourced on PDF). |
| 25 | **Declaration (`ynPerused`)** | 🔒 Fixed | Set to **Yes** (`Y`). |
| 26 | **Remarks** | 🔧 Cleaned | Strict-cleaned **Remarks Default** from Settings (`Done` shipped). |
| 27 | **Assessment Uploads (5)** | 📎 File | Attaches available files from `assessment_files` (`Upload Assessment Report`, `Upload Survey Report`, `Upload Estimate`, `Upload Invoice`, `Upload Re-Inspection Report`), compressing files over **2.0 MB** and dismissing upload popups automatically. |

---

## 8. All value changes at a glance

| Value | Example from the report | What App3 enters |
| --- | --- | --- |
| Any date | `2026-03-16 00:00:00` · `16-03-2026` · `16.03.2026` | `16/03/2026` |
| Expected Completion Date | Survey on `31/01/2026` | `28/02/2026` (+1 calendar month, clamped) |
| Survey Time (Excel missing) | Survey Date present, Time missing | `11` and `00` (`11:00`) |
| Mobile No | `"+91 98765 43210"` | `9876543210` |
| Place, Observation, Remarks | `"Workshop, Sector-14 (Gurugram)!"` | `"Workshop Sector 14 Gurugram"` (symbols & commas removed) |
| Initial Loss Assessment | `40,000` | `30000` (75%, rounded) |
| Monetary amounts | `"₹12,345.67"` | `12346` (nearest whole rupee) |
| Parts GST 18% (Nil Dep = Yes) | Age `10,000` + 50% `5,000` + Nil `2,000` | `17000` |
| Report No | `"JDB/2026-27/PORTAL/0042"` | `0042` |
| WS Invoice No / Invoice No | `"INV-104 (Main)"` | `INV-104` (max 20 chars) |
| Professional Fee | Survey Fee `3,500` + Re-inspection `1,000` | `4500` |
| Total Claimed Amount | Travel `1,000` + Prof Fee `4,500` + Photo `200` | `5700` |

---

## 9. Checks before the run starts

**Extraction Review** shows missing or flagged fields above the preview table. See [`_validate_uiic`](../app/data/data_model.py).

### 9.1 These block the start (Excel only)

When the source is **Excel**, App3 blocks the run if any of these **5** values is missing:

- **Date of Survey**
- **Place of Survey**
- **Initial Loss Amount**
- **Final Report No**
- **Total Claimed Amount**

> **PDF claims:** When the source is a **PDF**, those 5 missing fields are **downgraded to warnings** so you can still run automation and fill any occasional missing field manually before **Final Submit**.

### 9.2 These only warn (the run continues)

- Claim No not found
- Type of Settlement missing (uses `"Partial Loss"`)
- Survey Time not found (skipped for manual review)
- Workshop Invoice No or Workshop Invoice Date not found
- Surveyor Observation is empty
- No assessment files or no claim documents found in folder
- Labour charges are zero

---

## 10. When a field cannot be filled & logs

- **No floating pause card:** Unlike OIC and New India, UIIC does **not** use the floating `RecoveryDialog` pause card between steps.
- **Automatic retries:** Text/number fields retry once (`retries=1`), and Claim Document file rows retry once if the visible row drops the filename. Any field that still fails is logged with a warning and marked with a red highlight ring on the page (`chrome_hud.py`) while automation continues to the remaining fields.
- **Manual review at the end:** When Claim Assessment finishes, App3 leaves Chrome open (`READY FOR FINAL SUBMISSION`) until you close or finish reviewing.
- **Logs & AI debug report:** The **Logs** tab shows a concise summary by default (`Show details` reveals every field/scan line). The **AI debug report** switch starts **ON** by default at launch and writes `<claim>_run_<time>_<pid>_ai_debug.md` beside `.json`/`.txt` logs in `~/Automations/logs/uiic/`, capturing browser console/network errors and page snapshots when a UIIC field or step fails. See [AI debug report](../app/automation/debug_recorder.py) and [automation engine](../app/automation/engine.py).

---

## 11. Settings you can change

### 11.1 Settings → Automation Defaults (UIIC)

A search bar at the top of **Automation Defaults** filters rows by **Setting**, **Value**, or **Used In** (keeping your search text across portal switches and saving all settings including filtered-out rows). See [settings_page.py](../app/ui/components/settings_page.py) and [automation_defaults.json](../app/portals/uiic/config/automation_defaults.json).

| Setting | Shipped Default | Affects |
| --- | --- | --- |
| **Remarks Default** | `Done` | Interim Report & Claim Assessment `Remarks` |
| **Observation Default** | `Ok` | Interim Report `Surveyor's Observation` fallback |
| **Print Mode** | `Scale Percentage` | Printable survey report, fee bill, and re-inspection PDF exports |
| **Scale Percentage** | `80 %` | Used when Print Mode = Scale Percentage (`25–300 %`) |
| **Column Range** | `A:L` | Used when Print Mode = Column Range |

*(Two additional shipped keys in `automation_defaults.json` — `survey_time_default: "11:00"` and `reinspection_output_filename: "reinspection.xlsx"` — are used during scanning/defaults.)*

### 11.2 Settings → General

Username, Password, Portal URL, Slow-Mo (ms), Timeout (ms), Captcha Max Retries, Upload Wait (ms), Field Wait (ms), and Manual Login Timeout (s). *(UIIC shows an informational card on **PDF Mapping** because UIIC PDF intake uses built-in structured labels rather than custom PDF invoice mapping inputs.)*

---

## 12. Points worth checking

These are actual behaviors in the current UIIC code that are helpful to keep in mind:

| # | Area | What App3 does today |
| :---: | --- | --- |
| 1 | **Odometer Reading** | Always skipped on **Interim Report** because the UIIC portal field is read-only. |
| 2 | **Strict text stripping** | **Place of Survey**, **Surveyor's Observation**, and **Remarks** strip all punctuation (including commas, dots, and hyphens) because UIIC rejects special symbols. |
| 3 | **Whole-rupee rounding** | All monetary amounts on Interim Report and Claim Assessment are rounded to the nearest whole rupee (`12345.67` → `12346`). |
| 4 | **4 vehicle photo copies** | Scanning a folder with a `vehicle` / `photo_sheet` file creates 4 copies (`vehicle_photo_1`–`4`) to fill Front, Rear, Left, and Right slots. |
| 5 | **Missing Claim Document row** | If a mapped file is missing on disk during Claim Documents upload, App3 sets that row's dropdown to **option index 3** and logs it as `SKIPPED`. |
| 6 | **Report No & Invoice No** | **Report No** keeps only the part after the last `/`, `\`, or `-` (falling back to `invoice_no`), while **Invoice No** and **WS Invoice No** cut at the first space or `(` (max 20 chars). |
| 7 | **Nil Depreciation = Yes** | **Parts GST 18%** is automatically set to `Age Dep + 50% Dep + Nil Dep` instead of reading `parts_gst18_amount`. |
| 8 | **2.0 MB upload limit** | Any Claim Document or Claim Assessment file over **2.0 MB** is compressed before upload. |

---

## Appendix A: Excel labels App3 looks for

From [UIIC field mapping](../app/portals/uiic/config/field_mapping.json). Labels are tried in order; App3 reads inline values first, then `col_offset`, then scans rightward on the same row.

| Field | Sheet | Labels tried | Hint (`row`, `col`) | Fallback |
| --- | --- | --- | :---: | --- |
| **claim_no** | `ALL` | `Claim no` · `Claim Number` · `claim_number` · `claim_no` | `(0, 1)` | |
| **date_of_survey** | `ALL` | `Date and Time of Survey` · `Date of Survey` · `Survey Date` | `(0, 4)` | |
| **time_of_survey** | `ALL` | `Time` · `Time of Survey` · `Survey Time` · `time of servey` | `(0, 1)` | `11:00` (Excel) |
| **place_of_survey** | `ALL` | `Place of survey` · `address` *(text allowed)* | `(0, 4)` | |
| **mobile_no** | `Sheet1` | `surveyor_mobile` · `mobile` · `Mobile:` | `(0, 1)` | |
| **email_id** | `Sheet1` | `surveyor_email` · `email` · `e-mail:-` *(also `.com` regex starting at cell `I4`)* | `(0, 1)` | |
| **initial_loss_amount** | `ALL` | `initial loss assessment` · `intial losss` · `intial loss` *(converted to 75%)* | `(0, 1)` | |
| **parts_age_dep_excl_gst** | `Sheet1` | `SUB TOTAL` | `(0, 5)` | `0` |
| **parts_50_dep_excl_gst** | `Sheet1` | `SUB TOTAL` | `(0, 6)` | `0` |
| **parts_nil_dep_excl_gst** | `Sheet1` | `SUB TOTAL` | `(0, 7)` | `0` |
| **nil_depreciation** | `Sheet1` | `Nil Depreciation` *(Yes/No literal)* | `(0, 1)` | |
| **parts_gst18_amount** | `Sheet1` | `SUB TOTAL` | `(0, 8)` | `0` |
| **labour_gst18_amount** | `Sheet1` | `TOTAL (R/R, DENTING, C/W, PAINTING)` | `(0, 1)` | `0` |
| **towing_charges** | `Sheet1` | `TOWING CHARGE` · `TOWING CHARGES` | `(0, 4)` | `0` |
| **voluntary_excess** | `Sheet1` | `voluntry excess` | `(0, 5)` | `0` |
| **compulsory_excess** | `Sheet1` | `Coumpulsary excess` · `excess clause` · `Less Compulsory Excess` | `(0, 1)` | `0` |
| **imposed_excess** | `Sheet1` | `Imposed Excess` · `imposed excess` · `Less Imposed Excess` | `(0, 5)` | `0` |
| **salvage_value** | `Sheet1` | `LESS SALVAGE VALUE` · `Less Salvage Value` · `salvage value` · `Salvage_value` | `(0, 5)` | `0` |
| **invoice_no** | `ALL` | `invoice_no` · `Invoice No` · `Ref:` | `(0, 1)` | |
| **invoice_date** | `ALL` | `invoice_date` · `invoice date` · `Date:` | `(0, 1)` | |
| **workshop_invoice_no** | `ALL` | `workshop_invoice_no` · `Workshop Invoice No` · `Workshop Invoice Number` · `WS Invoice No` · `Work shop invoice` · `Repairer Invoice No` · `Garage Invoice No` · `Workshop Bill No` | `(0, 1)` | |
| **workshop_invoice_date** | `ALL` | `workshop_invoice_date` · `Workshop Invoice Date` · `WS Invoice Date` · `Work shop invoice date` · `Repairer Invoice Date` · `Workshop Bill Date` | `(0, 1)` | |
| **final_report_no** | `ALL` | `Ref:` · `Ref No` · `Ref No:` · `Report No` · `Report No:` · `Final Report No` | `(0, 1)` | |
| **final_report_date** | `ALL` | `Date:` · `Report Date` · `Final Report Date` | `(0, 1)` | |
| **traveling_expenses** | `ALL` | `traveling_expenses` · `conveyance` · `CONVEYANCE CHARGE` · `CONVEYANCE CHARGES` | `(0, 5)` | `0` |
| **survey_fee** | `ALL` | `SURVEY FEE` · `SURVEY FEES` · `survey fee` | `(0, 5)` | `0` |
| **reinspection_fee** | `ALL` | `REINSPECTION FEE` · `RE-INSPECTION FEE` · `reinspection fee` | `(0, 5)` | `0` |
| **daily_allowance** | `ALL` | `DAILY_ALLOWANCE` · `daily allowance` · `DAILY allowances` | `(0, 5)` | `0` |
| **photo_charges** | `ALL` | `photocharges` · `PHOTOGRAPHS` · `PHOTO charge` · `photo charges` | `(0, 5)` | `0` |
| **surveyor_observation** | `ALL` | *(uses **Observation Default** from Automation Defaults)* | `(1, 0)` | `Ok` |

---

## Appendix B: Survey PDF extraction rules

When there is no Excel file, [pdf_report_reader.py](../app/data/pdf_report_reader.py) uses these UIIC-specific rules:

1. **Report selection:** Picks the highest-scoring PDF in the folder (`looks_like_survey_report` rewards markers like `"motor final survey report"`, `"final survey report"`, `"summary of assessment"`, `"vehicle particulars"` and penalizes `"tax invoice"` / `"repair estimate"` / `reinspection` / `survey_fee_bill.pdf`).
2. **Structured-only fields:** Parts buckets (`parts_age_dep_excl_gst`, `parts_50_dep_excl_gst`, `parts_nil_dep_excl_gst`), `parts_gst18_amount`, `labour_gst18_amount`, `workshop_invoice_no/date`, `invoice_no/date`, `final_report_no/date`, and all 5 surveyor fee fields are **excluded** from generic first-label matching and extracted only by UIIC's dedicated table/header parsers (`_apply_uiic_structured_fields` and `_apply_uiic_overflow_fields`).
3. **Workshop invoice vs Fee invoice:** Workshop invoice must come from explicit workshop/repairer/garage labels; surveyor fee invoice comes only from a confirmed fee-bill page (falling back to report Ref/Header Date if no separate fee invoice is printed).
4. **GST & parts tables:** Reads `GST SUMMARY – SPARES / LABOUR` (18% taxable) or classic `GST SUMMARY FOR <vehicle>` rows (`PARTS METALLIC`, `PARTS PLASTIC/RUBBER` / `NON-METALLIC`, `GLASS PARTS`, `LABOUR`).
5. **Nil Depreciation:** Inferred as `Yes` only from explicit wording (`"nil depreciation policy"`, `"nil depreciation cover"`, `"not deducted being nil depreciation"`, `"nil depreciation add on"`).
6. **Secondary PDF supplement:** Other PDFs in the folder containing strong markers (`"final survey bill"`, `"survey fee bill"`, `"summary of assessment"`, `"gst summary"`, `"motor final survey report"`) fill only missing/zero fields after verifying both Claim No. and Vehicle Registration No. match.
7. **Survey Time on PDFs:** Missing time stays blank (no `11:00` fallback on PDF claims).

---

*End of guide.*
