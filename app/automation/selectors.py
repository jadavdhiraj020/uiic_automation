"""
selectors.py — Single source of truth for ALL confirmed element selectors.

VERIFIED 2026-04-18 via live DOM inspection of:
  https://portal.uiic.in/surveyor/data/Surveyor.html#/SurveyorClaimSurvey

Rules:
  - No iframe. All elements are on the main page.
  - #id selectors are primary (fastest, most stable).
  - Update ONLY this file when the portal changes — all modules auto-update.
"""

# ─────────────────────────────────────────────────────────────────────────────
# Worklist / Navigation
# VERIFIED: data-ng-model="claimType", placeholder="Claim No"
# ─────────────────────────────────────────────────────────────────────────────
WORKLIST = {
    "sidebar_link":   "a:has-text('Worklist'), li:has-text('Worklist') > a",
    "claim_type_dd":  "select[data-ng-model='claimType'], select[ng-model*='claimType']",
    "claim_type_val": "string:NONMARUTI",          # <option value="string:NONMARUTI">Non Maruti</option>
    "claim_no_input": "input[placeholder='Claim No'], input[ng-model*='claimNo']",
    "filter_btn":     "button:has-text('Filter')",
    "reset_btn":      "button:has-text('Reset')",
    "action_btn":     "button:has-text('Click Here'), a:has-text('Click Here')",
    "no_records":     "td:has-text('No Record')",
    "next_page":      "li.next:not(.disabled) a, a:has-text('Next')",
}

# ─────────────────────────────────────────────────────────────────────────────
# Tab selectors — VERIFIED: li.resp-tab-item contains the tabs
# Tab text (case-insensitive match): "interim", "documents", "assessment"
# ─────────────────────────────────────────────────────────────────────────────
TABS = {
    "interim":    {"text": "interim",    "index": 1},
    "documents":  {"text": "documents",  "index": 2},
    "assessment": {"text": "assessment", "index": 3},
}
TAB_SEL = "li.resp-tab-item, li[role='tab']"

# ─────────────────────────────────────────────────────────────────────────────
# Interim Report tab — VERIFIED IDs from live DOM
# ─────────────────────────────────────────────────────────────────────────────
INTERIM = {
    # Dropdowns
    "settlement_type":   "#settlementType",
    "time_hours":        "#surveyTimeHours",
    "time_minutes":      "#surveyTimeMinutes",
    # Text inputs
    "survey_date":       "#surveyDate",
    "odometer":          "#numOdoMeterReading",
    "place":             "#surveyPlace",
    "initial_loss":      "#initialLossAssAmt",
    "mobile":            "#claimantMobileNo",
    "email":             "#claimantEmailId",
    "repair_date":       "#repairCompleteDate",
    # Textarea
    "observation":       "#recommendation",
    # Radio buttons — confirmed name attributes, value always 'Y'
    "radio_vehicle":     "input[name='ynVehicleInspected'][value='Y']",
    "radio_survey_done": "input[name='ynSurveyCompleted'][value='Y']",
    "radio_dl_appl":     "input[name='ynDLApplicable'][value='Y']",
    "radio_dl_ver":      "input[name='ynDLVerified'][value='Y']",
    "radio_rc_book":     "input[name='ynRCBookVerified'][value='Y']",
}

# ─────────────────────────────────────────────────────────────────────────────
# Claim Documents tab — VERIFIED IDs from live DOM
# UPDATED 2026-04-20: Use proven name^= selectors from Doc_uploader.py
# ─────────────────────────────────────────────────────────────────────────────
DOCUMENTS = {
    # Verification radios (Y/N)
    "radio_rc_book":     "#rcBookVerified",
    "radio_damage":      "#relevantDamage",
    "radio_dl":          "#drivingLicense",
    # Payment option radio
    "radio_cashless":    "input[value='CASHLESS'], input[value='Cashless']",
    # Upload panel — scope all upload locators to this panel
    "upload_panel":      ".panel.panel-yellow",
    # Document upload rows — UPDATED: name^= selectors (proven in Doc_uploader.py)
    "doc_type_select":   "select[name^='docType'], select[ng-model='input.docType'], select#docType",
    "file_input":        "input[type='file'][name^='fileToUpload'], input[ng-model='input.fileToUpload'], input[type='file']",
    # Add Row — VERIFIED: clicking the <img> works directly (proven in Doc_uploader.py)
    # The plus button is inside: <a ng-click="addDocumentRow()"><img src="plus-4-xxl.png"></a>
    "add_row": (
        "img[src*='plus-4-xxl'], "
        "a[ng-click*='addDocumentRow'], "
        "a[ng-click*='addDocument'], "
        "a[ng-click*='addRow'], "
        "button[ng-click*='addDocument'], "
        "button[ng-click*='addRow'], "
        "button.btn-warning, "
        "a:has(img[src*='plus'])"
    ),
}

# ─────────────────────────────────────────────────────────────────────────────
# Claim Assessment tab — VERIFIED IDs from live DOM
# ─────────────────────────────────────────────────────────────────────────────
ASSESSMENT = {
    # Parts depreciation
    "age_dep":            "#ageBasedDep",
    "dep_50":             "#Dep50",
    "dep_30":             "#dep30",
    "nil_dep":            "#nilDep",
    # Labour
    "labour":             "#labourCharge",
    # GST (auto-calculated by portal, but may need manual 0 entry)
    "gst_parts":          "#gstOnParts",
    "gst_labour":         "#gstOnLabourCharge",
    # Workshop invoice — NOTE: capital W, I, N in WorkshopInvoiceNo
    "ws_invoice_no":      "#WorkshopInvoiceNo",
    "ws_invoice_date":    "#labourInvoiceDate",
    # Other charges
    "towing":             "#towingCharge, #towingCharges, input[ng-model*='towing']",
    "spot_repairs":       "#spotRepair, #spotRepairs, #spotRepairsAmt, input[ng-model*='spot']",
    "salvage":            "#salvageValue, #salvageAmt, input[ng-model*='salvage']",
    "vol_excess":         "#voluntaryExcess, #volExcess, input[ng-model*='voluntaryExcess']",
    "comp_excess":        "#compulsoryExcess, #compExcess, input[ng-model*='compulsoryExcess']",
    "imp_excess":         "#imposedExcess, #impExcess, input[ng-model*='imposed']",
    # Invoice (final)
    "invoice_no":         "#invoiceNo",
    "invoice_date":       "#invoiceDate",
    # Report
    "report_no":          "#reportNo",
    "report_date":        "#reportDate",
    # Surveyor charges — NOTE: profFeeAmount (not professionalFee)
    "prof_fee":           "#profFeeAmount",
    "travel":             "#travelExpense",
    "daily_allowance":    "#dailyAllowance",
    "photo":              "#photoCharge",
    "total":              "#totalClaimedAmt, #totalClaimAmt, #totalClaimed, #totalClaimedAmount, input[ng-model*='totalClaimed'], input[ng-model*='totalSurveyorCharges']",
    # Declaration
    "radio_declaration":  "input[name='ynPerused'][value='Y']",
    # Remarks
    "remarks":            "#remarks, #surveyor_remarks, #surveyorRemarks, textarea[ng-model*='remark'], textarea[name*='RemarksOffice'], textarea[name*='emarks']",
    # File uploads (5 fixed slots)
    "file_input":         "input[type='file']",
}

# Assessment file slot mapping: key → slot index (0-based nth)
ASSESSMENT_SLOTS = {
    "assessment_report":   0,
    "survey_report":       1,
    "estimate":            2,
    "invoice":             3,
    "reinspection_report": 4,
}
