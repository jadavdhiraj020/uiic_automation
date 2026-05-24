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
SEL_REGISTRATION_DATE = "#registrationDate"
SEL_MANUFACTURING_YEAR = "#manufacturingYear"
SEL_CHASSIS_NUMBER = "#chasisNumber"
SEL_ENGINE_NUMBER = "#engineNumber"
SEL_CUBIC_CAPACITY = "#cubicCapacity"
SEL_TYPE_OF_BODY = "#typeOfBody"
SEL_CLASS_OF_VEHICLE = "#classOfVehicle"
SEL_UNLADEN_WEIGHT = "#unladenWeight"
SEL_ROAD_TAX_PAID_UPTO = "#roadTaxPaidUpto"
SEL_COLOR_OF_VEHICLE = "#colorOfVehicle"
SEL_TYPE_OF_FUEL = "#typeOfFuel"
SEL_RTO_DROPDOWN = "#rto"
SEL_REGISTERED_LADEN_WEIGHT = "#registeredLadenWeight"
SEL_SEATING_CAPACITY = "#seatingLoadCarryingCapacity"
SEL_FITNESS_VALID_UPTO = "#fitnessValidUpto"
SEL_PERMIT_NUMBER = "#permitNumber"
SEL_TYPE_OF_PERMIT = "#typeOfPermit"
SEL_PERMIT_VALID_UPTO = "#permitValidUpto"
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
SEL_DOB_OF_DRIVER = "#dateOfBirth"
SEL_LICENSE_TYPE_DROPDOWN = "#licenseType"
SEL_LICENSE_VALID_FROM = "#validFrom"
SEL_LICENSE_VALID_UPTO = "#validUpTo"
SEL_LICENSE_NO_1 = "#driverLicenseNoOne"
SEL_LICENSE_NO_2 = "#driverLicenseNoTwo"
SEL_LICENSE_NO_3 = "#driverLicenseNoThree"
SEL_BADGE_NO = "#badgeNo"
SEL_BADGE_ISSUE_DATE = "#badgeIssueDate"
SEL_OWNER_DRIVER_YES = "#ownerDriver1"
SEL_OWNER_DRIVER_NO = "#ownerDriver2"
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
SEL_WORKSHOP_GST = "#gstNumber"

# --- BASIC DETAILS: NEXT BUTTON ---
SEL_BASIC_DETAILS_NEXT = "button:has-text('Next'), button[aria-label='Next']"

