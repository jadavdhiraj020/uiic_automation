# app/portals/oic/automation/selectors.py
"""
selectors.py — Centralized Playwright CSS/xpath selector definitions for OIC portal.
Allows zero-code modification of selector targets when portal structure changes.
"""

# --- LOGIN FORM SELECTORS ---
SEL_USERNAME = "#userName, #username, [name='username'], [name='userName'], #login-username"
SEL_PASSWORD = "#password, [name='password'], #login-password"
SEL_CAPTCHA_IN = "#captcha, input[name='captcha'], input[name='captchaInput'], input[name='captchaValue']"
SEL_CAPTCHA_CVS = "canvas#captcha, canvas, img#captchaImg"
SEL_LOGIN_BTN = ".login-formno button[type='submit'], .login-formno #continue-btn, #continue-btn, .login-formno button.btn-login-btn"
SEL_REFRESH_BTN = "button[aria-label*='Refresh CAPTCHA'], button.reset-btn-icon, button[title='Refresh Captcha'], .captcha-refresh, [title*='Refresh']"
SEL_ERROR_MSG = ".error-msg, .alert-danger, .text-danger, .ng-scope .alert, #errorMsg, .error-message"

# --- HEADER / LOGIN CONTAINER SELECTORS ---
SEL_HEADER_LOGIN_BTN = "button.header-login-btn, button#login-btn:visible"
SEL_LOGIN_FORM_CONTAINER = ".login-formno"
SEL_STARTUP_DIALOG_CLOSE = "button.p-dialog-header-close, button[aria-label='Close'], button.p-dialog-header-icon"

# --- ADVERTISEMENT / DIALOG POPUP SELECTORS ---
SEL_POPUP_CLOSE = [
    "button.p-dialog-header-close",
    "button[aria-label='Close']",
    ".p-dialog-header-close-icon",
    "button:has-text('Close')",
]

# --- NAVIGATION TAB SELECTORS ---
SEL_OTHERS_TABS = [
    "role=tab[name='Others'i]",
    "role=tab[name*='Others'i]",
    "a:has-text('Others')",
    "div:has-text('Others')",
    "[role='tab']:has-text('Others')",
    "text=Others",
]

SEL_MOTOR_SUB_LINKS = [
    "a:has-text('Motor OD Surveyor Assessment')",
    "text=Motor OD Surveyor Assessment",
    "li a:has-text('Surveyor Assessment')",
    "a[href*='surveyor-assessment']",
    "a[href*='surveyorAssessment']",
]

SEL_GENERATE_ASSESSMENT_BTNS = [
    "button:has-text('Generate Assessment +')",
    "button:has-text('Generate Assessment')",
    "a:has-text('Generate Assessment +')",
    ".btn-primary:has-text('Generate Assessment')",
    "button:has-text('+')",
    "[data-ng-click*='generate']",
    "button[ng-click*='generate']",
    "button:has-text('Generate')",
]

# --- GENERATE ASSESSMENT SEARCH FORM SELECTORS (Step 1) ---
SEL_CLAIM_TYPE_DROPDOWN = "#claimType"
SEL_CLAIM_NUMBER_INPUT = "#claimNumber"
SEL_POLICY_NUMBER_INPUT = "#policyNumber"
SEL_NEXT_BTN = "button[aria-label='Next'], button.next-btn"

# --- BASIC DETAILS: VEHICLE DETAILS FIELDS ---
SEL_REG_NUMBER = "#regNumber"
SEL_MAKE = "#make"
SEL_VARIANT = "#model"
# Registration Date is a MUI DatePicker (dynamic id like :r4e:).
# Located at runtime by its visible label text via fill_mui_datepicker().
SEL_REGISTRATION_DATE_LABEL = "Registration Date"
SEL_MANUFACTURING_YEAR = "#manufacturingYear"
SEL_CHASSIS_NUMBER = "#chasisNumber"
SEL_ENGINE_NUMBER = "#engineNumber"
SEL_CUBIC_CAPACITY = "#cubicCapacity"
SEL_TYPE_OF_BODY = "#typeOfBody"
SEL_CLASS_OF_VEHICLE = "#classOfVehicle"
SEL_UNLADEN_WEIGHT = "#unladenWeight"
# Road Tax Paid Upto is a MUI DatePicker (dynamic id).
SEL_ROAD_TAX_PAID_UPTO_LABEL = "Road Tax Paid Upto"
SEL_COLOR_OF_VEHICLE = "#colorOfVehicle"
SEL_TYPE_OF_FUEL = "#typeOfFuel"
SEL_RTO_DROPDOWN = "#rto"
SEL_REGISTERED_LADEN_WEIGHT = "#registeredLadenWeight"
SEL_SEATING_CAPACITY = "#seatingLoadCarryingCapacity"
# Fitness Valid Upto is a MUI DatePicker (dynamic id, has name='fitnessValidUpto').
SEL_FITNESS_VALID_UPTO_LABEL = "Fitness Valid Upto"
SEL_PERMIT_NUMBER = "#permitNumber"
SEL_TYPE_OF_PERMIT = "#typeOfPermit"
# Permit Valid Upto is a MUI DatePicker (dynamic id).
SEL_PERMIT_VALID_UPTO_LABEL = "Permit Valid Upto"
SEL_AUTH_NUMBER = "#authorizationNumber"
SEL_VALIDITY_AUTH = "#validityOfAuthorization"
SEL_ROAD_AREA = "#roadAreaOfOperation"

# --- BASIC DETAILS: LOSS DETAILS FIELDS ---
SEL_CLOSE_PROXIMITY_YES = "#closeProximity1"
SEL_CLOSE_PROXIMITY_NO = "#closeProximity2"
SEL_VB_CONFIRMED_YES = "#vbConfirmed1"
SEL_VB_CONFIRMED_NO = "#vbConfirmed2"
SEL_NIL_DEP_COVER_YES = "#nillDepreciationCover1"
SEL_NIL_DEP_COVER_NO = "#nillDepreciationCover2"
SEL_VEHICLE_AGE = "#vehicleAge"
SEL_LOSS_DESCRIPTION = "#lossDescription"

# --- BASIC DETAILS: SURVEYOR DETAILS FIELDS ---
SEL_SURVEYOR_NAME = "#surveyorName"
SEL_SURVEYOR_EMAIL = "#surveyorEmail"
SEL_SURVEYOR_MOBILE = "#surveyorMobileNo"
SEL_SURVEYOR_ADDRESS = "#surveyorAddress"
SEL_SURVEYOR_PAN = "#panNumber"

# --- BASIC DETAILS: DRIVER DETAILS FIELDS ---
SEL_DRIVER_NAME = "#driverName"
# Date of Birth is a MUI DatePicker (dynamic id like :r4q:).
# Located at runtime by its visible label text via fill_mui_datepicker().
SEL_DOB_OF_DRIVER_LABEL = "Date of Birth"
SEL_LICENSE_TYPE_DROPDOWN = "#licenseType"
# Valid From (DL issue date) is a MUI DatePicker (dynamic id like :r4s:).
SEL_LICENSE_VALID_FROM_LABEL = "Valid From"
# Valid Up To (DL expiry date) is a MUI DatePicker (dynamic id like :r4u:).
SEL_LICENSE_VALID_UPTO_LABEL = "Valid Up To"
SEL_LICENSE_NO_1 = "#driverLicenseNoOne"
SEL_LICENSE_NO_2 = "#driverLicenseNoTwo"
SEL_LICENSE_NO_3 = "#driverLicenseNoThree"
SEL_BADGE_NO = "#badgeNo"
# Badge Issue Date is a MUI DatePicker (dynamic id like :r50:).
SEL_BADGE_ISSUE_DATE_LABEL = "Badge Issue Date"
SEL_OWNER_DRIVER_YES = "#ownerDriver1"
SEL_OWNER_DRIVER_NO = "#ownerDriver2"
# Relation of Driver: appears only when Is Owner Driver = NO.
# Hardcoded default is "Self" (see automation_defaults.json → driver_relation_default).
# NOTE: The OIC portal has a typo in the id attribute ("Ralationship" instead of "Relationship").
SEL_RELATION_OF_DRIVER = "#driverRalationship"
SEL_QUALIFICATION = "#qualification"
SEL_TP_INVOLVED_YES = "#thirdPartyInvolved1"
SEL_TP_INVOLVED_NO = "#thirdPartyInvolved2"
SEL_COUNTRY = "#country"
SEL_STATE_DROPDOWN = "#state"
SEL_CITY_DROPDOWN = "#city"
SEL_PINCODE_DROPDOWN = "#pincode, #pinCode, #pin_code"
SEL_DRIVER_ADDRESS = "#address"
SEL_CHARGES_FILED = "#chargesFiled"

# --- BASIC DETAILS: WORKSHOP DETAILS FIELDS ---
SEL_WORKSHOP_NAME = "#workshopName"
SEL_WORKSHOP_ESTIMATE_AMT = "#workshopEstimateAmount"
# Workshop Estimate Date uses a MUI DatePicker with dynamic ID.
# We locate it by its visible label text (see fill_mui_datepicker in ui_utils.py).
# Using a partial match 'Workshop Estim' ensures compatibility if the website typo 'Workshop Estimiate Date' is ever corrected.
SEL_WORKSHOP_ESTIMATE_DATE_LABEL = "Workshop Estim"
SEL_WORKSHOP_GST = "#gstNumber"

# --- BASIC DETAILS: NEXT BUTTON ---
SEL_BASIC_DETAILS_NEXT = "button:has-text('Next'), button[aria-label='Next']"


# ============================================================================
# INTERIM REPORT (STEP 3) SELECTORS
# ============================================================================

# --- INTERIM REPORT: SURVEY DETAILS ---
SEL_VEHICLE_INSPECTED_YES = "#whetherVehicleInspected1"
SEL_VEHICLE_INSPECTED_NO = "#whetherVehicleInspected2"
SEL_SURVEY_COMPLETED_YES = "#isSurveyCompleted1"
SEL_SURVEY_COMPLETED_NO = "#isSurveyCompleted2"
SEL_TYPE_OF_SETTLEMENT = "#typeOfSettlement"          # Read-only / p-disabled
SEL_PLACE_OF_SURVEY = "#placeOfSurvey"
# NOTE: Date of Survey & Surveyor Appointed Date use MUI DatePickers with
# dynamic IDs (e.g. :r0:, :r4:). Selectors are resolved at runtime via
# label text in fill_mui_datepicker(). No static constants needed.

# --- INTERIM REPORT: DOCUMENTATION VERIFICATION ---
SEL_DL_APPLICABLE_YES = "#isDrivingLicenseApplicable1"
SEL_DL_APPLICABLE_NO = "#isDrivingLicenseApplicable2"
SEL_DOCS_VERIFIED_YES = "#isDrivingLicenseVerified1"
SEL_DOCS_VERIFIED_NO = "#isDrivingLicenseVerified2"
SEL_DOCS_VERIFIED_REMARKS = "#isDrivingLicenseVerifiedRemarks"
SEL_SPOT_SURVEY_YES = "#spotSurveyDone1"
SEL_SPOT_SURVEY_NO = "#spotSurveyDone2"
SEL_SPOT_SURVEY_REMARKS = "#spotSurveyDoneRemarks"

# --- INTERIM REPORT: CLAIM ASSESSMENT & CONTACT ---
SEL_INITIAL_LOSS_AMOUNT = "input[name='initialLossAssessmentAmount']"
SEL_MOBILE_CLAIMANT = "#mobileNumberClaimant"
SEL_EMAIL_CLAIMANT = "#claimantEmail"
SEL_SURVEYOR_OBSERVATION = "#surveyorObservation"
SEL_CAUSE_NATURE_ACCIDENT = "#causeNatureOfAccident"
SEL_PARTICULARS_LOSS = "#particularsOfLossDamage"
# NOTE: Submission Date of Final Document uses MUI DatePicker (dynamic ID).

# --- INTERIM REPORT: NAVIGATION ---
SEL_INTERIM_NEXT = "button.next-btn[aria-label='Next'], button:has-text('Next')"


# ============================================================================
# ASSESSMENT OF LOSS (STEP 4) SELECTORS
# ============================================================================

# --- INVOICE SECTION ---
SEL_LOSS_INV_NO = "input#invoiceNumber"
SEL_LOSS_INV_DATE_LABEL = "Invoice Date"
SEL_LOSS_GST_TYPE_DROPDOWN = "#gstType"
SEL_LOSS_INV_AMT_NO_GST = "#invoiceAmount"
SEL_LOSS_INV_GST_AMT = "#invoiceGstAmount"
SEL_LOSS_ADD_INV_BTN = "button[aria-label='Add Invoice +']"

# --- EXCESS SECTION ---
SEL_LOSS_EXCESS_DROPDOWN = "#excess"
SEL_LOSS_ADD_EXCESS_BTN = "button[aria-label='Add Excess +']"
SEL_LOSS_EXCESS_AMT_INPUT = "#amount"

# --- SALVAGE CHARGES SECTION ---
SEL_LOSS_SALVAGE_AMT_INPUT = "#salvageAmount"

# --- SURVEY CHARGES SECTION ---
SEL_LOSS_SURVEY_GST_YES = "#isSurveyorGstApplicable1"
SEL_LOSS_SURVEY_GST_NO = "#isSurveyorGstApplicable2"
SEL_LOSS_SURVEY_LICENSE_NO = "#licenseNumber"
SEL_LOSS_SURVEY_LICENSE_EXP_LABEL = "License Expiry Date"
SEL_LOSS_SURVEY_OICL_GST_NO = "#oiclGstNo"
SEL_LOSS_EXPENSES_DROPDOWN = "#expenses"
SEL_LOSS_ADD_EXPENSES_BTN = "button[aria-label='Add Expenses +']"

# --- DYNAMIC EXPENSE ACCORDION BLOCKS ---
SEL_EXPENSE_ACCORDION_TABS = ".p-accordion-tab"
SEL_EXPENSE_DESC_INPUT = "input#description"
SEL_EXPENSE_AMT_INPUT = "input[name='amount']"

# --- RECOMMENDATION & DECLARATION ---
SEL_LOSS_FINAL_REC = "textarea#finalRecommendation"
SEL_LOSS_DECLARATION = "input#declaration1, input[name='surveyorDeclaration']"

# --- NAVIGATION ---
SEL_LOSS_SAVE_AND_NEXT_BTN = "button[aria-label='Save and Next']"


# ============================================================================
# DOCUMENT UPLOAD (STEP 5) SELECTORS
# ============================================================================

# --- FILE INPUT SELECTORS ---
# Sections 1-4 use sequential numeric IDs (fileInput0..fileInput3)
SEL_UPLOAD_WORKSHOP_ESTIMATE = "#fileInput0"
SEL_UPLOAD_DISCHARGE_VOUCHER = "#fileInput1"
SEL_UPLOAD_INVOICE = "#fileInput2"
SEL_UPLOAD_REINSPECTION = "#fileInput3"

# Section 5: Driving License — TWO file inputs share id="fileInput" (duplicate).
# We differentiate via sibling <span> placeholder text using XPath.
SEL_UPLOAD_DL_FRONT = "xpath=//span[contains(text(),'Upload Front Side')]/preceding-sibling::input[@type='file']"
SEL_UPLOAD_DL_BACK = "xpath=//span[contains(text(),'Upload Back Side')]/preceding-sibling::input[@type='file']"

# Section 6 & 7 have unique IDs
SEL_UPLOAD_PHOTOGRAPHS = "#photographs"
SEL_UPLOAD_OTHER_DOCS = "#otherDocument"

# --- TEXT FIELDS ---
SEL_UPLOAD_DL_NUMBER = "#identificationNumber"   # Disabled, pre-filled by portal
SEL_UPLOAD_REMARKS = "textarea#remarks"

# --- NAVIGATION & ACTION BUTTONS ---
SEL_UPLOAD_BACK_BTN = "button[aria-label='Back']"
SEL_UPLOAD_PREVIEW_BTN = "button[aria-label='Preview']"
SEL_UPLOAD_SUBMIT_BTN = "button[aria-label='Submit']"

