"""
data_model.py — Single source of truth passed through all automation modules.

STABILITY POLICY (2026-04-18):
  - ALL values must come from Excel. No assumed/hardcoded defaults.
  - Amount fields default to "0" (neutral — portal accepts 0 for optional amounts).
  - String fields default to "" (empty = not filled = portal skips gracefully).
  - REMOVED dangerous defaults: type_of_settlement, compulsory_excess, time_hh/mm
    These had hardcoded "guesses" that could fill wrong values on real claims.

MULTI-PORTAL SUPPORT (2026-05-09):
  - ClaimData now holds fields for ALL supported portals.
  - validate() and all_fields_for_preview() are portal-aware via active portal registry.
  - UIIC fields are unchanged — 100% backward compatible.
  - New India fields are additive (new attributes with empty defaults).
"""
import logging
from datetime import date, datetime
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _parse_amount_for_total(value) -> int:
    """Parse an extracted amount into an integer rupee value for derived totals."""
    if value is None or str(value).strip() == "":
        return 0

    normalized = str(value).replace(",", "")
    matches = re.findall(r"-?\d+(?:\.\d+)?", normalized)
    if not matches:
        raise ValueError(f"No numeric value found in: {value!r}")

    try:
        return int(Decimal(matches[-1]))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid amount value: {value!r}") from exc


def _get_active_portal_id(override: Optional[str] = None) -> str:
    """Lazy import to avoid circular dependency."""
    if override:
        return override
    try:
        from app.portals.registry import get_active_portal_id
        return get_active_portal_id() or "uiic"
    except ImportError:
        return "uiic"


def clean_mobile_number(raw: Optional[str]) -> str:
    """
    Standardized, prefix-aware mobile number cleaning for all portals.
    1. Handles None and 'None' string inputs.
    2. Removes Excel float suffixes (.0).
    3. Strips out all non-digits.
    4. Finds the first 10-digit window starting with valid Indian mobile prefix (5, 6, 7, 8, 9).
    5. Falls back to the last 10 digits if a valid prefix-matching window is not found.
    """
    if raw is None:
        return ""
    s = str(raw).strip()
    if s.lower() == "none":
        return ""

    if re.match(r'^\d+\.0$', s):
        s = s[:-2]
    digits = re.sub(r"[^\d]", "", s)

    if len(digits) >= 10:
        # Check if the last 10 digits start with 5, 6, 7, 8, or 9
        last_10 = digits[-10:]
        if last_10[0] in "56789":
            return last_10
        # Search for first 10-digit sequence starting with 5, 6, 7, 8, or 9
        match = re.search(r"[56789]\d{9}", digits)
        if match:
            return match.group(0)

    return digits[-10:] if len(digits) >= 10 else digits


_clean_mobile_10 = clean_mobile_number


def _normalise_time(raw: str) -> str:
    """Normalize time to HH:MM (24-hour format) for Website 2."""
    s = str(raw).strip()
    # Check for AM/PM format first
    time_match = re.search(r"(\d{1,2})[.:\s]?(\d{2})?\s*([aA]\.?[mM]\.?|[pP]\.?[mM]\.?)", s)
    if time_match:
        h = int(time_match.group(1))
        m = time_match.group(2) or "00"
        ampm = time_match.group(3).replace(".", "").lower()
        if ampm == "pm" and h < 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        return f"{h:02d}:{int(m):02d}"
    
    # Check for direct HH:MM 24-hour format
    m24 = re.search(r"\b([01]?\d|2[0-3])[.:\s]([0-5]\d)\b", s)
    if m24:
        return f"{int(m24.group(1)):02d}:{int(m24.group(2)):02d}"
        
    # Fallback to standard regex match or first 5 chars
    m = re.match(r"(\d{1,2})[:\.\s](\d{2})", s)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return s[:5]


@dataclass
class ClaimData:
    # ── Identification ────────────────────────────────────────────────────────
    claim_no: str = ""
    payment_to: str = ""               # "REPAIRER" → Cashless, "INSURED" → Reimbursement

    # ── Interim Report ────────────────────────────────────────────────────────
    type_of_settlement: str = "Partial Loss"  # Default for non-TL motor claims.
                                               # Not in Excel — override via field_mapping if needed.
    date_of_survey: str = ""
    time_hh: str = ""                  # From Excel only.
    time_mm: str = ""                  # From Excel only.
    odometer: str = "0"
    place_of_survey: str = ""
    mobile_no: str = ""
    email_id: str = ""
    expected_completion_date: str = ""
    surveyor_observation: str = ""
    initial_loss_amount: str = ""      # Must come from Excel (NET PAYABLE)

    # ── Claim Assessment — Parts ──────────────────────────────────────────────
    parts_age_dep_excl_gst: str = "0"
    parts_50_dep_excl_gst: str = "0"
    parts_nil_dep_excl_gst: str = "0"
    nil_depreciation: str = ""
    parts_gst18_amount: str = "0"

    # ── Claim Assessment — Labour ─────────────────────────────────────────────
    labour_excl_gst: str = "0"

    # ── Claim Assessment — Other Charges ─────────────────────────────────────
    workshop_invoice_no: str = ""
    workshop_invoice_date: str = ""
    towing_charges: str = "0"
    spot_repairs: str = "0"
    voluntary_excess: str = "0"
    compulsory_excess: str = "0"       # From Excel only. Never assume "500"
    imposed_excess: str = "0"
    salvage_value: str = "0"

    # ── Invoice Details ───────────────────────────────────────────────────────
    invoice_no: str = ""
    invoice_date: str = ""

    # ── Report Details ────────────────────────────────────────────────────────
    final_report_no: str = ""
    final_report_date: str = ""

    # ── Internal Metadata ─────────────────────────────────────────────────────
    portal_id: str = "uiic"            # The portal this data was extracted for
    _excel_logs: List[str] = field(default_factory=list)
    _excel_coords: Dict[str, str] = field(default_factory=dict)

    # ── Surveyor Charges ──────────────────────────────────────────────────────
    traveling_expenses: str = "0"
    professional_fee: str = "0"
    daily_allowance: str = "0"
    photo_charges: str = "0"
    sfb_others: str = "0"               # NIA Survey Fee Bill "Others" amount
    total_claimed_amount: str = "0"

    # ── OIC Assessment of Loss ───────────────────────────────────────────────
    invoice_amount_without_gst: str = "0"
    invoice_gst_amount: str = "0"
    salvage_amount: str = "0"
    surveyor_license_number: str = ""
    surveyor_license_expiry_date: str = ""
    oicl_gst_number: str = ""
    surveyor_other_expenses: str = "0"

    # ── File Paths (from folder_scanner) ─────────────────────────────────────
    claim_doc_files: Dict[str, str] = field(default_factory=dict)
    assessment_files: Dict[str, str] = field(default_factory=dict)
    upload_doc_files: Dict[str, str] = field(default_factory=dict)  # DL, RC, Claim Form for doc upload section

    # ══════════════════════════════════════════════════════════════════════════
    # NEW INDIA ASSURANCE — Additional Fields
    # These are only populated when the New India portal is active.
    # They have no effect on UIIC workflow.
    # ══════════════════════════════════════════════════════════════════════════

    # ── Vehicle Details ───────────────────────────────────────────────────────
    registered_owner_name: str = ""
    vehicle_registration_number: str = ""
    date_of_registration: str = ""
    engine_no: str = ""
    chassis_no: str = ""
    physically_verified: str = ""
    vehicle_make: str = ""
    type_of_body: str = ""
    class_of_vehicle: str = ""
    pre_accident_condition: str = ""
    rto_name: str = ""
    odometer_reading: str = "0"
    vehicle_color: str = ""
    vehicle_color_type: str = ""
    type_of_vehicle: str = ""
    type_of_fuel: str = ""
    vehicle_details_matching_policy: str = ""
    vehicle_details_mismatch_remarks: str = ""  # Optional
    reference_no: str = ""  # Optional, under Registration Cert Details
    registered_laden_weight: str = ""  # Weight from Excel (in KG)

    # ── Accident Details ──────────────────────────────────────────────────────
    cause_nature_of_accident: str = ""
    vehicle_parked_during_accident: str = ""
    route_area_of_operation: str = ""    # Optional
    tax_paid_upto: str = ""              # Optional
    transfer_date: str = ""              # Optional

    # ── Driver Details ────────────────────────────────────────────────────────
    driver_relationship_with_insured: str = ""
    license_type_of_driver: str = ""
    dob_of_driver: str = ""
    driver_name: str = ""
    age_of_driver: str = ""
    is_license_valid: str = ""
    license_issuing_authority: str = ""
    driver_license_number: str = ""
    driver_license_issue_date: str = ""
    driver_license_expiry_date: str = ""
    badge_number: str = ""               # Optional
    charged_us_motor_vehicle_act: str = ""  # Optional
    charged_us_ipc: str = ""             # Optional

    # ── Survey Details ────────────────────────────────────────────────────────
    time_of_survey: str = ""

    # ── FIR Details ───────────────────────────────────────────────────────────
    fir_number: str = ""
    fir_date: str = ""
    police_station_name: str = ""        # Optional
    name_of_informant: str = ""          # Optional
    sections_of_law: str = ""            # Optional
    remarks: str = ""                    # Optional
    whether_driver_without_license: str = ""
    any_previous_police_records: str = "" # Optional
    is_there_any_tp_claim: str = ""

    # ── Bank Details ──────────────────────────────────────────────────────────
    bank_payment_to: str = ""
    ifsc_code: str = ""
    account_number: str = ""
    account_type: str = ""
    party_payment_method: str = ""

    # ── Assessment & Invoice (NIA-specific) ───────────────────────────────────
    approval_type: str = ""
    work_approval_date: str = ""
    work_approval_time: str = ""
    no_of_invoices: str = ""
    payment_invoice_in_name_of_nia: str = ""
    is_gst_applicable: str = ""
    vendor_invoice_date: str = ""
    vendor_invoice_number: str = ""
    primary_assessment: str = ""
    is_supplementary_estimate: str = ""
    painting_work_details: str = ""
    re_inspection_required: str = ""

    # ── Add-on Covers & Deductions (NIA) ──────────────────────────────────────
    nil_depreciation_amount: str = "0"
    engine_protect_amount: str = "0"
    consumable_items_amount: str = "0"
    key_protect_amount: str = "0"
    net_salvage: str = "0"               # Optional
    net_salvage_invoice_map: str = ""
    less_compulsory_excess: str = "0"
    less_voluntary_excess: str = "0"     # Optional
    less_imposed_excess: str = "0"       # Optional
    towing_additional_charges: str = "0" # Optional
    additional_towing_charges: str = "0" # Optional — separate from towing charges
    less_other_deductions: str = "0"     # Optional
    verification_checkbox: str = ""

    # ══════════════════════════════════════════════════════════════════════════
    # OIC (ORIENTAL INSURANCE) — Additional Fields
    # These are only populated when the OIC portal is active.
    # They have no effect on UIIC or NIA workflow.
    # ══════════════════════════════════════════════════════════════════════════

    # ── Vehicle Details (OIC) ─────────────────────────────────────────────────
    cubic_capacity: str = ""
    year_of_manufacture: str = ""
    unladen_weight: str = ""
    road_tax_paid_upto: str = ""
    seating_capacity: str = ""
    fitness_valid_upto: str = ""
    permit_number: str = ""
    type_of_permit: str = ""
    permit_valid_upto: str = ""
    authorization_number: str = ""
    validity_of_authorization: str = ""
    road_area_of_operation: str = ""

    # ── Loss Details (OIC) ────────────────────────────────────────────────────
    age_of_vehicle: str = ""
    date_of_accident: str = ""
    date_of_allotment: str = ""

    # ── Driver Details (OIC) ──────────────────────────────────────────────────
    driver_address: str = ""
    driver_city_state: str = ""      # Raw "City, State" from Excel — split at fill time
    driver_pin_code: str = ""
    badge_issue_date: str = ""       # Badge Issue Date — date field
    driver_qualification: str = ""   # Educational qualification of driver
    charges_filed: str = ""          # Any charges filed against driver

    # ── Workshop Details (OIC) ────────────────────────────────────────────────
    workshop_name: str = ""
    workshop_estimate_amount: str = ""
    workshop_estimate_date: str = ""
    gst_number: str = ""

    # ── Surveyor Details (OIC) ────────────────────────────────────────────────
    surveyor_name: str = ""
    surveyor_email: str = ""
    surveyor_mobile: str = ""
    surveyor_address: str = ""
    surveyor_pan: str = ""


    def calculate_derived_fields(self):
        """Calculate fields that are derived from other extracted values."""
        # 0. Clean and format mobile number & surveyor mobile number globally for all portals
        if self.mobile_no:
            self.mobile_no = _clean_mobile_10(self.mobile_no)
            self._excel_logs.append(f"  📊 mobile_no cleaned: '{self.mobile_no}'")

        if self.surveyor_mobile:
            self.surveyor_mobile = _clean_mobile_10(self.surveyor_mobile)
            self._excel_logs.append(f"  📊 surveyor_mobile cleaned: '{self.surveyor_mobile}'")

        # 1. Expected completion date aligns with date of survey
        if self.date_of_survey:
            self.expected_completion_date = self.date_of_survey
            self._excel_coords["expected_completion_date"] = self._excel_coords.get("date_of_survey", "")

        # 2. Total Claimed Amount (Sum of surveyor charges)
        try:
            calculated_total = 0
            invalid_values = []
            for key in ["traveling_expenses", "professional_fee", "daily_allowance", "photo_charges", "sfb_others"]:
                try:
                    calculated_total += _parse_amount_for_total(getattr(self, key, "0"))
                except ValueError:
                    invalid_values.append(f"{key}={getattr(self, key, '')!r}")

            if invalid_values:
                logger.warning(
                    "Invalid surveyor charge values while calculating total_claimed_amount: %s",
                    ", ".join(invalid_values),
                )

            self.total_claimed_amount = str(calculated_total)
            self._excel_coords["total_claimed_amount"] = "Calculated"
            self._excel_logs.append(f"  📊 total_claimed_amount: '{self.total_claimed_amount}' (Source: Calculated)")
        except Exception as exc:
            logger.warning("Failed to calculate total_claimed_amount: %s", exc)

        portal_id = _get_active_portal_id(self.portal_id)
        if portal_id == "newindia":
            # 3. Calculate Type of Vehicle based on Registered Laden Weight
            weight_str = self.registered_laden_weight or ""
            # Clean string: strip spaces, remove case-insensitive "kg", "kilogram", "kilograms"
            cleaned = re.sub(r'(?i)\bkg\b|\bkilograms?\b|\s', '', weight_str).strip()
            # Find any integer number in the cleaned string
            match = re.search(r'\d+', cleaned)
            if match:
                try:
                    weight_val = int(match.group(0))
                    if weight_val > 3000:
                        self.type_of_vehicle = "Goods Carrying (A)"
                    else:
                        self.type_of_vehicle = "Passenger Carrying (C)"
                    self._excel_coords["type_of_vehicle"] = "Derived from Registered Laden Weight"
                    self._excel_logs.append(f"  📊 type_of_vehicle: '{self.type_of_vehicle}' (Derived from Registered Laden Weight '{weight_str}')")
                except Exception as exc:
                    logger.warning("Failed to parse weight value %r: %s", weight_str, exc)
            else:
                if weight_str:
                    logger.warning("No numeric digits found in Registered Laden Weight: %r", weight_str)

            # 4. Calculate Age of Driver based on dob_of_driver
            if self.dob_of_driver:
                try:
                    dob_str = str(self.dob_of_driver).strip()
                    if dob_str:
                        # Find all groups of digits
                        parts = re.findall(r'\d+', dob_str)
                        if len(parts) >= 3:
                            if len(parts[0]) == 4:
                                birth_year = int(parts[0])
                                birth_month = int(parts[1])
                                birth_day = int(parts[2])
                            else:
                                birth_day = int(parts[0])
                                birth_month = int(parts[1])
                                birth_year = int(parts[2])
                            
                            today = date.today()
                            
                            age = today.year - birth_year
                            if (today.month, today.day) < (birth_month, birth_day):
                                age -= 1
                                
                            self.age_of_driver = str(age)
                            self._excel_coords["age_of_driver"] = "Calculated from Driver DOB"
                            self._excel_logs.append(f"  📊 age_of_driver: '{self.age_of_driver}' (Derived from DOB '{dob_str}')")
                except Exception as exc:
                    logger.warning("Failed to calculate age_of_driver from DOB %s: %s", self.dob_of_driver, exc)

            # 6. Normalize or construct time of survey for New India
            if self.time_of_survey:
                self.time_of_survey = _normalise_time(self.time_of_survey)
                self._excel_logs.append(f"  📊 time_of_survey normalized: '{self.time_of_survey}'")
            elif self.time_hh and self.time_mm:
                self.time_of_survey = f"{self.time_hh}:{self.time_mm}"
                self._excel_logs.append(f"  📊 time_of_survey derived: '{self.time_of_survey}' (Source: {self.time_hh}:{self.time_mm})")

        elif portal_id == "oic":
            # Calculate Age of Vehicle based on date_of_registration
            if self.date_of_registration:
                try:
                    reg_date_str = str(self.date_of_registration).strip()
                    accident_date_str = str(self.date_of_accident).strip()
                    if reg_date_str:
                        reg_date = None
                        clean_val = reg_date_str.split()[0]
                        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y"):
                            try:
                                reg_date = datetime.strptime(clean_val, fmt).date()
                                break
                            except ValueError:
                                continue
                        
                        accident_date = None
                        if accident_date_str and not re.match(r'^(NA|N/A|nil|none|-)$', accident_date_str, re.IGNORECASE):
                            clean_acc_val = accident_date_str.split()[0]
                            for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y"):
                                try:
                                    accident_date = datetime.strptime(clean_acc_val, fmt).date()
                                    break
                                except ValueError:
                                    continue
                        
                        # Use Date of Accident if available, otherwise fall back to today's date
                        end_date = accident_date if accident_date else date.today()
                        
                        if reg_date:
                            years = end_date.year - reg_date.year
                            months = end_date.month - reg_date.month
                            days = end_date.day - reg_date.day
                            if days < 0:
                                months -= 1
                            if months < 0:
                                years -= 1
                                months += 12
                            
                            self.age_of_vehicle = f"{years} years {months} months"
                            self._excel_coords["age_of_vehicle"] = "Calculated from Registration & Accident Date"
                            self._excel_logs.append(f"  📊 age_of_vehicle: '{self.age_of_vehicle}' (Derived from Registration Date '{reg_date_str}' vs Accident Date '{end_date}')")
                except Exception as exc:
                    logger.warning("Failed to calculate age_of_vehicle from Registration Date %s: %s", self.date_of_registration, exc)

            # Clean Year of Manufacture (keep only 4 digit year, e.g. 19xx or 20xx)
            if self.year_of_manufacture:
                try:
                    yom_str = str(self.year_of_manufacture).strip()
                    m = re.search(r'\b(19|20)\d{2}\b', yom_str)
                    if m:
                        self.year_of_manufacture = m.group(0)
                        self._excel_logs.append(f"  📊 year_of_manufacture cleaned: '{self.year_of_manufacture}' (extracted from '{yom_str}')")
                except Exception as exc:
                    logger.warning("Failed to clean year_of_manufacture %s: %s", self.year_of_manufacture, exc)

    def validate(self) -> Tuple[List[str], List[str]]:
        """
        Validate the claim data before automation starts.
        Returns (errors, warnings).
          errors   — critical missing values, automation should NOT start
          warnings — non-critical missing values, automation can proceed

        Portal-aware: returns different validation rules based on instance portal_id.
        """
        portal_id = _get_active_portal_id(self.portal_id)

        if portal_id == "newindia":
            return self._validate_newindia()
        elif portal_id == "oic":
            return self._validate_oic()
        else:
            return self._validate_uiic()

    def _validate_oic(self) -> Tuple[List[str], List[str]]:
        """
        OIC-portal validation.

        Two severity levels:
          errors   — hard blockers; automation will NOT start until resolved
          warnings — soft cautions; automation can proceed but output may be incomplete

        Sections validated (mirrors the 4 portal steps):
          1. Claim identity
          2. Interim Report fields (Step 3) — validated early as they are hard errors
          3. Vehicle details
          4. Workshop / estimate details
          5. Assessment of Loss financials
        """
        errors, warnings = [], []

        # ── 1. Claim identity ─────────────────────────────────────────────────
        if not self.claim_no or self.claim_no.strip() == "":
            errors.append("Claim Number is missing")

        # ── 2. Interim Report fields (Step 3) ─────────────────────────────────
        # Validated early (before Vehicle details) because these fields carry a
        # red asterisk (*) on the OIC portal — the portal will refuse to advance
        # to Step 4 without them. Failing fast here prevents the browser session
        # from starting only to halt silently halfway through the form.
        if not self.date_of_survey or str(self.date_of_survey).strip() == "":
            errors.append("Date of Survey is missing (required by OIC portal — Step 3)")
        if not self.place_of_survey or str(self.place_of_survey).strip() == "":
            errors.append("Place of Survey is missing (required by OIC portal — Step 3)")
        if not self.initial_loss_amount or str(self.initial_loss_amount).strip() == "":
            errors.append("Initial Loss Assessment Amount is missing (required by OIC portal — Step 3)")

        # Optional Interim Report fields — warn so the user can investigate.
        if not self.cause_nature_of_accident or str(self.cause_nature_of_accident).strip() == "":
            warnings.append("Cause and Nature of Accident not found in Excel — field will be skipped")
        if not self.mobile_no or str(self.mobile_no).strip() == "":
            warnings.append("Claimant Mobile Number not found in Excel — optional field will be skipped")
        if not self.email_id or str(self.email_id).strip() == "":
            warnings.append("Claimant Email ID not found in Excel — optional field will be skipped")


        # ── 3. Vehicle details ────────────────────────────────────────────────
        if not self.chassis_no:
            warnings.append("Chassis Number not found in Excel")
        if not self.engine_no:
            warnings.append("Engine Number not found in Excel")
        if not self.cubic_capacity:
            warnings.append("Cubic Capacity not found in Excel")

        # Validate year_of_manufacture if present
        if self.year_of_manufacture:
            year_str = str(self.year_of_manufacture).strip()
            year_match = re.search(r'\b\d{4}\b', year_str)
            if year_match:
                year_val = int(year_match.group(0))
                current_year = datetime.now().year
                if not (1900 <= year_val <= current_year + 1):
                    errors.append(f"Year of Manufacture '{year_str}' is invalid (must be between 1900 and {current_year + 1})")
            else:
                errors.append(f"Year of Manufacture '{year_str}' must be a valid 4-digit year")

        # Driver mandatory fields
        if not self.driver_name:
            warnings.append("Driver Name not found in Excel")
        if not self.driver_license_number:
            warnings.append("Driver License Number not found in Excel")

        # ── 4. Workshop / estimate details ────────────────────────────────────
        if not self.workshop_name:
            warnings.append("Workshop Name not found in Excel")
        if not self.workshop_estimate_amount:
            warnings.append("Workshop Estimate Amount not found in Excel")
        else:
            amt_str = re.sub(r'[^\d]', '', str(self.workshop_estimate_amount))
            if amt_str:
                amt_val = int(amt_str)
                # 10 Crores = 100,000,000 (10,00,00,000)
                if not (1000 <= amt_val <= 100000000):
                    errors.append(f"Workshop Estimate Amount '{self.workshop_estimate_amount}' must be between 1,000 and 10 Crores")
            else:
                errors.append(f"Workshop Estimate Amount '{self.workshop_estimate_amount}' is not a valid numeric amount")

        if not self.workshop_estimate_date:
            warnings.append("Workshop Estimate Date not found in Excel")
        # Invoice file check — required for assessment
        invoice_file = self.assessment_files.get("invoice", "")
        if not invoice_file or invoice_file.strip() == "":
            errors.append("Invoice File is missing")

        if not self.workshop_invoice_no:
            warnings.append("Workshop Invoice No not found in PDF")
        if not self.workshop_invoice_date:
            warnings.append("Workshop Invoice Date not found in PDF")
        if not self.claim_doc_files:
            warnings.append("No claim documents found in folder")

        # ── 5. Assessment of Loss financials ──────────────────────────────────
        try:
            inv_amt = _parse_amount_for_total(self.invoice_amount_without_gst)
            if not self.invoice_amount_without_gst or str(self.invoice_amount_without_gst).strip() == "":
                errors.append("Invoice Amount Without GST is missing")
        except ValueError:
            errors.append(f"Invoice Amount Without GST '{self.invoice_amount_without_gst}' is not a valid numeric amount")
            inv_amt = None

        try:
            inv_gst = _parse_amount_for_total(self.invoice_gst_amount)
            if not self.invoice_gst_amount or str(self.invoice_gst_amount).strip() == "":
                errors.append("Invoice GST Amount is missing")
        except ValueError:
            errors.append(f"Invoice GST Amount '{self.invoice_gst_amount}' is not a valid numeric amount")
            inv_gst = None

        if inv_amt is not None and inv_gst is not None:
            if inv_amt < inv_gst:
                errors.append(f"Invoice Amount Without GST (₹{inv_amt}) cannot be less than Invoice GST Amount (₹{inv_gst})")

        if not self.surveyor_license_number or str(self.surveyor_license_number).strip() == "":
            errors.append("Surveyor License Number is missing")
        if not self.surveyor_license_expiry_date or str(self.surveyor_license_expiry_date).strip() == "":
            errors.append("Surveyor License Expiry Date is missing")

        return errors, warnings


    def _validate_uiic(self) -> Tuple[List[str], List[str]]:
        """Original UIIC validation — completely unchanged."""
        errors, warnings = [], []

        # ── Critical from Excel (automation cannot proceed without these) ──────
        if not self.date_of_survey:
            errors.append("Date of Survey is missing")
        if not self.place_of_survey:
            errors.append("Place of Survey is missing")
        # L3 FIX: "0" is a valid amount (e.g. Total Loss cases). Only block if truly absent.
        if not self.initial_loss_amount or self.initial_loss_amount.strip() == "":
            errors.append("Initial Loss Amount is missing")
        if not self.final_report_no:
            errors.append("Final Report No is missing")
        if not self.total_claimed_amount or self.total_claimed_amount.strip() == "":
            errors.append("Total Claimed Amount is missing")

        # ── Warnings (non-blocking — skipped or handled gracefully) ───────────
        if not self.claim_no:
            warnings.append("Claim No not in Excel — enter in the Claim Number field above")
        if not self.type_of_settlement:
            warnings.append("Type of Settlement missing — will use 'Partial Loss' default")
        if not self.time_hh:
            warnings.append("Survey Time (HH) not set — field will be skipped")
        if not self.workshop_invoice_no:
            warnings.append("Workshop Invoice No not found in Excel")
        if not self.surveyor_observation:
            warnings.append("Surveyor Observation is empty")
        if not self.assessment_files:
            warnings.append("No assessment files found in folder")
        if not self.claim_doc_files:
            warnings.append("No claim documents found in folder")
        if not self.labour_excl_gst or self.labour_excl_gst == "0":
            warnings.append("Labour charges are zero — verify this is correct")

        return errors, warnings

    def _validate_newindia(self) -> Tuple[List[str], List[str]]:
        """New India validation — driven by mandatory field list."""
        errors, warnings = [], []

        # ── Mandatory fields — automation cannot proceed without these ─────────
        mandatory_checks = [
            ("claim_no",                       "Claim Number"),
            ("registered_owner_name",          "Registered Owner Name"),
            ("vehicle_registration_number",    "Vehicle Registration Number"),
            ("date_of_registration",           "Date of Registration"),
            ("engine_no",                      "Engine No"),
            ("chassis_no",                     "Chassis No"),
            ("vehicle_make",                   "Vehicle Make"),
            ("type_of_body",                   "Type of Body"),
            ("class_of_vehicle",               "Class of Vehicle"),
            ("rto_name",                       "RTO Name"),
            ("odometer_reading",               "Odometer Reading"),
            ("vehicle_color",                  "Vehicle Color"),
            ("registered_laden_weight",        "Registered Laden Weight"),
            ("type_of_vehicle",                "Type of Vehicle"),
            ("type_of_fuel",                   "Type of Fuel"),
            ("cause_nature_of_accident",       "Cause/Nature of Accident"),
            ("driver_name",                    "Driver Name"),
            ("dob_of_driver",                  "DOB of Driver"),
            ("age_of_driver",                  "Age of Driver"),
            ("driver_license_number",          "Driver License Number"),
            ("driver_license_issue_date",      "Driver License Issue Date"),
            ("driver_license_expiry_date",     "Driver License Expiry Date"),
            ("ifsc_code",                      "IFSC Code"),
            ("account_number",                 "Account Number"),
            ("vendor_invoice_date",            "Vendor/Tax Invoice Date"),
            ("vendor_invoice_number",          "Vendor/Tax Invoice Number"),
            ("primary_assessment",             "Primary Assessment"),
        ]

        for attr, label in mandatory_checks:
            # Skip validation errors for fields deferred to background OCR
            if attr in ("vendor_invoice_date", "vendor_invoice_number") and getattr(self, "_pending_invoice_ocr", False):
                continue
            if attr in ("ifsc_code", "account_number") and getattr(self, "_pending_cheque_ocr", False):
                continue

            val = getattr(self, attr, "")
            if not val or str(val).strip() in ("", "0"):
                # "0" is valid for amounts but NOT for text fields like names
                if attr in ("odometer_reading", "primary_assessment"):
                    if not val or str(val).strip() == "":
                        errors.append(f"{label} is missing")
                else:
                    errors.append(f"{label} is missing")

        # ── Warnings — optional fields that are nice to have ──────────────────
        optional_checks = [
            ("vehicle_details_mismatch_remarks", "Vehicle Details Mismatch Remarks"),
            ("route_area_of_operation",          "Route/Area of Operation"),
            ("tax_paid_upto",                    "Tax Paid Upto"),
            ("transfer_date",                    "Transfer Date"),
            ("badge_number",                     "Badge Number"),
            ("fir_number",                       "FIR Number"),
            ("fir_date",                         "FIR Date"),
            ("police_station_name",              "Police Station Name"),
            ("name_of_informant",                "Name of Informant"),
            ("net_salvage",                      "Net Salvage"),
            ("less_voluntary_excess",            "Voluntary Excess"),
            ("less_imposed_excess",              "Imposed Excess"),
            ("towing_additional_charges",        "Towing/Additional Charges"),
        ]

        for attr, label in optional_checks:
            val = getattr(self, attr, "")
            if not val or str(val).strip() in ("", "0"):
                warnings.append(f"{label} not found — optional")

        if not self.claim_doc_files:
            warnings.append("No claim documents found in folder")

        return errors, warnings

    def summary(self) -> str:
        """Human-readable one-liner for UI preview."""
        portal_id = _get_active_portal_id(self.portal_id)
        if portal_id == "newindia":
            return (
                f"Claim: {self.claim_no or 'N/A'} | "
                f"Owner: {self.registered_owner_name or '—'} | "
                f"Vehicle: {self.vehicle_registration_number or '—'} | "
                f"Assessment: ₹{self.primary_assessment or '—'}"
            )
        elif portal_id == "oic":
            return (
                f"Claim: {self.claim_no or 'N/A'} | "
                f"Invoice: {self.workshop_invoice_no or '—'}"
            )
        return (
            f"Claim: {self.claim_no or 'N/A'} | "
            f"Survey: {self.date_of_survey or '—'} | "
            f"Place: {self.place_of_survey or '—'} | "
            f"Initial Loss: ₹{self.initial_loss_amount or '—'}"
        )

    def all_fields_for_preview(self) -> List[Tuple[str, str, bool, str]]:
        """
        Returns list of (label, value, is_critical, source_coord) for UI preview table.
        is_critical=True means field is required for automation success.

        Portal-aware: returns different field sets based on instance portal_id.
        """
        portal_id = _get_active_portal_id(self.portal_id)

        if portal_id == "newindia":
            return self._preview_newindia()
        elif portal_id == "oic":
            return self._preview_oic()
        else:
            return self._preview_uiic()

    def _preview_oic(self) -> List[Tuple[str, str, bool, str]]:
        """OIC preview — Claim, Vehicle, Driver, Workshop details."""
        def _src(key: str) -> str:
            return self._excel_coords.get(key, "")

        # Extract variant dynamically for preview
        from app.portals.oic.automation.basic_details_module import _extract_variant
        variant = _extract_variant(self.vehicle_make)

        # State & City derived from driver_city_state
        from app.portals.oic.automation.basic_details_module import (
            _extract_state, _extract_city, _extract_pin_code, _is_owner_driver
        )
        state_fallback = _extract_state(self.driver_city_state)
        city_fallback = _extract_city(self.driver_city_state)
        pincode_fallback = _extract_pin_code(self.driver_address or self.place_of_survey or "")

        # Close Proximity and Nil Dep Cover derived/keyword
        from app.portals.oic.automation.basic_details_module import _resolve_loss_proximity, _resolve_nil_depreciation
        close_prox = "YES" if _resolve_loss_proximity(self.date_of_accident, self.date_of_allotment) else "NO"
        nil_dep = "YES" if _resolve_nil_depreciation(self.nil_depreciation) else "NO"

        return [
            # Claim Details
            ("Claim No",              self.claim_no,              True,  _src("claim_no")),
            ("Claim Type",            "Reimbursement" if "insured" in str(self.payment_to).lower() or "reimbursement" in str(self.payment_to).lower() else "Cashless",
                                                                  True,  _src("payment_to")),
            
            # Vehicle Details (all 24 fields)
            ("Registration No",       self.vehicle_registration_number, True, _src("vehicle_registration_number")),
            ("Make",                  self.vehicle_make,          True,  _src("vehicle_make")),
            ("Variant",               variant,                    False, "Derived from Make"),
            ("Registration Date",     self.date_of_registration,  False, _src("date_of_registration")),
            ("Year of Manufacture",   self.year_of_manufacture,   False, _src("year_of_manufacture")),
            ("Chassis No",            self.chassis_no,            True,  _src("chassis_no")),
            ("Engine No",             self.engine_no,             True,  _src("engine_no")),
            ("Cubic Capacity",        self.cubic_capacity,        True,  _src("cubic_capacity")),
            ("Type of Body",          self.type_of_body,          False, _src("type_of_body")),
            ("Class of Vehicle",      self.class_of_vehicle,      False, _src("class_of_vehicle")),
            ("Unladen Weight",        self.unladen_weight,        False, _src("unladen_weight")),
            ("Road Tax Paid Upto",    self.road_tax_paid_upto,    False, _src("road_tax_paid_upto")),
            ("Color of Vehicle",      self.vehicle_color,         False, _src("vehicle_color")),
            ("Type of Fuel",          self.type_of_fuel,          False, _src("type_of_fuel")),
            ("RTO",                   self.rto_name,              False, _src("rto_name")),
            ("Registered Laden Weight", self.registered_laden_weight, False, _src("registered_laden_weight")),
            ("Seating Capacity",      self.seating_capacity,      False, _src("seating_capacity")),
            ("Fitness Valid Upto",    self.fitness_valid_upto,     False, _src("fitness_valid_upto")),
            ("Permit Number",         self.permit_number,          False, _src("permit_number")),
            ("Type of Permit",        self.type_of_permit,         False, _src("type_of_permit")),
            ("Permit Valid Upto",     self.permit_valid_upto,      False, _src("permit_valid_upto")),
            ("Authorization Number",  self.authorization_number,   False, _src("authorization_number")),
            ("Validity of Auth",      self.validity_of_authorization, False, _src("validity_of_authorization")),
            ("Road/Area of Operation", self.road_area_of_operation, False, _src("road_area_of_operation")),


            # Loss Details
            ("Date of Accident",      self.date_of_accident,      False, _src("date_of_accident")),
            ("Date of Allotment",     self.date_of_allotment,     False, _src("date_of_allotment")),
            ("Close Proximity",       close_prox,                 False, "Calculated"),
            ("64VB Confirmed",        "YES",                      False, "Hardcoded"),
            ("Nil Depreciation Cover",nil_dep,                    False, _src("nil_depreciation")),
            ("Age of Vehicle",        self.age_of_vehicle,        False, _src("age_of_vehicle")),
            ("Loss Description",      "As per estimate",          False, "Hardcoded"),

            # Surveyor Details
            ("Name Of The Surveyor",  self.surveyor_name,         False, _src("surveyor_name")),
            ("Email ID",              self.surveyor_email,        False, _src("surveyor_email")),
            ("Mobile Number",         self.surveyor_mobile,       False, _src("surveyor_mobile")),
            ("Address",               self.surveyor_address,      False, _src("surveyor_address")),
            ("PAN Number",            self.surveyor_pan,          False, _src("surveyor_pan")),

            # Driver Details (all 19 fields)
            ("Driver Name",           self.driver_name,           True,  _src("driver_name")),
            ("Registered Owner Name", self.registered_owner_name, False, _src("registered_owner_name")),
            ("Date of Birth",         self.dob_of_driver,         True,  _src("dob_of_driver")),
            ("License Type",          self.license_type_of_driver,True,  _src("license_type_of_driver")),
            ("Valid From (DL Issue)",  self.driver_license_issue_date, True, _src("driver_license_issue_date")),
            ("Valid Up To (DL Expiry)",self.driver_license_expiry_date, True, _src("driver_license_expiry_date")),
            ("License Number",        self.driver_license_number, True,  _src("driver_license_number")),
            ("Badge Number",          self.badge_number,          False, _src("badge_number")),
            ("Badge Issue Date",      self.badge_issue_date,      False, _src("badge_issue_date")),
            ("Is Owner Driver?",      "YES" if _is_owner_driver(self.driver_name, self.registered_owner_name) else "NO", False, "Derived"),
            ("Qualification",         self.driver_qualification,  False, _src("driver_qualification")),
            ("Third Party Involved",  "NO",                       False, "Hardcoded"),
            ("Country",               "INDIA",                    True,  "Hardcoded"),
            ("State",                 state_fallback,             True,  _src("driver_city_state")),
            ("City",                  city_fallback,              True,  _src("driver_city_state") or "Derived"),
            ("Pincode",               self.driver_pin_code or pincode_fallback, True, _src("driver_pin_code") or "Derived from Address"),
            ("Address",               self.driver_address,        True,  _src("driver_address")),
            ("Charges Filed",         self.charges_filed,         False, _src("charges_filed")),

            # Workshop Details
            ("Workshop Name",         self.workshop_name,              True,  _src("workshop_name")),
            ("Estimate Amount",        self.workshop_estimate_amount,   True,  _src("workshop_estimate_amount")),
            ("Estimate Date",          self.workshop_estimate_date,     False, _src("workshop_estimate_date")),
            ("GST Number",             self.gst_number,                 False, _src("gst_number")),

            # ── Interim Report Details (Step 3) ─────────────────────────────
            # These fields are filled during the portal's Interim Report step.
            # They were previously hidden from the preview, meaning users could
            # not verify extraction before running automation.
            ("Date of Survey",        self.date_of_survey,             True,  _src("date_of_survey")),
            ("Place of Survey",       self.place_of_survey,            True,  _src("place_of_survey")),
            ("Surveyor Apptd Date",   self.date_of_allotment,          False, _src("date_of_allotment")),
            ("Initial Loss Amt (₹)",  self.initial_loss_amount,        True,  _src("initial_loss_amount")),
            ("Cause of Accident",     self.cause_nature_of_accident,   False, _src("cause_nature_of_accident")),
            ("Claimant Mobile",       self.mobile_no,                  False, _src("mobile_no")),
            ("Claimant Email",        self.email_id,                   False, _src("email_id")),
            ("Submission Date",       self.expected_completion_date or self.date_of_survey, False,
                                      _src("expected_completion_date") or _src("date_of_survey")),

            # Invoice Details
            ("Workshop Inv No",       self.workshop_invoice_no,   False, _src("workshop_invoice_no") or _src("vendor_invoice_number")),
            ("Workshop Inv Date",     self.workshop_invoice_date, False, _src("workshop_invoice_date") or _src("vendor_invoice_date")),

            # Assessment of Loss Details
            ("Inv Amt Without GST (₹)", self.invoice_amount_without_gst, True, _src("invoice_amount_without_gst")),
            ("Invoice GST Amt (₹)",   self.invoice_gst_amount,    True,  _src("invoice_gst_amount")),
            ("Voluntary Excess (₹)",  self.voluntary_excess,      False, _src("voluntary_excess")),
            ("Imposed Excess (₹)",    self.imposed_excess,        False, _src("imposed_excess")),
            ("Salvage Amount (₹)",     self.salvage_amount,        False, _src("salvage_amount")),
            ("Traveling Expenses (₹)", self.traveling_expenses,    False, _src("traveling_expenses")),
            ("Professional Fee (₹)",   self.professional_fee,      False, _src("professional_fee")),
            ("Daily Allowance (₹)",    self.daily_allowance,       False, _src("daily_allowance")),
            ("Photo Charges (₹)",      self.photo_charges,         False, _src("photo_charges")),
            ("Surveyor License No",   self.surveyor_license_number, True, _src("surveyor_license_number")),
            ("License Expiry Date",   self.surveyor_license_expiry_date, True, _src("surveyor_license_expiry_date")),
            ("OICL GST Number",        self.oicl_gst_number,       False, _src("oicl_gst_number")),
            ("Surveyor Other Exp (₹)", self.surveyor_other_expenses, False, _src("surveyor_other_expenses")),
        ]


    def _preview_uiic(self) -> List[Tuple[str, str, bool, str]]:
        """Original UIIC preview — completely unchanged."""
        def _src(key: str) -> str:
            return self._excel_coords.get(key, "")

        return [
            ("Claim No",              self.claim_no,              True,  _src("claim_no")),
            ("Payment Option",        "Cashless" if "repairer" in self.payment_to.lower() or not self.payment_to else "Reimbursement" if "insured" in self.payment_to.lower() else "—",
                                                                  True,  _src("payment_to")),
            ("Date of Survey",        self.date_of_survey,        True,  _src("date_of_survey")),
            ("Time of Survey",        f"{self.time_hh}:{self.time_mm}" if self.time_hh else "", False, _src("time_hh")),
            ("Place of Survey",       self.place_of_survey,       True,  _src("place_of_survey")),
            ("Mobile No",             self.mobile_no,             False, _src("mobile_no")),
            ("Email ID",              self.email_id,              False, _src("email_id")),
            ("Expected Compl. Date",  self.expected_completion_date, False, _src("expected_completion_date") or _src("date_of_survey")),
            ("Type of Settlement",    self.type_of_settlement,    True,  _src("type_of_settlement")),
            ("Odometer Reading",      self.odometer,              False, _src("odometer")),
            ("Initial Loss (₹)",      self.initial_loss_amount,   True,  _src("initial_loss_amount")),
            ("Parts Age Dep (₹)",     self.parts_age_dep_excl_gst, False, _src("parts_age_dep_excl_gst")),
            ("Parts 50% Dep (₹)",     self.parts_50_dep_excl_gst,  False, _src("parts_50_dep_excl_gst")),
            ("Parts Nil Dep (₹)",     self.parts_nil_dep_excl_gst, False, _src("parts_nil_dep_excl_gst")),
            ("Nil Depreciation",      self.nil_depreciation,       False, _src("nil_depreciation")),
            ("Parts GST 18% (₹)",     self.parts_gst18_amount,     False, _src("parts_gst18_amount")),
            ("Labour (₹)",            self.labour_excl_gst,        True,  _src("labour_excl_gst")),
            ("Workshop Inv No",       self.workshop_invoice_no,   False, _src("workshop_invoice_no")),
            ("Workshop Inv Date",     self.workshop_invoice_date, False, _src("workshop_invoice_date")),
            ("Towing Charges (₹)",    self.towing_charges,        False, _src("towing_charges")),
            ("Spot Repairs (₹)",      self.spot_repairs,          False, _src("spot_repairs")),
            ("Voluntary Excess (₹)",  self.voluntary_excess,      False, _src("voluntary_excess")),
            ("Compulsory Excess (₹)", self.compulsory_excess,     False, _src("compulsory_excess")),
            ("Imposed Excess (₹)",    self.imposed_excess,        False, _src("imposed_excess")),
            ("Salvage Value (₹)",     self.salvage_value,         False, _src("salvage_value")),
            ("Invoice No",            self.invoice_no,            False, _src("invoice_no")),
            ("Invoice Date",          self.invoice_date,          False, _src("invoice_date")),
            ("Report No",             self.final_report_no,       True,  _src("final_report_no")),
            ("Report Date",           self.final_report_date,     False, _src("final_report_date")),
            ("Travel Exp (₹)",        self.traveling_expenses,    False, _src("traveling_expenses")),
            ("Prof. Fee (₹)",         self.professional_fee,      False, _src("professional_fee")),
            ("Daily Allow. (₹)",      self.daily_allowance,       False, _src("daily_allowance")),
            ("Photo Charges (₹)",     self.photo_charges,         False, _src("photo_charges")),
            ("Observation",           self.surveyor_observation,  False, _src("surveyor_observation")),
        ]

    def _preview_newindia(self) -> List[Tuple[str, str, bool, str]]:
        """New India preview — organized by form sections."""
        def _src(key: str) -> str:
            return self._excel_coords.get(key, "")

        def _inv_val(val: str) -> str:
            if getattr(self, "_pending_invoice_ocr", False) and (not val or str(val).strip() in ("", "—")):
                return "Deferred (OCR in background)"
            return val or "—"

        def _inv_src(key: str) -> str:
            if getattr(self, "_pending_invoice_ocr", False) and (not getattr(self, key, None) or str(getattr(self, key, "")).strip() in ("", "—")):
                return "Deferred OCR"
            return _src(key)

        def _chk_val(val: str) -> str:
            if getattr(self, "_pending_cheque_ocr", False) and (not val or str(val).strip() in ("", "—")):
                return "Deferred (OCR in background)"
            return val or "—"

        def _chk_src(key: str) -> str:
            if getattr(self, "_pending_cheque_ocr", False) and (not getattr(self, key, None) or str(getattr(self, key, "")).strip() in ("", "—")):
                return "Deferred OCR"
            return _src(key)

        return [
            # ── Claim Details ───────────────────────────────
            ("Claim No",              self.claim_no,                 True,  _src("claim_no")),
            
            # ── Survey Details ──────────────────────────────
            ("Date of Survey",        self.date_of_survey,           True,  _src("date_of_survey")),
            ("Time of Survey",        self.time_of_survey,           True,  _src("time_of_survey")),
            ("Place of Survey",       self.place_of_survey,          True,  _src("place_of_survey")),
            ("Mobile No",             self.mobile_no,                True,  _src("mobile_no")),
            ("Email ID",              self.email_id,                 True,  _src("email_id")),

            # ── Vehicle Details ─────────────────────────────
            ("Owner Name",            self.registered_owner_name,    True,  _src("registered_owner_name")),
            ("Vehicle Reg No",        self.vehicle_registration_number, True, _src("vehicle_registration_number")),
            ("Date of Registration",  self.date_of_registration,     True,  _src("date_of_registration")),
            ("Engine No",             self.engine_no,                True,  _src("engine_no")),
            ("Chassis No",            self.chassis_no,               True,  _src("chassis_no")),
            ("Physically Verified",   self.physically_verified,      True,  _src("physically_verified")),
            ("Vehicle Make",          self.vehicle_make,             True,  _src("vehicle_make")),
            ("Type of Body",          self.type_of_body,             True,  _src("type_of_body")),
            ("Class of Vehicle",      self.class_of_vehicle,         True,  _src("class_of_vehicle")),
            ("Pre-Accident Cond.",    self.pre_accident_condition,   True,  _src("pre_accident_condition")),
            ("RTO Name",              self.rto_name,                 True,  _src("rto_name")),
            ("Odometer Reading",      self.odometer_reading,         True,  _src("odometer_reading")),
            ("Vehicle Color",         self.vehicle_color,            True,  _src("vehicle_color")),
            ("Color Type",            self.vehicle_color_type,       True,  _src("vehicle_color_type")),
            ("Laden Weight",          self.registered_laden_weight,  True,  _src("registered_laden_weight")),
            ("Type of Vehicle",       self.type_of_vehicle,          True,  _src("type_of_vehicle")),
            ("Type of Fuel",          self.type_of_fuel,             True,  _src("type_of_fuel")),
            ("Details Match Policy",  self.vehicle_details_matching_policy, True, _src("vehicle_details_matching_policy")),
            ("Reference No",          self.reference_no,             False, _src("reference_no")),
            ("Mismatch Remarks",      self.vehicle_details_mismatch_remarks, False, _src("vehicle_details_mismatch_remarks")),

            # ── Accident Details ────────────────────────────
            ("Cause of Accident",     self.cause_nature_of_accident, True,  _src("cause_nature_of_accident")),
            ("Vehicle Parked?",       self.vehicle_parked_during_accident, True, _src("vehicle_parked_during_accident")),
            ("Route/Area",            self.route_area_of_operation,  False, _src("route_area_of_operation")),
            ("Tax Paid Upto",         self.tax_paid_upto,            False, _src("tax_paid_upto")),
            ("Transfer Date",         self.transfer_date,            False, _src("transfer_date")),

            # ── Driver Details ──────────────────────────────
            ("Driver Name",           self.driver_name,              True,  _src("driver_name")),
            ("Driver DOB",            self.dob_of_driver,            True,  _src("dob_of_driver")),
            ("Driver Age",            self.age_of_driver,            True,  _src("age_of_driver")),
            ("Relation w/ Insured",   self.driver_relationship_with_insured, True, _src("driver_relationship_with_insured")),
            ("License Type",          self.license_type_of_driver,   True,  _src("license_type_of_driver")),
            ("License Valid?",        self.is_license_valid,         True,  _src("is_license_valid")),
            ("License Authority",     self.license_issuing_authority, True, _src("license_issuing_authority")),
            ("DL Number",             self.driver_license_number,    True,  _src("driver_license_number")),
            ("DL Issue Date",         self.driver_license_issue_date, True, _src("driver_license_issue_date")),
            ("DL Expiry Date",        self.driver_license_expiry_date, True, _src("driver_license_expiry_date")),
            ("Badge Number",          self.badge_number,             False, _src("badge_number")),
            ("Charged MV Act",        self.charged_us_motor_vehicle_act, False, _src("charged_us_motor_vehicle_act")),
            ("Charged IPC",           self.charged_us_ipc,           False, _src("charged_us_ipc")),

            # ── FIR Details ─────────────────────────────────
            ("FIR Number",            self.fir_number,               False, _src("fir_number")),
            ("FIR Date",              self.fir_date,                 False, _src("fir_date")),
            ("Police Station",        self.police_station_name,      False, _src("police_station_name")),
            ("Informant Name",        self.name_of_informant,        False, _src("name_of_informant")),
            ("Sections of Law",       self.sections_of_law,          False, _src("sections_of_law")),
            ("Remarks",               self.remarks,                  False, _src("remarks")),
            ("Driver Without License?",self.whether_driver_without_license, True, _src("whether_driver_without_license")),
            ("Previous Police Records?",self.any_previous_police_records, False, _src("any_previous_police_records")),
            ("Any TP Claim?",         self.is_there_any_tp_claim,    True,  _src("is_there_any_tp_claim")),

            # ── Bank Details ────────────────────────────────
            ("Payment To",            self.bank_payment_to or "Unknown",          True,  _src("bank_payment_to")),

            ("IFSC Code",             _chk_val(self.ifsc_code),      True,  _chk_src("ifsc_code")),
            ("Account Number",        _chk_val(self.account_number), True,  _chk_src("account_number")),
            ("Account Type",          _chk_val(self.account_type),   True,  _chk_src("account_type")),
            ("Payment Method",        self.party_payment_method,     True,  _src("party_payment_method")),

            # ── Invoice & Assessment ────────────────────────
            ("Approval Type",         self.approval_type,            True,  _src("approval_type")),
            ("Approval Date",         self.work_approval_date,       True,  _src("work_approval_date")),
            ("Approval Time",         self.work_approval_time,       True,  _src("work_approval_time")),
            ("No. of Invoices",       self.no_of_invoices,           True,  _src("no_of_invoices")),
            ("Invoice in NIA Name?",  self.payment_invoice_in_name_of_nia, True, _src("payment_invoice_in_name_of_nia")),
            ("GST Applicable?",       self.is_gst_applicable,        True,  _src("is_gst_applicable")),
            ("Invoice Date",          _inv_val(self.vendor_invoice_date), True, _inv_src("vendor_invoice_date")),
            ("Invoice Number",        _inv_val(self.vendor_invoice_number), True, _inv_src("vendor_invoice_number")),
            ("Primary Assessment (₹)",self.primary_assessment,       True,  _src("primary_assessment")),
            ("Supplementary Est.?",   self.is_supplementary_estimate, True, _src("is_supplementary_estimate")),
            ("Painting Details",      self.painting_work_details,    True,  _src("painting_work_details")),
            ("Re-Inspection Req?",    self.re_inspection_required,   True,  _src("re_inspection_required")),

            # ── Add-on Covers & Deductions ──────────────────
            ("Nil Dep Amount (₹)",    self.nil_depreciation_amount,  True,  _src("nil_depreciation_amount")),
            ("Engine Protect (₹)",    self.engine_protect_amount,    True,  _src("engine_protect_amount")),
            ("Consumables (₹)",       self.consumable_items_amount,  True,  _src("consumable_items_amount")),
            ("Key Protect (₹)",       self.key_protect_amount,       True,  _src("key_protect_amount")),
            ("Net Salvage (₹)",       self.net_salvage,              False, _src("net_salvage")),
            ("Salvage Invoice Map",   self.net_salvage_invoice_map,  True,  _src("net_salvage_invoice_map")),
            ("Compulsory Excess (₹)", self.less_compulsory_excess,   True,  _src("less_compulsory_excess")),
            ("Voluntary Excess (₹)",  self.less_voluntary_excess,    False, _src("less_voluntary_excess")),
            ("Imposed Excess (₹)",    self.less_imposed_excess,      False, _src("less_imposed_excess")),
            ("Towing Charges (₹)",    self.towing_additional_charges, False, _src("towing_additional_charges")),
            ("Addl. Towing (₹)",      self.additional_towing_charges, False, _src("additional_towing_charges")),
            ("Other Deductions (₹)",   self.less_other_deductions,     False, _src("less_other_deductions")),
            ("Verification",          self.verification_checkbox,    True,  _src("verification_checkbox")),

            # ── Survey Fee Bill ─────────────────────────────
            ("SFB Invoice Number",    _inv_val(self.vendor_invoice_number), True, _inv_src("vendor_invoice_number")),
            ("SFB Invoice Date",      _inv_val(self.vendor_invoice_date), True, _inv_src("vendor_invoice_date")),
            ("Professional Fee (₹)",  self.professional_fee,         False, _src("professional_fee")),
            ("Photos Amount (₹)",     self.photo_charges,            False, _src("photo_charges")),
            ("Conveyance Amount (₹)", self.traveling_expenses,       False, _src("traveling_expenses")),
            ("Others (₹)",            self.sfb_others,               False, _src("sfb_others")),
        ]
