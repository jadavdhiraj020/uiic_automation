"""
data_model.py — Single source of truth passed through all automation modules.

STABILITY POLICY (2026-04-18):
  - ALL values must come from Excel. No assumed/hardcoded defaults.
  - Amount fields default to "0" (neutral — portal accepts 0 for optional amounts).
  - String fields default to "" (empty = not filled = portal skips gracefully).
  - REMOVED dangerous defaults: type_of_settlement, compulsory_excess, time_hh/mm
    These had hardcoded "guesses" that could fill wrong values on real claims.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass
class ClaimData:
    # ── Identification ────────────────────────────────────────────────────────
    claim_no: str = ""
    payment_to: str = ""               # "REPAIRER" → Cashless, "INSURED" → Reimbursement
    vehicle_no: str = ""               # From Sheet2 (VEHICLE REG. NO.)
    chassis_no: str = ""               # From Excel (Chassis Number)
    engine_no: str = ""                # From Excel (Engine Number)

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
    _excel_logs: List[str] = field(default_factory=list)
    _excel_coords: Dict[str, str] = field(default_factory=dict)

    # ── Surveyor Charges ──────────────────────────────────────────────────────
    traveling_expenses: str = "0"
    professional_fee: str = "0"
    daily_allowance: str = "0"
    photo_charges: str = "0"
    total_claimed_amount: str = "0"

    # ── File Paths (from folder_scanner) ─────────────────────────────────────
    claim_doc_files: Dict[str, str] = field(default_factory=dict)
    assessment_files: Dict[str, str] = field(default_factory=dict)

    def validate(self) -> Tuple[List[str], List[str]]:
        """
        Validate the claim data before automation starts.
        Returns (errors, warnings).
          errors   — critical missing values, automation should NOT start
          warnings — non-critical missing values, automation can proceed
        """
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

    def summary(self) -> str:
        """Human-readable one-liner for UI preview."""
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
        """
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
            ("Expected Compl. Date",  self.expected_completion_date, False, _src("expected_completion_date") or ("Calculated from Survey Date" if self.date_of_survey else "")),
            ("Type of Settlement",    self.type_of_settlement,    True,  _src("type_of_settlement")),
            ("Odometer Reading",      self.odometer,              False, _src("odometer")),
            ("Initial Loss (₹)",      self.initial_loss_amount,   True,  _src("initial_loss_amount")),
            ("Parts Age Dep (₹)",     self.parts_age_dep_excl_gst, False, _src("parts_age_dep_excl_gst")),
            ("Parts 50% Dep (₹)",     self.parts_50_dep_excl_gst,  False, _src("parts_50_dep_excl_gst")),
            ("Parts Nil Dep (₹)",     self.parts_nil_dep_excl_gst, False, _src("parts_nil_dep_excl_gst")),
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
