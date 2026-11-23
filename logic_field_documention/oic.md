# OIC Portal Automation: Complete Field Guide

**App3 Â· Oriental Insurance Company (OIC) Â· Motor OD Surveyor Assessment**

This guide explains, in plain language, every field App3 fills on the OIC portal: where each value comes from, whether it is copied directly or worked out, what App3 changes before entering it, and what happens when it is missing.

> Based on the uiic_automation repository, main branch (commit 243c09c), reviewed on 21 November 2026.

---

## Contents

1. [How to read this guide](#1-how-to-read-this-guide)
2. [Where the data comes from](#2-where-the-data-comes-from)
3. [The journey through the portal](#3-the-journey-through-the-portal)
4. [Login and opening the form](#4-login-and-opening-the-form)
5. [Step 1: Search](#5-step-1-search)
6. [Step 2: Basic Details](#6-step-2-basic-details)
7. [Step 3: Interim Report](#7-step-3-interim-report)
8. [Step 4: Assessment of Loss](#8-step-4-assessment-of-loss)
9. [Step 5: Document Upload](#9-step-5-document-upload)
10. [All value changes at a glance](#10-all-value-changes-at-a-glance)
11. [Checks before the run starts](#11-checks-before-the-run-starts)
12. [When a field cannot be filled](#12-when-a-field-cannot-be-filled)
13. [Settings you can change](#13-settings-you-can-change)
14. [Points worth checking](#14-points-worth-checking)
15. [Appendix A: Excel labels App3 looks for](#appendix-a-excel-labels-app3-looks-for)
16. [Appendix B: Survey PDF labels App3 looks for](#appendix-b-survey-pdf-labels-app3-looks-for)
17. [Appendix C: Licence code to State](#appendix-c-licence-code-to-state)

---

## 1. How to read this guide

Every field is tagged with one method:

| Tag          | Method               | Meaning                                                                               |
| ------------ | -------------------- | ------------------------------------------------------------------------------------- |
| ðŸ“„     | **Direct**     | Copied from the survey report as written (extra spaces trimmed).                      |
| ðŸ”§     | **Cleaned**    | Taken from the report, then tidied: date format, digits only, capitals, length limit. |
| ðŸ§®     | **Calculated** | Worked out by App3 from other values.                                                 |
| ðŸ”     | **Matched**    | App3 picks the best option from the portal's own dropdown list.                       |
| âš™ï¸ | **Setting**    | A value from App3 Settings (Automation Defaults). You can change it.                  |
| ðŸ”’     | **Fixed**      | Always the same value, built into App3.                                               |
| â­ï¸ | **Skipped**    | The portal fills or locks this field, so App3 leaves it alone.                        |

**"If missing" column:**

- **Left empty:** App3 skips the field and moves on.
- **Pauses:** App3 stops on that field and asks you to fix it in Chrome (see section 12).
- **Blocks start:** App3 will not start the run until the value is found (see section 11).

All dates are entered on OIC as **DD-MM-YYYY** (for example 15-01-2024), whatever form they had in the report.

---

## 2. Where the data comes from

### 2.1 Two possible sources

| Source                                                       | When it is used                               | How App3 reads it                                                                                                                                                                                                                                                                                                                                          |
| ------------------------------------------------------------ | --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Excel survey report**                                | Used first whenever the claim folder has one. | App3 searches every sheet for a label (for example "Chassis No") and takes the first real value to the right of it on the same row. It tries each label in the list in order. A few values are read from an exact cell position (GST summary, depreciation rates).                                                                                         |
| **Survey PDF** (final survey report, typed or scanned) | Used when there is no Excel.                  | App3 reads the report section by section (Header, Insured, Vehicle, Driver, Accident, Survey, Workshop, Cause of Accident, Assessment, Fees). A label is only accepted inside its own section. Scanned text that is less than 84% certain is not used. If two different values are found for the same field, App3 flags it for review instead of guessing. |

**Extra PDF rules**

- Supporting reports (re-inspection, spot survey, supplementary) are rejected. You must select the final survey report.
- Fee bill PDFs in the folder (file name containing "fee bill" or starting with "SF bill") are used only to fill fees that are missing, and only when their claim, policy or vehicle number matches the survey report.

### 2.2 Files App3 looks for in the claim folder

| Document                               | File name contains                                            |
| -------------------------------------- | ------------------------------------------------------------- |
| Invoice (needed for Step 4 and Step 5) | final_invoice, invoice                                        |
| Workshop Repair Estimate               | estimate, workshop_estimate, repair_estimate, workshop_repair |
| Discharge cum Satisfaction Voucher     | discharge, voucher, satisfaction, discharge_voucher           |
| Re-Inspection Report                   | reinspection, re_inspection                                   |
| Driving Licence                        | driving_license, driving license, dl                          |
| Registration Certificate (RC)          | registration_certificate, registration certificate, rc        |
| Photographs                            | vehicle_photo, photograph, photo                              |
| Spot survey (Step 3 radio only)        | spot survey, spot_survey, spot-survey                         |

---

## 3. The journey through the portal

| Order | Stage                                | What happens                                                                |
| ----- | ------------------------------------ | --------------------------------------------------------------------------- |
| 1     | Login                                | Username, password and CAPTCHA                                              |
| 2     | Open the form                        | Others tab â†’ Motor OD Surveyor Assessment â†’ Generate Assessment + |
| 3     | **Step 1: Search**             | Claim Type and Policy or Claim Number                                       |
| 4     | **Step 2: Basic Details**      | Vehicle, Loss, Surveyor, Driver and Workshop details                        |
| 5     | **Step 3: Interim Report**     | Survey, document verification, initial loss and contact details             |
| 6     | **Step 4: Assessment of Loss** | Invoice and items, excess, salvage, survey charges, declaration             |
| 7     | **Step 5: Document Upload**    | Seven upload slots and remarks. Stops before Submit by default.             |

---

## 4. Login and opening the form

| Field          | Method               | How it is filled                                                                                                                                             |
| -------------- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Username       | âš™ï¸ Setting | From OIC settings in App3.                                                                                                                                   |
| Password       | âš™ï¸ Setting | From OIC settings in App3.                                                                                                                                   |
| CAPTCHA        | ðŸ§® Calculated  | App3 reads the CAPTCHA picture automatically. It tries up to 5 times (setting). If it still fails, you solve it and click Login in Chrome within 45 seconds. |
| Language popup | ðŸ”’ Fixed       | Clicks "Continue in English".                                                                                                                                |
| Advert popups  | ðŸ”’ Fixed       | Closed automatically.                                                                                                                                        |

---

## 5. Step 1: Search

| Field                   | Method              | How the value is decided                                                                                                        | If missing                                    |
| ----------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| **Claim Type**    | ðŸ§® Calculated | **REIMBURSEMENT** when the report says payment goes to the insured (or says reimbursement). Otherwise **CASHLESS**. | Excel: CASHLESS (setting). PDF: Blocks start. |
| **Policy Number** | ðŸ“„ Direct     | Used when available. OIC finds the claim more reliably by policy.                                                               | Claim Number is used instead.                 |
| **Claim Number**  | ðŸ“„ Direct     | Used only when there is no Policy Number.                                                                                       | Blocks start if both are missing.             |

**How "payment to" is found**

- **Excel:** App3 scans all cells for phrases such as "payment to insured" or "payment to reimbursement" (â†’ Reimbursement), or "payment to repairer" or "payment to dealer" (â†’ Cashless). It also reads sentences with "favour" plus insured, repairer or dealer.
- **PDF:** App3 reads lines such as "The payment to be made in favour of", "Payment To", "Claim Type" or "Settlement Type". Insured, claimant, reimbursement or non-cashless â†’ Reimbursement. Cashless, repairer, workshop or dealer â†’ Cashless.

---

## 6. Step 2: Basic Details

### 6.1 Policy and Claim Details

| Field                    | Method               | Notes                                         |
| ------------------------ | -------------------- | --------------------------------------------- |
| All fields in this block | â­ï¸ Skipped | OIC fills them from the claim and locks them. |

### 6.2 Vehicle Details (24 fields)

| #  | Portal field                     | Method              | How the value is decided or changed                                                                                                   | If missing                                                              |
| -- | -------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| 1  | Registration Number              | ðŸ“„ Direct     | As in the report. From a PDF, spaces are removed and letters are made capital.                                                        | Left empty                                                              |
| 2  | Make                             | ðŸ“„ Direct     | Full text, for example "MARUTI ALTO K10 VXI".                                                                                         | Left empty                                                              |
| 3  | Variant                          | ðŸ§® Calculated | Same full value as Make.                                                                                                              | Left empty                                                              |
| 4  | Registration Date                | ðŸ”§ Cleaned    | Changed to DD-MM-YYYY.                                                                                                                | Left empty                                                              |
| 5  | Year of Manufacture              | ðŸ”§ Cleaned    | Keeps only the 4-digit year ("2019 Model" â†’ 2019). If empty, App3 uses a year written inside Make ("ALTO VXI 2019" â†’ 2019). | Left empty. Blocks start if the year is not between 1900 and next year. |
| 6  | Chassis Number                   | ðŸ“„ Direct     | From a PDF it must have at least 8 characters and a digit.                                                                            | Left empty                                                              |
| 7  | Engine Number                    | ðŸ“„ Direct     | As in the report.                                                                                                                     | Left empty                                                              |
| 8  | Cubic Capacity                   | ðŸ”§ Cleaned    | Digits only ("1197 cc" â†’ 1197).                                                                                                  | Left empty                                                              |
| 9  | Type of Body                     | ðŸ“„ Direct     | As in the report.                                                                                                                     | Left empty                                                              |
| 10 | Class of Vehicle                 | ðŸ“„ Direct     | As in the report. Also used to choose Licence Type (6.5).                                                                             | Left empty                                                              |
| 11 | Unladen Weight                   | ðŸ”§ Cleaned    | Digits only ("865 kg" â†’ 865).                                                                                                    | Left empty                                                              |
| 12 | Road Tax Paid Upto               | ðŸ”§ Cleaned    | Changed to DD-MM-YYYY.                                                                                                                | Left empty                                                              |
| 13 | Color of Vehicle                 | ðŸ“„ Direct     | As in the report.                                                                                                                     | Left empty                                                              |
| 14 | Type of Fuel                     | ðŸ”§ Cleaned    | Removes a "Fuel used:" prefix and uses capitals ("Fuel used: Petrol" â†’ PETROL).                                                  | Left empty                                                              |
| 15 | RTO                              | ðŸ” Matched    | Chosen from OIC's RTO list. See the RTO rules below.                                                                                  | Pauses                                                                  |
| 16 | Registered Laden Weight          | ðŸ”§ Cleaned    | Digits only.                                                                                                                          | Left empty                                                              |
| 17 | Seating / Load Carrying Capacity | ðŸ”§ Cleaned    | Digits only ("5 persons" â†’ 5).                                                                                                   | Left empty                                                              |
| 18 | Fitness Valid Upto               | ðŸ”§ Cleaned    | Changed to DD-MM-YYYY. App3 reads the field back to make sure OIC kept the date.                                                      | Left empty                                                              |
| 19 | Permit Number                    | ðŸ“„ Direct     | As in the report.                                                                                                                     | Left empty                                                              |
| 20 | Type of Permit                   | ðŸ“„ Direct     | As in the report.                                                                                                                     | Left empty                                                              |
| 21 | Permit Valid Upto                | ðŸ”§ Cleaned    | Changed to DD-MM-YYYY.                                                                                                                | Left empty                                                              |
| 22 | Authorization Number             | ðŸ“„ Direct     | As in the report.                                                                                                                     | Left empty                                                              |
| 23 | Validity of Authorization        | ðŸ“„ Direct     | As text from Excel. Read as a date from a PDF.                                                                                        | Left empty                                                              |
| 24 | Road / Area of Operation         | ðŸ“„ Direct     | As in the report.                                                                                                                     | Left empty                                                              |

#### RTO rules (field 15)

App3 tries these in order and stops at the first match:

1. **Office code from the Registration Number.** GJ01AB1234 â†’ **GJ01**. Old-style numbers such as GJ011234 also work. If the registration has no code, a code written in the report's RTO text is used.
2. **An OIC office showing that code**, or a known office name for it (for example PB65 â†’ Mohali / SAS Nagar, DL01 â†’ North Delhi).
3. **The district for that code** from App3's list of 772 codes (for example GJ01 â†’ Ahmadabad, MH12 â†’ Pune).
4. **The RTO name written in the report**, matched by place name. Words like "Regional", "Transport" and "Office" are ignored.
5. **Fallback:** the district, then the first OIC office in the same state. App3 writes a warning asking you to review the office.

> **Mismatch guard:** if the registration code and the report's RTO name point to different places (another state, district or direction such as North vs South), App3 pauses and lets you pick the RTO in Chrome when the source is a PDF. With Excel it continues with the registration-code choice and writes a warning.

### 6.3 Loss Details (5 fields)

| # | Portal field           | Method              | How the value is decided                                                                                                                                                                                                         | If missing                                                                      |
| - | ---------------------- | ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| 1 | Close Proximity        | ðŸ§® Calculated | **YES** when Date of Accident and Date of Allotment of Survey are **more than 10 days apart**. Otherwise **NO**.                                                                                               | NO (also when a date is NA or unreadable)                                       |
| 2 | 64VB Confirmed         | ðŸ”’ Fixed      | Always **YES**.                                                                                                                                                                                                            | Not applicable                                                                  |
| 3 | Nil Depreciation Cover | ðŸ”§ Cleaned    | **YES** when the report says Yes, Y, True, 1, "Nil Dep" or "Nil Depreciation", or the text contains "yes". Otherwise **NO**.                                                                                         | Blocks start (it must be clearly Yes or No, because depreciation depends on it) |
| 4 | Age of Vehicle         | ðŸ§® Calculated | Time from Registration Date to Accident Date (or to today if there is no accident date), written as "5 years 3 months". If there is no usable registration date, the report's own value (for example "LIFE OF VEHICLE") is used. | Left empty (also when the registration date is after the accident date)         |
| 5 | Loss Description       | ðŸ”’ Fixed      | Always "As per estimate".                                                                                                                                                                                                        | Not applicable                                                                  |

**Examples**

- Accident 01-03-2026, allotment 15-03-2026 â†’ 14 days apart â†’ Close Proximity **YES**.
- Accident 01-03-2026, allotment 05-03-2026 â†’ 4 days apart â†’ Close Proximity **NO**.
- Registered 15-01-2019, accident 20-04-2024 â†’ Age of Vehicle **5 years 3 months**.

### 6.4 Surveyor Details (5 fields)

| # | Portal field         | Method           | How the value is decided                                                       | If missing |
| - | -------------------- | ---------------- | ------------------------------------------------------------------------------ | ---------- |
| 1 | Name of the Surveyor | ðŸ“„ Direct  | Filled only if OIC allows editing. Normally OIC fills and locks it.            | Left empty |
| 2 | Email ID             | ðŸ“„ Direct  | Same rule.                                                                     | Left empty |
| 3 | Mobile Number        | ðŸ”§ Cleaned | Same rule. Reduced to a 10-digit mobile ("+91 98765 43210" â†’ 9876543210). | Left empty |
| 4 | Address              | ðŸ“„ Direct  | Same rule.                                                                     | Left empty |
| 5 | PAN Number           | ðŸ“„ Direct  | Same rule.                                                                     | Left empty |

### 6.5 Driver Details (19 fields + 1 that appears only sometimes)

| #   | Portal field             | Method               | How the value is decided or changed                                                                                                                                                                            | If missing                                           |
| --- | ------------------------ | -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| 1   | Driver Name              | ðŸ”§ Cleaned     | Line breaks removed and **cut to 20 characters** (OIC's limit). From a PDF, any "DOB ..." text on the same line is removed. App3 checks that OIC kept the name and retypes it letter by letter if not.   | Pauses                                               |
| 2   | Date of Birth            | ðŸ”§ Cleaned     | Changed to DD-MM-YYYY. In a PDF it may sit on the same line as the driver name.                                                                                                                                | Pauses                                               |
| 3   | Licence Type             | ðŸ” Matched     | Chosen from Class of Vehicle. See the licence type table below.                                                                                                                                                | Left empty with a warning. OIC needs it before Next. |
| 4   | Valid From               | ðŸ”§ Cleaned     | Driving licence issue date, changed to DD-MM-YYYY.                                                                                                                                                             | Pauses                                               |
| 5   | Valid Up To              | ðŸ”§ Cleaned     | Driving licence expiry date, changed to DD-MM-YYYY.                                                                                                                                                            | Pauses                                               |
| 6   | Licence No. box 1        | ðŸ§® Calculated  | First 2 letters of the licence (state code), chosen from the dropdown.                                                                                                                                         | Pauses                                               |
| 7   | Licence No. box 2        | ðŸ§® Calculated  | First 6 digits.                                                                                                                                                                                                | Pauses                                               |
| 8   | Licence No. box 3        | ðŸ§® Calculated  | Last 6 digits.                                                                                                                                                                                                 | Pauses                                               |
| 9   | Badge No.                | ðŸ“„ Direct      | As in the report.                                                                                                                                                                                              | Left empty                                           |
| 10  | Badge Issue Date         | ðŸ”§ Cleaned     | Changed to DD-MM-YYYY.                                                                                                                                                                                         | Left empty                                           |
| 11  | Is Owner Driver?         | ðŸ§® Calculated  | Compares Driver Name with Registered Owner Name. See the rules below.                                                                                                                                          | YES                                                  |
| 11a | Relationship with Driver | âš™ï¸ Setting | Only when Owner Driver is NO and OIC shows the field. Default "other".                                                                                                                                         | Left empty                                           |
| 12  | Qualification            | ðŸ“„ Direct      | As in the report.                                                                                                                                                                                              | Left empty                                           |
| 13  | Third Party Involved     | ðŸ”’ Fixed       | Always **NO**.                                                                                                                                                                                           | Not applicable                                       |
| 14  | Country                  | â­ï¸ Skipped | OIC fills INDIA and locks it.                                                                                                                                                                                  | Not applicable                                       |
| 15  | State                    | ðŸ§® Calculated  | From the first 2 letters of the driving licence (Appendix C). GJ â†’ GUJARAT.                                                                                                                               | Pauses                                               |
| 16  | City                     | ðŸ§® Calculated  | From the first 4 characters of the licence (state + 2-digit office). GJ01 â†’ AHMADABAD. Uses App3's list of 772 codes.                                                                                     | Pauses                                               |
| 17  | Pincode                  | ðŸ” Matched     | **Excel:** the first pincode OIC offers after the City is chosen. **PDF:** the driver's pincode from the report (or a 6-digit number inside the driver address). It must match exactly one option. | Pauses                                               |
| 18  | Address                  | ðŸ“„ Direct      | Driver address. If empty, Place of Survey is used.                                                                                                                                                             | Pauses if both are empty                             |
| 19  | Charges Filed            | âš™ï¸ Setting | Uses the setting. Empty by default, so it is skipped.                                                                                                                                                          | Left empty                                           |

#### Licence Type rules (field 3)

| Class of Vehicle contains                                         | Licence Type chosen                                                               |
| ----------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| motor cycle, m cycle, scooter, two wheeler, 2 wheeler             | MOTOR CYCLE WITH GEAR                                                             |
| HGV, or heavy + goods                                             | HGV                                                                               |
| HPV, or heavy + passenger                                         | HPV                                                                               |
| LMV or LGV or light, together with goods                          | LIGHT MOTOR VEHICLE - GOODS                                                       |
| LMV or light, together with passenger                             | LIGHT MOTOR VEHICLE - PASSENGER                                                   |
| LMV, light motor, car or jeep (no goods or passenger)             | LIGHT MOTOR VEHICLE - NON TRANSPORT                                               |
| "heavy" without goods or passenger, or more than one of the above | No choice made (unclear). Warning written.                                        |
| none of the above                                                 | The report's own licence type. "LMV" becomes LIGHT MOTOR VEHICLE - NON TRANSPORT. |

Whole words are matched, so "cargo" or "carriage" is not read as "car".

#### Licence Number split (fields 6 to 8)

Spaces, slashes and dashes are removed first. OIC needs **2 letters + 6 digits + 6 digits**.

| Licence in report | Box 1 | Box 2  | Box 3  | What happens                                                                              |
| ----------------- | ----- | ------ | ------ | ----------------------------------------------------------------------------------------- |
| GJ-012011-001234  | GJ    | 012011 | 001234 | Exactly 12 digits. Filled straight away.                                                  |
| GJ01 20110012345  | GJ    | 012011 | 012345 | 13 digits. App3 shows that it will leave out the middle "0" and waits for you to confirm. |
| GJ1A 2011 0012345 |       |        |        | Not in the expected shape. App3 pauses so you can enter it.                               |

> Most new-format licences have 13 digits, so expect the confirmation on most claims.

#### Is Owner Driver rules (field 11)

Names are compared without caring about capitals or extra spaces.

| Driver Name  | Registered Owner | Result        | Why                                        |
| ------------ | ---------------- | ------------- | ------------------------------------------ |
| Ramesh Patel | RAMESH K PATEL   | **YES** | 2 words in common                          |
| Ramesh       | Ramesh Patel     | **YES** | One-word driver name that matches          |
| Suresh Patel | Ramesh Patel     | **NO**  | Only 1 word in common                      |
| (blank)      | any              | **YES** | Safe default, most claims are owner-driven |

### 6.6 Workshop Details (4 fields)

| # | Portal field             | Method           | How the value is decided or changed                                                                                                                                                                                 | If missing                                                                    |
| - | ------------------------ | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| 1 | Workshop Name            | ðŸ“„ Direct  | As in the report.                                                                                                                                                                                                   | Left empty                                                                    |
| 2 | Workshop Estimate Amount | ðŸ”§ Cleaned | Only digits and the decimal point are kept ("â‚¹52,345.00" â†’ 52345.00). From a PDF, App3 can also take the estimate column of the Summary of Assessment when Parts + Labour + Towing add up to Net Payable. | Left empty. Blocks start if it is not between â‚¹1,000 and â‚¹10 crore. |
| 3 | Workshop Estimate Date   | ðŸ”§ Cleaned | Changed to DD-MM-YYYY.                                                                                                                                                                                              | Left empty                                                                    |
| 4 | GST Number               | ðŸ“„ Direct  | Filled only if OIC allows editing. From a PDF it must be a valid 15-character GSTIN.                                                                                                                                | Left empty                                                                    |

---

## 7. Step 3: Interim Report

### 7.1 Survey Details (6 fields)

| # | Portal field                         | Method               | How the value is decided                                                                                              | If missing     |
| - | ------------------------------------ | -------------------- | --------------------------------------------------------------------------------------------------------------------- | -------------- |
| 1 | Whether Vehicle Inspected Personally | âš™ï¸ Setting | Default **YES**.                                                                                                | Not applicable |
| 2 | Is Survey Completed                  | âš™ï¸ Setting | Default **YES**.                                                                                                | Not applicable |
| 3 | Type of Settlement                   | â­ï¸ Skipped | OIC locks it.                                                                                                         | Not applicable |
| 4 | Date of Survey                       | ðŸ”§ Cleaned     | From "Date and Time of Survey", changed to DD-MM-YYYY.                                                                | Blocks start   |
| 5 | Place of Survey                      | ðŸ“„ Direct      | As in the report. In a PDF where the Workshop Name sits under a "Place of Survey" heading, the workshop name is used. | Blocks start   |
| 6 | Surveyor Appointed Date              | ðŸ”§ Cleaned     | The **Date of Allotment of Survey**, changed to DD-MM-YYYY.                                                     | Pauses         |

### 7.2 Documentation Verification (5 fields)

| #  | Portal field                                 | Method               | How the value is decided                                                                                | If missing     |
| -- | -------------------------------------------- | -------------------- | ------------------------------------------------------------------------------------------------------- | -------------- |
| 7  | Is Driving Licence Applicable                | âš™ï¸ Setting | Default **YES**.                                                                                  | Not applicable |
| 8  | Are DL, RC Book and Other Documents Verified | âš™ï¸ Setting | Default **YES**.                                                                                  | Not applicable |
| 9  | Remarks (documents)                          | âš™ï¸ Setting | Default "okay".                                                                                         | Not applicable |
| 10 | Is Spot Survey Done                          | ðŸ§® Calculated  | **YES** if the claim folder has a file whose name contains "spot survey". Otherwise **NO**. | NO             |
| 11 | Remarks (spot survey)                        | âš™ï¸ Setting | Default "okay". Filled only when OIC shows the box.                                                     | Not applicable |

### 7.3 Claim Assessment and Contact (7 fields)

| #  | Portal field                      | Method               | How the value is decided or changed                                                                                                                                                                                       | If missing                         |
| -- | --------------------------------- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| 12 | Initial Loss Assessment Amount    | ðŸ§® Calculated  | **Excel:** 75% of the report's "initial loss assessment" amount, rounded to whole rupees. **PDF:** the amount printed in the PDF. If the PDF has none, 75% of the Workshop Estimate. Entered in whole rupees. | Blocks start                       |
| 13 | Mobile Number of the Claimant     | ðŸ”§ Cleaned     | Reduced to a 10-digit Indian mobile starting with 5 to 9.                                                                                                                                                                 | Left empty (warning)               |
| 14 | Email ID of the Claimant          | ðŸ“„ Direct      | **Excel:** App3 first looks for any email ending in ".com" in the sheet (cell I4 first), then the email label. **PDF:** the email in the Insured section.                                                     | Left empty (warning)               |
| 15 | Submission Date of Final Document | ðŸ”§ Cleaned     | From a "Submission Date" type label. In a PDF it can also be the "Date:" on the report heading line. If none is found, the Date of Survey is used. Changed to DD-MM-YYYY.                                                 | Date of Survey. PDF: Blocks start. |
| 16 | Surveyor's Observation            | âš™ï¸ Setting | Default "okay". Filled only if OIC allows editing.                                                                                                                                                                        | Not applicable                     |
| 17 | Cause and Nature of Accident      | ðŸ“„ Direct      | As in the report. From a PDF, the full paragraph under the "Cause and Nature of Accident" heading.                                                                                                                        | Pauses (warning before start)      |
| 18 | Particulars of Loss / Damage      | âš™ï¸ Setting | Default "As per estimate".                                                                                                                                                                                                | Not applicable                     |

**Examples**

- Excel initial loss 40,000 â†’ **30000**.
- PDF with no initial loss and estimate 52,345 â†’ 75% = 39,258.75 â†’ **39259**.

---

## 8. Step 4: Assessment of Loss

### 8.1 Invoice and items (uploaded as one workbook)

App3 does not type invoice items one by one. When you scan the claim folder, App3 builds an upload workbook (auto_oic_upload_current.xlsx) with an **Invoice** sheet and an **Items** sheet. During the run it uploads this file to OIC's import, waits for OIC to accept it (up to 75 seconds), clicks Submit, then checks that the invoice appears **once** with **every item** listed.

- If OIC already shows this invoice with all items, App3 does not upload again.
- If OIC shows validation errors, App3 pauses so you can review them.
- If the workbook changed after the folder scan, App3 stops and asks you to rescan.

#### Invoice sheet (one row)

| Column             | Method               | How the value is decided                                                                                                                    |
| ------------------ | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Invoice Number     | ðŸ“„ Direct      | Workshop invoice number. If empty, the general invoice number.                                                                              |
| Invoice Date       | ðŸ”§ Cleaned     | Workshop invoice date, changed to DD-MM-YYYY.                                                                                               |
| Invoice GST Type   | âš™ï¸ Setting | Default **IGST** (other allowed value: CGST/SGST).                                                                                    |
| Invoice Amount     | ðŸ§® Calculated  | **Total of all item amounts** in the Items sheet (before depreciation). OIC compares this with the items, so App3 uses the same rows. |
| Invoice GST Amount | ðŸ§® Calculated  | From the GST summary: Spares CGST + Spares SGST + Labour CGST + Labour SGST. If all of these are zero, Spares IGST + Labour IGST is used.   |

**Where the GST summary comes from**

- **Excel:** the blocks titled "GST SUMMARY â€“ SPARES" and "GST SUMMARY â€“ LABOUR". Values are read 4 rows below the title: taxable amount 1 column right, CGST 3 columns right, SGST 4 columns right, IGST 5 columns right.
- **PDF:** the GST summary tables in the assessment pages.

#### Items sheet (one row per item)

| Column                   | Value                                                                   |
| ------------------------ | ----------------------------------------------------------------------- |
| Invoice Number           | Same as the Invoice sheet                                               |
| Item Description         | Category: Metallic Parts, Plastic, Glass or Labour Charge (rules below) |
| Item Sub Type            | Part name, or the labour name (R/R, DENTING, C/W, PAINT)                |
| Side Description         | ðŸ”’ Always "Front"                                                 |
| Item Amount              | Amount from the report                                                  |
| Depreciation Rate        | Rules below                                                             |
| GST Rate                 | ðŸ”’ Always 18                                                      |
| Estimated Amount         | Estimate column from the report (for labour, same as the amount)        |
| Estimated Amount Remarks | Left blank                                                              |
| HSN Code                 | âš™ï¸ Parts 8512, labour 8729                                    |
| GST Amount               | ðŸ§® (Item Amount âˆ’ depreciation) Ã— 18%                     |

Example: part of â‚¹10,000 at 30% depreciation â†’ (10,000 âˆ’ 3,000) Ã— 18% = **â‚¹1,260**.

#### Spare parts rules

App3 reads the parts table (the "Survey Report" sheet if there is one) with columns S.N., Part Description, Estimated, Metal, Plastic and Glass. It stops at "sub total", "total" or "grand total". The column that holds the amount decides the category:

| Amount is in | Category       | Depreciation (normal)                   | Depreciation (Nil Dep = Yes) |
| ------------ | -------------- | --------------------------------------- | ---------------------------- |
| Metal        | Metallic Parts | Metal depreciation rate from the report | 0%                           |
| Plastic      | Plastic        | 50%                                     | 0%                           |
| Glass        | Glass          | 0%                                      | 0%                           |

- A row with no amount in any material column is skipped.
- A row with amounts in **two or more** material columns stops the run for review.
- A negative or unreadable amount stops the run for review.

#### Labour rules

App3 adds up each labour column of the labour table:

| Labour column total                                                   | Item                                                                                                                                                   | Depreciation                            |
| --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------- |
| R/R                                                                   | Labour Charge "R/R"                                                                                                                                    | 0%                                      |
| Denting                                                               | Labour Charge "DENTING"                                                                                                                                | 0%                                      |
| C/W                                                                   | Labour Charge "C/W"                                                                                                                                    | 0%                                      |
| Painting (normal)                                                     | Labour Charge "PAINT"                                                                                                                                  | Paint depreciation rate from the report |
| Painting when paint depreciation is **12.5%** or Nil Dep is Yes | Split in two: **25%** as Plastic "Painting material" (50% depreciation, 0% if Nil Dep) and **75%** as Labour Charge "Painting labour" (0%) | as stated                               |

Labour items with a zero total are left out.

Example: painting total â‚¹4,000 at 12.5% â†’ "Painting material" â‚¹1,000 (Plastic, 50%) + "Painting labour" â‚¹3,000.

#### Depreciation rates

| Rate  | Excel                                                         | PDF                                |
| ----- | ------------------------------------------------------------- | ---------------------------------- |
| Metal | Cell 3 columns right of "SO, DEP. ON METAL"                   | A line such as "Dep. on metal 30%" |
| Paint | Cell 1 column **left** of "LESS COST OF PAINT MATERIAL" | A line such as "Paint dep 12.5%"   |

Allowed rates: 0, 5, 10, 15, 20, 25, 30, 35, 40, 50. Paint can also be 12.5 (split as above). Any other rate blocks the start. With Nil Dep = Yes, rates are not needed.

#### Safety checks on the workbook

- If the invoice amount is lower than the total of item amounts, App3 warns you before starting.
- **PDF only:** the items after depreciation must equal the GST summary's taxable amounts (within 2 paise), separately for spares and labour. Otherwise the start is blocked.
- If no non-zero part or labour amount is found, the start is blocked.

### 8.2 Excess (3 fields)

| Portal field      | Method           | How the value is decided                                                        | If missing |
| ----------------- | ---------------- | ------------------------------------------------------------------------------- | ---------- |
| Compulsory Excess | ðŸ”§ Cleaned | **Always added.** Amount from the report in whole rupees (paise dropped). | 0          |
| Imposed Excess    | ðŸ”§ Cleaned | Added only if more than 0.                                                      | Not added  |
| Voluntary Excess  | ðŸ”§ Cleaned | Added only if more than 0. OIC calls it "Voluntarily Excess".                   | Not added  |

### 8.3 Salvage (1 field)

| Portal field   | Method          | How the value is decided        | If missing |
| -------------- | --------------- | ------------------------------- | ---------- |
| Salvage Amount | ðŸ“„ Direct | Salvage amount from the report. | 0          |

### 8.4 Survey Charges (4 fields + 5 expense types)

| Portal field               | Method               | How the value is decided                                                          | If missing     |
| -------------------------- | -------------------- | --------------------------------------------------------------------------------- | -------------- |
| Is Surveyor GST Applicable | âš™ï¸ Setting | Default **No**.                                                             | Not applicable |
| License Number             | ðŸ“„ Direct      | Surveyor licence number. From a PDF, any "Expiry" text joined to it is removed.   | Blocks start   |
| License Expiry Date        | ðŸ”§ Cleaned     | Changed to DD-MM-YYYY. In a PDF it can be on the same line as the licence number. | Blocks start   |
| OICL GST Number            | ðŸ“„ Direct      | Optional. From a PDF it must be a valid 15-character GSTIN.                       | Left empty     |

**Expenses.** Each type is added only when its amount is more than 0. The description for every row is the setting value (default "conveyance").

| Expense type on OIC | Where the amount comes from                            | Amount format |
| ------------------- | ------------------------------------------------------ | ------------- |
| Traveling Expenses  | Traveling expenses or conveyance                       | Whole rupees  |
| Professional Fee    | Professional fee or survey fee                         | Whole rupees  |
| Daily Allowance     | Daily allowance                                        | Whole rupees  |
| Photo Charge        | Photo charges or photographs                           | Whole rupees  |
| Others              | ðŸ§® **Re-inspection Charges + Misc Charge** | Paise kept    |

Example: Re-inspection â‚¹500 + Misc â‚¹150.50 â†’ Others **â‚¹650.50**.

After adding them, App3 reads every expense row back to confirm the amount and description.

### 8.5 Final Recommendation and Declaration (2 fields)

| Portal field         | Method               | How the value is decided                                                  |
| -------------------- | -------------------- | ------------------------------------------------------------------------- |
| Final Recommendation | âš™ï¸ Setting | Default "agree". Filled **only if at least one expense was added**. |
| Surveyor Declaration | âš™ï¸ Setting | Ticked (setting "Yes"). App3 checks that it stays ticked.                 |

Then App3 clicks **Save and Next**.

---

## 9. Step 5: Document Upload

| Slot | Portal section                     | Required | Which file App3 uses                                                                                                              | Changes made                                                                                   |
| ---- | ---------------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| 1    | Workshop Repair Estimate           | Yes      | Estimate file (2.2)                                                                                                               | Compressed if over 5 MB                                                                        |
| 2    | Discharge cum Satisfaction Voucher | Yes      | Discharge or voucher file                                                                                                         | Compressed if over 5 MB                                                                        |
| 3    | Invoice                            | Yes      | Invoice file                                                                                                                      | Compressed if over 5 MB                                                                        |
| 4    | Re-Inspection Report               | No       | Re-inspection file                                                                                                                | Compressed if over 5 MB                                                                        |
| 5a   | Driving Licence, front side        | No       | Driving licence file                                                                                                              | Compressed if over 10 MB                                                                       |
| 5b   | Driving Licence, back side         | No       | **The vehicle RC** file goes in this second slot                                                                            | Compressed if over 10 MB                                                                       |
| 5c   | Licence number box                 |          | â­ï¸ Skipped. OIC fills and locks it.                                                                                     |                                                                                                |
| 6    | Photographs                        | Yes      | **One** photo: files with "photo" or "vehicle" in the name (not RC or licence). Originals are preferred over App3's copies. | PDFs and other image types are turned into a JPG or PNG. Other photos go into Other Documents. |
| 7    | Other Documents                    | No       | **All remaining files** merged into one PDF (prepared at folder scan). App3's own generated files are left out.             | Merged file up to 15 MB                                                                        |
|      | Remarks                            |          | âš™ï¸ Default "Documents verified and uploaded."                                                                           | At least 10 characters, otherwise the default is used                                          |
|      | Submit                             |          | âš™ï¸ **Not clicked by default.** App3 stops so you can review and submit.                                           | Can be turned on in settings                                                                   |

If a required slot (1, 2, 3) cannot be uploaded, App3 pauses so you can attach the file in Chrome.

---

## 10. All value changes at a glance

| Value                          | Example from the report                                            | What App3 enters                            |
| ------------------------------ | ------------------------------------------------------------------ | ------------------------------------------- |
| Any date                       | 2024-01-15 Â· 15/01/2024 Â· 15 Jan 2024 Â· Excel date number | 15-01-2024                                  |
| Year of Manufacture            | "2019 Model"                                                       | 2019                                        |
| Cubic Capacity, weights, seats | "1197 cc", "865 kg", "5 persons"                                   | 1197, 865, 5                                |
| Fuel                           | "Fuel used: Petrol"                                                | PETROL                                      |
| Variant                        | (no source)                                                        | Same as Make                                |
| Driver Name                    | "RAMESHBHAI KANTILAL PATEL" (25 letters)                           | "RAMESHBHAI KANTILAL" (first 20 characters) |
| Mobile numbers                 | "+91 98765 43210"                                                  | 9876543210                                  |
| Licence number                 | GJ01 20110012345                                                   | GJ / 012011 / 012345 (after you confirm)    |
| State                          | Licence starts with GJ                                             | GUJARAT                                     |
| City                           | Licence starts with GJ01                                           | AHMADABAD                                   |
| Age of Vehicle                 | Registered 15-01-2019, accident 20-04-2024                         | 5 years 3 months                            |
| Close Proximity                | 14 days between accident and allotment                             | YES                                         |
| Owner Driver                   | Driver "Ramesh Patel", owner "RAMESH K PATEL"                      | YES                                         |
| Initial Loss (Excel)           | 40,000                                                             | 30000 (75%)                                 |
| Initial Loss (PDF fallback)    | Estimate 52,345                                                    | 39259 (75%)                                 |
| Workshop Estimate              | "â‚¹52,345.00"                                                  | 52345.00                                    |
| Claim Type                     | "Payment to insured"                                               | REIMBURSEMENT                               |
| Excess, expenses               | "â‚¹1,250.50"                                                   | 1250                                        |
| Others expense                 | Re-inspection 500 + Misc 150.50                                    | 650.50                                      |
| Invoice Amount                 | Item amounts 10,000 + 5,000 + 2,000                                | 17000                                       |
| Painting at 12.5%              | 4,000                                                              | Material 1,000 + Labour 3,000               |

---

## 11. Checks before the run starts

**Extraction Review** shows short chips above the field table. Red chips mark critical issues and amber chips mark optional fields or other warnings. Hover over a field or workbook chip to read the full message.

### 11.1 These block the start

- Policy Number **and** Claim Number are both missing.
- Date of Survey, Place of Survey or Initial Loss Assessment Amount is missing.
- Year of Manufacture is not a valid year between 1900 and next year.
- Workshop Estimate Amount is not a number, or is outside â‚¹1,000 to â‚¹10 crore.
- No invoice file in the claim folder.
- Invoice Amount Without GST or Invoice GST Amount is missing or not a number.
- Invoice Amount Without GST is lower than the Invoice GST Amount.
- Surveyor Licence Number or Licence Expiry Date is missing.
- Nil Depreciation is not clearly Yes or No.
- Metal or paint depreciation rate is missing or not an allowed rate (when Nil Dep is No).
- The upload workbook could not be prepared, or the parts table needs review.
- **PDF only:** any of these is missing, unreadable or has conflicting values: Registration Number, Make, Chassis, Engine, Cubic Capacity, Driver Name, Driver DOB, Licence Number, Licence Issue Date, Licence Expiry Date, Driver Address, Workshop Name, Workshop Estimate Amount, Workshop Invoice Number, Workshop Invoice Date, Nil Depreciation, Invoice GST Amount, Survey Date, Place of Survey, Initial Loss, Submission Date, Surveyor Licence Number, Surveyor Licence Expiry, Claim Type / Payment To.
- **PDF only:** dates in the wrong order: DOB after licence issue, licence issue after expiry, or accident after survey.
- **PDF only:** Licence Type cannot be worked out.

### 11.2 These only warn (the run continues)

- Cause and Nature of Accident, Claimant Mobile or Claimant Email not found.
- Chassis Number, Engine Number or Cubic Capacity not found.
- Driver Name or Driver Licence Number not found.
- Workshop Name, Workshop Estimate Amount or Workshop Estimate Date not found.
- Workshop Invoice Number or Date not found.
- No claim documents found in the folder.
- Invoice amount lower than the total of item amounts.
- PDF: licence number has extra digits, or fee amounts are missing from the PDF and fee bills.

---

## 12. When a field cannot be filled

App3 does not guess silently. When a value is missing, unclear, or OIC does not keep it:

1. App3 pauses and shows a floating always-on-top card (`RecoveryDialog`) near the top-right corner of the screen (with the **field name** and **reason** in plain English) without pulling the desktop app over Chrome.
2. You correct the field in Chrome (click **Show Chrome** on the card header if Chrome is covered or minimized, or **Show Pause Card** in App3 to bring the card forward).
3. Click **Continue** (or **Skip this field** / **Stop automation**), and App3 acknowledges any benign save/info popup and carries on from where it stopped.

You can also click **Pause** in the App3 toolbar mid-run to pause between fields/steps for manual edits in Chrome, then click **Resume** on the card or in the toolbar. While OIC runs, App3 shows a compact live progress badge in Chrome (bottom-left corner with colored rings on the active field — blue while filling, brief green when verified, and red on failure until edited) and updates the App3 top status bar with the active section, field name, and running counts (`✓` filled / `⚠` failed).

By default, OIC's **Logs** tab shows a compact icon-led stream: folder readiness, step banners, per-step completion summaries (duration and filled/skipped/uploaded/issue counts), pauses/warnings, and a final headline summary. Detailed per-field lines and folder-scan logs remain hidden unless you tick **Show details** on the **Logs** tab, while full details are always written to the `.json` and readable `.txt` log files. Unexpected pauses or errors automatically save a Chrome screenshot in `logs/oic/screenshots/` and include it in the end-of-run summary. Every typed value is read back after filling. Dropdowns pick an exact match first; a partial match is used only when there is exactly one possible option. When all automated steps finish, App3 keeps Chrome open and shows a green **"All Steps Complete — Ready for Review"** floating card (`RecoveryDialog`) with **Show Chrome** and **Done (Keep Chrome Open)** so you can review and submit manually without hunting for a log message. See [chrome HUD](../app/automation/chrome_hud.py), [run diagnostics](../app/automation/run_diagnostics.py), [structured logger](../app/automation/automation_logger.py), [OIC UI helpers](../app/portals/oic/automation/ui_utils.py), [OIC recovery](../app/portals/oic/automation/recovery.py), [logs tab & Show details toggle](../app/ui/components/workspace_page.py), [pause card](../app/ui/components/recovery_dialog.py), [main window](../app/ui/main_window.py), [automation engine](../app/automation/engine.py), and [browser launch & focus](../app/portals/oic/automation/review_browser.py).

**AI debug report (optional, OFF by default).** The **Logs** tab has an **AI debug report** switch beside **Show details** and **Auto-scroll**. It starts OFF every time App3 opens (it is not saved), the same choice applies to UIIC, OIC and New India during the session, and it is locked while a run is active, so it takes effect from the next run. When it is ON, App3 does nothing extra in Chrome or on the portal: it only writes one more file, `<claim>_run_<time>_<pid>_ai_debug.md`, beside that run's `.json` / `.txt` logs in `~/Automations/logs/oic/`. The file is created as soon as the run log starts, updated during the run (straight away after each error), finished with the run summary, and its path is printed as the last summary line (`AI debug report: …`). It lists each error, warning and failed field with the code place that logged it, the line that raised the error and the call chain, the raw error text (for a failed OIC field this is the technical text behind the plain-English reason, which the normal logs do not keep), a few source lines (only when App3 runs from source; the packaged EXE shows `file:line` only), the Python traceback, a timeline of steps and problems, the environment, the run settings with username and password hidden, the claim's validation messages and mapped documents (file names only), the folder-scan trace and the last 250 lines of the readable log. Paths under the Windows user folder are shown as `~`. **Copy AI Debug** (beside **Export**) becomes clickable once the report exists and copies the whole report for pasting into an AI assistant; switching portal clears it. Claim values such as names, numbers and amounts stay in the report on purpose; credentials do not. This first version has no browser console, network or page snapshots, and it does not change pauses, retries or the pause card.

**Password and Captcha values in logs.** Whether the switch is ON or OFF, the logger writes `********` for the value of any field whose label looks like Password, Captcha, OTP or Passcode, and hides typed text that a failed fill echoes back. OIC's login fills **Password** and **Captcha** through the normal field helper, so their log lines now read, for example (synthetic), `— Filling Password • Source: Excel • Value: ********`. The CAPTCHA reader's own lines still show the one-time text it read, so reading mistakes can be checked. See [AI debug report](../app/automation/debug_recorder.py), [structured logger](../app/automation/automation_logger.py), [engine start of the report](../app/automation/engine.py), [worker](../app/ui/worker.py), [Logs tab switch & Copy AI Debug](../app/ui/components/workspace_page.py), [main window](../app/ui/main_window.py), and [tests](../tests/test_ai_debug_report.py).

---

## 13. Settings you can change

These are in App3 Settings â†’ Automation Defaults for OIC.

| Setting                      | Default                          | Affects                                              |
| ---------------------------- | -------------------------------- | ---------------------------------------------------- |
| Unknown claim type           | CASHLESS                         | Step 1 Claim Type when the report does not say       |
| Instant fill                 | Yes                              | Fill each field at once (No = type letter by letter) |
| Typing delay                 | 25 ms                            | Speed when typing letter by letter                   |
| Driver relation              | other                            | Step 2 Relationship with Driver                      |
| Charges filed                | (empty)                          | Step 2 Charges Filed                                 |
| Vehicle inspected personally | YES                              | Step 3                                               |
| Survey completed             | YES                              | Step 3                                               |
| Driving licence applicable   | YES                              | Step 3                                               |
| Documents verified           | YES                              | Step 3                                               |
| Documents verified remarks   | okay                             | Step 3                                               |
| Spot survey remarks          | okay                             | Step 3                                               |
| Surveyor observation         | okay                             | Step 3                                               |
| Particulars of loss / damage | As per estimate                  | Step 3                                               |
| GST type                     | IGST                             | Step 4 Invoice GST Type                              |
| Surveyor GST applicable      | No                               | Step 4 Survey Charges                                |
| Expense description          | conveyance                       | Step 4 every expense row                             |
| Final recommendation         | agree                            | Step 4                                               |
| Declaration checked          | Yes                              | Step 4                                               |
| Item HSN code                | 8512                             | Step 4 spare part items                              |
| Labour HSN code              | 8729                             | Step 4 labour items                                  |
| Table end words              | sub total, total, grand total    | Where the parts and labour tables end                |
| Upload remarks               | Documents verified and uploaded. | Step 5 Remarks                                       |
| Auto submit documents        | No                               | Step 5 Submit                                        |
| Upload size limit            | 5 MB                             | Step 5 compression                                   |
| CAPTCHA attempts             | 5                                | Login                                                |
| Manual login wait            | 45 seconds                       | Login                                                |

Three settings (Item side description, Item IGST rate, Labour estimated amount) are **not used** by the current invoice upload. It always uses "Front" and 18%, and labour estimated amount equals the labour amount.

---

## 14. Points worth checking

These are not errors in App3's working. They are rules that may differ from what you expect, so they are worth confirming with how you work.

| # | Point                          | What App3 does today                                                                                                                      |
| - | ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| 1 | Claimant email from Excel      | Takes the first email ending in ".com" in the sheet, starting with cell I4. On many layouts I4 holds the surveyor's own letterhead email. |
| 2 | Pincode for Excel claims       | Uses the first pincode OIC offers for the city, not the driver's own pincode, even though the Excel pincode is read.                      |
| 3 | Close Proximity                | YES only when accident and allotment are more than 10 days apart.                                                                         |
| 4 | Licence numbers with 13 digits | One middle digit is left out after you confirm.                                                                                           |
| 5 | Surveyor's Observation         | Always the setting value. Nothing is read from the report for OIC.                                                                        |
| 6 | Driver Name                    | Cut to 20 characters.                                                                                                                     |
| 7 | Excess and expense amounts     | Paise are dropped (â‚¹1,250.50 â†’ 1250), except the Others expense.                                                                |
| 8 | Final Recommendation           | Left blank when no expense is added.                                                                                                      |

---

## Appendix A: Excel labels App3 looks for

Labels are tried left to right. The value is the first real entry to the right of the label, unless a fixed position is stated.

| Field                        | Labels                                                                                                                                                              |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Claim Number                 | Claim no Â· Claim Number Â· claim_number Â· claim_no                                                                                                          |
| Policy Number                | Cover Note/Policy No. Â· Policy Number Â· Policy No. Â· Policy No                                                                                             |
| Registration Number          | Registration No. Â· Registration No Â· Vehicle Registration Number Â· Regn No Â· Vehicle No                                                                 |
| Registration Date            | Date of Registration Â· Regn Date Â· Registration Date                                                                                                          |
| Make                         | Make & Year of Manufacturer Â· Make of Vehicle Â· Vehicle Make Â· Make                                                                                        |
| Chassis Number               | Chassis No Â· Chassis Number Â· Ch No                                                                                                                           |
| Engine Number                | Engine No Â· Engine Number Â· Eng No                                                                                                                            |
| Cubic Capacity               | Cubic capacity Â· CC                                                                                                                                              |
| Year of Manufacture          | Year of Manufacture Â· Mfg Year Â· Year of Mfg Â· Year                                                                                                        |
| Type of Body                 | Type of Body Â· Body Type                                                                                                                                         |
| Class of Vehicle             | Class of Vehicle Â· Vehicle Class                                                                                                                                 |
| Type of Fuel                 | Fuel used Â· Type of Fuel Â· Fuel Type Â· Fuel                                                                                                                |
| Color                        | Color of Vehicle Â· Color Â· Colour                                                                                                                             |
| Registered Owner Name        | Name of Regd. Owner Â· Registered Owner Name Â· Owner Name Â· Name of Owner Â· Insured Name                                                                 |
| RTO                          | RTO Name Â· RTO Office Â· Registering Authority Â· Registration Authority Â· Registration Office Â· RTO                                                   |
| Registered Laden Weight      | Registered Laden Weight Â· Laden Weight                                                                                                                           |
| Unladen Weight               | Unladen Weight Â· ULW Â· Unladen Wt                                                                                                                             |
| Road Tax Paid Upto           | Road Tax Paid Upto Â· Road Tax Â· Tax Valid Upto Â· Road Tax Validity                                                                                         |
| Seating Capacity             | Seating Capacity Â· Seating/Load Carrying Capacity Â· Seats Â· Seating                                                                                        |
| Fitness Valid Upto           | Fitness Valid Upto Â· Fitness Upto Â· Fitness Validity Â· Fitness Certificate Â· Fitness Cert. Valid Upto Â· Fitness Valid Up To Â· Fitness Expiry Date |
| Permit Number                | Permit Number Â· Permit No Â· Permit No.                                                                                                                        |
| Type of Permit               | Type of Permit Â· Permit Type                                                                                                                                     |
| Permit Valid Upto            | Permit Valid Upto Â· Permit Validity Â· Permit Expiry                                                                                                           |
| Authorization Number         | Authorization Number Â· Auth Number Â· Auth No Â· Authorization No                                                                                            |
| Validity of Authorization    | Validity of Authorization Â· Auth Validity Â· Authorization Validity                                                                                            |
| Road / Area of Operation     | Road/Area of Operation Â· Area of Operation Â· Route Â· Road Area                                                                                             |
| Date of Accident             | Date of Accident Â· Accident Date                                                                                                                                 |
| Date of Allotment            | Date of Allotment of Survey Â· Date of Allotment Â· Allotment Date                                                                                              |
| Age of Vehicle               | LIFE OF VEHICLE Â· Age of Vehicle Â· Vehicle Age                                                                                                                |
| Nil Depreciation             | Nil Depreciation Â· Less Depreciation Â· NIL DEP                                                                                                                |
| Driver Name                  | Name of Driver Â· Driver Name Â· Name of the Driver                                                                                                             |
| Driver DOB                   | DOB: Â· DOB of Driver Â· Driver DOB Â· Date of Birth of Driver                                                                                                |
| Licence Type                 | Type of Licence Â· License Type of Driver Â· License Type Â· Type of License Â· DL Type                                                                     |
| Licence Number               | LICENCE NO. Â· License No Â· Driving License Number Â· DL Number Â· DL No                                                                                   |
| Licence Issue Date           | Date of issue Â· DL Issue Date Â· License Issue Date                                                                                                            |
| Licence Expiry Date          | Valid Till Â· DL Expiry Date Â· License Expiry Date Â· License Valid Till                                                                                     |
| Badge Number                 | Badge Number Â· Badge No                                                                                                                                          |
| Badge Issue Date             | Badge Issue Date Â· Badge Date Â· Date of Badge Issue                                                                                                           |
| Driver Address               | Address                                                                                                                                                             |
| Driver City / State          | City/State Â· City / State                                                                                                                                        |
| Driver Pincode               | Pin Code Â· Pincode Â· Pin Â· Zip Code Â· Zip                                                                                                               |
| Qualification                | Qualification Â· Driver Qualification Â· Educational Qualification                                                                                              |
| Licence Issuing Authority    | Issuing Authority Â· License Issuing Authority Â· DL Issuing Authority                                                                                          |
| Workshop Name                | Workshop Â· Name of Workshop Â· Workshop Name                                                                                                                   |
| Workshop Estimate Amount     | TOTAL NET FOR PARTS Â· NET PAYABLE Â· Total Net Parts                                                                                                           |
| Workshop Estimate Date       | Estimate Date Â· Workshop Estimate Date Â· Date of Estimate Â· Estimation Date Â· Workshop Date Â· Estimate Dt                                            |
| Workshop GST Number          | GST Number Â· GST No. Â· GSTIN Â· GST                                                                                                                         |
| Date of Survey               | Date and Time of Survey Â· date of survey Â· Survey Date                                                                                                        |
| Place of Survey              | Place of survey                                                                                                                                                     |
| Claimant Mobile              | Mobile: Â· mobile no Â· mobile                                                                                                                                  |
| Claimant Email               | (any .com email, cell I4 first) Â· e-mail:- Â· email id Â· email                                                                                              |
| Initial Loss                 | initial loss assessment Â· intial losss Â· intial loss                                                                                                          |
| Cause and Nature of Accident | CAUSE AND NATURE OF ACCIDENT Â· Nature of Accident Â· Cause of Accident                                                                                         |
| Workshop Invoice No          | invoice_no Â· Invoice No Â· Tax Invoice No.                                                                                                                     |
| Workshop Invoice Date        | invoice_date Â· Invoice Date Â· Invoice Date and Time                                                                                                           |
| Surveyor Name                | Name of the Surveyor Â· Surveyor Name Â· Name of Surveyor Â· Surveyor                                                                                         |
| Surveyor Email               | Surveyor Email Â· Email ID Â· e-mail:- Â· email id Â· email                                                                                                 |
| Surveyor Mobile              | Surveyor Mobile Number Â· Mobile Number Â· mobile no Â· mobile                                                                                                |
| Surveyor Address             | Surveyor Address Â· Address                                                                                                                                       |
| Surveyor PAN                 | PAN Number Â· PAN No. Â· PAN                                                                                                                                    |
| Submission Date              | Submission Date Â· Final Document Date Â· Expected Completion Date Â· Completion Date Â· Date of Final Submission Â· Date:                                |
| Spares GST summary           | GST SUMMARY â€“ SPARES (4 rows below: taxable +1 col, CGST +3, SGST +4, IGST +5)                                                                                 |
| Labour GST summary           | GST SUMMARY â€“ LABOUR (same positions)                                                                                                                          |
| Metal depreciation           | SO, DEP. ON METAL Â· DEP. ON METAL (3 columns right)                                                                                                              |
| Paint depreciation           | LESS COST OF PAINT MATERIAL Â· PAINT DEP. (1 column left)                                                                                                         |
| Invoice Amount Without GST   | Invoice Amount Without GST Â· Invoice Amount Excl GST Â· Net Invoice Amt (normally calculated from the GST summary)                                             |
| Invoice GST Amount           | Invoice GST Amount Â· Invoice GST Â· GST Amount (normally calculated from the GST summary)                                                                      |
| Voluntary Excess             | Voluntary Excess Â· voluntry excess                                                                                                                               |
| Imposed Excess               | Imposed Excess                                                                                                                                                      |
| Compulsory Excess            | Compulsory Excess Â· Less Compulsory Excess Â· Compulsory Excess Amount Â· Comp Excess                                                                        |
| Salvage Amount               | Salvage Amount Â· LESS SALVAGE VALUE Â· Less Salvage Value                                                                                                      |
| Surveyor Licence Number      | License Number Â· Surveyor License Number Â· Lic No Â· License No                                                                                             |
| Surveyor Licence Expiry      | License Expiry Date Â· Expiry Date Â· Lic Expiry Date                                                                                                           |
| OICL GST Number              | OICL GST Number Â· OICL GST No Â· GST No of OICL                                                                                                                |
| Traveling Expenses           | conveyance Â· CONVEYANCE CHARGE Â· CONVEYANCE CHARGES Â· traveling expenses                                                                                   |
| Professional Fee             | professional fee Â· SURVEY FEE Â· SURVEY FEES                                                                                                                   |
| Daily Allowance              | daily allowance Â· DAILY allowances                                                                                                                               |
| Photo Charges                | photocharges Â· PHOTOGRAPHS Â· PHOTO charge Â· photo charges                                                                                                  |
| Re-inspection Charges        | Re Inspection Charges Â· Re-inspection Charges Â· Reinspection Charges (amount in the same cell)                                                                |
| Misc Charge                  | Misc Charge Â· Misc Charges Â· Miscellaneous Charges (amount in the same cell)                                                                                  |

---

## Appendix B: Survey PDF labels App3 looks for

Each label is only accepted inside the section shown.

| Section    | Field                                   | Labels                                                                                                                       |
| ---------- | --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Header     | Claim Number                            | Claim No Â· Claim Number Â· Claim Reference Â· Claim #                                                                 |
| Header     | Policy Number                           | Cover Note/Policy No Â· Policy No Â· Policy Number                                                                       |
| Header     | Surveyor Name                           | Surveyor Name Â· Name of Surveyor (or the line above "Surveyor & Loss Assessor")                                           |
| Header     | Surveyor Licence Number                 | Surveyor Licence No Â· Licence No Â· License No                                                                          |
| Header     | Surveyor Licence Expiry                 | License Expiry Date Â· Expiry Date Â· Expiry Â· Expirey                                                                |
| Header     | Surveyor Email / Mobile / Address / PAN | Surveyor Email Â· Email Â· Surveyor Mobile Â· Mobile No Â· Surveyor Address Â· Surveyor PAN Â· PAN No            |
| Header     | Submission Date                         | Submission Date Â· Final Report Date Â· Date of Final Submission Â· Date (or "Date:" on the report heading)            |
| Insured    | Claimant Mobile                         | Contact No Â· Contact Number Â· Claimant Mobile Â· Mobile Number Â· Mobile                                           |
| Insured    | Claimant Email                          | Claimant Email Â· Email ID Â· Email Â· E-mail                                                                          |
| Vehicle    | Registration Number                     | Registration No / RTO Â· Registration No Â· Vehicle Registration Number Â· Regn No Â· Vehicle No                     |
| Vehicle    | RTO                                     | RTO Office Â· RTO Name Â· Registration Authority (or text after the number in "Registration No / RTO")                   |
| Vehicle    | Make                                    | Make & Model Â· Make and Model Â· Make / Model Â· Make                                                                 |
| Vehicle    | Registration Date                       | Date of Registration Issue Â· Date of Registration Â· Registration Date                                                  |
| Vehicle    | Chassis / Engine / CC                   | Chassis No Â· Engine No Â· Cubic Capacity Â· Engine Capacity Â· CC                                                   |
| Vehicle    | Year of Manufacture                     | Year of Manufacture Â· Manufacturing Year Â· Mfg Year                                                                    |
| Vehicle    | Body / Class / Fuel / Colour            | Type of Body Â· Class of Vehicle Â· Fuel Used Â· Fuel Type Â· Color Â· Colour                                      |
| Vehicle    | Registered Owner                        | Name of Regd Owner as per RC Â· Name of Registered Owner Â· Registered Owner Name                                        |
| Vehicle    | Weights / Seats                         | Laden weight GVW Â· GVW Â· Unladen Weight ULW Â· ULW Â· Seating Capacity                                             |
| Vehicle    | Road Tax / Fitness                      | Road Tax Paid Upto Â· Tax Valid Upto Â· Fitness Cert Valid upto Â· Fitness Valid Upto                                  |
| Vehicle    | Permit                                  | Route Permit No Â· Permit Number Â· Type of Permit Â· Route Permit Validity Â· Permit Validity                       |
| Vehicle    | Authorization / Area                    | Authorization No Â· Authorization Validity Â· Route/Area of Operation                                                    |
| Driver     | Driver Name                             | Name of Driver Â· Driver Name Â· Name of the Driver                                                                      |
| Driver     | DOB                                     | DOB Â· Driver DOB Â· Date of Birth                                                                                       |
| Driver     | Licence Number                          | DL No Â· Driving Licence Number Â· Licence No Â· License No                                                            |
| Driver     | Licence Issue / Expiry                  | Date of Issue Â· DL Issue Date Â· Valid Till Â· Valid Up To Â· DL Expiry Date                                        |
| Driver     | Licence Type                            | Type of Licence Â· Type of License Â· License Type                                                                       |
| Driver     | Address / City / Pincode                | Address of Driver Â· Driver Address Â· Address Â· City/State Â· Pincode Â· Pin Code                                |
| Driver     | Badge / Qualification / Authority       | Badge No Â· Badge Issue Date Â· Qualification Â· Issuing Authority                                                     |
| Accident   | Date of Accident                        | Date & Time of Accident Â· Accident Date Â· Date of Accident                                                             |
| Survey     | Date of Allotment                       | Date of Allotment of Survey Â· Date of Allotment Â· Survey Appointment Date                                              |
| Survey     | Date of Survey                          | Date and Time of Survey Â· Date & Time of Survey Â· Date of Survey Â· Survey Date                                      |
| Survey     | Place of Survey                         | Place of Survey Â· Survey Location Â· Inspection Place                                                                   |
| Survey     | Initial Loss                            | Initial Loss Assessment Amount Â· Initial Loss Assessment Â· Initial Loss                                                |
| Workshop   | Workshop Name                           | Workshop Name Â· Name of Workshop Â· Repairer Name Â· Workshop                                                         |
| Workshop   | Estimate Amount                         | Workshop Estimate Amount Â· Repair Estimate Amount Â· Estimated Repair Cost Â· Estimate Amount                         |
| Workshop   | Estimate Date                           | Workshop Estimate Date Â· Estimate Date Â· Date of Estimate                                                              |
| Workshop   | GST Number                              | Workshop GSTIN Â· Workshop GST Number Â· GST Number Â· GSTIN                                                           |
| Cause      | Cause and Nature of Accident            | Full paragraph under the heading                                                                                             |
| Assessment | Workshop Invoice No / Date              | Workshop Invoice No Â· Workshop Invoice Number Â· Repairer Invoice No Â· Workshop Invoice Date                         |
| Assessment | Nil Depreciation                        | Nil Depreciation Cover Â· Nil Depreciation Â· Zero Depreciation Â· Nil Dep                                             |
| Assessment | Age of Vehicle                          | Life of Vehicle (in years) Â· Life of Vehicle Â· Age of Vehicle                                                          |
| Assessment | Excess                                  | Compulsory Excess Â· SO, Excess Clause (in Rs.) Â· Voluntary Excess Â· Imposed Excess                                  |
| Assessment | Salvage                                 | Salvage Amount Â· Less Salvage Value Â· Salvage Value                                                                    |
| Fees       | Professional Fee                        | Professional Fee Â· Survey Fee                                                                                             |
| Fees       | Traveling Expenses                      | Travelling Expenses Â· Traveling Expenses Â· Conveyance Charges Â· Conveyance                                          |
| Fees       | Daily Allowance / Photo                 | Daily Allowance Â· Photo Charges Â· Photograph Charges Â· Photographs                                                  |
| Fees       | Re-inspection / Misc                    | Re Inspection Charges Â· Misc Charge Â· Miscellaneous Charges                                                            |
| Fees       | OICL GST Number                         | OICL GST Number Â· OICL GST No Â· GST No of OICL                                                                         |
| Anywhere   | Claim Type / Payment To                 | The payment to be made in favour of Â· Payment To Â· Payable To Â· Claim Type Â· Payment Option Â· Settlement Type |

---

## Appendix C: Licence code to State

| Code   | State                                    | Code   | State          |
| ------ | ---------------------------------------- | ------ | -------------- |
| AN     | ANDAMAN & NICOBAR ISLANDS                | ML     | MEGHALAYA      |
| AP     | ANDHRA PRADESH                           | MN     | MANIPUR        |
| AR     | ARUNACHAL PRADESH                        | MP     | MADHYA PRADESH |
| AS     | ASSAM                                    | MZ     | MIZORAM        |
| BR     | BIHAR                                    | NL     | NAGALAND       |
| CG     | CHATTISGARH                              | OD, OR | ODISHA         |
| CH     | CHANDIGARH                               | PB     | PUNJAB         |
| DD, DN | DAMAN AND DIU AND DADRA AND NAGAR HAVELI | PY     | PONDICHERRY    |
| DL     | DELHI                                    | RJ     | RAJASTHAN      |
| GA     | GOA                                      | SK     | SIKKIM         |
| GJ     | GUJARAT                                  | TG, TS | TELANGANA      |
| HP     | HIMACHAL PRADESH                         | TN     | TAMIL NADU     |
| HR     | HARYANA                                  | TR     | TRIPURA        |
| JH     | JHARKHAND                                | UA, UK | UTTARAKHAND    |
| JK     | JAMMU AND KASHMIR                        | UP     | UTTAR PRADESH  |
| KA     | KARNATAKA                                | WB     | WEST BENGAL    |
| KL     | KERALA                                   | LA     | LADAKH         |
| LD     | LAKSHADWEEP                              | MH     | MAHARASHTRA    |

City (district) uses the first 4 characters of the licence, for example GJ01 â†’ AHMADABAD, MH12 â†’ PUNE, AP02 â†’ ANANTAPUR. App3 knows 772 such codes.

---

*End of guide.*
