# app/portals/oic/automation/selectors.py
"""
selectors.py — Centralized Playwright CSS/xpath selector definitions for OIC portal.
Allows zero-code modification of selector targets when portal structure changes.
"""

# --- LOGIN FORM SELECTORS ---
SEL_USERNAME = "#userName, #username, [name='username'], [name='userName'], #login-username"
SEL_PASSWORD = "#password, [name='password'], #login-password"
SEL_CAPTCHA_IN = "input[name='captchaInput'], input[name='captcha'], input[name='captchaValue'], #captcha"
SEL_CAPTCHA_CVS = "canvas#captcha, canvas, img#captchaImg"
SEL_LOGIN_BTN = "button[type='submit'], #continue-btn, #btn-login, button:has-text('Login'), button:has-text('Sign In')"
SEL_REFRESH_BTN = "button[title='Refresh Captcha'], a[ng-click*='captcha'], .captcha-refresh, [title*='Refresh']"
SEL_ERROR_MSG = ".alert-danger, .text-danger, .ng-scope .alert, #errorMsg, .error-message"

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
