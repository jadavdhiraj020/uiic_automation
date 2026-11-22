# New India Assurance (NIA) Surveyor Portal — Complete End-to-End DOM & Behavior Reference

> **Purpose:** Authoritative technical reference of the **New India Assurance Bancs Surveyor Portal** (`https://web.newindia.co.in/NIABancsPortal/Surveyor.html`) for AI coding agents maintaining or extending `app/portals/newindia/automation/`.
> **Sources Verified:** Live rendered AngularJS DOM capture (`#/WorklistSurvey`, Claim `98000031260391244679`), `Surveyor.html`, `js/app.js`, `js/surveyor/surveyorHome.js`, and all 90+ static `InnerHTML/*.html` templates fetched read-only on `2026-11-21`.

---

## 1. Architecture, Tech Stack & Entry URLs

| Property | Value / Detail |
| :--- | :--- |
| **Login URL** | `https://web.newindia.co.in/NIABancsPortal/IntermediaryLogin.html` (renders `InnerHTML/loginNC.html`; legacy `InnerHTML/Login.html`) |
| **Surveyor SPA Shell** | `https://web.newindia.co.in/NIABancsPortal/Surveyor.html` (`#/home`, `#/Worklist`, `#/ClaimSearch`, `#/SurveyorFee`, `#/WorklistSurvey`, `#/WorklistSurveyNew`, OEM routes) |
| **Frontend Framework** | AngularJS `1.4.3`, `angular-ui-router`, `ui-bootstrap-tpls-0.12.0` (`tabset`/`tab`, `accordion-group`, `datepicker-popup`, `typeahead`, `$modal`) |
| **UI & Utilities** | Bootstrap 3 (`col-md-*`), jQuery, jQuery UI, `angular-datatables` + `jquery.dataTables.min.js`, FontAwesome, `moment.min.js` |
| **File & Excel Libraries** | `angular-base64-upload` (`base-sixty-four-input` + `FileReader.js`), `xlsx.core.min.js` (`XLSX`), `xls.core.min.js` (`XLS`), `pdfmake.min.js` |
| **Controllers / Globals** | Main claim controller: `surveyorWorklistSurveyCtrl` (`$scope.surveyorWorklistSurvey`, `$scope.surveyorData.worklist.*`, form name `workListForm`) |

---

## 2. Routing & Claim Workspace Variants

A claim opened from **Worklist** or **Claim Search** routes to a different Angular state depending on `claimDetails.tieupFlag` and channel (`claimTypeNM` / `surveyorTabs*`):

| Route (`ui-router` State) | URL Hash | Outer Template | Tab Config Array | When Used |
| :--- | :--- | :--- | :--- | :--- |
| `home` | `#/home` | `SurveyorHome.html` *(MA)* or `SurveyorWorklist.html` *(MI/NM)* | — | Initial landing after login (`surveyorType` controls view) |
| `Worklist` | `#/Worklist` | `InnerHTML/surveyor/SurveyorWorklist.html` | — | Pending claims queue & filters |
| `ClaimSearch` | `#/ClaimSearch` | `InnerHTML/surveyor/SurveyorClaimSearch.html` | — | Search by Policy / Claim / Loss Date / Reg No |
| `SurveyorFee` | `#/SurveyorFee` | `InnerHTML/surveyor/SurveyorFee.html` | — | Settled claims surveyor fee list & export |
| **`WorklistSurveyNew`** | `#/WorklistSurveyNew` | `InnerHTML/surveyor/SurveyorWorklistSurveyNew.html` | **`surveyorTabsNew`** *(or `surveyorTabsOld`)* | **Standard Non-Tie-Up (`tieupFlag == 'NM'` / `nonMarutiClaim`)** |
| **`WorklistSurvey`** | `#/WorklistSurvey` | `InnerHTML/surveyor/SurveyorWorklistSurvey.html` | **`surveyorTabsMaruti`** *(or `surveyorTabs`)* | **Maruti / Tie-Up claims (`performActions` when `tieupFlag != 'NM'`)** |
| OEM Tie-Up States | `#/WorklistSurveyHyundai`, `#/WorklistSurveyHyundaiHIIB`, `#/WorklistSurveyTATA`, `#/WorklistSurveyKIA`, `#/WorklistSurveyHero`, `#/WorklistSurveyAshokLeyland`, `#/WorklistSurveyRoyalEnfield`, `#/WorklistSurveyMorrisGarage`, `#/WorklistSurveyMorrisGarageMGD2C`, `#/WorklistSurveyMorrisGarageLockton` | OEM `WorklistSurvey*.html` | `surveyorTabsHyundai`, `surveyorTabsTATA`, `surveyorTabsKIA`, etc. | OEM-specific dealer channels selected via `claimType` in Worklist |

### Tab Mapping: `WorklistSurveyNew` vs `WorklistSurvey`

| Tab ID | Heading | `WorklistSurveyNew` (`surveyorTabsNew`) | `WorklistSurvey` (`surveyorTabsMaruti`) | Initially Disabled? |
| :--- | :--- | :--- | :--- | :--- |
| **`#one`** | Quick Update | `tab-quickupdate-nonTieUp.html` | `tab-quickupdate.html` | `false` (always enabled) |
| **`#two`** | Additional Details | `tab-additionalDetails_nonTieUp.html` | `tab-additionalDetails_nonTieUp.html` | `true` in `New` (`false` in `Maruti`, `true` in `surveyorTabs`) |
| **`#three`** | Claim Assessment | `tab-claimAssessment-nonTieUp.html` | `tab-claimassesment.html` | `true` in `New` (`false` in `Maruti`, `true` in `surveyorTabs`) |
| **`#four`** | Document Upload | `tab-doc_up_nontieup.html` | `tab-documentupload.html` | `true` in `New` (`false` in `Maruti`, `true` in `surveyorTabs`) |
| **`#five`** | Connect with Claim Office | `tab-connectwithclaimoffice.html` | `tab-connectwithclaimoffice.html` | `false` (`surveyorTabs` omits Tab 5; `surveyorTabsOld` shifts `#two`..`#four`) |

> **Important Variant Difference:**
> - **Standard Non-Tie-Up (`WorklistSurveyNew`)** puts **Vehicle Photo Upload** on **Tab 1** (`tab-quickupdate-nonTieUp.html`), **NEFT + Work Approval + RC/Driver/FIR/Kept Open** on **Tab 2**, and **Primary/Supplementary Excel upload (`#chooseFilePrim`, `#chooseFileSup`) + Painting Charges + Delivery Order** on **Tab 3** (`tab-claimAssessment-nonTieUp.html`).
> - **Tie-Up / Maruti (`WorklistSurvey`)** omits Vehicle Photo from Tab 1 (`tab-quickupdate.html`), shares `tab-additionalDetails_nonTieUp.html` on **Tab 2** (with several sections gated by `claimTypeNM == 'nonMarutiClaim'`), and shows **TOTAL** + **PART-WISE (`#example`)** + **Add-on Cover** + **Delivery Order** on **Tab 3** (`tab-claimassesment.html`).

---

## 3. Global Shell, Navbar, Header & 5-Tab Bar Mechanics

### 3.1 Top Navigation Bar (`InnerHTML/SurveyorHeader.html`)

| Element | ID / Selector | Attribute / Action | Notes |
| :--- | :--- | :--- | :--- |
| **Dashboard** | `#navlink-dashboard > a` | `ng-click="redirectSurveyor('home')"` | Returns to Dashboard / Worklist based on role |
| **Worklist** | `#navlink-worklist > a` | `ng-click="redirectSurveyor('Worklist')"` | Navigates to `#/Worklist` |
| **Claim Search** | `#navlink-claim > a` | `ng-click="redirectSurveyor('ClaimSearch')"` | Navigates to `#/ClaimSearch` |
| **Surveyor Fee** | `#navlink-surveyor > a` | `ng-click="redirectSurveyor('SurveyorFee')"` | Navigates to `#/SurveyorFee` |
| **Pending Requests Bell** | `div.notify-flt` | `ng-click="surveyorPendingRequest.pushNotificationFn()"` | Dropdown contains inline `Accept` / `Reject` buttons (`pendingRequestsAccept`, `pendingRequestsReject`) |
| **Profile Dropdown** | `a.navbar-icon-name-container` | `Change Password`, `Profile Update`, `Activate / Block Survey`, `Role Change`, `Upload Digital Signature`, `Logout` | Each item triggers its own controller helper/modal |

### 3.2 Claim Header Action Bar & Bottom Declaration Bar (`SurveyorWorklistSurvey.html` / `SurveyorWorklistSurveyNew.html`)

| Section | Element / ID | Action / Model | Behavior |
| :--- | :--- | :--- | :--- |
| **Top Right Actions** | `button` *"View Past Claims"* | `surveyorWorklistSurvey.pastClaimDetails(claimNo)` | Opens `Surveyor_pastClaims.html` modal |
| **Top Right Actions** | `button` *"View Claim Details"* | `surveyorClaimDetails(claimNo)` *(or `_nontieup`)* | Opens `Surveyor_ClaimDetails.html` modal |
| **Top Right Actions** | `button` *"Prioritize"* | `surveyorWorklistSurvey.getPrioriy(claimNo, isPriority)` | Toggles priority star (`Y`/`N`) |
| **Bottom Checkboxes (`a)`–`l)`)** | `input[type="checkbox"]#checkbox` **(12 elements share `#checkbox`!)** | Names: `engChaVerified`, `damage`, `supEstimate`, `repaisReplace`, `reinspected`, `ncbVerified`, `dlVerified` *(disabled)*, `rcVerified` *(disabled)*, `dlVerifiedPar` *(disabled)*, `rcVerifiedPar` *(disabled)*, `permitVerifiedPar`, `fitnessCertVerifiedPar` | Items `g)`–`j)` are auto-bound & `disabled`; **always select by `name`**, never `#checkbox` |
| **Bottom Action Buttons** | `button` *"Back"* / *"View Summary"* / **`#completeSurveyMain`** | `data-ui-sref="Worklist"`, `surveyorClaimDetails*(claimNo, 'summary')`, `completeSurvey(claimNo)` | `#completeSurveyMain` is disabled when `workListForm.quickUpdateForm.$invalid` (or `surveyCompletedFlag == 1` in `New`) |

### 3.3 The 5-Tab Bar (`#one`..`#five`) & Simultaneous `.tab-pane` Mounting

```html
<tabset justified="true" vertical="true">
  <tab data-ng-repeat="tab in surveyorTabsNew" heading="{{tab.heading}}"
       data-ng-click="surveyorWorklistSurvey.clickTabs(tab.heading, tab.disabled)"
       active="tab.active" class="clearfix" id="{{tab.class}}" disabled="tab.disabled">
    <div data-ng-include="tab.template" class="clearfix"></div>
  </tab>
</tabset>
```

1. **All 5 `.tab-pane` DOM subtrees stay mounted simultaneously!** Switching tabs only toggles `.active` class on the `<li id="one".."five">` and its `.tab-pane`. Hidden tab controls STILL exist in the DOM (`offsetParent === null`).
2. **Clicking a tab directly:** `clickTabs(heading, disabled)` calls `event.stopImmediatePropagation()` when `tab.disabled === true`. Wait for `#two` / `#three` / `#four` to lose `.disabled` before clicking, or click via `li#three > a` / `#three`.
3. **Save/Next auto-advance:** Portal `Next` buttons (`saveQuickUpdate()`, `saveQuickUpdateNM()`, `toClaimAssessment()`, `docUploadCall()`) programmatically unlock target `surveyorTabs*[i].disabled = false`, call `$('#two')[0].click()` / `$('#three')[0].click()` / `$('#four')[0].click()`, call `clickTabs(...)`, and pop an alert modal (`errMsgs.claimJobSuccess`) **in parallel**.

---

## 4. Critical AngularJS 1.4.3 & DOM Behavior Rules (Must-Know for Automation)

| Rule / Trap | Observed Behavior in Portal | Required Automation Strategy |
| :--- | :--- | :--- |
| **1. Angular `$digest` Sync** | AngularJS 1.4.3 ignores raw `.value = ...` unless DOM events fire (`ng-model`, `ng-change`, `custom-field-validate`, `ng-required`). | Always dispatch `input`, `change`, and `blur` (or use Playwright `.fill()` / `.select_option()` / `type()`). For `input`/`change` inside JS, trigger `angular.element(el).triggerHandler('change')` or native events. |
| **2. Custom Radio Overlays** | Radios wrap `<input type="radio">` inside `<span class="rdb mb-none">` + sibling `<label for="...">` which visually intercepts clicks or requires exact target click. | Prefer clicking the visible `<label for="...">` or calling `.click()` on the `<input>` / `$scope` fallback; verify checked state settled. |
| **3. `<select>` `ng-options` Value Prefix** | Dynamically populated `<select>` elements generate `<option value="string:Y">Yes</option>`, `<option value="string:Petrol">Petrol</option>`, or `? string:REPLACE ?` for uninitialized bindings. Static `<select>`s use plain strings (`Insured`, `Yes`). | Match options by normalized **visible label (`text`)** first, or strip `string:`/`number:` prefix when inspecting `.value`. Do not hardcode `value="Y"` blindly across both `ng-options` and static selects. |
| **4. Duplicate DOM `id` Collisions** | Live DOM audit on `#/WorklistSurvey` + static templates confirmed **massive duplicate IDs** across tabs, repeaters, and `ng-if` branches. | **NEVER use bare `#id` without scoping to visible `.tab-pane.active` or using `name` / `data-ng-model` / `data-ng-click`!** (See Table 4.1 below.) |
| **5. Datepickers (`dd/MM/yyyy`)** | Every date input uses `uib/ui-bootstrap` `datepicker-popup="dd/MM/yyyy"` (`is-open="opened"`). Typing `dd/mm/yyyy` directly works cleanly if formatted cleanly and followed by `change` + `blur`; note quick-update date is radios + conditional `Others` box. | Format dates strictly `dd/mm/yyyy`, ensure `isSame`/model binding clears prior `×` clear button if present, and blur to close calendar popups before clicking Save/Next. |
| **6. HSN Typeahead (`typeahead-editable="false"`)** | **Critical:** Every HSN input (`#hsnCode`, `#hsnCodeLabour`, `#hsnCodePart`, **`#hSNCode`**) binds `typeahead-editable="false"`, `data-typeahead-on-select="...getgstPercent(...)"`, AND `data-ng-change="...changegstAmount(...)"`. Typing sets `gstPercent = ""` (wiping it!). Only clicking/pressing Enter on a dropdown suggestion fires `getgstPercent()`! | Type HSN slowly (`delay=60ms+`), wait for visible `.dropdown-menu li a` / `ul[typeahead-popup] a`, click matching item (or `ArrowDown`+`Enter`), then wait until `#gstPercent` / `#gstPercetage` populates non-empty. |
| **7. Base64 File Inputs & Size Limits** | All file inputs use `angular-base64-upload` (`base-sixty-four-input`). `myFiles` becomes `{filename, filetype, filesize, base64}`. `getUploadFileSize()` fetches backend limits (`MAX_FILE_UPLOAD_SIZE`, `minJPGUploadSize`, `MAX_SIZE_FINAL_REPORT`, `MAX_FILE_UPLOAD_SIZE_NON_MANDATORY`). Max 40 total uploaded docs (`uploadFileNonTieUp`). | Upload via Playwright `set_input_files()`, wait for Angular `FileReader` to populate `uploadedFileName` / `myFiles`, and compress files `> 2 MB` beforehand. |
| **8. Primary/Sup Excel Parsing (`xlsx.core.min.js`)** | `readExcel()` / `readExcelSup()` reads `workbook.Sheets.Primary_Assessment_Template` / `Supplementary_Assessment_Template` in browser memory and checks **`Object.keys(exceljson[0]).length == 11`**! | Output `.xlsx` must keep exact sheet name `Primary_Assessment_Template` and exact 11 headers (`SlNo` through `gstPercentage`). |
| **9. Modals & SweetAlert / Growl Interrupts** | Every Save/Next/Error pops `$modal.open` (`alertMessage.html`, `mandatoryFields_nontieup.html`) with `.modal-content` buttons (`×Close`, `OK`, `Confirm`, `Yes`, `No`, `Cancel`). `mandatoryFields_nontieup.html` lists invalid `$name` fields! | Dismiss non-blocking alert modals (`popup_service.py`) before interacting with underlying tab buttons. Never blind-click `Complete Survey` modals. |

### 4.1 Confirmed Duplicate ID Registry (Avoid Unscoped `#id` Lookups!)

| Duplicate ID | Where It Collides | Safe Alternative Selector |
| :--- | :--- | :--- |
| `#saveClaimAssesment` | 4 buttons in `tab-claimassesment.html`: `saveDetailsMaruti()`, `saveMarutiExtraDeatils()`, AND `saveAssesment()` (x2)! | `.tab-pane.active button[data-ng-click*="saveAssesment"]` vs `saveDetailsMaruti` |
| `#checkbox` | All 12 bottom certification checkboxes (`a)`–`l)`) | `input[type="checkbox"][name="engChaVerified"]`, etc. |
| `#checkBox` | 2 `id="checkBox"` elements in `tab-additionalDetails_nonTieUp.html` (`physicallyVerified`, `disclaimer`), plus `PendingRqstAcpt_NT.html`, `CompleteSurvey_nonTieUp.html` | `input[name="Physically Verified -checkBox"]`, `input[name="Disclaimer -CheckBox"]` |
| `#saveQuickUpdateNM` | IFSC **Find** button on Tab 2 **AND** quick-update **Next** button on Tab 1 (`tab-quickupdate-nonTieUp.html`)! | Scope to `.tab-pane.active`: Tab 1 `button[data-ng-click*="saveQuickUpdateNM"]`, Tab 2 `button[data-ng-click*="getIFSCDetails"]` |
| `#saveQuickUpdate` | Quick Update Next + `tab-dealerUploadedDoc.html` Next (`toClaimAssmntHyundai()`) | `.tab-pane.active button[data-ng-click*="saveQuickUpdate"]` |
| `#hsnCode` / `#deprePercent` / `#gstPercetage` / `#sel1` / `#vItem` | Repeated per table row (`$index`) and across Primary/Supplementary/Maruti tables | Use row index suffix `#hsnCode{{$index}}{{invoiceIndex}}` or `input[name="Primary Assessment Hsn Code00"]` |
| `#hsnCodeLabour` / `#billedAmtPainting` / `#nilDepAmountWithoutGST` / `#nilDepAmountWithGST` / `#addRows` / `#myTable` | Duplicated across `BREAK UP` vs `CONSOLIDATED` painting modes and Primary vs Supplementary tables in `tab-claimAssessment-nonTieUp.html` | Scope to parent container or `name` + `:visible` |
| `#netSalvageMapInvoice` | 3 `ng-if` branches (`noOfInvoices == '1'/'2'/'3'`) across Tie-Up and Non-Tie-Up assessment | `[data-ng-model="surveyorData.worklist.claimAssessment.netSalvageMapInvoice"]:visible` |
| `#claimantMobileNo` | 2 `ng-if` branches in `tab-quickupdate.html` (`claimTypeNM!='Maruti'` vs `=='Maruti'`) | `[data-ng-model="surveyorData.worklist.quickUpdate.claimantMobileNo"]` |
| `#typeOfVehicle` / `#typeOfBody` / `Is there any TP claim?` / `Description of the TP claim` | Duplicated across `Maruti` vs `!= 'Maruti'` / 7 `typeOfBody` product branches in `tab-additionalDetails_nonTieUp.html` | `[data-ng-model="surveyorData.worklist.additionalDetails.typeOfBody"]:visible` |
| `#mandatoryFiles` / `#blahFile` | Reused inside `ng-repeat` rows for Vehicle Photo + Document Upload | Scope to `li` row index `input[name="mandatoryFiles0"]` |
| `#remarks` | Quick Update `#remarks` **AND** Tab 5 Connect with Claim Office `#remarks`! | `.tab-pane.active textarea[data-ng-model="..."]` |
| `#dropdownMenu1` / `#claimNo` / `#priority{{$index}}` | Repeated on KPI cards (`SurveyorHome.html`) & claim cards (`SurveyorWorklist.html`) | Target card container by claim number text |

---

## 5. End-to-End Page & Tab DOM Specifications

### Section 0: Login, Role Selection, Profile & Dashboard

#### 0A. Login (`IntermediaryLogin.html` -> `InnerHTML/loginNC.html`)
- **Username:** `input#userName[name="userName"]` (`data-ng-model="loginData.userData.userName"`)
- **Password:** `input#password[name="password"][type="password"]` (`data-ng-model="loginData.userData.password"`)
- **Captcha Controls:** `div[vc-recaptcha][key="loginData.captchaKey"]` (reCAPTCHA) OR image captcha `div.captcha-Img-Div` + refresh `button[data-ng-click="loginData.reloadCaptcha()"]` + input `input.captcha-input[maxlength="10"]` (`data-ng-model="loginData.captchaResponse"`)
- **Submit:** `button.ncr_lp-btn` (`data-ng-click="loginData.validateLoginForm(loginData.userData, login.form)"`, disabled when `loginForm.$invalid`)

#### 0B. Dashboard (`InnerHTML/surveyor/SurveyorHome.html`)
- **4 KPI Cards** (Pending / Completed / Rejected / Fees) with time-filter dropdowns (`Today`, `Last 7 days`, `Last 30 days`) triggering `surveyorPendingRequest.onClickKPIDetails()`.
- **Pending Requests panel:** `Accept` (`pendingRequestsAccept(pendingReq)`) and `Reject` (`pendingRequestsReject(pendingReq)`).

---

### Section 1: Worklist (`#/Worklist` — `InnerHTML/surveyor/SurveyorWorklist.html`)

- **Card-Based List (Not a single `<table>`):** Claims render in `div.card-claim` via `data-ng-repeat="pendingClaim in surveyorWorklist.pendingClaimsRecords"` (highlighted `.danger-pink` when `pendingClaim.lastChatFlag == 'O'`).
- **Filter Controls:**

| Control | ID / Name | `ng-model` | Options / Action |
| :--- | :--- | :--- | :--- |
| Filter By | `#searchType` | `surveyorWorklist.searchType` | `Claim No.`, `Insured Name`, `Vehicle Registration No.`, `Claim branch` (`ng-change=searchTypeChange(...)`) |
| Conditional Filter Value | `#filterWorklistClaimNo` *(20)* / `#filterWorklistInsured` *(180)* / `#filterWorklistVehicalReg` *(180)* / `#filterWorklistClmBrnh` *(6)* | `surveyorData.worklist.filterWorklist*` | Shown according to `#searchType` |
| Claim Channel | `#claimType` | `surveyorWorklist.claimType` | Populated via `surveyorWorklist.surveyorClaimTypes` (`nonMarutiClaim`, `Maruti`, `Hyundai`, `Tata Motor PC Portal`, `Kia`, `Hero MotoCorp`, etc.) |
| Buttons | `Filter` / `Export to Excel` | — | `surveyorWorklist.filterClaims()` / `surveyorWorklist.openCsvModal()` (`#csvClaimType`, `#csvFromDate`, `#csvToDate`) |
| Row Actions | `Priority` checkbox `#priority{{$index}}`, `View Claim Details`, **`Click Here To Proceed`**, Past Claims count link | `pendingClaim.priority` | `nonMarutiClaimCheck(...)` -> **`WorklistSurveyNew`**; `performActions(...)` -> **`WorklistSurvey`** *(if tie-up)* or **`WorklistSurveyNew`** *(if `tieupFlag == 'NM'`)*; `performActionsHyundai/KIA/Hero/MarineCargoClaims(...)` for OEM channels |

---

### Section 2: Claim Search (`#/ClaimSearch` — `InnerHTML/surveyor/SurveyorClaimSearch.html`)

- **Search Mode Radios** (`name="radios-inline"`): `#polNo` (`handleSearch('policy')`), `#claimNo` (`handleSearch('claim')`), `#lossDateRange` (`handleSearch('date')`), `#vehRegNo` (`handleSearch('vehicle')`).
- **Inputs:** `#claimNo_id` (`claimNo`, max 20), `#polNo_id` (`PolicyNo`, max 20), `fromDate` / `toDate` (`dd/MM/yyyy` datepickers) + `serachType_New` select (`SURVEYOR_NEW_SEARCH_TYPE`), split Vehicle Reg (`registrationNo1`/`2`/`3` max 3, `registrationNo4` max 4).
- **Actions:** `Search` (`surveyorClaimsearch.claimSearch()`), result link `a` *"View Claim Details"* (`viewClaim(claimNumber)` or `performActionsMarineCargoClaims(claimNumber)`).

---

### Section 3: Tab 1 — Quick Update (`#one`)

Compares Standard Non-Tie-Up (**`tab-quickupdate-nonTieUp.html`**, state `WorklistSurveyNew`) and Tie-Up (**`tab-quickupdate.html`**, state `WorklistSurvey`):

| Field | Control / ID / Name | `data-ng-model` (`surveyorData.worklist.quickUpdate.*`) | Rules & Differences (`New` vs `Tie-Up`) |
| :--- | :--- | :--- | :--- |
| **Basic Claim Details** | Read-only grid (top) | `viewClaimDetails.claimDetails.*` | Shows Claim No., Insured Name, Intimation Date, Loss Date, Assessment Amt, Estimate Amt, Branch, Status |
| **Date of Survey** | Radios `#dateOfSurveyRadio1`..`4` (`Others`) + conditional `input[name="dateOfSurvey"]` (`dd/MM/yyyy`) | `.surveyDateRadio` + `.surveyDate` | Selecting `1`–`3` runs `resetSurveyDateVal()`; selecting `value="Others"` reveals text datepicker input |
| **Time of Survey** | `name="timeOfSurvey"` (`#timeOfSurvey` in Tie-Up) | `.timeOfSurvey` | **`New`:** `maxlength="5"` (`HH:MM`, `surveyTimeValNM()`). **Tie-Up:** `maxlength="8"` (`HH:MM:SS`, `surveyTimeVal()`). **Required** |
| **Place of Survey** *(New only)* | `textarea[name="placeOfSurvey"]` | `.placeOfSurvey` | **Required in `tab-quickupdate-nonTieUp.html` only** (absent in Tie-Up `tab-quickupdate.html`) |
| **Survey Completed** | Radios `#radioDataCompleted{{$index}}` | `.surveyCompleted` | `Y`/`N` (`YES_NO`). Triggers `resetSurveyCompleted('survey')` |
| **Reason** *(if Completed = N)* | `select[name="reason"]` (`#reason` in Tie-Up) | `.dpReasonForSurveyNotCompleted` | Required when `surveyCompleted == 'N'`. Live values: `string:Vehicle not available for survey`, `string:Incomplete documents`, `string:Vehicle to be dismantled`, `string:Other reasons`. Selecting `Other reasons` shows `textarea[name="comment"]` (`maxlength=150`) |
| **DL Applicable?** *(New only)* | Radios `#radioDrivingLicenseApplicable{{$index}}` | `.drivingLicenseApplicable` | `tab-quickupdate-nonTieUp.html` only; **`drivingLicenseVerified` shows only when `'Y'`** (`checkDrivingLicenseApplicableFn`) |
| **DL Verified with Original** | Radios `#radioDrivingLicense{{$index}}` | `.drivingLicenseVerified` | `Y`/`N` (`certificationsCheck()` updates bottom checkboxes `g)`–`j)`) |
| **RC Book Verified with Original** | Radios `#radioRCbook{{$index}}` | `.rcBookVerified` | `Y`/`N` |
| **DL Verified via Parivahan** | Radios `#radioDrivingLicensePar{{$index}}` | `.drivingLicenseVerifiedParivahan` | `Y`/`N` |
| **RC Verified via Parivahan** | Radios `#radioRCbookPar{{$index}}` | `.rcBookVerifiedParivahan` | `Y`/`N` |
| **Close Proximity & Break-In** | Radios `#isCloseProximityBreakIn{{$index}}` | `.isCloseProximityBreakIn` | If `'Y'`, shows **Inspection Report Uploaded** `#inspectionReportUploaded{{$index}}` (`'N'` disables `#saveQuickUpdateNM`!) |
| **Allow Cashless Claim** | Radios `#radioAllowCashless{{$index}}` | `.allowCashlessClaim` | `Y`/`N`, required |
| **Estimated Amount (In Rs.)** | `input[name="surveyorAccessedAmount"]` (`#surveyorAccessedAmount` in Tie-Up) | `.surveyorAccessedAmount` | Disabled unless `natureOfLoss == 'THEF-EV'` or `whetherTotalLossClm == 'Yes'`. Max 10 |
| **Remarks** | `textarea[name="remarks"]` (`#remarks` in Tie-Up — **collides with Tab 5!**) | `.remarks` | Required, max 240 |
| **Claimant Mobile / Email** | `input[name="mobileNo"]` *(or `"Mobile No of the Claimant"`)* & `input[name="emailId"]` | `.claimantMobileNo`, `.claimantEmailId` | Mobile max 10 (`disabled` if `quickRenewalObj.disMobileNo`) |
| **Expected Date of Repair** | `input[name="expectedDateOfRepair"]` *(Tie-Up name `"Expected date of completion of repair"`, `#expectedDateOfRepair`)* | `.expectedDateOfRepair` | Required, `dd/MM/yyyy` datepicker |
| **Vehicle Photo Graph** *(New only)* | Repeater rows (`mandatoryFilesList`): `select[name="docType{{$index}}"]`, `input[name="uploadedFileTxt{{$index}}"]`, `input#mandatoryFiles[type="file"][base-sixty-four-input]`, `+` icon `addRow('man')`, `-` icon `deleteRow('man',$index)` | `manDoc.docType`, `manDoc.myFiles` | Live `dropDownQuickUpdate`: `string:DRIVING LICENSE`, `string:REGISTRATION CERTIFICATE`, `string:CLAIM FORM`, `string:CLAIM RELATED DOCUMENTS`, `string:UPLOAD GARAGE ESTIMATE`, `string:PHOTOGRAPHS OF THE VEHICLE`. Click **Upload** (`uploadFileNonTieUp_quickUpdate('mandatory')`) to populate `uploadDocArrayQuickUpdate` |
| **Buttons** | **View History**, **Reset**, **Next (`#saveQuickUpdateNM` / `#saveQuickUpdate`)** | — | `saveQuickUpdateNM()` / `saveQuickUpdate()` saves Quick Update, unlocks Tabs `#two`–`#four` (`NEW_SURVEYOR`), and clicks `#two` |

---

### Section 4: Tab 2 — Additional Details (`#two` — `InnerHTML/surveyor/tab-additionalDetails_nonTieUp.html`)

All sections below live in Bootstrap accordions (`is-open`). **Note:** Sections marked *(NM only)* are wrapped in `data-ng-if="claimTypeNM == 'nonMarutiClaim'"`.

#### 4.1 Header Summary Accordion (Read-Only Tables)
- **Additional Details** outer accordion displays read-only reference tables for **Workshop**, **Service Advisor**, **Claim Reported Branch**, and **Insured**.

#### 4.2 Registration Certificate Details Accordion *(Live Row Order: Owner Name → Reg No 1..4 → Type of Vehicle → Date of Reg → Engine/Chassis/Physically Verified → Make/Model (disabled)/Class/Pre-Accident Cond → Reg Laden/Unladen Wt & Fitness/Permit → Route/Tax/RTO/Transfer/Odometer/Color/Color Type/Type of Fuel)*
| Field | ID / Name | `data-ng-model` (`surveyorData.worklist.additionalDetails.*`) | Notes & Options |
| :--- | :--- | :--- | :--- |
| Reference Number | `name="Reference No"` | `.refernceNo` | Note spelling `refernceNo`! Max 30 *(outside accordion)* |
| Registered Owner Name* | `name="Registered Owner Name"` | `.registeredOwnerName` | Required, max 50 |
| Vehicle Registration No. (4 boxes) | `name="registrationNo1"`, `registrationNo2`, `registrationNo3`, `registrationNo4` | `.registrationNo1`..`4` | `registrationNo2 == 'BH' && surveyorData.reg34BHFlag` switches `reg3`/`reg4` maxlength between `(3,4)` and `(4,2)` |
| Date of Registration | `name="registrationDate"` (`ng-if="efgFlag == 0"`) | `.dateOfReg` | `dd/MM/yyyy` datepicker |
| Engine No.* / Chassis No.* | `name="Engine no"`, `name="Chassis no"` | `.engineNo`, `.chasisNo` | Note spelling `chasisNo`! Required, max 25 |
| Physically Verified* | `#checkBox` (`name="Physically Verified -checkBox"`) | `.physicallyVerified` | Checkbox (required) |
| Vehicle Make* / Model* | `name="Vehicle Make"`, `name="Model"` | `.vehicleMake`, `.vehicleModel` | Disabled in template (pre-filled from policy) |
| ~~Type of Body*~~ *(removed on live portal)* | **`#typeOfBody`** (`name="Type of Body"`, legacy 7 `ng-if` branches) | `.typeOfBody` | Removed from current live portal form; App3 no longer extracts or fills this field for New India |
| Class of Vehicle* / Pre-Accident Condition* | `name="Class of Vehicle"`, `name="Pre-Accident Condition"` | `.classOfVehicle`, `.preAccCondition` | Required, max 120 |
| Reg Laden Wt / Unladen Wt | `.regLadenWt`, `.unLadenWt` | `.regLadenWt`, `.unLadenWt` | `ng-if="productCode != 'PC'"` (hidden for Private Car!), max 10 |
| Fitness Cert No. / Valid Upto / Permit No. / Permit Valid Upto | `name="fitnessCertNo"`, `name="permitValidUpto"`, etc. | `.fitnessCertNo`, `.fitnessCertValidUpto`, `.permitNo`, `.permitValidUpto` | Shown when `productCode != 'PC'`; required when `claimTypeNM == 'Maruti' && productCode == 'CV'` |
| Vehicle Permit Type* / Permit Type* | `#vehiclePermitType` (`pctwefg == 0`), `#Permit Type` (`productCode == 'CV'`) | `.vehiclePermitType`, `.permitType` | Required when visible |
| Route/Area of Operation / Tax Paid Upto / RTO Name* / Transfer Date / Odometer Reading* / Vehicle Color* / Vehicle Color Type* | `name="taxPaidUpto"`, `name="RTO Name"`, `name="transferDate"`, `name="Odometer Reading"`, `name="Vehicle Color"`, `name="Vehicle Color Type"` | `.routeOfOprtn`, `.taxPaidUpto`, `.rtoName`, `.transferDate`, `.odometerReading`, `.vehicleColor`, `.vehicleColorType` | `vehicleColor` & `vehicleColorType` gated by `efgFlag == 0` / `efgbFlag == 0` |
| Type of Vehicle* | **`#typeOfVehicle`** (`name="Type of Vehicle"`, 2 `ng-if` branches!) | `.typeOfVehicle` | Live opts: `string:Private Car`, `string:Standard Two Wheeler`, `string:Goods Carrying (A)`, `string:Trailers (B)`, `string:Passenger Carrying (C)`, `string:Misc & Special Type (D)`, etc. |
| Type of Fuel* | `#Type of fuel` (`name="Type of fuel"`) | `.typeOfFuel` | Live opts: `string:Petrol`, `string:Diesel`, `string:Bifuel`, `string:Electric`, `string:CNG`, `string:LPG` |

#### 4.3 Driver Details Accordion
| Field | ID / Name | `data-ng-model` (`surveyorData.worklist.additionalDetails.*`) | Condition / Options |
| :--- | :--- | :--- | :--- |
| Was the vehicle parked during accident?* | **`#vehicleParked`** (`name="Was the vehicle parked during accident ?"`) | `.vehicleParked` | Static opts: `""` (`--Select--`), **`"Yes"`**, **`"No"`**. **All fields below show ONLY when `'No'`!** |
| Relationship with Insured* | `#relationship` | `.relationship` | `string:Self`, `string:Friend`, `string:Paid Driver`, `string:Relative`, `string:Employee`, `string:Other` |
| License Type of Driver* | `#licenseType` (`bfgFlag == 0`) | `.licenseType` | `string:Light Motor Vehicle`, `string:Heavy Goods vehicle`, `string:Heavy Passenger Motor vehicle`, `string:Transport Vehicle`, `string:Motor Cycle with Gear`, `string:Motor Cycle without Gear`, `string:Auto Rickshaw`, `string:Learner`, `string:Others`, etc. |
| DOB of Driver* / Age of Driver* | `name="DOB of Driver"` (`dd/MM/yyyy`), `name="Age of Driver"` | `.dobOfDriver`, `.ageOfDriver` | `ng-change="calculateDriverAge(...)"` auto-populates Age! |
| Driver Name* | `#driverName` | `.driverName` | Required, max 50 |
| Is DL valid for type of vehicle on date of accident?* | Radios `#radioisDlValidForType{{$index}}` | `.isDlValidForType` | `Y` / `N` |
| License Issuing Authority* / DL No.* / Issue Date* / Expiry Date* / Badge No. | `name="License Issuing Authority"`, `name="Driver driving License Number"`, `name="Driver driving License Issue Date"`, `name="Driver driving License Expiry Date"`, `.badgeNo` | `.licenseIssueAuth`, `.driverLicenseNo`, `.drivingLicenseDate`, `.driverLicenseExpDate`, `.badgeNo` | `bfgFlag == 0` required on auth/no/dates; Badge optional (max 20) |

#### 4.4 FIR Details Accordion *(Live Row Order: `Is there any TP claim?` Row 1 Col 1 → `FIR/GDR No.` → `FIR Date` → `Police Station` → `Charged U/S MV Act` → `Charged U/S IPC` → `Whether driver without license?` → `Any Previous Police Records?`)*
| Field | ID / Name | `data-ng-model` (`surveyorData.worklist.additionalDetails.*`) | Notes |
| :--- | :--- | :--- | :--- |
| FIR/GDR No. / FIR Date / Police Station / Charged U/S MV Act / Charged U/S IPC | `name="firDate"` + `placeholder` labels (`FIR/GDR No.`, `Police Station`, etc.) | `.firNo`, `.firDate`, `.policeStation`, `.chargedUSMotorVehAct`, `.chargedUSIPC` | Optional text inputs + `dd/MM/yyyy` datepicker |
| Whether driver without license?* | `name="Whether driver without license ?"` | `.withoutLicense` | Required (`string:Yes` / `string:No`) |
| Any Previous Police Records? | `ng-model="prevRecord"` | `prevRecord` | `--select--` / `Yes` / `No`; if `additionalDetails.prevPoliceRecords == 'Yes'`, reveals `Details of previous police records` (`maxlength=240`) |
| Is there any TP claim?* | **`#Is there any TP claim?`** (`2` branches: `Maruti` / `!= 'Maruti'`) | `anyTpClaims` (`ng-change=removeTpClaim(...)`) | Required (`--select--`, `Yes`, `No`); if `Yes`, reveals **`#Description of the TP claim`** (`.descTpClaim`, required, max 240) |

#### 4.5 NEFT Details Accordion *(Gated by `claimTypeNM == 'nonMarutiClaim'`)*
| Field | ID / Name | `data-ng-model` (`surveyorData.worklist.additionalDetails.*`) | Condition / Behavior |
| :--- | :--- | :--- | :--- |
| Provide bank details for payment to | `label="Provide bank details for payment to"` | `.paymentTo` | Static opts: `""`, `Insured`, `Dealer`, `Garage` |
| Policy Holder Name* / Code* | `name="Policy Holder Name"`, `name="Policy Holder Code"` | `.policyHolderName`, `.policyHolderCode` | `readonly` when `paymentTo == 'Insured'` |
| Dealer Name* / Garage Name* | `name="Dealer Name"`, `name="Garage Name"` | `.dealerName`, `.garageName` | Shown when `paymentTo == 'Dealer'` / `'Garage'` (max 75) |
| IFSC Code* + **Find** button | `name="IFSC Code"` + `button#saveQuickUpdateNM` *"Find"* (`getIFSCDetails_nt()`) | `.IFSC` | Clicking **Find** queries `fetchIFSCDetail` and populates readonly **Bank Name**, **Bank Branch Name**, **Bank Addess** (note spelling!) |
| Account Number* / Re-Enter Account Number* | `name="Account Number"`, `type="password"[name="Re-Enter Account Number"]` | `.accountNo`, `.reAccountNo` | `saveAdditionalDetails()` rejects if `accountNo != reAccountNo` |
| Account Type* / Party Payment Method* | `#accountType` (`name="Account Type"`), `#partyPaymentMethod` (`name="Party Payment Method"`) | `.accountType`, `.partyPaymentMethod` | `partyPaymentMethod` static opt: `NEFT:NEFT` |

#### 4.6 Kept Open Parts, Work Approval Details & Tab 2 Footer
- **Kept Open Parts:** `select#keptOpen` (`string:Y` / `string:N`); when `'Y'`, shows `textarea#keptOpenRemarks` (required, max 240).
- **Work Approval Details** *(NM only)*: `select[name="Approval Type"]` (`workApprovalType`, `ng-change="resetDateTime()"`), `input#workApprovalFile[type="file"][accept=".pdf,application/pdf"]` (`workApprovalFile`), `input[name="Work Approval Date"]` (`dd/MM/yyyy`), `input[name="workApprovalTime"]` (`HH:MM`, max 5, disabled if `workApprovalType == 'Rejected'`), **Submit** button (`submitDocs('Additional Details','WORK APPROVAL')`), table of uploaded rows `workApproval in worklistAprvList`.
- **Mandatory tail fields:** `select[name="Whether Vehicle Details are matching with policy ?"]` (`string:Y`/`string:N`; `'N'` opens `textarea[name="Vehicle Details Mismatch Remarks"]`), `textarea[name="Cause and Nature of Accident"]` (required, max 240), and `#checkBox` (`name="Disclaimer -CheckBox"`, required).
- **Tab 2 Buttons:** **Save** (`saveAdditionalDetails()`, disabled when `RCDForm.$invalid`), **`button#toClaimAssessment` Next** (`toClaimAssessment()` — unlocks `#three` and activates Claim Assessment!).

---

### Section 5: Tab 3 — Claim Assessment (`#three`)

Two completely distinct templates depending on whether the claim is **Non-Tie-Up** or **Tie-Up/Maruti**:

#### 5A. Standard Non-Tie-Up Claim Assessment (`InnerHTML/surveyor/tab-claimAssessment-nonTieUp.html`)
- **Top Policy/Invoice Header:**
  - `No of invoices available` (`noOfInvoices`, triggers `changeNoOfInvoice(value)`) -> repeats **Invoice `{{$index+1}}`** blocks (`multiInvoice[$index]`).
  - `Nil Depreciation` radios `#nilDepreciation{{$index}}` (`ng-if="policyInfo.nilDepreciationFlag"`, triggers `recalculateNilDepForAllAssessmentRows()`).
- **Per-Invoice Header (`Invoice 1..N`):**

| Label | Name | `data-ng-model` (`multiInvoice[$index].*`) | Rules |
| :--- | :--- | :--- | :--- |
| Whether Workshop is GST Registered* | `Whether the Workshop is GST Registered{{invoiceIndex}}` | `.isWorkshopGstRegistered` | `string:Y` / `string:N`, required |
| Whether Payment invoice is in name of NIA* | `Whether Payment invoice is in the name of NIA{{invoiceIndex}}` | `.isPaymentInvoice` | Triggers `gstApplicableInv(...)` (`'Y'` makes Estimated/HSN/GST/Invoice fields required!) |
| Is GST Applicable?* | `Is GST Applicable?{{invoiceIndex}}` | `.isGstApplicable` | Disabled/auto-synced from NIA invoice flag |
| Vendor/Tax Invoice Date / Number | `Vendor/Tax Invoice Date{{invoiceIndex}}`, `Vendor/Tax Invoice Number{{invoiceIndex}}` | `.vendorTaxInvoiceDate`, `.vendorTaxInvoiceNumber` | Required when `isPaymentInvoice == 'Y'`; max 30 |

- **Primary Assessment & Supplementary Assessment Sub-Sections:**
  - Trigger dropdowns: `select[name="Is there any primary estimate"]` (`isPrimaryAssessment`: `string:Y`/`string:N`) and `select[name="Is there any supplementary estimate{{invoiceIndex}}"]` (`isSupplementaryEstimate`).
  - **Excel Bulk Upload:**
    - Primary: `#chooseFilePrim` (`accept=".xls,.xlsx"`) + button `Upload` (`readExcel(invoiceIndex)`) + `Validate` (`checkFields('PrimaryAssessment')`) + `Download Template`
    - Supplementary: `#chooseFileSup` (`accept=".xls,.xlsx"`) + button `Upload` (`readExcelSup(invoiceIndex)`) + `Validate` (`checkFields('SupAssessment')`)
    - Sheet & schema check: reads **`Primary_Assessment_Template`** / **`Supplementary_Assessment_Template`** and requires **all 11 columns**: `SlNo`, `category`, `description`, `partName`, `serviceType`, `estimatedAmount`, `billedAmount`, `assessedAmount`, `depreciationPercentage`, `hsnCode`, `gstPercentage`.
  - **OCR Populate Data (optional):** `#pDocTypeOCR` + `#priOcr` / `#sDocTypeOCR` + `#supOcr` (`uploadToOcr(...)`).
  - **Line-Item Table (`table#myTable`, `addList` / `addListSup`):**
    - Add rows via `#rowsForPrim` / `#rowsForSup` + `#addRows` (`addMultipleRows`).
    - Per row (`{{$index}}{{invoiceIndex}}`): `Category` (`Spare Parts` / `Labor Charges`), `Description` (`Parts at Cost`, `Parts at 50% Depreciation`, `Parts at Agewise Depreciation`, `Labor charges...`), `Part Name*`, `Service Type*` (`REPLACE`/`ALLOW`/etc.), `Estimated`, `Billed*`, `Assessed`, `Depreciation %` *(auto-calculated/disabled per category)*, **`#hsnCode{{$index}}{{invoiceIndex}}` (`typeahead-editable="false"`, triggers `getgstPercent` on select)**, `GST %` *(disabled readonly)*, `Amount Allowed (Excl/Incl)` & `Nil Dep` *(readonly)*.
- **Painting Charges Sub-Section:**
  - Read-only rollup inputs `#labourCharges`, `#paintMaterialCharges`.
  - Dropdown `name="Painting work details{{invoiceIndex}}"` (`CONSOLIDATED` vs `BREAK UP`, triggers `breakUpConsolidatedFn`) switching between `#myTable` tables for Break-Up vs Consolidated painting rows (`#billedAmtPainting`, `#hsnCodePart`, `#hsnCodeLabour`, etc.).
- **Delivery Order Details Accordion** *(when `claimTypeNM == 'nonMarutiClaim'`)*:
  - `#deliveryOrderFile` (`accept=".pdf,application/pdf"`), `name="Delivery Order Date"`, `name="Delivery Order Time"` (`HH:MM`), button **Submit** (`submitDocs('Claim Assessment','DELIVERY ORDER')`). **Required when `isCashlessApprovedFlag` is true!**
- **Summary Deductions, Additions & Reinspection (`$index == 0`):**
  - `#netSlavage` (Net Salvage, max 13), `#netSalvageMapInvoice` (if >1 invoice), `#lessCompulsoryExcess` *(disabled)*, `#lessVoluntaryExpress` *(disabled)*, `#lessOtherDeductions` (max 13, triggers `getAssesementAmt`), `#imposedExcess` *(disabled)*, `#towingCharges` (max 13), `#additionalTowingCharges` (max 13).
  - `#whetherReinspectionRequired` (`string:YES` / `string:NO`): `'YES'` opens `#dateOfReinspection`, `#reInspectionRemark1`, `#reInspectionRemark2`.
  - **Note on Recommendations (`#recommendations`):** Present in Tie-Up/Maruti (`tab-claimassesment.html`), NOT in `tab-claimAssessment-nonTieUp.html` — check visibility before filling!
- **Add-on Cover wise Assessment without GST:** Visible only when `addOnFlag == 'Y'` & policy flags match (`#nilDepreciationCover`, `#engineProtectCover`, `#consumableItemsCover`, `#keyProtectCover`, `#returnToInvoiceCover`, `#tyreAndAlloyCover`, `#roadTaxCover`, `#batteryProtectCover`, `#HybridProtectCover`, `#personalBelongingsCover`, `#lossOfContentCover`, `#additionalTowingChargesCover`).
- **Tab 3 Action Buttons (Non-Tie-Up):**
  - `View History` (`claimAssessment_nt_Hstry(claimNo)`)
  - `Temporary Save` (`checkClaimAsssessment('tempsave')`)
  - `Reset` (`resetClaimAssessmentNM()`)
  - **`Submit Assessment`** (`checkClaimAsssessment('submit')` -> `saveClaimAssessmentNTNew('submit')` — validates `claimAssessmentForm.$invalid` and pops `mandatoryFields_nontieup.html` if incomplete!)
  - `Assessment Summary` (`claimAssessment_nt_Summary(claimNo)`, disabled when `assessmentSummaryFlag == 0`)
  - **`Next`** (`surveyorWorklistSurvey.docUploadCall()` -> unlocks `#four` and clicks `#four`!)

#### 5B. Tie-Up / Maruti Claim Assessment (`InnerHTML/surveyor/tab-claimassesment.html`)
- **Claim Assessment: TOTAL** *(when `marutiClaimInd == 'N' || (marutiClaimInd == 'Y' && cutOffFlag == 'N')`)*: Yes/No radios (`#labourChangeAmount{{$index}}`, `#sparePartsAmount{{$index}}`, etc.) + manual `SA` override inputs (`#labourChangeAmountSA`..`#miscAmountSA`, `#totalAmountEA`), `Reset` (`defaultClaimAssessment()`), **`#saveClaimAssesment` Submit (`saveAssesment()`)**.
- **Claim Assessment: PART-WISE** *(when `marutiClaimInd == 'Y' && (cutOffFlag == 'Y' || surveyCategory == 'DSP')`)*:
  - Top fields: `#isWorkshopGstRegistered`, `#PaymentInvoiceName`, `#IsGSTApplicable?`, Vendor Tax Invoice Date/Number, Nil Depreciation radios, **`#saveClaimAssesment` Save (`saveDetailsMaruti()`)**.
  - Versioned Accordions (`Claim Version 1` / `Subversion` / `Assessment 1 (Pending|Final)`): `table#example` (`item4 in item3`) with `#vItem` (`Labour`, `Glass`, `Painting`, `Plastic`, `Metal`, `Denting`, `Misc`, `Spare`, `Other`), `#deprePercent`, `#sel1` (`Repair`, `Replace`, `Not Allowed` — note `? string:REPLACE ?` live option quirk!), `approvalAmount`, **`#hsnCode`**, `#gstPercetage`; buttons **Expand**, **Save as Draft** (`saveMarutiAssesment(1,item3)`), **Revise Assessment** (`2`), **Submit** (`3`), **Discard Draft** (`4`), **Add Row**.
  - Tail fields: `#netSlavage`, `#lessCompulsoryExcess`, `#imposedExcess`, `#lessVoluntaryExpress`, `#towingCharges`, `#additionalTowingCharges`, **`textarea#recommendations`**, `#whetherReinspectionRequired`, **`#saveClaimAssesment` Save (`saveMarutiExtraDeatils`)** + Add-on Cover **`#saveAddOnCoversButton`**, Delivery Order, **Assessment Summary**, and final **`#saveClaimAssesment` (`saveAssesment()`) Next**.

---

### Section 6: Tab 4 — Document Upload & Survey Fee Bill (`#four`)

Uses **`tab-doc_up_nontieup.html`** (`WorklistSurveyNew`) or **`tab-documentupload.html`** (`WorklistSurvey`). Structure is nearly identical:

#### 6.1 Uploaded Documents Accordion
- Displays already uploaded documents (`uploadDocArray` / `uploadedDocuments`) with download links (`docDownload(...)`), **`Download file Zip`** (`downloadZip()`), and delete action (triggers `ConfirmDeleteDoc.html` in Tie-Up/NT).

#### 6.2 Upload New Documents Accordion
| List | Document Type Dropdown (`ng-options`) | Inputs & Buttons |
| :--- | :--- | :--- |
| **Mandatory Documents** (`manDoc in mandatoryFilesList`) | `select#docType{{$index}}` (`name="docType{{$index}}"`, `SURVEYOR_DOCTYPE_NT_MAN` / `_T_MAN`): `string:DRIVING LICENSE`, `string:REGISTRATION CERTIFICATE`, `string:CLAIM FORM`, `string:CLAIM RELATED DOCUMENTS`, `string:UPLOAD GARAGE ESTIMATE`, `string:PHOTOGRAPHS OF THE VEHICLE` | `input#uploadedFileTxt{{$index}}` *(disabled)*, `input#mandatoryFiles{{$index}}[type="file"][base-sixty-four-input]`, `+`/`-` row buttons, **Upload** (`uploadFileNonTieUp('mandatory')` or `uploadFile('mandatory')`), **Reset** (`clearDocList('mandatory')`). Max 40 docs enforced! |
| **Non-Mandatory Documents** (`nonmanDoc in nonMandatoryFilesList`) | `select#docTypeNonMan{{$index}}` (`SURVEYOR_DOCTYPE_NT_NONMAN` / `_T_NONMAN`): `Damages`, `Estimate`, `PUC Certificate`, `Spot Photograph and Spot Survey Report`, `Others`, `Chassis Number Photograph`, `Odometer Reading Photograph`, `Permit-Fitness Certificate`, `FIR and Police Records`, `Cancelled Cheque Photograph`, `Front Photograph`, `Rear Photograph`, etc. | `input#uploadedFileTxtNon{{$index}}`, optional user filename `#uploadedFileTxtNonMan1{{$index}}` *(if `SURVEYOR UPLOADED PHOTO`)*, `#nonMandatoryFiles{{$index}}`, **Upload** (`uploadFileNonTieUp_nonMandatory('nonmandatory')` or `uploadFile('nonmandatory')`), **Reset** |

#### 6.3 Survey Fee Bill Accordion *(Hidden in Non-Tie-Up if `isGarageSurveyor`)*
| Field Label | Exact ID | `name` | `data-ng-model` (`surveyorData.worklist.surveyFeeBill.*`) | Notes & Triggers |
| :--- | :--- | :--- | :--- | :--- |
| Is Invoice in name of NIA* | **`#isInvoiceInNameOfNIA`** | `isInvoiceInNameOfNIA` | `.isInvoiceInNameOfNIA` | `""` (`Select`), `string:Y` (`Yes`), `string:N` (`No`) |
| Surveyor Fee Invoice number* | **`#surveyorFeeInvoiceNumber`** | `surveyorFeeInvoiceNumber` | `.surveyorFeeInvoiceNumber` | Required, max 20 |
| Surveyor Fee Invoice Date* | *(no id)* | `surveyorFeeInvoiceDate` | `.surveyorFeeInvoiceDate` | `dd/MM/yyyy` datepicker |
| Professional Fee | **`#professionalFee`** | `professionalFee` | `.professionalFee` | Max 10, `ng-change="totalFn()"` |
| Photos Amount | **`#photosAmount`** | `photosAmount` | `.photosAmount` | Max 10, `ng-change="totalFn()"` |
| Conveyance Amount | **`#conveyanceAmount`** | `conveyanceAmount` | `.conveyanceAmount` | Max 10, `ng-change="totalFn()"` |
| Others | **`#others`** | `others` | `.others` | Max 10, `ng-change="totalFn()"` |
| Is GST applicable? | **`#isGSTApplicable`** | `isGSTApplicable` | `.isGSTApplicable` | `""` (`Select`), `string:Y`, `string:N`; `ng-change="totalFn()"` |
| HSN Code | **`#hSNCode`** *(capital S & N!)* | `Primary Assessment Hsn Code{{$index}}` | `.hsnCode` | **`typeahead-editable="false"`**: typing resets `#gstPercent`; MUST select suggestion to invoke `getgstPercent($index, hsnCode, 'SFB')` |
| GST % | **`#gstPercent`** | `Primary Assessment Gst Percentage{{$index}}` | `.gstPercent` | Always `disabled` (populated via `getgstPercent` on HSN typeahead select) |
| GST Amount | **`#totalGSTAmount`** | `totalGSTAmount` | `.totalGSTAmount` | Always `disabled` (calculated via `totalFn()`) |
| Total* | **`#total`** | `total` | `.total` | `readonly` |
| Digital Signature Upload | **`#uploadDigSig`** | `mandatoryFiles{{$index}}` | `manDoc.myFiles` | + **Upload** button (`uploadDigSignature1('mandatory')`) |
| **Submit Fee Bill** | `button` *"Submit"* | — | `saveSurveyFeeBill()` | Enabled ONLY when `total`, `isInvoiceInNameOfNIA`, `surveyorFeeInvoiceNumber`, `surveyorFeeInvoiceDate` are set **and** `submitFeeBillFlag == true` |

#### 6.4 Reminder to Insured & Send Reminder Accordion
- History table `table#mytbl` (`Reminder Number`, `SMS Content`, `Sent Date Time`).
- Select/Deselect lists (`totalList` / `selectedValue` with `editAdd` / `edit`), SMS `textarea#smsarea` (`surveyor.content`), **`button#sendrem`** *"Send Reminder"* (`sendReminder(claimNo)`). *(In Tie-Up `tab-documentupload.html`, only shown for `claimTypeNM == 'Maruti' || 'Hero MotoCorp'`.)*

---

### Section 7: Tab 5 — Connect with Claim Office (`#five` — `InnerHTML/surveyor/tab-connectwithclaimoffice.html`)
- Sections: `View Chat History` (fetched by `fetchSurveyorComment()` on tab open) and `Submit Feedback`.
- Input: `textarea#remarks[name="remarks"]` (`surveyorData.worklist.connectwithclaimofc.remarks`, max 240 — **collides with Tab 1 `#remarks`!**).
- Button: `button` *"Send"* (`surveyorWorklistSurvey.saveSurveyorComment()`).

---

### Section 8: Standalone Surveyor Fee Page (`#/SurveyorFee` — `InnerHTML/surveyor/SurveyorFee.html`)
- Controls: `input[name="fromDate"]` (`SurveyFee.FromDate`, `dd/MM/yyyy`), `input[name="toDate"]` (`SurveyFee.ToDate`, `dd/MM/yyyy`), `itemsPerPage` select (`changeItemsPerPage()`).
- Buttons: `Search` (`fetchSettledClaimList()`, disabled until `FromDate` set), `Export` (`fetchEntireRecords()`).
- Table (`record in surveyorFee.onloadSurveyorFeeRecords`): `Sr.No`, `Cho Code`, `Claim No.`, `Policy No.`, `IntimationDate`, `Loss Date`, `SurveyorPayment Date`, `Surveyorfees`, `ReportSubmission Date`.

---

### Section 9: Modals, Popups & Session Timeout Inventory

| Template | Controller / Trigger | Purpose & Key DOM Elements |
| :--- | :--- | :--- |
| `InnerHTML/Quote/motor/alertMessage.html` | `alertCtrl` / `$modal.open` (`ALERT_POPUP_PATH`) | Global alert/confirmation popup used after almost every Save, Upload, IFSC lookup, or validation failure. Buttons: `×Close`, `OK`, `Confirm`, `Yes`, `No`, `Cancel`, `Proceed`. |
| `InnerHTML/surveyor/mandatoryFields_nontieup.html` | `checkFields(...)` on Submit Assessment / Complete Survey | Lists all `$invalid` field `$name`s, Row Number, Invoice Number, and `Redirect` tab links (`redirectKiaTab(obj.formTab)`) inside `table#myTable`. |
| `InnerHTML/surveyor/CompleteSurvey_nonTieUp.html` | `#completeSurveyMain` -> `completeSurvey(claimNo)` | Final `Please fill the below details to proceed` modal: `#keptOpen` (`Y`/`N`), `#keptOpenRemarks` (max 240), `#checkBox` disclaimer, **Submit** (`proceedNonTieUp()`). **NEVER auto-submit!** |
| `InnerHTML/surveyor/CompleteSurvey.html` | `#completeSurveyMain` (Maruti/Tie-Up) | `Reinspection Details`: `select#reAllowed` (`Y`/`N`), `name="reDate"`, `name="reTime"`, **Proceed** (`proceedMaruti()`). |
| `InnerHTML/surveyor/Alert_Digital_Sig_Complete_Survey.html` & `Upload_Digital_Signature.html` | Complete Survey sig check / Header `Upload Digital Signature` | Prompts if `.gif` surveyor digital signature (`#uploadDigSig[accept=".gif"]`) is missing before Complete Survey. |
| `InnerHTML/surveyor/PendingRqstAcpt_NT.html` & `PendingRqstReject.html` | Header Bell / Dashboard `Accept` & `Reject` | Disclaimer checkbox `#checkBox` + `Accept` / `Yes` / `No`. |
| `InnerHTML/surveyor/Surveyor_ClaimDetails.html`, `Surveyor_pastClaims.html`, `Surveyor_UpdateHistory*.html`, `AssessmentSummary_*.html` | Header action buttons / View History / Assessment Summary | Read-only modals (some with `Download as PDF`). |
| `InnerHTML/CountDown.html` | `idleTimeout` session timer | `Logout Alert!` modal with `Continue` (`countDownObj.stay()`) and `Logout` (`countDownObj.logout()`). |

---

## 6. Project Codebase Crosswalk (`app/portals/newindia/`)

| Portal Screen / Section | Project Automation Module | Config / Shared Helper | Critical Maintenance Notes |
| :--- | :--- | :--- | :--- |
| **Login Page (`loginNC.html`)** | `automation/login_module.py` | `config/settings.json` | `#userName`, `#password`, reCAPTCHA/image captcha, `button.ncr_lp-btn` |
| **Worklist / Claim Search -> Open Claim** | `automation/navigation_module.py` | `popup_service.py` | Navigates to `#/WorklistSurveyNew` (`WorklistSurvey` for tie-up) |
| **Tab 1: Quick Update** | `automation/quick_update_module.py` | `automation/ui_utils.py` | Fills survey date/time, radios, remarks, mobile/email, repair date |
| **Tab 1: Vehicle Photo Graph** | `automation/vehicle_photo_module.py` | `config/doc_mapping.json` | Only on `tab-quickupdate-nonTieUp.html` (`+` add row, `docType`, `#mandatoryFiles`, `Upload`) |
| **Tab 2: Registration Certificate** | `automation/registration_cert_module.py` | `config/field_mapping.json` | Handles `BH` registration branching & `productCode != 'PC'` hidden fields |
| **Tab 2: Driver Details** | `automation/driver_details_module.py` | `automation_defaults.json` | Sets `#vehicleParked` (`No`) before filling license/DOB/age |
| **Tab 2: FIR Details** | `automation/fir_details_module.py` | `automation_defaults.json` | Handles `NA` fallbacks & `withoutLicense` / `anyTpClaims` |
| **Tab 2: NEFT Details** | `automation/neft_module.py` | `folder_scanner.py` *(bank proof)* | Fills `paymentTo`, `#saveQuickUpdateNM` (`Find` IFSC), accounts + `#accountType` |
| **Tab 2: Work Approval + Next** | `automation/work_approval_module.py` | `config/doc_mapping.json` | `#workApprovalFile`, approval date/time, disclaimer `#checkBox`, `#toClaimAssessment` |
| **Tab 3: Claim Assessment + DO + Next** | `automation/claim_assessment_module.py` | `assessment_generator.py`, `pdf_assessment.py` | Uploads `Primary_Assessment_Template` via `#chooseFilePrim`, fills DO (`Cashless`), GST/deductions, clicks Next (`docUploadCall()`). **Note:** `#recommendations` only exists in Tie-Up template, not Non-Tie-Up |
| **Tab 4: Upload Docs + Survey Fee Bill** | `automation/document_upload_module.py`, `automation/survey_fee_bill_module.py` | `config/doc_mapping.json`, `automation_defaults.json` | Mandatory/Non-Mandatory uploads + **`#hSNCode` typeahead selection** + Fee Bill **Submit** (pauses before final `#completeSurveyMain`) |
| **Popups / Recovery / Shared Helpers** | `automation/popup_service.py`, `automation/recovery.py`, `automation/ui_utils.py` | `automation/ocr_helper.py` | Dismisses `alertMessage.html`, enforces per-page human review via `NewIndiaRecovery`, provides Angular-safe input/select/radio/upload helpers |
