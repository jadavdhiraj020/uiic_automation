
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

> **Big difference from OIC:** on New India, App3 does **not** stop and wait for you when a field cannot be filled. It writes a line in the log and carries on (see section 17). Always review the form before final submission.

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
- Text fields (names, body type, colour, cause of accident, RTO and similar) accept any text.
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
| Primary assessment (Excel)     | Claim Assessment                                              | primary_assessment, primary assessment, assessment. If none, App3 builds one (section 12.2).                                                                                |
| Supplementary estimate (Excel) | Claim Assessment                                              | supplementary_estimate, supplementary estimate, estimate                                                                                                                    |
| Driving Licence                | Document Upload                                               | dl, driving_license, driving_licence, driving license, driving licence, license                                                                                             |
| Registration Certificate       | Document Upload                                               | rc, rc_book, registration_certificate, registration certificate, regn_cert                                                                                                  |
| Claim Form                     | Document Upload                                               | claim_form, claim form, claimform                                                                                                                                           |
| Everything else                | Document Upload                                               | Every other PDF or picture in the folder is merged into one "Claim Related Documents" PDF.                                                                                  |

Files larger than 1.5 MB are compressed before upload. The merged PDF may be up to 15 MB.

---

## 3. The journey through the portal

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

Before NEFT Details and Claim Assessment, App3 waits for the cheque and invoice reading to finish (it may run in the background while earlier steps are filled). If that reading is not ready, the run stops at that step.

---

## 4. Login and finding the claim

| Field           | Method               | How it is filled                                                                                                                    |
| --------------- | -------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| Username        | âš™ï¸ Setting | From New India settings in App3.                                                                                                    |
| Password        | âš™ï¸ Setting | From New India settings in App3.                                                                                                    |
| reCAPTCHA       | ðŸ§® Calculated  | App3 ticks "I'm not a robot". If Google shows a picture puzzle, you solve it and click Login in Chrome within 45 seconds (setting). |
| Worklist        | ðŸ”’ Fixed       | Opens the Worklist menu.                                                                                                            |
| Filter Criteria | ðŸ”’ Fixed       | "Claim No."                                                                                                                         |
| Claim No        | ðŸ“„ Direct      | Typed letter by letter, then Filter is clicked. Blocks start if missing.                                                            |
| Edit            | ðŸ”’ Fixed       | Opens the first claim in the results.                                                                                               |

---

## 5. Quick Update

| Field                             | Method              | How the value is decided                                                                                                                                        | If missing                       |
| --------------------------------- | ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| **Date of Survey**          | ðŸ”§ Cleaned    | DD/MM/YYYY. If the portal lists the same date as a choice, App3 picks it. Otherwise it picks "Others" and types the date.                                       | Left empty                       |
| **Time of Survey**          | ðŸ”§ Cleaned    | 24-hour HH:MM. Looked for in the survey date cell (for example "27/04/2023 11:30 AM"), then the cells next to it, then a "Time" label. "4:15 PM" becomes 16:15. | Excel: "11:00". PDF: left empty. |
| **Place of Survey**         | ðŸ“„ Direct     | From "Place of Survey" (Excel can fall back to "Address").                                                                                                      | Left empty                       |
| Survey Completed                  | ðŸ”’ Fixed      | YES                                                                                                                                                             |                                  |
| Driving Licence Applicable        | ðŸ”’ Fixed      | YES                                                                                                                                                             |                                  |
| DL Verified with Original         | ðŸ”’ Fixed      | YES                                                                                                                                                             |                                  |
| RC Verified with Original         | ðŸ”’ Fixed      | YES                                                                                                                                                             |                                  |
| DL Verified on Parivahan          | ðŸ”’ Fixed      | YES                                                                                                                                                             |                                  |
| RC Verified on Parivahan          | ðŸ”’ Fixed      | YES                                                                                                                                                             |                                  |
| Close Proximity / Break-In        | ðŸ”’ Fixed      | YES                                                                                                                                                             |                                  |
| Inspection Report Uploaded        | ðŸ”’ Fixed      | YES                                                                                                                                                             |                                  |
| **Remarks**                 | ðŸ“„ Direct     | From "Remarks" or "Surveyor observation".                                                                                                                       | "Ok" (setting)                   |
| **Mobile No**               | ðŸ”§ Cleaned    | 10 digits only. When the cell has more digits, App3 takes the 10-digit number starting with 5 to 9.                                                             | Left empty                       |
| **Email ID**                | ðŸ“„ Direct     | Excel: the first email ending in ".com" on the first sheet, checking cell I4 first, then the email labels.                                                      | Left empty                       |
| **Expected Date of Repair** | ðŸ§® Calculated | Same date as the Date of Survey.                                                                                                                                | Left empty                       |

The YES answers are only clicked when the portal does not already show YES.

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

| Field                                   | Method               | How the value is decided                                                                                                                                                                                                                                                                     | If missing   |
| --------------------------------------- | -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ |
| Reference No                            | ðŸ“„ Direct      | From "Reference No."                                                                                                                                                                                                                                                                         | Left empty   |
| **Registered Owner Name**         | ðŸ“„ Direct      |                                                                                                                                                                                                                                                                                              | Blocks start |
| **Registration Number** (4 boxes) | ðŸ”§ Cleaned     | Spaces and dashes removed, capitals. Split into state letters / district number / series letters / number. GJ-01-AB-1234 â†’ GJ / 01 / AB / 1234. GJ011234 â†’ GJ / 01 / (empty) / 1234. A number that does not follow this pattern (for example BH series 22BH1234AA) is not entered. | Blocks start |
| **Registration Date**             | ðŸ”§ Cleaned     | DD/MM/YYYY                                                                                                                                                                                                                                                                                   | Blocks start |
| **Engine No**                     | ðŸ“„ Direct      |                                                                                                                                                                                                                                                                                              | Blocks start |
| **Chassis No**                    | ðŸ“„ Direct      |                                                                                                                                                                                                                                                                                              | Blocks start |
| Physically Verified                     | ðŸ”’ Fixed       | Ticked.                                                                                                                                                                                                                                                                                      |              |
| **Type of Body**                  | ðŸ” Matched     | From the report.                                                                                                                                                                                                                                                                             | Blocks start |
| **Class of Vehicle**              | ðŸ“„ Direct      | Typed as written.                                                                                                                                                                                                                                                                            | Blocks start |
| Pre-Accident Condition                  | ðŸ“„ Direct      |                                                                                                                                                                                                                                                                                              | "Good"       |
| Route/Area of Operation                 | ðŸ“„ Direct      |                                                                                                                                                                                                                                                                                              | Left empty   |
| Tax Paid Upto                           | ðŸ“„ Direct      | Typed as read, not converted to DD/MM/YYYY.                                                                                                                                                                                                                                                  | Left empty   |
| **RTO Name**                      | ðŸ“„ Direct      |                                                                                                                                                                                                                                                                                              | Blocks start |
| Transfer Date                           | ðŸ”§ Cleaned     | DD/MM/YYYY                                                                                                                                                                                                                                                                                   | Left empty   |
| **Odometer Reading**              | ðŸ”§ Cleaned     | Digits only. "45,230 km" â†’ 45230.                                                                                                                                                                                                                                                       | Blocks start |
| **Vehicle Color**                 | ðŸ“„ Direct      |                                                                                                                                                                                                                                                                                              | Blocks start |
| Vehicle Color Type                      | ðŸ“„ Direct      |                                                                                                                                                                                                                                                                                              | "Solid"      |
| **Type of Vehicle**               | ðŸ§® Calculated  | From Registered Laden Weight: **over 3,000 kg â†’ Goods Carrying (A)**, 3,000 kg or less â†’ Passenger Carrying (C). The report's own "Type of Vehicle" is used only when the weight has no number in it.                                                                        | Blocks start |
| **Type of Fuel**                  | ðŸ” Matched     | From the report.                                                                                                                                                                                                                                                                             | Blocks start |
| Vehicle Make                            | ðŸš« Not entered | Read and required before start, but never typed.                                                                                                                                                                                                                                             | Blocks start |
| Registered Laden Weight                 | ðŸš« Not entered | Only used to work out Type of Vehicle.                                                                                                                                                                                                                                                       | Blocks start |

---

## 8. Driver Details

| Field                                                                 | Method              | How the value is decided                                                                                        | If missing       |
| --------------------------------------------------------------------- | ------------------- | --------------------------------------------------------------------------------------------------------------- | ---------------- |
| Was the vehicle parked during accident?                               | ðŸ”’ Fixed      | Always "No". The report's answer is read but not used.                                                          |                  |
| Relationship of the driver with the Insured                           | ðŸ” Matched    | From the report.                                                                                                | "Self" (setting) |
| Licence Type of Driver                                                | ðŸ” Matched    | From the report.                                                                                                | Left empty       |
| **DOB of Driver**                                               | ðŸ”§ Cleaned    | DD/MM/YYYY                                                                                                      | Blocks start     |
| **Driver Name**                                                 | ðŸ“„ Direct     |                                                                                                                 | Blocks start     |
| **Age of Driver**                                               | ðŸ§® Calculated | Completed years from the date of birth to the **day of the run**. Replaces any age written in the report. | Blocks start     |
| Is the licence valid for the type of vehicle on the date of accident? | ðŸ”’ Fixed      | Yes                                                                                                             |                  |
| Licence Issuing Authority                                             | ðŸ“„ Direct     |                                                                                                                 | Left empty       |
| **Driving Licence Number**                                      | ðŸ“„ Direct     | Typed as written.                                                                                               | Blocks start     |
| **Licence Issue Date**                                          | ðŸ”§ Cleaned    | DD/MM/YYYY                                                                                                      | Blocks start     |
| **Licence Expiry Date**                                         | ðŸ”§ Cleaned    | DD/MM/YYYY                                                                                                      | Blocks start     |
| Badge No                                                              | ðŸ“„ Direct     |                                                                                                                 | Left empty       |

---

## 9. FIR Details

| Field                           | Method               | How the value is decided                                       | If missing     |
| ------------------------------- | -------------------- | -------------------------------------------------------------- | -------------- |
| FIR Number                      | ðŸ“„ Direct      |                                                                | "NA" (setting) |
| FIR Date                        | ðŸ”§ Cleaned     | DD/MM/YYYY                                                     | Left empty     |
| Police Station Name             | ðŸ“„ Direct      |                                                                | "NA" (setting) |
| Charged U/S Motor Vehicle Act   | ðŸ“„ Direct      |                                                                | "NA" (setting) |
| Charged U/S IPC                 | ðŸ“„ Direct      |                                                                | "NA" (setting) |
| Whether driver without licence? | ðŸ”§ Cleaned     | "Yes" only when the report says Yes. Anything else becomes No. | "No"           |
| Any previous police records     | ðŸ”§ Cleaned     | Same rule.                                                     | "No"           |
| Is there any TP claim?          | ðŸ”§ Cleaned     | Same rule.                                                     | "No"           |
| Name of Informant               | ðŸš« Not entered | Read only.                                                     |                |
| Sections of Law                 | ðŸš« Not entered | Read only.                                                     |                |

---

## 10. NEFT Details

| Field                          | Method               | How the value is decided                                                                                                                                                                                                                | If missing                                   |
| ------------------------------ | -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| **Payment To**           | ðŸ§® Calculated  | **Dealer** when the report says "payment to repairer", "payment to dealer" or "in favour of" a repairer or dealer. **Insured** when it says "payment to insured", "payment to reimbursement" or "in favour of" the insured. | "Insured"                                    |
| Dealer Name (only when Dealer) | ðŸ§® Calculated  | The Registered Owner Name. There is no dealer label for New India.                                                                                                                                                                      |                                              |
| **IFSC Code**            | ðŸ“„ Direct      | From the report, else from the cheque photo. App3 then clicks Find to load the bank branch.                                                                                                                                             | Blocks start unless the cheque can supply it |
| **Account Number**       | ðŸ“„ Direct      | From the report, else from the cheque photo.                                                                                                                                                                                            | Blocks start unless the cheque can supply it |
| Re-Enter Account Number        | ðŸ§® Calculated  | Same as Account Number.                                                                                                                                                                                                                 |                                              |
| Account Type                   | ðŸ” Matched     | From the report. When the report says nothing (or says Savings) and the cheque shows a type, the cheque wins. Entered in capitals.                                                                                                      | "Savings" (setting)                          |
| Party Payment Method           | âš™ï¸ Setting | NEFT                                                                                                                                                                                                                                    |                                              |

The cheque is only read when IFSC Code or Account Number is missing from the report.

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

### 12.1 Fields

| Field                                                                  | Method               | How the value is decided                                                                                                                       | If missing                                    |
| ---------------------------------------------------------------------- | -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| Whether payment invoice is in name of NIA                              | âš™ï¸ Setting | Yes                                                                                                                                            |                                               |
| **Vendor/Tax Invoice Date**                                      | ðŸ”§ Cleaned     | DD/MM/YYYY. From the report, else from the invoice PDF.                                                                                        | Blocks start unless the invoice can supply it |
| **Vendor/Tax Invoice Number**                                    | ðŸ“„ Direct      | From the report, else from the invoice PDF.                                                                                                    | Blocks start unless the invoice can supply it |
| Is there any primary estimate                                          | ðŸ”’ Fixed       | Yes                                                                                                                                            |                                               |
| Primary assessment sheet                                               | ðŸ“Ž File        | The assessment Excel from the folder, or the one App3 builds (12.2). Then Upload is clicked.                                                   | Skipped with a warning                        |
| Is there any supplementary estimate                                    | ðŸ§® Calculated  | Yes when an estimate Excel is in the folder, otherwise No. The report's answer is not used.                                                    |                                               |
| Supplementary estimate sheet                                           | ðŸ“Ž File        | Uploaded only when the answer above is Yes.                                                                                                    |                                               |
| Painting work details                                                  | ðŸ” Matched     | Text containing "break", "labour" or "labor" â†’ Break-up. Containing "consol" â†’ Consolidated. Otherwise as written.                   | Left empty                                    |
| Net Salvage                                                            | ðŸ“„ Direct      | Skipped when 0.                                                                                                                                | Left empty                                    |
| Less Any Other Deductions                                              | ðŸ“„ Direct      | Skipped when 0.                                                                                                                                | Left empty                                    |
| Towing Charges                                                         | ðŸ“„ Direct      | Skipped when 0.                                                                                                                                | Left empty                                    |
| Additional Towing Charges                                              | ðŸ“„ Direct      | Skipped when 0.                                                                                                                                | Left empty                                    |
| Whether Re-Inspection Required                                         | âš™ï¸ Setting | No. The report's answer is not used.                                                                                                           |                                               |
| Nil Depreciation (Zero Dep) Amount                                     | ðŸ“„ Direct      | Only when the portal shows the box and the amount is not 0.                                                                                    | Left empty                                    |
| Engine Protect Amount                                                  | ðŸ“„ Direct      | Same rule.                                                                                                                                     | Left empty                                    |
| Consumable Items Amount                                                | ðŸ“„ Direct      | Same rule.                                                                                                                                     | Left empty                                    |
| Key Protect Amount                                                     | ðŸ“„ Direct      | Same rule.                                                                                                                                     | Left empty                                    |
| Compulsory, Voluntary and Imposed Excess                               | ðŸš« Not entered | Read only.                                                                                                                                     |                                               |
| Primary Assessment amount                                              | ðŸš« Not entered | Required before start. The portal takes the figures from the uploaded sheet.                                                                   | Blocks start                                  |
| No. of invoices, Salvage invoice mapping, GST Applicable, Verification | ðŸš« Not entered | Read only.                                                                                                                                     |                                               |
| Next                                                                   | ðŸ”’ Fixed       | Clicked, and retried once. If Document Upload still does not open, the run stops and the log names the portal fields still marked as required. |                                               |

### 12.2 How App3 builds the primary assessment sheet

When the folder has no assessment Excel, App3 builds **auto_primary_assessment.xlsx** from the **first sheet** of the survey Excel, in the portal's own template (columns SlNo, category, description, partName, serviceType, estimatedAmount, billedAmount, assessedAmount, depreciationPercentage, hsnCode, gstPercentage). A short audit file is saved next to it.

**Spare parts table.** Found by its header row: Sr/S.No, Description/Particulars/Item, Metal, Plastic, Glass (Estimated is optional). Each part row becomes:

| Amount found in | Description written           | Service type |
| --------------- | ----------------------------- | ------------ |
| Metal           | Parts at Agewise Depreciation | REPLACE      |
| Plastic         | Parts at 50% Depreciation     | REPLACE      |
| Glass           | Parts at Cost                 | REPLACE      |

Billed and Assessed both equal that amount. Estimated comes from the Estimated column. HSN is 8512 (setting). Depreciation % and GST % are written as 0.

Part rows are **left out** when: the name is blank; the name is a total, sub total, summary, less, add, salvage, depreciation, imposed, GST, tax or net line, or contains "%"; the name contains "labour"; there is no Metal, Plastic or Glass amount; or there are amounts in **more than one** of those columns. The table ends at a "sub total" row.

**Labour table.** Found by its header row: Sr, Description, R/R, Denting, C/W. For each row, the R/R, Denting and C/W amounts are **added together**. Category is Labor Charges, description "Labor charges for Repairing and Alignment", service type ALLOW, Estimated 0, HSN 8729 (setting), GST % 0. **Painting and Alignment columns are not included.**

A table whose header App3 is less than 80% sure of is skipped. If neither table gives any rows, no sheet is built.

---

## 13. Document Upload

| Row | Document Type            | File                              |
| --- | ------------------------ | --------------------------------- |
| 1   | Driving License          | Driving licence file              |
| 2   | Registration Certificate | RC file                           |
| 3   | Claim Form               | Claim form file                   |
| 4   | Claim Related Documents  | One merged PDF of all other files |

- A row is added only for a file that was found, so the numbering shifts when one is missing.
- **Claim Related Documents** holds every other PDF and picture in the folder that is not used elsewhere. App3's own outputs are left out, and Word, Excel and text files cannot be merged.
- Chassis and odometer photos, the cheque, the approval letter, the invoice and the assessment sheets are **not** in the merged PDF.
- After all rows are attached, App3 clicks Upload once and waits up to 30 seconds for the portal.

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
| Type of Vehicle               | Laden weight 16200 kg                                      | Goods Carrying (A)     |
| Type of Vehicle               | Laden weight 1450 kg                                       | Passenger Carrying (C) |
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

The run does not start when any of these 27 values is missing:

Claim Number Â· Registered Owner Name Â· Vehicle Registration Number Â· Date of Registration Â· Engine No Â· Chassis No Â· Vehicle Make Â· Type of Body Â· Class of Vehicle Â· RTO Name Â· Odometer Reading Â· Vehicle Color Â· Registered Laden Weight Â· Type of Vehicle Â· Type of Fuel Â· Cause/Nature of Accident Â· Driver Name Â· DOB of Driver Â· Age of Driver Â· Driver License Number Â· Driver License Issue Date Â· Driver License Expiry Date Â· IFSC Code Â· Account Number Â· Vendor/Tax Invoice Date Â· Vendor/Tax Invoice Number Â· Primary Assessment

- Odometer Reading and Primary Assessment may be 0. For the other fields, 0 counts as missing.
- Invoice Number and Date do not block the start when they will be read from the invoice PDF. IFSC Code and Account Number do not block the start when they will be read from the cheque. The run stops later if that reading does not deliver them.

### 16.2 These only warn (the run continues)

Vehicle Details Mismatch Remarks Â· Route/Area of Operation Â· Tax Paid Upto Â· Transfer Date Â· Badge Number Â· FIR Number Â· FIR Date Â· Police Station Name Â· Name of Informant Â· Net Salvage Â· Voluntary Excess Â· Imposed Excess Â· Towing/Additional Charges

---

## 17. When a field cannot be filled

New India works differently from OIC:

1. App3 waits up to 5 seconds for each field to appear. If it does not, App3 writes the field name in the log and **moves on**.
2. Typed values are **not read back** after filling.
3. Dropdowns are matched in three passes: exact text, then partial text either way, then any word of 3 or more letters. The **first** option that matches is chosen.
4. The run only stops when a whole step fails, for example: the claim cannot be found, Claim Assessment does not reach Document Upload, the Survey Fee Bill Submit button is missing, or the cheque or invoice reading is not ready.

So after every run, check the log for skipped fields and look over the form in Chrome.

---

## 18. Settings you can change

These are in App3 Settings â†’ Automation Defaults for New India.

| Setting                    | Default    | Affects                                                         |
| -------------------------- | ---------- | --------------------------------------------------------------- |
| Remarks                    | Ok         | Quick Update Remarks                                            |
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

Two settings are **not used** on New India today: **Observation default** (Remarks uses the Remarks setting) and **Table end words** (the sheet builder always stops at "sub total"). The 11:00 survey time is built in and has no New India setting.

---

## 19. Points worth checking

These are not errors in App3's working. They are rules that may differ from what you expect, so they are worth confirming with how you work.

| #  | Point                                      | What App3 does today                                                                                                                                                                                                    |
| -- | ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1  | Laden weight written with a comma          | "12,000 kg" is read as 12, so a goods vehicle is marked Passenger Carrying (C).                                                                                                                                         |
| 2  | Light goods vehicles                       | Any vehicle of 3,000 kg or less is marked Passenger Carrying (C), whatever the report says.                                                                                                                             |
| 3  | Excess amounts                             | Compulsory, Voluntary and Imposed Excess are read but never entered.                                                                                                                                                    |
| 4  | Vehicle Make and Primary Assessment amount | Both must be found before the run starts, but neither is typed on the portal.                                                                                                                                           |
| 5  | Fixed answers                              | Vehicle parked = No, Vehicle details matching policy = Yes, Licence valid = Yes, Physically Verified ticked, and all eight Quick Update answers (including Close Proximity / Break-In) = YES, whatever the report says. |
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
| Vehicle Make                    | Vehicle Make Â· Make of Vehicle Â· Make                                                                                                                                |               |
| Type of Body                    | Type of Body Â· Body Type                                                                                                                                                |               |
| Class of Vehicle                | Class of Vehicle Â· Vehicle Class                                                                                                                                        |               |
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
| Remarks                         | remarks Â· Remark Â· surveyor observation Â· OBERVATIONS/COMMENTS                                                                                                    | Ok            |
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
