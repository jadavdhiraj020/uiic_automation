from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class WorkflowPhase:
    id: str
    label: str


@dataclass(frozen=True)
class FieldGroup:
    id: str
    label: str
    labels: List[str]


@dataclass(frozen=True)
class PortalUiMetadata:
    portal_id: str
    phases: List[WorkflowPhase]
    field_groups: List[FieldGroup]


_UIIC_METADATA = PortalUiMetadata(
    portal_id="uiic",
    phases=[
        WorkflowPhase("login", "Login"),
        WorkflowPhase("navigate", "Navigate to Claim"),
        WorkflowPhase("interim_report", "Interim Report"),
        WorkflowPhase("claim_documents", "Claim Documents"),
        WorkflowPhase("claim_assessment", "Claim Assessment"),
        WorkflowPhase("complete", "Complete"),
    ],
    field_groups=[
        FieldGroup(
            "claim",
            "Claim & Survey",
            [
                "Claim No",
                "Payment Option",
                "Date of Survey",
                "Time of Survey",
                "Place of Survey",
                "Mobile No",
                "Email ID",
                "Expected Compl. Date",
                "Type of Settlement",
                "Odometer Reading",
                "Observation",
            ],
        ),
        FieldGroup(
            "assessment",
            "Assessment Amounts",
            [
                "Initial Loss (₹)",
                "Parts Age Dep (₹)",
                "Parts 50% Dep (₹)",
                "Parts Nil Dep (₹)",
                "Nil Depreciation",
                "Parts GST 18% (₹)",
                "Labour (₹)",
                "Towing Charges (₹)",
                "Spot Repairs (₹)",
                "Voluntary Excess (₹)",
                "Compulsory Excess (₹)",
                "Imposed Excess (₹)",
                "Salvage Value (₹)",
            ],
        ),
        FieldGroup(
            "invoice_report",
            "Invoice & Report",
            [
                "Workshop Inv No",
                "Workshop Inv Date",
                "Invoice No",
                "Invoice Date",
                "Report No",
                "Report Date",
            ],
        ),
        FieldGroup(
            "surveyor_charges",
            "Surveyor Charges",
            [
                "Travel Exp (₹)",
                "Prof. Fee (₹)",
                "Daily Allow. (₹)",
                "Photo Charges (₹)",
            ],
        ),
    ],
)


_NEWINDIA_METADATA = PortalUiMetadata(
    portal_id="newindia",
    phases=[
        WorkflowPhase("login", "Login"),
        WorkflowPhase("navigate", "Navigate to Claim"),
        WorkflowPhase("quick_update", "Quick Update"),
        WorkflowPhase("vehicle_photo", "Vehicle Photo"),
        WorkflowPhase("registration", "Registration Certificate"),
        WorkflowPhase("driver", "Driver Details"),
        WorkflowPhase("fir", "FIR Details"),
        WorkflowPhase("neft", "NEFT Details"),
        WorkflowPhase("work_approval", "Work Approval"),
        WorkflowPhase("claim_assessment", "Claim Assessment"),
        WorkflowPhase("document_upload", "Document Upload"),
        WorkflowPhase("manual_review", "Manual Review"),
    ],
    field_groups=[
        FieldGroup(
            "claim_survey",
            "Claim & Survey",
            [
                "Claim No",
                "Date of Survey",
                "Time of Survey",
                "Place of Survey",
                "Mobile No",
                "Email ID",
            ],
        ),
        FieldGroup(
            "vehicle",
            "Vehicle Details",
            [
                "Owner Name",
                "Vehicle Reg No",
                "Date of Registration",
                "Engine No",
                "Chassis No",
                "Physically Verified",
                "Vehicle Make",
                "Model",
                "Type of Body",
                "Class of Vehicle",
                "Pre-Accident Cond.",
                "RTO Name",
                "Odometer Reading",
                "Vehicle Color",
                "Color Type",
                "Type of Vehicle",
                "Type of Fuel",
                "Details Match Policy",
                "Reference No",
                "Mismatch Remarks",
            ],
        ),
        FieldGroup(
            "accident_driver_fir",
            "Accident, Driver & FIR",
            [
                "Cause of Accident",
                "Vehicle Parked?",
                "Route/Area",
                "Tax Paid Upto",
                "Transfer Date",
                "Driver Name",
                "Driver DOB",
                "Driver Age",
                "Relation w/ Insured",
                "License Type",
                "License Valid?",
                "License Authority",
                "DL Number",
                "DL Issue Date",
                "DL Expiry Date",
                "Badge Number",
                "Charged MV Act",
                "Charged IPC",
                "FIR Number",
                "FIR Date",
                "Police Station",
                "Informant Name",
                "Sections of Law",
                "Remarks",
                "Driver Without License?",
                "Previous Police Records?",
                "Any TP Claim?",
            ],
        ),
        FieldGroup(
            "bank",
            "Bank Details",
            [
                "Payment To",
                "IFSC Code",
                "Bank Name",
                "Branch Name",
                "Bank Address",
                "Account Number",
                "Account Type",
                "Payment Method",
            ],
        ),
        FieldGroup(
            "invoice_assessment",
            "Invoice & Assessment",
            [
                "Approval Type",
                "Approval Date",
                "Approval Time",
                "No. of Invoices",
                "Invoice in NIA Name?",
                "GST Applicable?",
                "Invoice Date",
                "Invoice Number",
                "Primary Assessment (₹)",
                "Supplementary Est.?",
                "Painting Details",
                "Re-Inspection Req?",
            ],
        ),
        FieldGroup(
            "deductions",
            "Add-ons & Deductions",
            [
                "Nil Dep Amount (₹)",
                "Engine Protect (₹)",
                "Consumables (₹)",
                "Key Protect (₹)",
                "Net Salvage (₹)",
                "Salvage Invoice Map",
                "Compulsory Excess (₹)",
                "Voluntary Excess (₹)",
                "Imposed Excess (₹)",
                "Towing Charges (₹)",
                "Addl. Towing (₹)",
                "Other Deductions (₹)",
                "Verification",
            ],
        ),
    ],
)


_METADATA: Dict[str, PortalUiMetadata] = {
    _UIIC_METADATA.portal_id: _UIIC_METADATA,
    _NEWINDIA_METADATA.portal_id: _NEWINDIA_METADATA,
}


def get_portal_ui_metadata(portal_id: str | None) -> PortalUiMetadata:
    return _METADATA.get(portal_id or "uiic", _UIIC_METADATA)
