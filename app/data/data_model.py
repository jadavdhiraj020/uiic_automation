"""
ClaimData — single source of truth passed through all automation modules.
All values are strings for easy form injection. Numeric fields default to "0".
"""
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class ClaimData:
    # ── Identification ────────────────────────────────────────────────────────
    claim_no: str = ""

    # ── Interim Report ────────────────────────────────────────────────────────
    type_of_settlement: str = "Partial Loss"
    date_of_survey: str = ""
    time_hh: str = "05"
    time_mm: str = "00"
    odometer: str = "0"
    place_of_survey: str = ""
    mobile_no: str = ""
    email_id: str = ""
    expected_completion_date: str = ""
    surveyor_observation: str = ""
    initial_loss_amount: str = "0"

    # ── Claim Assessment — Parts ──────────────────────────────────────────────
    parts_age_dep_excl_gst: str = "0"   # Metal parts (vehicle-age based, ~10%)
    parts_50_dep_excl_gst: str = "0"    # Rubber/plastic/tyre/battery (50%)
    parts_30_dep_excl_gst: str = "0"    # Fibre glass (30%)
    parts_nil_dep_excl_gst: str = "0"   # Glass parts (nil depreciation)

    # ── Claim Assessment — Labour ─────────────────────────────────────────────
    labour_excl_gst: str = "0"

    # ── Claim Assessment — Other Charges ─────────────────────────────────────
    workshop_invoice_no: str = ""
    workshop_invoice_date: str = ""
    towing_charges: str = "0"
    spot_repairs: str = "0"
    voluntary_excess: str = "0"
    compulsory_excess: str = "500"
    imposed_excess: str = "0"
    salvage_value: str = "0"

    # ── Invoice Details (separate from workshop invoice) ──────────────────────
    invoice_no: str = ""
    invoice_date: str = ""

    # ── Report Details ────────────────────────────────────────────────────────
    final_report_no: str = ""
    final_report_date: str = ""

    # ── Surveyor Charges ──────────────────────────────────────────────────────
    traveling_expenses: str = "0"
    professional_fee: str = "0"
    daily_allowance: str = "0"
    photo_charges: str = "0"
    total_claimed_amount: str = "0"

    # ── File Paths ────────────────────────────────────────────────────────────
    # Populated by folder_scanner.py
    # Key = Document Type string (matches doc_mapping.json)
    # Value = absolute file path
    claim_doc_files: Dict[str, str] = field(default_factory=dict)
    assessment_files: Dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        """Human-readable one-liner for UI preview."""
        return (
            f"Claim: {self.claim_no or 'N/A'} | "
            f"Survey: {self.date_of_survey or 'N/A'} | "
            f"Place: {self.place_of_survey or 'N/A'} | "
            f"Initial Loss: ₹{self.initial_loss_amount}"
        )
