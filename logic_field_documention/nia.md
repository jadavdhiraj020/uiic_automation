
# New India Assurance Portal Automation: Complete Field Guide

**App3 Â· The New India Assurance Co. (NIA) Â· Motor Claim Survey (Surveyor Worklist)**

This guide explains, in plain language, every field App3 fills on the New India portal: where each value comes from, whether it is copied directly or worked out, what App3 changes before entering it, and what happens when it is missing.

> Based on the uiic_automation repository, main branch, reviewed on 21 November 2026. Companion to the OIC Field Guide.

---

## Contents

1. [How to read this guide](#1-how-to-read-this-guide)
2. [Where the data comes from](#2-where-the-data-comes-from)
3. [The journey through the portal](#3-the-journey-through-the-portal)
4. [Login and finding the claim](#4-login-and-finding-the-claim)
5. [Quick Update](#5-quick-update)
6. [Vehicle Photo Graph](#6-vehicle-photo-graph)
7. [Registration Certificate Details](#7-registration-certificate-details)
8. [Driver Details](#8-driver-details)
9. [FIR Details](#9-fir-details)
10. [NEFT Details](#10-neft-details)
11. [Work Approval Details](#11-work-approval-details)
12. [Claim Assessment](#12-claim-assessment)
13. [Document Upload](#13-document-upload)
14. [Survey Fee Bill](#14-survey-fee-bill)
15. [All value changes at a glance](#15-all-value-changes-at-a-glance)
16. [Checks before the run starts](#16-checks-before-the-run-starts)
17. [When a field cannot be filled](#17-when-a-field-cannot-be-filled)
18. [Settings you can change](#18-settings-you-can-change)
19. [Points worth checking](#19-points-worth-checking)
20. [Appendix A: Excel labels App3 looks for](#appendix-a-excel-labels-app3-looks-for)
21. [Appendix B: Extra survey PDF labels](#appendix-b-extra-survey-pdf-labels)

---

## 1. How to read this guide

Every field is tagged with one method:

| Tag          | Method                | Meaning                                                                                   |
| ------------ | --------------------- | ----------------------------------------------------------------------------------------- |
| ðŸ“„     | **Direct**      | Copied from the survey report as written (extra spaces trimmed).                          |
| ðŸ”§     | **Cleaned**     | Taken from the report, then tidied: date format, digits only, capitals, split into boxes. |
| ðŸ§®     | **Calculated**  | Worked out by App3 from other values.                                                     |
| ðŸ”     | **Matched**     | App3 picks the closest option from the portal's own dropdown list.                        |
| âš™ï¸ | **Setting**     | A value from App3 Settings (Automation Defaults for New India). You can change it.        |
| ðŸ”’     | **Fixed**       | Always the same value, built into App3.                                                   |
| ðŸ“Ž     | **File**        | A document from the claim folder is attached.                                             |
| ðŸš«     | **Not entered** | App3 reads the value from the report but never types it on the portal.                    |

**"If missing" column:**

- **Left empty:** App3 skips the field and moves on.
- **A value in quotes** (for example "Self"): App3 enters that fallback instead.
- **Blocks start:** App3 will not start the run until the value is found (see section 16).

All dates are entered on New India as **DD/MM/YYYY** (for example 15/01/2024), whatever form they had in the report.

> On New India, App3 attempts the remaining fields on the page and reviews unresolved issues at **Next** (see section 17). Review the form before final submission.

---

## 2. Where the data comes from

### 2.1 Four possible sources

| Source                                     | When it is used                                                | How App3 reads it                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ------------------------------------------ | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Excel survey report**              | Used first whenever the claim folder has one.                  | App3 searches every sheet for a label (for example "Chassis No"). Capital letters and extra spaces are ignored, and the label must appear as whole words somewhere in the cell. The value is taken from the same cell when it follows the label (for example "Mobile: 98765 43210"), otherwise from the next cell to the right, otherwise from the first real value further right on the same row. Labels are tried in the order listed in Appendix A. |
| **Survey PDF** (final survey report) | Used when there is no Excel.                                   | Same field list, read with the same PDF reader as OIC (section by section, unclear scanned text ignored, supporting reports rejected). Extra PDF labels are listed in Appendix B. Very short labels such as "Address" and "Time" are not used on PDFs.                                                                                                                                                                                                 |
| **Cancelled cheque photo**           | Only when the report has no IFSC Code or Account Number.       | App3 reads IFSC, account number and account type from the cheque picture.                                                                                                                                                                                                                                                                                                                                                                              |
| **Workshop invoice PDF**             | Only when the report has no Vendor/Tax Invoice Number or Date. | App3 reads the invoice for "Tax Invoice No." Â· "Invoice No" Â· "Bill No" and "Invoice Date and Time" Â· "Bill Date" Â· "Invoice Date" Â· "date".                                                                                                                                                                                                                                                                                            |

**How a report value is accepted**

- Number-type fields (registration, engine, chassis, dates, amounts) ignore cells that hold only words with no digits, such as "Lifetime" or "Attached".
- Text fields (names, colour, cause of accident, RTO and similar) accept any text.
- Yes/No fields accept "Yes" or "No" as written.
- Every field whose name contains "date" or "DOB" is converted to DD/MM/YYYY when it is read. Tax Paid Upto is not (see section 19).

### 2.2 Files App3 looks for in the claim folder

| Document                       | Used in                                                       | File name contains                                                                                                                                                          |
| ------------------------------ | ------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Chassis Number Photograph      | Vehicle Photo Graph                                           | chassis_number, chassis, chassisno, chasis                                                                                                                                  |
| Odometer Reading Photograph    | Vehicle Photo Graph                                           | odometer_reading, odometer, odo, odometer_photo                                                                                                                             |
| Cancelled Cheque               | NEFT Details (read only, never uploaded)                      | cancel_check, cancel_cheque, cancelled_cheque, cancelled, cheque, check, bank_detail, bank                                                                                  |
| Work Approval Document         | Found, but not uploaded (see section 19)                      | cashless, caseless, non_cashless, non-cashless, noncashless, non cashless, non_caseless, non-caseless. If none is found, App3 copies the invoice as work_approval_fallback. |
| Final invoice (PDF)            | Work Approval upload, Survey Fee Bill upload, invoice reading | final_invoice, invoice                                                                                                                                                      |
| Primary assessment (Excel)     | Claim Assessment                                              | App3 prepares auto_primary_assessment.xlsx from the current scan (section 12.3).                                                                                |
| Supplementary estimate (Excel) | Claim Assessment                                              | supplementary_estimate, supplementary estimate, estimate                                                                                                                    |
| Driving Licence                | Document Upload                                               | dl, driving_license, driving_licence, driving license, driving licence, license                                                                                             |
| Registration Certificate       | Document Upload                                               | rc, rc_book, registration_certificate, registration certificate, regn_cert                                                                                                  |
| Claim Form                     | Document Upload                                               | claim_form, claim form, claimform                                                                                                                                           |
| Everything else                | Document Upload                                               | Every other PDF or picture in the folder is merged into one "Claim Related Documents" PDF.                                                                                  |

Files larger than 1.5 MB are compressed before upload. The merged PDF may be up to 15 MB.

---

## 3. The journey through the portal

App3 opens a visible Chrome window when automation starts. The former invisible browser setting is ignored in older saved configurations. See the [automation engine](../app/automation/engine.py).

| Order | Stage                                      | What happens                                                                |
| ----- | ------------------------------------------ | --------------------------------------------------------------------------- |
| 1     | Login                                      | Username, password and reCAPTCHA                                            |
| 2     | Find the claim                             | Worklist â†’ filter by Claim No. â†’ Edit                             |
| 3     | **Quick Update**                     | Survey date, time and place, verification answers, remarks, contact details |
| 4     | **Vehicle Photo Graph**              | Chassis and odometer photos, then Next (this saves Quick Update)            |
| 5     | **Registration Certificate Details** | Vehicle and registration details                                            |
| 6     | **Driver Details**                   | Driver and licence details                                                  |
| 7     | **FIR Details**                      | Police details and three Yes/No questions                                   |
| 8     | **NEFT Details**                     | Payee and bank details                                                      |
| 9     | **Work Approval Details**            | Approval type, document, date and time, then Next                           |
| 10    | **Claim Assessment**                 | Invoice, assessment sheet, estimates, deductions, add-on covers, then Next  |
| 11    | **Document Upload**                  | Driving Licence, RC, Claim Form, Claim Related Documents, then Upload       |
| 12    | **Survey Fee Bill**                  | Fee amounts, GST, HSN, fee bill document, then **Submit**             |
| End   | Your review                                | App3 leaves Chrome open so you can check everything.                        |

When **Start Automation** begins a New India run, App3 starts any pending cheque reading on a background thread before launching Chrome. Login, Worklist, and the form steps continue while the cheque is being read. App3 checks for a completed result before **Additional Details → Next**. **Stop** can end the run without waiting for cheque reading. If reading was cancelled, a later run can retry it once the previous reader exits. Claim Assessment still waits for the workshop invoice reading when needed. See the [automation engine](../app/automation/engine.py).

---

## 4. Login and finding the claim

| Field           | Method         | How it is filled                                                                                                                                                                                                 |
| --------------- | -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Username        | ⚙️ Setting     | From New India settings in App3.                                                                                                                                                                                 |
| Password        | ⚙️ Setting     | From New India settings in App3.                                                                                                                                                                                 |
| reCAPTCHA       | 🧮 Calculated  | App3 ticks "I'm not a robot". If Google shows a picture puzzle, you solve it and click Login in Chrome within 45 seconds (setting). If sign-in takes longer, App3 pauses with the floating card instead of failing. |
| Worklist        | 🔒 Fixed       | Opens the Worklist menu.                                                                                                                                                                                         |
| Filter Criteria | 🔒 Fixed       | Selects `"Claim No."`.                                                                                                                                                                                           |
| Claim No        | 📄 Direct      | Enters the extracted claim number and clicks **Filter**. Blocks start if missing.                                                                                                                                |
| Channel Check   | 🔍 Auto-detect | Reads New India's auto-selected Worklist channel dropdown (`#claimType`) and `sessionStorage.claimTypeNM`, then cross-checks the opened URL: **`Non Tie-up claims`** routes to the Non-Tie-Up order, **`Maruti`** routes to the Maruti order, and any other channel (**`Hyundai HIIB`**, **`Kia`**, **`Marine Cargo claims`**, etc.) pauses with a **Not Supported Yet** popup while keeping Chrome open. |
| Edit            | 🔒 Fixed       | Opens the matching claim card in Chrome.                                                                                                                                                                         |

---

## 5. Quick Update

| Order | Portal field | Source and entry rule |
| --- | --- | --- |
| 1 | Date of Survey | Excel or PDF. App3 formats the date as DD/MM/YYYY and selects the matching preset. For example, 3/11/2026 selects the 03/11/2026 radio. If the date is outside the three choices, App3 selects **Others** and enters the date. |
| 2 | Time of Survey | Extracted from the report. App3 writes HH:MM or HH:MM:SS according to the portal control. For example, 4:15 PM becomes 16:15 or 16:15:00. The existing Excel fallback is 11:00. |
| 3 | Place of Survey *(Non-Tie-Up)* | If shown on the claim page, uses the extracted Place of Survey (Excel can fall back to Address). Skipped automatically on Maruti where absent. |
| 4 | Survey Completed | Automation Defaults, shipped **Yes**. With **No**, New India requires a Reason. App3 leaves the Reason for the operator and includes it in page review if the portal requires it and it is blank. |
| 5 | DL Applicable | Selects **Yes** when this control is shown. It can reveal the driver's licence verification fields. |
| 6 | Driving License verified with original | Automation Defaults, shipped **Yes**. |
| 7 | RC Book verified with original | Automation Defaults, shipped **Yes**. |
| 8 | Driving License verified through Parivahan | Automation Defaults, shipped **Yes**. |
| 9 | RC Book verified through Parivahan | Automation Defaults, shipped **Yes**. |
| 10 | Close Proximity / Break-In | Automation Defaults, shipped **No**. When the portal shows **Inspection Report Uploaded**, App3 selects **Yes** as before. |
| 11 | Allow Cashless Claim | Automation Defaults, shipped **Yes**. |
| 12 | Remarks | Uses **Remarks Default**, shipped text **Yes**. Extraction Review shows the same configured text. |
| 13 | Mobile No of the Claimant | Uses the extracted 10-digit mobile number, if available. |
| 14 | Email ID of the Claimant | Uses the extracted email, if available. |
| 15 | Expected date of completion of repair | Uses the formatted Date of Survey, if available. |

App3 keeps a radio already set to the configured answer. It continues filling the page when a field is missing or rejected. The existing Vehicle Photo Graph phase runs where shown, then App3 reviews unresolved issues together at **Next** before moving to **Additional Details**.

[Quick Update entry](../app/portals/newindia/automation/quick_update_module.py) · [Shipped defaults](../app/portals/newindia/config/automation_defaults.json) · [Next and page review](../app/portals/newindia/automation/vehicle_photo_module.py)

---

## 6. Vehicle Photo Graph

| Field                | Method         | How it is filled                                                         | If missing    |
| -------------------- | -------------- | ------------------------------------------------------------------------ | ------------- |
| Row 1 Document Type  | ðŸ”’ Fixed | CHASSIS NUMBER PHOTOGRAPH                                                |               |
| Row 1 File           | ðŸ“Ž File  | Chassis photo from the folder.                                           | Left empty    |
| Row 2 (added with +) | ðŸ”’ Fixed | ODOMETER READING PHOTOGRAPH. Added only when an odometer photo is found. | Row not added |
| Row 2 File           | ðŸ“Ž File  | Odometer photo from the folder.                                          |               |
| Upload               | ðŸ”’ Fixed | One click uploads both rows. Skipped when no file was attached.          |               |
| Next                 | ðŸ”’ Fixed | Saves Quick Update and opens the next section.                           |               |

---

## 7. Registration Certificate Details

Fields are filled in each channel's top-to-bottom portal order (`Reference No` outside the accordion, then):
- **Maruti:** `Registered Owner Name` → `Registration Number` → `Type of Vehicle` → `Date of Registration` → `Engine No` → `Chassis No` → `Physically Verified` → optional `Type of Body` *(skipped silently when hidden)* → `Class of Vehicle` → `Pre-Accident Condition` → optional Weight & Fitness/Permit fields → `Route/Area of Operation` → `Tax Paid Upto` → `RTO Name` → `Transfer Date` → `Odometer Reading` → `Vehicle Color` → `Vehicle Color Type` → `Type of Fuel`.
- **Non-Tie-Up:** `Registered Owner Name` → `Registration Number` → `Date of Registration` → `Engine No` → `Chassis No` → `Physically Verified` → optional `Type of Body` *(filled when shown on the portal)* → `Class of Vehicle` → `Pre-Accident Condition` → optional Weight & Fitness/Permit fields → `Route/Area of Operation` → `Tax Paid Upto` → `RTO Name` → `Transfer Date` → `Odometer Reading` → `Vehicle Color` → `Vehicle Color Type` → `Type of Vehicle` → `Type of Fuel`.

| Field                                   | Method               | How the value is decided                                                                                                                                                                                                                                                                     | If missing   |
| --------------------------------------- | -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ |
| Reference No                            | 📄 Direct      | From "Reference No."                                                                                                                                                                                                                                                                         | Left empty   |
| **Registered Owner Name**         | 📄 Direct      |                                                                                                                                                                                                                                                                                              | Blocks start |
| **Registration Number** (4 boxes) | 🔧 Cleaned     | Spaces and dashes removed, capitals. Split into state letters / district number / series letters / number. GJ-01-AB-1234 → GJ / 01 / AB / 1234. GJ011234 → GJ / 01 / (empty) / 1234. A number that does not follow this pattern (for example BH series 22BH1234AA) is not entered. | Blocks start |
| **Type of Vehicle**               | 🧮 Mapped / Weight  | Mapped from **Class of Vehicle** via [`resolve_newindia_vehicle_type`](../app/portals/newindia/field_values.py): `M/cycle / scooter / two wheeler` → **Standard Two Wheeler**, `LMV Goods / LMV Transport` → **Goods Carrying (A)**, `Car / jeep / LMV (non-transport) / private car / SUV` → **Private Car**. For other classes, falls back to Registered Laden Weight (commas stripped; **> 3,000 kg → Goods Carrying (A)**, **≤ 3,000 kg → Passenger Carrying (C)**), then the report's own "Type of Vehicle". | Blocks start |
| **Registration Date**             | 🔧 Cleaned     | DD/MM/YYYY                                                                                                                                                                                                                                                                                   | Blocks start |
| **Engine No**                     | 📄 Direct      |                                                                                                                                                                                                                                                                                              | Blocks start |
| **Chassis No**                    | 📄 Direct      |                                                                                                                                                                                                                                                                                              | Blocks start |
| Physically Verified                     | 🔒 Fixed       | Ticked.                                                                                                                                                                                                                                                                                      |              |
| Type of Body                            | 🔍 Fallback    | When New India displays `#typeOfBody`, matches Excel's **Type of Body** first; if unmatched or blank, auto-selects **Saloon** when **Saloon** exists in that dropdown (pauses for review if not). Skipped silently when hidden on the portal (for example on Maruti). | **Saloon** (if shown & available) |
| **Class of Vehicle**              | 📄 Direct      | Typed as written.                                                                                                                                                                                                                                                                            | Blocks start |
| Pre-Accident Condition                  | 📄 Direct      |                                                                                                                                                                                                                                                                                              | "Good"       |
| Registered Laden Weight / Unladen Weight / Fitness Cert & Permit fields | 📄 / 🔧 Optional | Filled when visible on the portal form (commercial / non-PC claims). Laden/Unladen Weight also used to calculate Type of Vehicle.                                                                                                                                    | Left empty   |
| Route/Area of Operation                 | 📄 Direct      |                                                                                                                                                                                                                                                                                              | Left empty   |
| Tax Paid Upto                           | 📄 Direct      | Typed as read, not converted to DD/MM/YYYY.                                                                                                                                                                                                                                                  | Left empty   |
| **RTO Name**                      | 📄 Direct      |                                                                                                                                                                                                                                                                                              | Blocks start |
| Transfer Date                           | 🔧 Cleaned     | DD/MM/YYYY                                                                                                                                                                                                                                                                                   | Left empty   |
| **Odometer Reading**              | 🔧 Cleaned     | Digits only. "45,230 km" → 45230.                                                                                                                                                                                                                                                       | Blocks start |
| **Vehicle Color**                 | 📄 Direct      |                                                                                                                                                                                                                                                                                              | Blocks start |
| Vehicle Color Type                      | 📄 Direct      |                                                                                                                                                                                                                                                                                              | "Solid"      |
| **Type of Fuel**                  | 🔍 Matched     | From the report.                                                                                                                                                                                                                                                                             | Blocks start |
| Vehicle Make                            | 🚫 Not entered | Read and required before start, but never typed.                                                                                                                                                                                                                                             | Blocks start |

---

## 8. Driver Details

| Field                                                                 | Method              | How the value is decided                                                                                        | If missing       |
| --------------------------------------------------------------------- | ------------------- | --------------------------------------------------------------------------------------------------------------- | ---------------- |
| Was the vehicle parked during accident?                               | 🔒 Fixed      | Always "No". The report's answer is read but not used.                                                          |                  |
| Relationship of the driver with the Insured                           | 🔍 Matched    | From the report.                                                                                                | "Self" (setting) |
| Licence Type of Driver                                                | 🧮 Mapped     | Always checks **Class of Vehicle** first via [`resolve_newindia_license_type`](../app/portals/newindia/field_values.py): `Heavy passenger / HPV` → **Heavy Passenger Motor vehicle**, `Heavy goods / HGV / Truck / Goods carrier / Trans / LMV Goods-Transport` (beats `LMV` when both appear) → **Heavy Goods vehicle**, `M/Cycle / scooter / two wheeler` → **Motor Cycle with Gear**, `Car / jeep / private car / LMV / light motor vehicle / SUV` → **Light Motor Vehicle**. Falls back to the report's **License Type** only for unlisted classes (e.g. Auto Rickshaw). | Excel value / empty |
| **DOB of Driver**                                               | 🔧 Cleaned    | DD/MM/YYYY                                                                                                      | Blocks start     |
| **Driver Name**                                                 | 📄 Direct     |                                                                                                                 | Blocks start     |
| **Age of Driver**                                               | 🧮 Calculated | Completed years from the date of birth to the **day of the run**. Replaces any age written in the report. | Blocks start     |
| Is the licence valid for the type of vehicle on the date of accident? | 🔒 Fixed      | Yes                                                                                                             |                  |
| Licence Issuing Authority                                             | 📄 Direct     |                                                                                                                 | Left empty       |
| **Driving Licence Number**                                      | 📄 Direct     | Typed as written.                                                                                               | Blocks start     |
| **Licence Issue Date**                                          | 🔧 Cleaned    | DD/MM/YYYY                                                                                                      | Blocks start     |
| **Licence Expiry Date**                                         | 🔧 Cleaned    | DD/MM/YYYY                                                                                                      | Blocks start     |
| Badge No                                                              | 📄 Direct     |                                                                                                                 | Left empty       |

---

## 9. FIR Details

Fields follow each channel's top-to-bottom order:
- **Maruti:** `Is there any TP claim?` first in Row 1 Col 1, then `FIR Number` → `FIR Date` → `Police Station Name` → `Charged U/S MV Act` → `Charged U/S IPC` → `Whether driver without licence?` → `Any previous police records`.
- **Non-Tie-Up:** `FIR Number` → `FIR Date` → `Police Station Name` → `Charged U/S MV Act` → `Charged U/S IPC` → `Whether driver without licence?` → `Any previous police records` → `Is there any TP claim?` last.

| Field                           | Method         | How the value is decided                                       | If missing     |
| ------------------------------- | -------------- | -------------------------------------------------------------- | -------------- |
| Is there any TP claim?          | 🔧 Cleaned     | "Yes" only when the report says Yes. Anything else becomes No. | "No"           |
| FIR Number                      | 📄 Direct      |                                                                | "NA" (setting) |
| FIR Date                        | 🔧 Cleaned     | DD/MM/YYYY                                                     | Left empty     |
| Police Station Name             | 📄 Direct      |                                                                | "NA" (setting) |
| Charged U/S Motor Vehicle Act   | 📄 Direct      |                                                                | "NA" (setting) |
| Charged U/S IPC                 | 📄 Direct      |                                                                | "NA" (setting) |
| Whether driver without licence? | 🔧 Cleaned     | Same rule.                                                     | "No"           |
| Any previous police records     | 🔧 Cleaned     | Same rule.                                                     | "No"           |
| Name of Informant               | 🚫 Not entered | Read only.                                                     |                |
| Sections of Law                 | 🚫 Not entered | Read only.                                                     |                |

---

## 10. NEFT Details

| Field                          | Method               | How the value is decided                                                                                                                                                                                                                | If missing                                   |
| ------------------------------ | -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| **Payment To**           | ðŸ§® Calculated  | **Dealer** when the report says "payment to repairer", "payment to dealer" or "in favour of" a repairer or dealer. **Insured** when it says "payment to insured", "payment to reimbursement" or "in favour of" the insured. | "Insured"                                    |
| Dealer Name (only when Dealer) | ðŸ§® Calculated  | The Registered Owner Name. There is no dealer label for New India.                                                                                                                                                                      |                                              |
| **IFSC Code**            | ðŸ“„ Direct      | From the report, then from the cheque. App3 clicks **Find** to load the bank branch. | If still blank or invalid at **Next**, New India validation can put it in the page review. |
| **Account Number**       | ðŸ“„ Direct      | From the report, then from the cheque. | If still blank or invalid at **Next**, New India validation can put it in the page review. |
| Re-Enter Account Number        | ðŸ§® Calculated  | Same as Account Number.                                                                                                                                                                                                                 |                                              |
| Account Type                   | ðŸ” Matched     | From the report. When the report says nothing (or says Savings) and the cheque shows a type, the cheque wins. Entered in capitals.                                                                                                      | "Savings" (setting)                          |
| Party Payment Method           | âš™ï¸ Setting | NEFT                                                                                                                                                                                                                                    |                                              |

The cheque is only read when IFSC Code or Account Number is missing from the report. If a background result is ready by **Additional Details → Next**, App3 fills only blank, editable bank fields, including **Re-Enter Account Number**. For example, when the report supplies IFSC and the cheque supplies the account number during Work Approval, App3 can fill both blank account inputs in one pass. If an entered bank value conflicts with the result, App3 leaves the bank fields for review. When the scan is still running, any bank fields New India requires are listed in the same review as the other unfinished fields on the page. See [NEFT Details](../app/portals/newindia/automation/neft_module.py) and [Work Approval](../app/portals/newindia/automation/work_approval_module.py).

---

## 11. Work Approval Details

| Field                                             | Method               | How the value is decided                                                                                                                                                                                                                            | If missing     |
| ------------------------------------------------- | -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------- |
| **Approval Type**                           | ðŸ§® Calculated  | From the report's "Approval Type": contains "non-cashless" â†’ Non-cashless approved; contains "cashless" â†’ Cashless approved. Without it: Payment To Dealer â†’ **Cashless approved**, otherwise **Non-cashless approved**. |                |
| Work Approval Document                            | ðŸ“Ž File        | The final invoice PDF (or, if none, a PDF named garage bill or bill). PDF only. App3 then clicks the document's Submit button.                                                                                                                      | Upload skipped |
| Work Approval Date                                | ðŸ”§ Cleaned     | DD/MM/YYYY                                                                                                                                                                                                                                          | Left empty     |
| Work Approval Time                                | ðŸ”§ Cleaned     | The first 5 characters, for example "11:30:00" â†’ 11:30.                                                                                                                                                                                        | Left empty     |
| Whether vehicle details are matching with policy? | ðŸ”’ Fixed       | Always "Yes". The report's answer is not used.                                                                                                                                                                                                      |                |
| **Cause and Nature of Accident**            | ðŸ“„ Direct      |                                                                                                                                                                                                                                                     | Blocks start   |
| Vehicle Details Mismatch Remarks                  | ðŸš« Not entered | Read only.                                                                                                                                                                                                                                          |                |
| Next                                              | ðŸ”’ Fixed       | Opens Claim Assessment.                                                                                                                                                                                                                             |                |

---

## 12. Claim Assessment

App3 supports two New India Claim Assessment layouts: the **Non-Tie-Up** layout (Primary/Supplementary Excel upload) and the **Maruti / Tie-Up part-wise** layout (`Claim Version 1` nested rows editor). On both layouts, invoice header fields are filled in portal top-to-bottom order.

### 12.1 Header & Non-Tie-Up Fields

| Field                                                                  | Method               | How the value is decided                                                                                                                       | If missing                                    |
| ---------------------------------------------------------------------- | -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| Whether workshop is GST registered                                     | 🧮 Calculated        | Yes when Workshop GST amount > 0, else No.                                                                                                     | No                                            |
| Whether payment invoice is in name of NIA                              | ⚙️ Setting           | Yes                                                                                                                                            |                                               |
| **Vendor/Tax Invoice Date**                                            | 🔧 Cleaned           | DD/MM/YYYY. From the report, else from the invoice PDF.                                                                                        | Blocks start unless the invoice can supply it |
| **Vendor/Tax Invoice Number**                                          | 📄 Direct            | From the report, else from the invoice PDF.                                                                                                    | Blocks start unless the invoice can supply it |
| Nil Depreciation (Yes / No)                                            | 📄 Direct            | When Nil Depreciation radios appear on the portal, reads strict `Yes` or `No` from Excel (never matches *Nil Depreciation Amount*).         | Shows warning in Extraction Review & pause card |
| Is there any primary estimate                                          | 🔒 Fixed             | Non-Tie-Up only: Yes                                                                                                                           |                                               |
| Primary assessment sheet                                               | 📎 File              | Non-Tie-Up only. App3 uploads the workbook prepared by the current scan (12.3).                                  | Skipped with a warning                        |
| Is there any supplementary estimate                                    | 🧮 Calculated        | Non-Tie-Up only: Yes when an estimate Excel is in the folder, otherwise No. The report's answer is not used.                                   |                                               |
| Supplementary estimate sheet                                           | 📎 File              | Non-Tie-Up only: Uploaded only when the answer above is Yes.                                                                                   |                                               |
| Painting work details                                                  | 🔍 Matched           | Non-Tie-Up only: Text containing "break", "labour" or "labor" → Break-up. Containing "consol" → Consolidated. Otherwise as written.            | Left empty                                    |
| Net Salvage                                                            | 📄 Direct            | Skipped when 0.                                                                                                                                | Left empty                                    |
| Less Any Other Deductions                                              | 📄 Direct            | Non-Tie-Up only. Skipped when 0.                                                                                                               | Left empty                                    |
| Towing Charges                                                         | 📄 Direct            | Skipped when 0.                                                                                                                                | Left empty                                    |
| Additional Towing Charges                                              | 📄 Direct / Setting  | From Automation Defaults (`0` by default).                                                                                                   | Must be non-negative                          |
| Whether Re-Inspection Required                                         | 🧮 Calculated        | Yes when a re-inspection file is in the folder, else No.                                                                                       |                                               |
| Nil Depreciation (Zero Dep) Amount                                     | 📄 Direct            | Non-Tie-Up add-on box: only when the portal shows the editable box and the amount is not 0.                                                    | Left empty                                    |
| Engine Protect Amount                                                  | 📄 Direct            | Same rule.                                                                                                                                     | Left empty                                    |
| Consumable Items Amount                                                | 📄 Direct            | Same rule.                                                                                                                                     | Left empty                                    |
| Key Protect Amount                                                     | 📄 Direct            | Same rule.                                                                                                                                     | Left empty                                    |
| Compulsory, Voluntary and Imposed Excess                               | 🚫 Not entered       | Read only.                                                                                                                                     |                                               |
| Primary Assessment amount                                              | 🚫 Not entered       | Required before start. The portal takes the figures from the uploaded sheet or part-wise editor.                                               | Blocks start                                  |
| No. of invoices, Salvage invoice mapping, GST Applicable, Verification | 🚫 Not entered       | Read only.                                                                                                                                     |                                               |
| Next                                                                   | 🔒 Fixed             | App3 checks unresolved fields before clicking Next. If Document Upload does not open, App3 pauses for review.                                  |                                               |

**Delivery Order Date and Delivery Order Time** are optional for App3's Non-Tie-Up Claim Assessment flow. The [Excel mapping](../app/portals/newindia/config/field_mapping.json) reads each value one column to the right of its label on the same row. App3 fills either value independently when it is available and usable.

For example, if Excel has `15/01/2026` for the date and the time is blank, App3 fills the date and leaves the time empty. If both are blank, App3 skips both and leaves them off the [pause popup](../app/portals/newindia/automation/recovery.py), even when the portal shows asterisks. New India still controls whether **Next** is available.

### 12.2 Maruti / Tie-Up part-wise flow (`Claim Version 1`)

When New India displays the **Maruti / Tie-Up** part-wise assessment layout (identified by `saveDetailsMaruti` / `saveMarutiExtraDeatils` / `Claim Version` panels without the Non-Tie-Up primary estimate selector), [`claim_assessment_module.py`](../app/portals/newindia/automation/claim_assessment_module.py) runs this exact sequence:

1. **Invoice & Nil Depreciation header:** Sets **Whether the Workshop is GST Registered** → **Whether Payment invoice is in the name of NIA** → **Vendor/Tax Invoice Date** → **Vendor/Tax Invoice Number** → **Nil Depreciation (`Yes` / `No`)** → clicks top **Save** (`saveDetailsMaruti()`) and closes any confirmation modal. If `nil_depreciation` was missing from Excel while the radio buttons are shown, App3 records a review notice instead of guessing.
2. **Nested accordions:** Expands **Claim Version 1 (Primary Estimates)** → **Claim Version 1 : Subversion 1** → **Assessment 1 (Pending)** in order (leaving any already-open section untouched).
3. **Dealer rows:** Sets **Allowed Service type** to **Not Allowed** on the original dealer rows in the pending table. When a **Not Allowed** dealer row displays the **Item** dropdown (`select#vItem`) still on **Select**, App3 automatically selects **Spare** so New India's `validateMarutiVItemSelection` check passes on **Save as Draft**. App3 keeps matching assessment rows already present and uses blank editable rows when available.
4. **Survey rows:** Adds one row per item prepared by the current scan, plus one **Painting** row per painted item from the source Excel's `PAINT` column (reduced by the sheet's paint depreciation %, or 0% when Nil Depreciation is Yes). Item is **Metal**, **Plastic**, **Glass**, **Labour**, or **Painting**. App3 fills **Part Description**, leaves **Part No.** blank, enters the row's **Estimated** amount in **MRP** whenever `Estimated > 0` (falling back to the row's **Assessed** amount when `Estimated` is blank or `0`), enters the **Assessed** amount in **Amount Allowed (GST Excluded)**, and enters **Quantity** as 1 and editable **Depreciation** as 0. On added rows, it fills **Dealer Service Type** (`input#vDealerServiceType`) and **Allowed Service type** (`select#sel1`) as **Replace** for spare parts (**Metal**, **Plastic**, **Glass**) and **Repair** for **Labour** and **Painting** (setting **Dealer Service Type = Repair** first unlocks **Repair** in New India's **Allowed Service type** dropdown). For example, a metal bonnet with `Estimated = ₹30,000` and `M-Age = ₹6,500` gets `Item = Metal`, `MRP = 30000`, `Dealer Service Type = Replace`, `Allowed Service type = Replace`, `Amount Allowed = 6500`; a labour line with blank `Estimate` and `R/R = ₹300` + `Denting = ₹700` gets `Item = Labour`, `MRP = 1000`, `Dealer Service Type = Repair`, `Allowed Service type = Repair`, `Amount Allowed = 1000`; and a painted panel with `PAINT = ₹4,000` and `12.5%` paint depreciation gets `Item = Painting`, `MRP = 3500`, `Dealer Service Type = Repair`, `Allowed Service type = Repair`, `Amount Allowed = 3500`.
5. **HSN/SAC and GST:** For Maruti part-wise rows, App3 types **`870840`** for spare parts (**Metal**, **Plastic**, **Glass**) and **`998714`** for **Labour** and **Painting** into **HSN/SAC Code** (`input#hsnCode`) and clicks the matching entry from New India's autopopulated suggestion list (`ul[typeahead-popup] li a`). Selecting the suggestion triggers New India's `getgstPercent` lookup, which auto-populates the read-only **GST%** box (for example `18`) and calculates **Amount Allowed (GST Included)**. App3 waits for the portal to populate a valid numeric **GST%** and lists any missing or rejected fields in the review card before saving. **Continue** rechecks the existing rows before saving.
6. **Save as Draft:** App3 requests a draft save after verifying the pending rows and waits for confirmation. It pauses in Chrome for the operator to review the draft. **Continue** resumes the existing summary fields and navigation to Document Upload. An unconfirmed draft stays open for inspection.
7. **Summary and Next:** After the draft review, App3 fills the existing Net Salvage, Towing, Additional Towing, Recommendations and Re-Inspection fields, saves the summary, and runs the existing **Next** review before opening Document Upload.

App3 changes the dealer dropdowns in row order, up to 20 per browser call. It checks Pause and Stop between groups and retries a dropdown individually if the browser did not retain the selection. For each new survey row, App3 enters standard fields together and checks which values New India kept. It still clicks **Add Row** once per item and selects each HSN/SAC suggestion in that row. GST responses can arrive while subsequent rows are filled, and App3 checks the results before saving. The summary fields use their existing verification without the extra between-field delay.

New India requires a valid **Item** on dealer rows that show the Item dropdown, including those marked **Not Allowed**, and App3 automatically sets any `Select` dealer row to **Spare** when marking it **Not Allowed** (retrying individually if needed). It also validates **Depreciation** on every row. If any dealer row still lacks a valid **Item** or **Depreciation**, App3 lists the row in the review card before clicking **Save as Draft**.

The table and draft controls were observed on the live page. Row entry and draft review were exercised in a local Chromium form. Live timing and draft confirmation remain to be verified.

[Maruti row mappings](../app/portals/newindia/automation/maruti_rows.py) · [Maruti draft and review](../app/portals/newindia/automation/claim_assessment_module.py)

### 12.3 How App3 builds the primary assessment sheet

On each scan, App3 builds **auto_primary_assessment.xlsx** from the active worksheet saved in the survey Excel, or from verified assessment rows when the survey PDF is the source. It uses the same filename for each successful replacement and saves a short audit text file beside it. Non-Tie-Up uploads the workbook prepared by that scan. Maruti reads the rows locally for direct entry (and also reads per-item net **Painting** rows from the source Excel's `PAINT` column).

If Excel locks the existing output, App3 keeps the existing file and skips its upload. The review message tells the operator to close the workbook and rescan. For example, if a new scan changes a bumper from ₹3,000 to ₹3,500 while Excel has the file open, the later successful rescan replaces the workbook with the ₹3,500 version.

[Workbook preparation](../app/ui/services/claim_folder_service.py) · [Workbook format and audit](../app/data/assessment_generator.py) · [Shared parts and painting extractor](../app/data/excel_parts_extractor.py)

**Spare parts table.** Found by its header row: Sr/S.No, Description/Parts Name/Particulars/Item, Metal (or `M-Age`), Plastic (or `P-50%`), Glass (or `G-0%`), with optional Estimated. Zero or negative cells in unused material columns are treated as empty. Each part row becomes:

| Amount found in | Description written           | Service type |
| --------------- | ----------------------------- | ------------ |
| Metal / M-Age   | Parts at Agewise Depreciation | REPLACE      |
| Plastic / P-50% | Parts at 50% Depreciation     | REPLACE      |
| Glass / G-0%    | Parts at Cost                 | REPLACE      |

Billed and Assessed both equal that positive material amount. Estimated comes from the Estimated column. HSN in the generated Non-Tie-Up workbook is 8512 (setting; Maruti part-wise row entry uses `870840` for spare parts). Depreciation % and GST % are written as 0.

Part rows are **left out** when: the name is blank; the name is a total, sub total, summary, less, add, salvage, depreciation, imposed, GST, tax or net line, or contains "%"; the name contains "labour"; there is no positive Metal, Plastic or Glass amount; or there are positive amounts in **more than one** of those columns. The table ends at a "sub total" row (or before the Labour table header).

**Labour table.** Found by its header row: Sr, Description, R/R, Denting, C/W (with optional Estimate and Paint). For each row, positive R/R, Denting and C/W amounts are **added together** (rows where R/R, Denting and C/W are all 0 or blank are skipped). Category is Labor Charges, description "Labor charges for Repairing and Alignment", service type ALLOW, Estimated from the row's Estimate cell when > 0 (else 0), HSN 8729 in the generated Non-Tie-Up workbook (setting; Maruti part-wise row entry uses `998714`), GST % 0. **Painting and Alignment columns are not included in the Non-Tie-Up upload sheet; on Maruti part-wise claims, each row with `PAINT > 0` is entered as an added `Painting` row (`Repair`, HSN `998714`) using the net painting amount after the sheet's paint depreciation %.**

A table whose header App3 is less than 80% sure of is skipped. If neither table gives any rows, no sheet is built.

---

## 13. Document Upload

| Row | Document Type            | File                              |
| --- | ------------------------ | --------------------------------- |
| 1   | Driving License          | Driving licence file              |
| 2   | Registration Certificate | RC file                           |
| 3   | Claim Form               | Claim form file                   |
| 4   | Claim Related Documents  | One merged PDF of all other files |

- A row is added only for a file that was found, so the numbering shifts when one is missing. For multi-document batches (1..9+ rows), App3 clicks the `+` icon inside `mandatoryDocForm`, scrolls the row dropdown into view, matches by value or visible label in 3 passes, dispatches Angular change events before file attachment so per-type size limits update immediately, and compresses oversized files as a safety net.
- **Claim Related Documents** holds every other PDF and picture in the folder that is not used elsewhere. App3's own outputs are left out, and Word, Excel and text files cannot be merged.
- Chassis and odometer photos, the cheque, the approval letter, the invoice and the assessment sheets are **not** in the merged PDF.
- After all rows are attached and verified, App3 strictly locates the Mandatory **Upload** button inside `mandatoryDocForm` (never Reset, Non-Mandatory Upload, or Survey Fee Bill Upload) and confirms completion via inline banners, per-row `Successful` indicators, confirmation modals, or an increase in the `Uploaded Documents` table count. If New India shows an alert instead of confirming, the portal alert message is shown on the floating review card with a **Continue** button. See [document upload module](../app/portals/newindia/automation/document_upload_module.py).

---

## 14. Survey Fee Bill

| Field                    | Method               | How the value is decided                                                                                                 | If missing                          |
| ------------------------ | -------------------- | ------------------------------------------------------------------------------------------------------------------------ | ----------------------------------- |
| Invoice in name of NIA   | âš™ï¸ Setting | Yes                                                                                                                      |                                     |
| Invoice Number           | ðŸ“„ Direct      | Same as the Vendor/Tax Invoice Number (the workshop invoice).                                                            | Left empty                          |
| Invoice Date             | ðŸ”§ Cleaned     | Same as the Vendor/Tax Invoice Date.                                                                                     | Left empty                          |
| Professional Fee         | ðŸ“„ Direct      | Skipped when 0.                                                                                                          | Left empty                          |
| Photos Amount            | âš™ï¸ Setting | Always 200.                                                                                                              |                                     |
| Conveyance Amount        | ðŸ“„ Direct      | From Conveyance or Traveling Expenses. Skipped when 0.                                                                   | Left empty                          |
| Others                   | ðŸ“„ Direct      | Skipped when 0.                                                                                                          | Left empty                          |
| GST Applicable           | âš™ï¸ Setting | Yes                                                                                                                      |                                     |
| HSN Code                 | âš™ï¸ Setting | 8512. Typed, then the matching entry is picked from the list.                                                            |                                     |
| Survey Fee Bill document | ðŸ“Ž File        | The final invoice PDF. Otherwise any PDF named survey_fee_bill, survey_fee, fee_bill or invoice. Then Upload is clicked. | Upload skipped, fields still filled |
| Submit                   | ðŸ”’ Fixed       | **Clicked automatically**, and the confirmation popup is closed.                                                   |                                     |

---

## 15. All value changes at a glance

| Value                         | Example from the report                                    | What App3 enters       |
| ----------------------------- | ---------------------------------------------------------- | ---------------------- |
| Any date                      | 2024-01-15 Â· 15-01-2024 Â· 15.01.2024 Â· Excel date | 15/01/2024             |
| Survey time                   | "4:15 PM" Â· "16.15"                                     | 16:15                  |
| Survey time not found (Excel) | (none)                                                     | 11:00                  |
| Registration Number           | GJ-01-AB-1234                                              | GJ / 01 / AB / 1234    |
| Odometer                      | "45,230 km"                                                | 45230                  |
| Mobile                        | "+91 98765 43210"                                          | 9876543210             |
| Type of Vehicle               | Class "Scooter / Two Wheeler"                              | Standard Two Wheeler   |
| Type of Vehicle               | Class "Private Car / Jeep / LMV / SUV"                     | Private Car            |
| Type of Vehicle               | Class "LMV - Transport / LMV Goods"                        | Goods Carrying (A)     |
| Type of Vehicle               | Class "Truck", laden weight 12,000 kg (commas stripped)    | Goods Carrying (A)     |
| Type of Vehicle               | Class "Auto Rickshaw", laden weight 800 kg                 | Passenger Carrying (C) |
| Type of Body (when visible)   | "Coupe" (unmatched) or blank                               | Saloon                 |
| Licence Type                  | Class "M/Cycle / Scooter / Two Wheeler"                    | Motor Cycle with Gear  |
| Licence Type                  | Class "Car / Jeep / Private Car / LMV / SUV"               | Light Motor Vehicle    |
| Licence Type                  | Class "HGV / Truck / Goods Carrier / Trans / LMV-Trans"    | Heavy Goods vehicle    |
| Licence Type                  | Class "Heavy Passenger Vehicle / HPV"                      | Heavy Passenger Motor vehicle |
| Age of Driver                 | DOB 10/05/1990, run on 21/11/2026                          | 36                     |
| FIR Yes/No questions          | "yes" Â· "NO" Â· "N.A."                                | Yes Â· No Â· No    |
| Painting work details         | "Labour break up"                                          | Break-up               |
| Account Type                  | Savings                                                    | SAVINGS                |
| Approval Type                 | (none), payment to repairer                                | Cashless approved      |
| Expected Date of Repair       | Survey on 12/03/2024                                       | 12/03/2024             |
| Work Approval Time            | 11:30:00                                                   | 11:30                  |
| Labour row                    | R/R 500 + Denting 1,200                                    | 1700                   |

---

## 16. Checks before the run starts

**Extraction Review** shows missing or flagged fields as short chips above the field table. Red chips mark critical issues and amber chips mark optional fields or other warnings. The full message appears when you hover over a chip.

### 16.1 These block the start

The run does not start when any of these 26 values is missing:

Claim Number · Registered Owner Name · Vehicle Registration Number · Date of Registration · Engine No · Chassis No · Vehicle Make · Class of Vehicle · RTO Name · Odometer Reading · Vehicle Color · Registered Laden Weight · Type of Vehicle · Type of Fuel · Cause/Nature of Accident · Driver Name · DOB of Driver · Age of Driver · Driver License Number · Driver License Issue Date · Driver License Expiry Date · IFSC Code · Account Number · Vendor/Tax Invoice Date · Vendor/Tax Invoice Number · Primary Assessment

- Odometer Reading and Primary Assessment may be 0. For the other fields, 0 counts as missing.
- Invoice Number and Date do not block the start when they will be read from the invoice PDF. IFSC Code and Account Number do not block the start when they will be read from the cheque. App3 checks the bank fields at **Additional Details → Next**.

### 16.2 These only warn (the run continues)

Vehicle Details Mismatch Remarks Â· Route/Area of Operation Â· Tax Paid Upto Â· Transfer Date Â· Badge Number Â· FIR Number Â· FIR Date Â· Police Station Name Â· Name of Informant Â· Net Salvage Â· Voluntary Excess Â· Imposed Excess Â· Towing/Additional Charges

---

## 17. When a field cannot be filled

While filling fields one by one, App3 shows a compact live progress badge in Chrome (bottom-left corner, forced high-contrast white text `#F8FAFC !important` so portal rules cannot darken it) alongside color rings on the active field (blue while filling, amber on automatic retry, brief green when verified, and red on failure until edited in Chrome) and updates the App3 top status bar with the active section, field name, and running counts (`✓` filled / `⚠` failed).

If a field does not stick on the first attempt (or a cascading dropdown has no options yet), App3 automatically retries it once (using native typing + blur/change events for text inputs) before recording a failure. It continues trying the remaining fields on **Quick Update**, **Additional Details**, and **Claim Assessment**. At **Next**, it checks what the current page retained and shows one compact floating pause card (`RecoveryDialog`) near the top-right corner of the screen without pulling the desktop app over Chrome (with a fixed-height header, escaped `&` button text such as **Skip & Try Next**, and a **Show Chrome** button). Blank **Delivery Order Date** and **Delivery Order Time** are skipped during that check. Modals whose OK button lives inside `.modal-body` (such as `"Claim job details updated successfully"`) have button text stripped during confirmation matching so `advance_next` closes confirmed save popups cleanly without an extra pause.

Each failed item on the card shows the section, field name, a **Tried: value (source)** pill with a 1-click **Copy** button, and either New India's inline error text or available dropdown options when a choice did not match. Fix the listed fields in Chrome and click **Continue** in the card (use **Show Chrome** on the card header if Chrome is covered or minimized, or **Show Pause Card** in App3 if the card is hidden). Clicking **Continue** rechecks Chrome, clicks **Next** automatically when ready, and waits briefly to dismiss any delayed save popup. When offered, **Skip & Try Next** attempts to move ahead with current values. You can also click **Pause** in the App3 toolbar at any time to edit Chrome calmly and click **Resume** when ready. App3 checks that the next page opened for the same claim. When all steps finish, App3 leaves Chrome open and shows a green **"All Steps Complete — Ready for Review"** floating card (**Show Chrome** + **Done (Keep Chrome Open)**). See [field fill & Chrome HUD](../app/portals/newindia/automation/ui_utils.py), [page review and resume](../app/portals/newindia/automation/recovery.py), [popup dismissal](../app/portals/newindia/automation/popup_service.py), [pause card](../app/ui/components/recovery_dialog.py), [main window](../app/ui/main_window.py), [automation engine](../app/automation/engine.py), and [browser launch & focus](../app/portals/oic/automation/review_browser.py).

By default, New India's **Logs** tab shows a compact icon-led stream: folder readiness, step banners, per-step completion summaries (counts of filled, skipped, uploaded, and issue items), manual action prompts, warnings/errors, and the final headline summary. Detailed per-field values, skipped reasons, folder-scan lines, retries, and screenshots remain hidden from the default view (available anytime in App3 by ticking **Show details** on the **Logs** tab) while still being written in full to the claim `.json` / `.txt` log files and session log file. See [structured logger](../app/automation/automation_logger.py), [logs table & Show details toggle](../app/ui/components/workspace_page.py), and [main window logging](../app/ui/main_window.py).

**AI debug report (optional, OFF by default).** The **Logs** tab has an **AI debug report** switch beside **Show details** and **Auto-scroll**. It starts OFF every time App3 opens (it is not saved), the same choice applies to UIIC, OIC and New India during the session, and it is locked while a run is active, so it takes effect from the next run. When it is OFF nothing below happens. When it is ON, App3 writes one more file, `<claim>_run_<time>_<pid>_ai_debug.md`, beside that run's `.json` / `.txt` logs in `~/Automations/logs/newindia/`. When it is ON, App3 also does two small read-only things in Chrome. (1) It listens to Chrome's own events in every tab of the run: console errors and warnings, page script errors, failed requests and 4xx/5xx replies (for a reply that carries text or JSON it keeps the first 600 characters, with secrets hidden, read within 2 seconds). These listeners only receive events: they never answer, block or change anything, and **no popup/dialog listener is added**, so the New India popup handling stays exactly as it is. Repeated events are counted once (`x3`), at most 300 events are kept, and the listeners are removed when the run summary is written or the run ends. (2) When a field fails, a step fails, or (OIC) a pause card appears, it takes one quick look at the page: how many elements matched, the element's state (visible, disabled, read-only, required), its current value, dropdown options, the browser's and the portal's validation messages, visible error messages and popups on screen, the fields the page marks invalid, and a short cleaned piece of HTML (scripts, styles and App3's own highlight marks removed). It never clicks, types, focuses or scrolls, and it stops after about 1 second (the report then says it is partial). Snapshots taken within 2 seconds of each other on the same tab are merged ("Also used for"), at most 25 are kept, and the Logs tab shows a short line `AI debug report: page snapshot S1 saved (<field>)`. Password-type fields and fields labelled Password, Captcha, OTP or Passcode show `********` instead of their value, in the value and in the HTML. For New India the field snapshot is taken inside `_check_entry` just before a failed field is recorded for the pause card (it adds the field type, the value tried, the portal's dropdown error code, the close matches, how many options the list had, and the source), and step failures and pauses use the New India screenshot helper, which shares the same screenshot code, so the snapshot sits next to the screenshot file name. The report never changes pauses, retries, Skip or Continue. The file is created as soon as the run log starts, updated during the run (straight away after each error; browser events at most every 3 seconds), finished with the run summary, and its path is printed as the last summary line (`AI debug report: …`). It has these sections: **1 Summary**, **2 Problems in detail** (each error, warning and failed field with the code place that logged it, the line that raised the error and the call chain, the raw error text, a few source lines only when App3 runs from source (the packaged EXE shows `file:line` only), the Python traceback, the nearest page snapshot and the browser events from the 12 seconds before it), **3 Browser errors and failed portal calls** (with the pages visited), **4 Page snapshots**, **5 Timeline of steps and problems**, **6 Environment**, **7 Run settings** (username and password hidden), **8 Claim input check** (validation messages and mapped documents, file names only), **9 Folder scan and extraction trace**, **10 End of the readable run log** (last 250 lines) and **11 Files saved for this run**. Paths under the Windows user folder are shown as `~`. If the file would pass 1.5 MB, App3 writes a shortened form (all problems kept, shorter timeline, browser list, snapshots and log tail) and, only as a last resort, cuts it with a note. **Copy AI Debug** (beside **Export**) becomes clickable once the report exists and copies the whole report for pasting into an AI assistant; **Export** also saves a copy named `<exported file name>_ai_debug.md` beside the exported log when a report exists for the last run; switching portal clears the report. Claim values such as names, numbers and amounts stay in the report on purpose; credentials do not. Separately, whether the switch is ON or OFF, the logger writes `********` for the value of any field whose label looks like Password, Captcha, OTP or Passcode, and hides typed text that a failed fill echoes back (synthetic example: `fill("********")`). New India's login types the password directly and does not log it. See [AI debug report](../app/automation/debug_recorder.py), [structured logger](../app/automation/automation_logger.py), [engine start of the report and browser hook](../app/automation/engine.py), [worker](../app/ui/worker.py), [Logs tab switch & Copy AI Debug](../app/ui/components/workspace_page.py), [main window and Export](../app/ui/main_window.py), [field failure snapshot](../app/automation/chrome_hud.py), [screenshot snapshot](../app/automation/run_diagnostics.py), [New India field entry](../app/portals/newindia/automation/ui_utils.py), and [tests](../tests/test_ai_debug_report.py).

---

## 18. Settings you can change

Under **Settings → Field Mapping**, New India shows **Delivery Order Date (Optional)** and **Delivery Order Time (Optional)**. When blank, both also show **OPTIONAL** in Extraction Review.

These settings are under **Settings → Automation Defaults** for New India.

| Setting                    | Default    | Affects                                                         |
| -------------------------- | ---------- | --------------------------------------------------------------- |
| Survey Completed           | Yes        | Quick Update, with a Reason required when set to No              |
| DL / RC verified with original | Yes   | Quick Update, separate Yes/No settings for DL and RC             |
| DL / RC verified through Parivahan | Yes | Quick Update, separate Yes/No settings for DL and RC             |
| Close Proximity / Break-In | No         | Quick Update                                                    |
| Allow Cashless Claim       | Yes        | Quick Update                                                    |
| Remarks Default            | Yes        | Quick Update Remarks text                                       |
| Missing text               | NA         | FIR Number, Police Station, Charged U/S MV Act, Charged U/S IPC |
| Photo charges              | 200        | Survey Fee Bill Photos Amount                                   |
| Assessment parts HSN code  | 8512       | Built assessment sheet, spare parts                             |
| Assessment labour HSN code | 8729       | Built assessment sheet, labour                                  |
| HSN code                   | 8512       | Survey Fee Bill                                                 |
| GST applicable             | Yes        | Survey Fee Bill                                                 |
| Invoice in company name    | Yes        | Claim Assessment and Survey Fee Bill                            |
| Payment method             | NEFT       | NEFT Party Payment Method                                       |
| Account type               | Savings    | NEFT Account Type                                               |
| Relationship with insured  | Self       | Driver Details                                                  |
| Re-inspection required     | No         | Claim Assessment                                                |
| Field wait                 | 600 ms     | Pause after each field                                          |
| Manual login wait          | 45 seconds | Login                                                           |

Saved workspace values take priority over the shipped defaults above. For example, a workspace that already saved Remarks Default as "Ok" keeps that text until you change it.

Two settings are **not used** on New India today: **Observation default** (Remarks uses the Remarks setting) and **Table end words** (the sheet builder always stops at "sub total"). The 11:00 survey time is built in and has no New India setting.

---

## 19. Points worth checking

These are not errors in App3's working. They are rules that may differ from what you expect, so they are worth confirming with how you work.

| #  | Point                                      | What App3 does today                                                                                                                                                                                                    |
| -- | ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1  | Commercial / unlisted laden weight        | Strips commas so `"12,000 kg"` is read as `12000`, giving `Goods Carrying (A)` when Class of Vehicle is unlisted/commercial. |
| 2  | Light cars & two-wheelers                 | Cars (`Car / Jeep / LMV Non-Transport / Private Car / SUV`) map to `Private Car`, two-wheelers map to `Standard Two Wheeler`, and `LMV Goods / Transport` maps to `Goods Carrying (A)`. |
| 3  | Excess amounts                             | Compulsory, Voluntary and Imposed Excess are read but never entered.                                                                                                                                                    |
| 4  | Vehicle Make and Primary Assessment amount | Both must be found before the run starts, but neither is typed on the portal.                                                                                                                                           |
| 5  | Fixed answers | Quick Update uses editable defaults for Survey Completed, the four DL/RC verification answers, Close Proximity / Break-In, and Allow Cashless Claim. DL Applicable and Inspection Report Uploaded select Yes when shown. Vehicle parked still selects No, licence valid selects Yes, and Physically Verified is ticked. |
| 6  | Work Approval Document                     | The invoice PDF goes in this slot, even when the folder has a cashless or non-cashless approval letter.                                                                                                                 |
| 7  | Approval letter and cheque                 | Neither is uploaded anywhere: both are kept out of Claim Related Documents.                                                                                                                                             |
| 8  | Dealer Name                                | Filled with the Registered Owner Name, not the workshop or dealer.                                                                                                                                                      |
| 9  | Unknown payee                              | When the report does not say who is paid, Payment To is Insured and Approval Type is Non-cashless approved.                                                                                                             |
| 10 | Survey Fee Bill invoice                    | Uses the workshop's invoice number, date and PDF, not a separate surveyor fee bill. Submit is clicked automatically.                                                                                                    |
| 11 | Expected Date of Repair                    | Always the same as the survey date.                                                                                                                                                                                     |
| 12 | Age of Driver                              | Worked out to the day of the run, not the date of accident.                                                                                                                                                             |
| 13 | Survey time label                          | The Excel label "Time" is tried first and can match another cell such as "Time of Accident".                                                                                                                            |
| 14 | Place of Survey                            | When "Place of Survey" is not found, Excel falls back to the first "Address" cell, often the insured's address.                                                                                                         |
| 15 | Tax Paid Upto                              | Not converted. An Excel date can arrive as "2025-03-31 00:00:00" or as a number.                                                                                                                                        |
| 16 | Work Approval Time                         | Only the first 5 characters are kept, so "4:30 PM" becomes 4:30 (PM is lost).                                                                                                                                           |
| 17 | Assessment sheet                           | Painting labour is left out, a part with amounts in two material columns is dropped, and GST % and depreciation % are 0 on every row.                                                                                   |
| 18 | Report answers not used                    | Re-Inspection (setting decides) and Supplementary Estimate (folder decides).                                                                                                                                            |
| 19 | Email ID                                   | Takes the first ".com" email starting with cell I4, which is often the surveyor's own letterhead email.                                                                                                                 |
| 20 | BH series numbers                          | Registration numbers outside the usual pattern are not entered.                                                                                                                                                         |
| 21 | Name of Informant and Sections of Law      | Read, never entered.                                                                                                                                                                                                    |
| 22 | No pause on problems                       | A field that cannot be filled is only logged, and dropdowns take the first loose match.                                                                                                                                 |

---

## Appendix A: Excel labels App3 looks for

Labels are tried left to right on every sheet. The value is the first real entry after the label (same cell, then to the right on the same row).

| Field                           | Labels                                                                                                                                                                     | Fallback      |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| Claim Number                    | Claim No. Â· Claim no. Â· Claim No Â· Claim no Â· Claim Number Â· claim_number Â· claim_no                                                                     |               |
| Registered Owner Name           | Registered Owner Name Â· Owner Name Â· Name of Owner Â· Insured Name Â· NAME OF INSURED                                                                            |               |
| Registration Number             | Vehicle Registration Number Â· Registration No Â· Regn No Â· Vehicle No                                                                                              |               |
| Registration Date               | Date of Registration Â· Regn Date Â· Registration Date                                                                                                                 |               |
| Engine No                       | Engine No Â· Engine Number Â· Eng No                                                                                                                                   |               |
| Chassis No                      | Chassis No Â· Chassis Number Â· Ch No                                                                                                                                  |               |
| Physically Verified             | Physically Verified Â· Physical Verification                                                                                                                             | Yes           |
| Vehicle Make                    | Vehicle Make · Make of Vehicle · Make                                                                                                                                |               |
| Type of Body                    | Type of Body · Body Type                                                                                                                                             | Saloon (when visible) |
| Class of Vehicle                | Class of Vehicle · Vehicle Class                                                                                                                                        |               |
| Pre-Accident Condition          | Pre-Accident Condition Â· Pre Accident Condition Â· Condition before Accident                                                                                          | Good          |
| RTO Name                        | RTO Name Â· RTO Â· Registering Authority                                                                                                                               |               |
| Odometer Reading                | Odometer Reading Â· Odometer Â· KM Reading                                                                                                                             |               |
| Vehicle Color                   | Vehicle Color Â· Colour Â· Color of Vehicle Â· Vehicle Colour                                                                                                        |               |
| Vehicle Color Type              | Vehicle Color Type Â· Color Type Â· Colour Type                                                                                                                        | Solid         |
| Type of Vehicle                 | Type of Vehicle Â· Vehicle Type                                                                                                                                          |               |
| Type of Fuel                    | Type of Fuel Â· Fuel Type Â· Fuel                                                                                                                                      |               |
| Reference No                    | Reference No. Â· Reference No Â· Reference Number                                                                                                                      |               |
| Registered Laden Weight         | Registered Laden Weight Â· Laden Weight Â· Laden Weight (KG) Â· Weight (KG)                                                                                          |               |
| Vehicle details matching policy | Whether Vehicle Details are matching Â· Vehicle Details matching Â· Details matching with policy                                                                       | Yes           |
| Mismatch Remarks                | Vehicle Details Mismatch Remarks Â· Mismatch Remarks                                                                                                                     |               |
| Cause and Nature of Accident    | Cause and Nature of Accident Â· Nature of Accident Â· Cause of Accident Â· Nature of Loss                                                                            |               |
| Vehicle parked                  | Was the vehicle parked Â· Vehicle parked during accident                                                                                                                 | No            |
| Route/Area of Operation         | Route/Area of Operation Â· Route Â· Area of Operation                                                                                                                  |               |
| Tax Paid Upto                   | Tax Paid Upto Â· Tax Paid Up to Â· Tax Valid                                                                                                                           |               |
| Transfer Date                   | Transfer Date Â· Date of Transfer                                                                                                                                        |               |
| Driver relationship             | Relationship of the driver with the Insured Â· Relationship of driver with insured Â· Driver Relationship Â· Relation with Insured Â· Relationship with Insured    | Self          |
| Licence Type                    | License Type of Driver Â· License Type Â· Type of License Â· DL Type                                                                                                 |               |
| DOB of Driver                   | DOB of Driver Â· Driver DOB Â· Date of Birth of Driver Â· Driver Date of Birth                                                                                       |               |
| Driver Name                     | Driver Name Â· Name of Driver Â· Name of the Driver                                                                                                                    |               |
| Age of Driver                   | Age of Driver Â· Driver Age (replaced by the calculated age)                                                                                                             |               |
| Licence valid                   | Is the motor driving license valid Â· License Valid Â· DL Valid                                                                                                        | Yes           |
| Issuing Authority               | License Issuing Authority Â· Issuing Authority Â· DL Issuing Authority                                                                                                 |               |
| Licence Number                  | Driver Driving License Number Â· Driving License Number Â· DL Number Â· DL No Â· License No                                                                        |               |
| Licence Issue Date              | Driver Driving License Issue Date Â· DL Issue Date Â· License Issue Date                                                                                               |               |
| Licence Expiry Date             | Driver Driving License Expiry Date Â· DL Expiry Date Â· License Expiry Date Â· License Valid Till                                                                    |               |
| Badge No                        | Badge Number Â· Badge No                                                                                                                                                 |               |
| Charged U/S MV Act              | Charged U/S Motor Vehicle Act Â· Charged under MV Act                                                                                                                    | NA            |
| Charged U/S IPC                 | Charged U/S IPC Â· Charged under IPC                                                                                                                                     | NA            |
| FIR Number                      | FIR Number Â· FIR No Â· F.I.R. No                                                                                                                                      | NA            |
| FIR Date                        | FIR Date Â· Date of FIR Â· F.I.R. Date                                                                                                                                 |               |
| Police Station                  | Police Station Name Â· Police Station Â· PS Name                                                                                                                       | NA            |
| Name of Informant               | Name of the Informant Â· Informant Name                                                                                                                                  |               |
| Sections of Law                 | Sections of Law Â· Section of Law                                                                                                                                        |               |
| Driver without licence          | Whether driver without license Â· Driver without license                                                                                                                 | No            |
| Previous police records         | Any Previous Police Records Â· Previous Police Record                                                                                                                    | No            |
| TP claim                        | Is there any TP claim Â· Any TP Claim Â· TP Claim                                                                                                                      | No            |
| IFSC Code                       | IFSC Code Â· IFSC Â· IFS Code                                                                                                                                          |               |
| Account Number                  | Account Number Â· Account No Â· A/C No Â· Acct No                                                                                                                    |               |
| Account Type                    | Account Type Â· A/C Type Â· Type of Account                                                                                                                            | Savings       |
| Payment Method                  | Party Payment Method Â· Payment Method Â· Mode of Payment                                                                                                              | NEFT          |
| Approval Type                   | Approval Type Â· Type of Approval                                                                                                                                        |               |
| Work Approval Date              | Work Approval Date Â· Approval Date                                                                                                                                      |               |
| Work Approval Time              | Work Approval Time Â· Approval Time                                                                                                                                      |               |
| No. of invoices                 | No of invoices available Â· Number of Invoices Â· No. of Invoices                                                                                                      | 1             |
| Invoice in name of NIA          | Whether Payment invoice is in name of NIA Â· Invoice in name of NIA                                                                                                      | Yes (setting) |
| GST Applicable                  | Is GST Applicable Â· GST Applicable                                                                                                                                      | Yes           |
| Vendor/Tax Invoice Date         | Vendor/Tax Invoice Date Â· Tax Invoice Date Â· Invoice Date                                                                                                            |               |
| Vendor/Tax Invoice Number       | Vendor/Tax Invoice Number Â· Tax Invoice Number Â· Invoice No Â· Invoice Number                                                                                      |               |
| Nil Depreciation (Yes / No)     | Nil Depreciation · Nil Dep · Zero Depreciation · Zero Dep (ignores rows containing "amount"; accepts Yes/No only)                                             |               |
| Primary Assessment              | Primary Assessment Â· Assessment Amount Â· Net Payable Â· Net Amount                                                                                                 |               |
| Supplementary estimate          | Is there any supplementary estimate Â· Supplementary Estimate Â· Supplementary                                                                                         | No            |
| Painting work details           | Painting work details Â· Painting Details Â· Painting Work                                                                                                             |               |
| Re-Inspection Required          | Whether Re-Inspection Required Â· Re-Inspection Required Â· Reinspection Required                                                                                      | No            |
| Nil Dep Amount                  | Nil Depreciation (Zero Dep) Amount Â· Zero Dep Amount Â· Nil Depreciation Amount                                                                                       |               |
| Engine Protect                  | Engine Protect Extension Amount Â· Engine Protect Amount Â· Engine Protection                                                                                          | 0             |
| Consumables                     | Consumable Items Amount Â· Consumables Amount Â· Consumable                                                                                                            | 0             |
| Key Protect                     | Key Protect Amount Â· Key Protection Amount                                                                                                                              | 0             |
| Net Salvage                     | Net Salvage Â· Salvage Value Â· Salvage                                                                                                                                | 0             |
| Salvage invoice mapping         | Net Salvage to map with which Invoice Â· Salvage Invoice Mapping                                                                                                         | Invoice 1     |
| Compulsory Excess               | Less Compulsory Excess Â· Compulsory Excess Â· Coumpulsary excess                                                                                                      | 0             |
| Voluntary Excess                | Less Voluntary Excess Â· Voluntary Excess Â· voluntry excess                                                                                                           | 0             |
| Imposed Excess                  | Less Imposed Excess Â· Imposed Excess                                                                                                                                    | 0             |
| Towing Charges                  | Towing / Additional Towing Charges Â· Towing Charges Â· Additional Towing                                                                                              | 0             |
| Additional Towing               | Additional Towing Charges Â· Addl Towing Charges Â· Addl. Towing                                                                                                       | 0             |
| Other Deductions                | Less Any Other Deductions Â· Other Deductions Â· Less Other Deductions Â· Any Other Deductions                                                                       | 0             |
| Verification                    | Verification Checkbox Â· Verification                                                                                                                                    | Yes           |
| Date of Survey                  | date of survey Â· date of servey Â· Date and Time of Survey Â· Survey Date                                                                                           |               |
| Time of Survey                  | Time Â· time of survey Â· Survey Time Â· time of servey                                                                                                              | 11:00         |
| Place of Survey                 | place of survey Â· place of servey Â· address                                                                                                                          |               |
| Remarks | Report labels remain available to extraction. Quick Update and Extraction Review use **Remarks Default** in Automation Defaults. | Yes (shipped) |
| Mobile No                       | mobile no Â· mobile Â· Mobile: Â· surveyor_mobile                                                                                                                    |               |
| Email ID                        | (first ".com" email, cell I4 first) Â· email id Â· email Â· e-mail:- Â· surveyor_email                                                                             |               |
| Professional Fee                | professional fee Â· professional fees Â· survey fee Â· survey fees Â· Prof. Fee Â· Prof. Fees                                                                    |               |
| Conveyance                      | Conveyance Â· Conveyance Charges Â· Traveling Expenses Â· Conveyance Amount Â· Travel Expenses Â· Conveyance Charge Â· Traveling Charge Â· Traveling Charges |               |
| Others (fee bill)               | Others Â· Other Charges Â· Other Amount Â· Misc Â· Misc Charges                                                                                                    |               |
| Payment To                      | Any cell with "payment to insured", "payment to reimbursement", "payment to repairer", "payment to dealer", or "favour" with insured, repairer or dealer                   | Insured       |

To stop a wrong match, a label without the word "date" never matches a cell that contains "date", and a label without "person" never matches a cell that contains "person".

---

## Appendix B: Extra survey PDF labels

When reading a survey PDF, App3 adds these labels to the Excel ones above. Longer labels are tried first.

| Field                        | Extra PDF labels                                                                                                           |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Claim Number                 | Claim #                                                                                                                    |
| Registered Owner Name        | Registered Owner Â· Insured Â· Name of Insured                                                                         |
| Registration Number          | Registered Number Â· Registration No.                                                                                    |
| Engine No / Chassis No       | Engine No. Â· Chassis No.                                                                                                |
| Vehicle Make                 | Make / Variant/ Model /Color Â· Make / Model                                                                             |
| Cause and Nature of Accident | CAUSE & NATURE OF ACCIDENT Â· CAUSE AND NATURE OF ACCIDENT                                                               |
| Licence Number               | Motor Driver License Number Â· Licence No.                                                                               |
| Licence Issue Date           | Date of Issue                                                                                                              |
| Licence Expiry Date          | Valid up to (NTV) Â· Valid Till                                                                                          |
| Net Salvage                  | (-) Salvage                                                                                                                |
| Compulsory Excess            | (-) Excess Â· Less Excess                                                                                                |
| Imposed Excess               | (-) Impose Excess                                                                                                          |
| Date of Survey               | Date & Time of Survey Â· Date of Survey                                                                                  |
| Time of Survey               | Time of Survey (the plain "Time" label is not used on PDFs)                                                                |
| Place of Survey              | Surveyed At Â· Inspection Place Â· Workshop Name Â· Name of Workshop (the plain "Address" label is not used on PDFs) |
| Mobile No                    | Mobile No. Â· Mobile Number Â· Mob Â· Contact No Â· Contact Number                                                 |
| Email ID                     | Email ID Â· Email Address Â· E-mail ID Â· E-mail Â· E mail                                                         |
| Professional Fee             | Professional Fees Â· Survey Fee                                                                                          |
| Conveyance                   | Travelling Expenses                                                                                                        |

For PDF claims, Photos Amount is always 200 (setting), and the primary assessment sheet can only be uploaded when the folder already has one (App3 builds it from Excel only).

---

*End of guide.*
