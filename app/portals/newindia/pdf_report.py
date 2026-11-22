"""New India Assurance PDF-only survey report intake, fee-bill supplementing, and advisory review."""

from collections import defaultdict
from dataclasses import replace
from datetime import datetime
import hashlib
from pathlib import Path
import re
from typing import Optional

from app.data.data_model import ClaimData, clean_mobile_number
from app.data.pdf_report_reader import DATE_RX, EMAIL_RX, MOBILE_RX, extract_time, read_lines
from app.portals.newindia.field_values import normalize_driver_license_number, normalize_vehicle_color
from app.portals.newindia.pdf_assessment import amount, read_newindia_pdf_assessment
from app.portals.newindia.scan_outputs import is_scan_output
from app.portals.oic.pdf_layout import Line, compact, read_pages
from app.utils import load_automation_defaults, load_field_mapping


REPORT_HEADING = re.compile(
    r"\b(?:"
    r"final\s+(?:motor\s+)?survey"
    r"|(?:motor\s+(?:od\s+)?)?(?:final\s+)?survey\s+(?:and\s+assessment|assessment)"
    r"|(?:motor\s+(?:od\s+)?)?final\s+survey"
    r"|(?:private\s*(?:&|and)\s*confidential\s+)?survey"
    r")\s+report\b",
    re.I,
)
SUPPORTING_REPORT_HEADING = re.compile(
    r"^(?:private|confidential|motor|vehicle|od|final)*"
    r"(?:reinspection(?:survey)?|spotsurvey|supplementarysurvey)report"
)
REGISTRATION = re.compile(r"^([A-Z]{2}\s*\d{1,2}\s*[A-Z]{0,3}\s*\d{1,4})(?=$|[\s,;/])", re.I)
BH_REGISTRATION = re.compile(r"^(\d{2}\s*BH\s*\d{4}\s*[A-Z]{1,2})(?=$|[\s,;/])", re.I)
IDENTIFIER = re.compile(r"^[A-Z0-9][A-Z0-9/*._-]*", re.I)
IFSC_RX = re.compile(r"\b([A-Z]{4}0[A-Z0-9]{6})\b", re.I)
ACCOUNT_NO_RX = re.compile(r"\b(\d{9,20})\b")
SURVEYOR_EXPIRY_LABEL = re.compile(r"(?<![A-Za-z])(?:expiry|expirey|expires|valid\s*until)\s*[:.-]?\s*", re.I)
PLACEHOLDERS = {"", "na", "nil", "none", "notapplicable", "notavailable", "nana"}
MIN_FIELD_CONFIDENCE = 0.84

SECTION_PATTERNS = (
    ("insured", r"insured\b(?!\s+vehicle)"),
    ("vehicle", r"(?:vehicle|registration)\s+(?:particulars|details)\b"),
    ("driver", r"driver(?:'s|s)?\s+(?:particulars|details)\b"),
    ("accident", r"accident\s+(?:history|particulars|details)\b"),
    ("survey", r"(?:details?\s+of\s+survey|survey\s+(?:details|particulars))\b"),
    ("workshop", r"(?:place\s+of\s+survey|workshop\s+details|repairer\s+details)\s*[:.]?$"),
    ("fir", r"(?:fir\s+details?|police\s+report|police\s+particulars)\b"),
    ("bank", r"(?:bank\s+details|neft\s+details|payment\s+details)\b"),
    ("work_approval", r"(?:work\s+approval\s+details|delivery\s+order\s+details)\b"),
    ("cause", r"(?:cause\s+(?:and|&)\s+nature|nature|cause)\s+of\s+accident\b"),
    ("notes", r"(?:observations?|comments?|notes|injury/third\s+party\s+loss)\b"),
    ("assessment", r"(?:details?\s+of\s+assessment|assessment\s+of\s+loss|summary\s+of\s+assessment|parts\s+details|add-?on\s+cover)\b"),
    ("fees", r"(?:(?:surveyor(?:'s)?|survey|professional|sf)\s+fee\s+bill|bill\s+of\s+survey\s+fees|final\s+survey\s+bill)\b"),
)
SECTIONS = tuple(
    (section, re.compile(r"^(?:\d{1,2}[.)]?\s*)?" + expression.replace(r"\s+", r"\s*"), re.I))
    for section, expression in SECTION_PATTERNS
)

FIELDS = {
    "header": {
        "claim_no": ("Claim No", "Claim Number", "Claim Reference", "Claim #"),
        "policy_number": ("Cover Note/Policy No", "Policy No", "Policy Number"),
        "reference_no": ("Reference No", "Ref. No", "Ref No"),
        "mobile_no": ("Surveyor Mobile", "Mobile No", "Mobile", "Mob"),
        "email_id": ("Surveyor Email", "Email ID", "E-mail", "Email"),
    },
    "insured": {
        "registered_owner_name": ("Name of Regd Owner as per RC", "Registered Owner Name", "Owner Name", "Name of Owner", "Insured Name", "NAME OF INSURED", "Insured"),
    },
    "vehicle": {
        "registered_owner_name": ("Name of Regd Owner as per RC", "Name of Registered Owner", "Registered Owner Name", "Owner Name"),
        "vehicle_registration_number": ("Registration No / RTO", "Vehicle Registration Number", "Registration No", "Regn No", "Vehicle No"),
        "date_of_registration": ("Date of Registration issue", "Date of Registration", "Registration Date", "Regn Date"),
        "chassis_no": ("Chassis No", "Chassis Number", "Ch No"),
        "engine_no": ("Engine No", "Engine Number", "Eng No"),
        "vehicle_make": ("Make & Year of Manufacturer", "Make & Model", "Make and Model", "Make / Model", "Vehicle Make", "Make of Vehicle", "Make"),
        "class_of_vehicle": ("Class of Vehicle", "Vehicle Class"),
        "rto_name": ("RTO Name", "RTO Office", "Registering Authority", "Registration Authority"),
        "odometer_reading": ("Odometer Reading", "Odometer", "KM Reading", "Mileage"),
        "vehicle_color": ("Vehicle Color", "Vehicle Colour", "Color of Vehicle", "Colour", "Color"),
        "vehicle_color_type": ("Vehicle Color Type", "Color Type", "Colour Type"),
        "registered_laden_weight": ("Registered Laden Weight", "Laden Weight (KG)", "Laden Weight", "Weight (KG)", "GVW"),
        "unladen_weight": ("Unladen Weight", "Unladen Wt", "Unladen Weight (KG)", "ULW"),
        "fitness_cert_no": ("Fitness Cert. No.", "Fitness Cert.No.", "Fitness Cert No", "Fitness Certificate No", "Fitness Certificate Number", "Fitness No"),
        "fitness_valid_upto": ("Fitness Cert. Valid Upto", "Fitness Valid Upto", "Fitness Valid Up to", "Fitness Certificate Valid Upto", "Fitness Upto"),
        "permit_number": ("Permit No.", "Permit No", "Permit Number"),
        "permit_valid_upto": ("Permit Valid Upto", "Permit Valid Up to", "Permit Upto"),
        "type_of_vehicle": ("Type of Vehicle", "Vehicle Type"),
        "type_of_fuel": ("Type of Fuel", "Fuel Used", "Fuel Type", "Fuel"),
        "route_area_of_operation": ("Route/Area of Operation", "Route / Area of Operation", "Area of Operation"),
        "tax_paid_upto": ("Tax Paid Upto", "Tax Paid Up to", "Road Tax Paid Upto"),
        "transfer_date": ("Transfer Date", "Date of Transfer"),
        "physically_verified": ("Physically Verified", "Physical Verification"),
        "vehicle_details_matching_policy": ("Whether Vehicle Details are matching", "Vehicle Details matching", "Details matching with policy"),
        "vehicle_details_mismatch_remarks": ("Vehicle Details Mismatch Remarks", "Mismatch Remarks"),
    },
    "driver": {
        "driver_name": ("Name of Driver", "Driver Name", "Name of the Driver"),
        "dob_of_driver": ("DOB of Driver", "Driver DOB", "Date of Birth of Driver", "Driver Date of Birth", "Date of Birth", "DOB"),
        "driver_relationship_with_insured": ("Relationship of the driver with the Insured", "Relationship of driver with insured", "Driver Relationship", "Relation with Insured", "Relationship with Insured"),
        "license_type_of_driver": ("License Type of Driver", "Type of Licence", "Type of License", "License Type", "DL Type"),
        "is_license_valid": ("Is the motor driving license valid", "License Valid", "DL Valid"),
        "license_issuing_authority": ("License Issuing Authority", "Licence Issuing Authority", "DL Issuing Authority", "Issuing Authority"),
        "driver_license_number": ("Driver Driving License Number", "Motor Driver License Number", "Driving Licence Number", "Driving License Number", "M.D.L. No", "MDL No", "DL Number", "DL No", "Licence No", "License No"),
        "driver_license_issue_date": ("Driver Driving License Issue Date", "DL Issue Date", "Licence Issue Date", "License Issue Date", "Date of Issue", "Date of lssue"),
        "driver_license_expiry_date": ("Driver Driving License Expiry Date", "DL Expiry Date", "Licence Expiry Date", "License Expiry Date", "License Valid Till", "Valid Till", "Valid Upto", "Valid Up To"),
        "badge_number": ("Badge Number", "Badge No"),
        "charged_us_motor_vehicle_act": ("Charged U/S Motor Vehicle Act", "Charged under MV Act"),
        "charged_us_ipc": ("Charged U/S IPC", "Charged under IPC"),
    },
    "survey": {
        "date_of_survey": ("Date and Time of Survey", "Date & Time of Survey", "Date of Survey", "Survey Date"),
        "time_of_survey": ("Time of Survey", "Survey Time"),
        "place_of_survey": ("Place of Survey", "Survey Location", "Inspection Place"),
    },
    "accident": {
        "vehicle_parked_during_accident": ("Was the vehicle parked", "Vehicle parked during accident"),
    },
    "fir": {
        "fir_number": ("FIR Number", "FIR No", "F.I.R. No"),
        "fir_date": ("FIR Date", "Date of FIR", "F.I.R. Date"),
        "police_station_name": ("Police Station Name", "Police Station", "PS Name"),
        "name_of_informant": ("Name of the Informant", "Informant Name"),
        "sections_of_law": ("Sections of Law", "Section of Law"),
        "any_previous_police_records": ("Any Previous Police Records", "Previous Police Record"),
        "is_there_any_tp_claim": ("Is there any TP claim", "Any TP Claim", "TP Claim", "Details Of Third Party Loss"),
    },
    "bank": {
        "ifsc_code": ("IFSC Code", "IFS Code", "IFSC"),
        "account_number": ("Account Number", "Account No", "A/C No", "Acct No"),
        "account_type": ("Account Type", "A/C Type", "Type of Account"),
        "party_payment_method": ("Party Payment Method", "Payment Method", "Mode of Payment"),
    },
    "work_approval": {
        "approval_type": ("Approval Type", "Type of Approval"),
        "work_approval_date": ("Work Approval Date", "Approval Date"),
        "work_approval_time": ("Work Approval Time", "Approval Time"),
        "no_of_invoices": ("No of invoices available", "Number of Invoices", "No. of Invoices"),
        "delivery_order_date": ("Delivery Order Date",),
        "delivery_order_time": ("Delivery Order Time",),
    },
    "assessment": {
        "primary_assessment": ("Primary Assessment", "Net Payable Amount", "Net Liability", "Net Payable", "Assessment Amount"),
        "painting_work_details": ("Painting work details", "Painting Details", "Painting Work"),
        "nil_depreciation_amount": ("Nil Depreciation (Zero Dep) Amount", "Zero Dep Amount", "Nil Depreciation Amount"),
        "engine_protect_amount": ("Engine Protect Extension Amount", "Engine Protect Amount", "Engine Protection"),
        "consumable_items_amount": ("Consumable Items Amount", "Consumables Amount", "Consumable"),
        "key_protect_amount": ("Key Protect Amount", "Key Protection Amount"),
        "net_salvage": ("Net Salvage", "Less Salvage Value", "Salvage Value", "Salvage"),
        "less_compulsory_excess": ("Less Compulsory Excess", "Compulsory Excess", "Coumpulsary excess", "Less Excess Clause", "Less Excess"),
        "less_voluntary_excess": ("Less Voluntary Excess", "Voluntary Excess", "voluntry excess"),
        "less_imposed_excess": ("Less Imposed Excess", "Imposed Excess"),
        "towing_additional_charges": ("Towing / Additional Towing Charges", "Towing Charges"),
        "less_other_deductions": ("Less Any Other Deductions", "Other Deductions", "Less Other Deductions", "Any Other Deductions"),
        "workshop_gst_amount": ("ADD GST (9%CGST+9%SGST)", "ADD GST (9% CGST + 9% SGST)"),
    },
    "fees": {
        "professional_fee": ("Professional Fee", "Professional Fees", "Survey Fee", "Survey Fees", "Prof. Fee", "Prof. Fees"),
        "traveling_expenses": ("Traveling Expenses", "Travelling Expenses", "Conveyance Charges", "Conveyance Charge", "Conveyance Amount", "Travel Expenses", "Conveyance"),
        "sfb_others": ("Others", "Other Charges", "Other Amount", "Misc Charges", "Misc"),
    },
}

FEE_FIELDS = tuple(FIELDS["fees"])
AMOUNT_FIELDS = {
    "primary_assessment",
    "nil_depreciation_amount",
    "engine_protect_amount",
    "consumable_items_amount",
    "key_protect_amount",
    "net_salvage",
    "less_compulsory_excess",
    "less_voluntary_excess",
    "less_imposed_excess",
    "towing_additional_charges",
    "less_other_deductions",
    "workshop_gst_amount",
    "professional_fee",
    "traveling_expenses",
    "sfb_others",
}
IDENTITY_KEYS = {"claim_no", "policy_number", "driver_license_number", "vehicle_registration_number", "vendor_invoice_number"}
CRITICAL_KEYS = {
    "claim_no",
    "registered_owner_name",
    "vehicle_registration_number",
    "date_of_registration",
    "engine_no",
    "chassis_no",
    "vehicle_make",
    "class_of_vehicle",
    "rto_name",
    "odometer_reading",
    "vehicle_color",
    "registered_laden_weight",
    "type_of_fuel",
    "cause_nature_of_accident",
    "driver_name",
    "dob_of_driver",
    "driver_license_number",
    "driver_license_issue_date",
    "driver_license_expiry_date",
    "ifsc_code",
    "account_number",
    "vendor_invoice_date",
    "vendor_invoice_number",
    "primary_assessment",
}
IGNORED_DRIVER_LABELS = ("Charges Filed", "Criminal Charges")


def _text(value: str) -> str:
    value = unicodedata_normalize(value).replace("’", "'")
    return " ".join(value.replace("–", "-").replace("—", "-").split())


def unicodedata_normalize(value: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKC", str(value or ""))


def _alias_patterns(aliases):
    for alias in sorted(set(aliases), key=lambda label: (-len(label), label)):
        if alias and "_" not in alias and (words := re.findall(r"[\w%#]+", alias)):
            yield r"[\s.:/&(),'\-]*".join(map(re.escape, words))


def _match_label(text: str, aliases):
    for pattern in _alias_patterns(aliases):
        # Support numbered bullets ("1.", "5)") and sub-bullets ("a)", "b)", "I)").
        match = re.match(
            r"^(?:(?:\d{1,2}[.)]?|[A-Za-z][.)])\s+)?" + pattern + r"(?![\w])",
            text,
            flags=re.I,
        )
        if match:
            return match
    return None


def _after(text: str, aliases) -> Optional[str]:
    match = _match_label(text, aliases)
    return text[match.end() :].lstrip(" .:=/-") if match else None


def _label_rows(rows, aliases):
    """Split side-by-side label/value pairs across columns or inline label boundaries."""
    patterns = tuple(_alias_patterns(aliases))
    if not patterns:
        yield from rows
        return
    labels = "|".join(patterns)
    cell_label = re.compile(rf"^(?:(?:\d{{1,2}}[.)]?|[A-Za-z][.)])\s+)?(?:{labels})\s*\.?(?=[:=\-]|$)", re.I)
    inline_label = re.compile(rf"(?<!\S)(?:(?:\d{{1,2}}[.)]?|[A-Za-z][.)])\s+)?(?:{labels})\s*\.?(?=[:=]|-\s|:\-)", re.I)
    first_label = re.compile(rf"^(?:(?:\d{{1,2}}[.)]?|[A-Za-z][.)])\s+)?(?:{labels})(?!\w)", re.I)
    for row in rows:
        if not isinstance(row, Line):
            row = Line(row.page, row.line, ((0, 1, row.text),))
        chunks = []
        cells = []
        for x0, x1, text in row.cells:
            if cells and cell_label.match(text):
                chunks.append(cells)
                cells = []
            cells.append((x0, x1, text))
        chunks.append(cells)
        for cells in chunks:
            text = " ".join(cell[2] for cell in cells)
            first = first_label.match(text)
            offsets = [
                match.start()
                for match in inline_label.finditer(text)
                if first and match.start() >= first.end()
            ]
            if not offsets:
                yield replace(row, cells=tuple(cells))
                continue
            for start, end in zip([0, *offsets], [*offsets, len(text)]):
                yield replace(row, cells=((cells[0][0], cells[-1][1], text[start:end].strip()),))


def _date(value: str) -> str:
    match = DATE_RX.search(value)
    raw = match[1] if match else ""
    if not raw:
        iso = re.search(r"\b\d{4}-\d{2}-\d{2}\b", value)
        if iso:
            raw = iso[0]
    for fmt in ("%d-%m-%Y", "%d-%m-%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.replace("/", "-").replace(".", "-"), fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return ""


def _registration(value: str) -> tuple[str, str]:
    match = REGISTRATION.match(value) or BH_REGISTRATION.match(value)
    if not match:
        return "", ""
    reg = re.sub(r"\s+", "", match[1]).upper()
    office = value[match.end() :].strip(" :;/,-")
    office = re.sub(r"^RTO\s*[:.-]?\s*", "", office, flags=re.I).strip()
    return reg, office


def _value(key: str, raw: str) -> str:
    value = _text(raw).strip(" .:;")
    if compact(value) in PLACEHOLDERS:
        return ""
    if key == "date_of_registration" and re.match(r"expir|valid\b", value, re.I):
        return ""
    if "date" in key or key == "dob_of_driver" or key.endswith(("_upto", "_valid_upto")):
        return _date(value)
    if key.endswith("_time"):
        hh, mm = extract_time(value)
        return f"{hh}:{mm}" if hh else ""
    if key == "vehicle_registration_number":
        return _registration(value)[0]
    if key == "driver_license_number":
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9 /-]{7,28}", value, re.I) or not re.search(r"\d", value):
            return ""
        return normalize_driver_license_number(value)
    if key == "ifsc_code":
        match = IFSC_RX.search(value)
        return match.group(1).upper() if match else ""
    if key == "account_number":
        match = ACCOUNT_NO_RX.search(value)
        return match.group(1) if match else ""
    if key in IDENTITY_KEYS or key in {"chassis_no", "engine_no", "reference_no", "badge_number", "fir_number"}:
        match = IDENTIFIER.match(value)
        token = match[0].strip(" .") if match else ""
        if key == "fir_number":
            return token if len(token) >= 1 and compact(token) not in PLACEHOLDERS else ""
        minimum = 4 if key in {"chassis_no", "engine_no", "badge_number", "reference_no"} else 4
        return token if len(token) >= minimum and any(c.isdigit() for c in token) else ""
    if key == "email_id":
        match = EMAIL_RX.search(value)
        return match.group(0) if match else ""
    if key == "mobile_no":
        match = MOBILE_RX.search(value)
        return clean_mobile_number(match.group(1)) if match else ""
    if key == "odometer_reading":
        digits = re.sub(r"\D", "", value.split()[0] if value else "")
        return digits if digits else ""
    if key in {"registered_laden_weight", "unladen_weight"}:
        match = re.match(r"(\d[\d,]*)(?:\s*(?:kg|kgs|kilograms?))?\b", value, re.I)
        return match.group(1).replace(",", "") if match else ""
    if key == "no_of_invoices":
        match = re.search(r"\b(\d{1,2})\b", value)
        return match.group(1) if match else ""
    if key == "place_of_survey":
        if re.match(r"^(?:survey\s*fee|re[\s-]*inspection\s*fee|bill\b|invoice\b)\s*\d*", value, re.I):
            return ""
        return value
    if key == "driver_name":
        return re.split(r"\b(?:DOB|date\s+of\s+birth)\b", value, maxsplit=1, flags=re.I)[0].strip(" :,")
    if key == "payment_to":
        if re.match(r"(?:non[- ]?cashless|reimbursement|(?:the\s+)?insured|claimant)\b", value, re.I):
            return "INSURED"
        if re.match(r"(?:cashless|(?:the\s+)?repairer|workshop|dealer)\b", value, re.I):
            return "REPAIRER"
        return ""
    if key in {
        "physically_verified",
        "vehicle_details_matching_policy",
        "vehicle_parked_during_accident",
        "is_license_valid",
        "is_gst_applicable",
        "is_supplementary_estimate",
        "any_previous_police_records",
        "is_there_any_tp_claim",
    }:
        match = re.match(r"(yes|no|y|n|true|false)\b", value, re.I)
        if not match:
            return ""
        return "Yes" if match.group(1).casefold() in {"yes", "y", "true"} else "No"
    if key in AMOUNT_FIELDS:
        # Lines in summary tables often show "Estimated   Assessed"; take rightmost Assessed value.
        numbers = []
        for token in re.split(r"\s+", value):
            parsed = amount(token.strip(",;"))
            if parsed is not None:
                numbers.append(parsed)
        return format(numbers[-1], "f") if numbers else ""
    if key == "vehicle_color":
        return normalize_vehicle_color(value)
    return value


def _set(claim: ClaimData, key: str, value: str, source: str) -> None:
    if value != "":
        setattr(claim, key, str(value))
        claim._excel_coords[key] = source


def _split_sections(lines):
    sections = defaultdict(list)
    section = "header"
    fee_page = 0
    for line in lines:
        for group, pattern in SECTIONS:
            if pattern.match(line.text):
                section = group
                if group == "fees":
                    fee_page = line.page
                break
        sections["fees" if line.page == fee_page else section].append(line)
    return sections


def _read_field(claim: ClaimData, key: str, rows, aliases, *, warnings: dict) -> None:
    candidates = {}
    low_conf = {}
    for line in rows:
        if key == "towing_additional_charges" and "additional towing" in line.text.lower():
            continue
        raw = _after(line.text, aliases)
        if raw is None:
            continue
        value = _value(key, raw)
        if not value:
            continue
        normalized = compact(value) if key in IDENTITY_KEYS else value.casefold()
        if key in AMOUNT_FIELDS:
            num = amount(value)
            if num is not None:
                normalized = str(num.normalize())
        if line.confidence < MIN_FIELD_CONFIDENCE:
            low_conf.setdefault(normalized, line.source)
            continue
        candidates.setdefault(normalized, (value, line.source))

    contradicting_ocr = (low_conf.keys() - candidates.keys()) if (key in CRITICAL_KEYS or key in IDENTITY_KEYS) else set()
    if len(candidates) == 1 and not contradicting_ocr:
        _set(claim, key, *next(iter(candidates.values())))
    elif candidates:
        label = key.replace("_", " ").title()
        sources = ", ".join(
            dict.fromkeys([
                *(src for _, src in candidates.values()),
                *(low_conf[v] for v in sorted(contradicting_ocr)),
            ])
        )
        warnings[key] = f"Conflicting values for {label} on {sources}."
    elif low_conf:
        label = key.replace("_", " ").title()
        warnings[key] = f"Check {label} on {', '.join(sorted(set(low_conf.values())))}; the OCR reading is uncertain."


def _document_identity(lines, *, fee_bill: bool = False):
    fields = defaultdict(dict)
    claim_labels = FIELDS["header"]["claim_no"]
    policy_labels = FIELDS["header"]["policy_number"]
    registration_labels = FIELDS["vehicle"]["vehicle_registration_number"]
    if fee_bill:
        policy_labels += ("C Note/Policy No.",)
        registration_labels += ("Vehicle/Item",)
    aliases = (*claim_labels, *policy_labels, *registration_labels)
    for line in _label_rows(lines, aliases):
        if getattr(line, "confidence", 1) < MIN_FIELD_CONFIDENCE:
            continue
        for key, configured in (("claim_no", claim_labels), ("policy_number", policy_labels)):
            if (raw := _after(line.text, configured)) and (value := _value(key, raw)):
                fields[key].setdefault(compact(value), value)
        if raw := _after(line.text, registration_labels):
            if value := _registration(raw)[0]:
                fields["vehicle_registration_number"].setdefault(compact(value), value)
    identity = {key: next(iter(values.values())) for key, values in fields.items() if len(values) == 1}
    conflicts = {key for key, values in fields.items() if len(values) > 1}
    return identity, conflicts


def _report_evidence(lines):
    heading = any(
        REPORT_HEADING.search(line.text)
        or "finalsurveyreport" in compact(line.text)
        or "surveyandassessmentreport" in compact(line.text)
        for line in lines
    )
    sections = _split_sections(lines)
    fee_ids = {id(line) for line in sections["fees"]}
    non_fee = [line for line in lines if id(line) not in fee_ids]
    identity, _ = _document_identity(non_fee)
    return heading, sections, identity


def _is_supporting_report(lines) -> bool:
    cover = [line for line in lines if line.page == 1]
    for line in cover[:20]:
        if SUPPORTING_REPORT_HEADING.match(compact(line.text)):
            return True
        if REPORT_HEADING.match(line.text) or (
            line.text.casefold().startswith("ref") and REPORT_HEADING.search(line.text)
        ):
            return False
    return False


def find_newindia_report(folder, *, preferred=None, stop_cb=None) -> Optional[str]:
    """Find the New India main final survey PDF, excluding generated outputs and supporting docs."""
    defaults = load_automation_defaults(portal_id="newindia")
    files = []
    seen = set()

    def candidate_order(path: Path):
        return (
            "printable" in path.name.casefold(),
            path.name.casefold(),
        )

    for path in sorted(Path(folder).iterdir(), key=candidate_order):
        if stop_cb and stop_cb():
            raise InterruptedError("PDF report selection cancelled")
        if not path.is_file() or path.suffix.casefold() != ".pdf":
            continue
        if is_scan_output(str(path), defaults):
            continue

        name = compact(path.stem).lstrip("0123456789")
        if (
            name.startswith(("claimothersdocuments", "vehiclephoto", "reinspection", "spotsurvey", "supplementarysurvey"))
            or "feebill" in name
            or name.startswith("sfbill")
        ):
            continue

        is_preferred = bool(preferred and Path(preferred) == path)
        if not (re.search(r"survey|final|assess|report", name) or is_preferred):
            if re.search(
                r"photo|invoice|estimate|policy|license|licence|cheque|receipt|card|aadhaar|aadhar|pan|claimform|voucher|^rc|^dl",
                name,
            ):
                continue

        try:
            sample = read_lines(str(path), max_pages=3)
        except Exception:
            continue
        if _is_supporting_report(sample):
            continue

        heading, sections, identity = _report_evidence(sample)
        core = {"vehicle", "driver", "survey", "assessment"}
        coverage = len(core & sections.keys())
        strong = (heading and bool(identity or coverage >= 2)) or (bool(identity) and coverage >= 2)
        named = name in {"main", "report", "assessment"} or bool(
            re.search(r"survey.*report|final.*report|assessmentreport", name)
        )

        if not strong and (heading or len(sample) < 12):
            try:
                cover = [line for page in read_pages(path, stop_cb=stop_cb, max_pages=3) for line in page.lines]
            except InterruptedError:
                raise
            except Exception:
                cover = []
            if _is_supporting_report(cover):
                continue
            if cover:
                heading, sections, identity = _report_evidence(cover)
                coverage = len(core & sections.keys())
                strong = (heading and bool(identity or coverage >= 2)) or (bool(identity) and coverage >= 2)

        if strong or (named and (heading or len(sample) < 12)):
            with path.open("rb") as stream:
                fingerprint = hashlib.sha256()
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    fingerprint.update(block)
                digest = fingerprint.digest()
            if digest in seen:
                continue
            seen.add(digest)

            financial_sections = 0
            if strong:
                try:
                    body_labels = [compact(row.text) for row in read_lines(str(path))]
                except Exception:
                    body_labels = [compact(row.text) for row in sample]
                financial_sections = sum((
                    any("gstsummaryspares" in row or "gstsummaryspareparts" in row or "sparesgstsummary" in row for row in body_labels),
                    any("gstsummarylabour" in row or "gstsummarylabourcharges" in row or "labourgstsummary" in row for row in body_labels),
                    any(("denting" in row and "paint" in row) or row in {"paintgst", "paintinggst"} for row in body_labels),
                    any("workshopinvoice" in row and "dated" in row for row in body_labels),
                ))
            rank = (bool(strong), financial_sections, coverage, len(identity))
            files.append((rank, path, identity))

    if not files:
        return None
    files.sort(key=lambda entry: entry[0], reverse=True)
    best_rank, best_path, best_identity = files[0]
    for rank, path, identity in files[1:]:
        if best_rank[0] and rank[0] and any(
            key in identity and compact(value) != compact(identity[key]) for key, value in best_identity.items()
        ):
            raise ValueError(
                f"More than one claim report found: {best_path.name} and {path.name}. Keep the PDF for this claim and rescan."
            )
        if rank == best_rank:
            if best_rank[0] and best_identity == identity and preferred:
                preferred_path = Path(preferred).resolve()
                if best_path.resolve() == preferred_path:
                    continue
                if path.resolve() == preferred_path:
                    best_path = path
                    continue
            raise ValueError(
                f"Multiple possible survey PDFs: {best_path.name} and {path.name}. Keep the final report and rescan."
            )
    return str(best_path)


def _apply_newindia_defaults(claim: ClaimData, defaults: dict, mapping: dict, warnings: dict) -> None:
    """Apply configured defaults ONLY when no value and no warning/conflict exists."""
    default_keys = {
        "remarks": ("remarks_default", "Ok"),
        "fir_number": ("missing_text_default", "NA"),
        "police_station_name": ("missing_text_default", "NA"),
        "charged_us_motor_vehicle_act": ("missing_text_default", "NA"),
        "charged_us_ipc": ("missing_text_default", "NA"),
        "account_type": ("account_type", "Savings"),
        "party_payment_method": ("payment_method", "NEFT"),
        "driver_relationship_with_insured": ("relationship_with_insured", "Self"),
        "re_inspection_required": ("reinspection_required", "No"),
        "is_gst_applicable": ("gst_applicable", "Yes"),
        "payment_invoice_in_name_of_nia": ("payment_invoice_in_company_name", "Yes"),
        "is_there_any_tp_claim": ("is_there_any_tp_claim", "No"),
    }
    for field_name, cfg in mapping.items():
        if field_name.startswith("_") or not isinstance(cfg, dict):
            continue
        if field_name in warnings:
            continue
        current = str(getattr(claim, field_name, "") or "").strip()
        if current and current != "0":
            continue
        if field_name == "odometer_reading" and claim._excel_coords.get(field_name):
            continue

        fallback = cfg.get("fallback_value")
        if field_name in default_keys:
            key, hard_default = default_keys[field_name]
            val = defaults.get(key)
            if val not in (None, ""):
                fallback = val
            elif fallback is None:
                fallback = hard_default
        if fallback is not None and str(fallback).strip() != "":
            setattr(claim, field_name, str(fallback))
            claim._excel_coords.setdefault(field_name, "Automation Defaults")
            claim._excel_logs.append(f"  [PDF DEFAULT] {field_name}: '{fallback}'")


def read_newindia_pdf_report(path, *, stop_cb=None) -> ClaimData:
    """Extract all New India claim fields, parts/labour assessment, and review warnings from PDF."""
    pages = read_pages(path, stop_cb=stop_cb)
    lines = [
        replace(line, cells=tuple((left, right, _text(text)) for left, right, text in line.cells))
        for page in pages
        for line in page.lines
    ]
    if not lines:
        raise ValueError("The survey PDF has no readable text. Try a clearer scan or the original PDF.")
    if _is_supporting_report(lines):
        raise ValueError("This PDF is a supporting survey report. Select the final survey report and rescan.")

    heading, sections, identity = _report_evidence(lines)
    if not (heading or (identity and {"vehicle", "driver", "survey"} & sections.keys())):
        raise ValueError(
            "This PDF does not have readable survey-report headings and claim or vehicle identifiers. Select the final survey report and rescan."
        )

    defaults = load_automation_defaults(portal_id="newindia")
    mapping = load_field_mapping(portal_id="newindia")
    claim = ClaimData(portal_id="newindia", source_report_path=str(path))
    warnings: dict[str, str] = {}
    review: list[str] = []

    fee_ids = {id(line) for line in sections["fees"]}
    header_ids = {id(line) for line in sections["header"]}
    non_fee_lines = [line for line in lines if id(line) not in fee_ids]
    non_fee_no_header = [line for line in non_fee_lines if id(line) not in header_ids]

    for group, fields in FIELDS.items():
        configured = {}
        for key, aliases in fields.items():
            custom = mapping.get(key, {}).get("search_labels", [])
            if isinstance(custom, str):
                custom = [custom]
            extra = tuple(
                alias
                for alias in custom
                if compact(alias) not in {
                    "address", "date", "time", "gst", "route", "insurer", "insured",
                    "netpayable", "others", "misc", "salvage", "make", "mobile", "email",
                }
            )
            configured[key] = (*aliases, *extra)

        rows = sections[group]
        if group == "fees" and rows:
            fee_identity, conflicts = _document_identity(rows, fee_bill=True)
            if conflicts or any(
                getattr(claim, k, "") and compact(getattr(claim, k, "")) != compact(v)
                for k, v in fee_identity.items()
            ):
                warnings["fee_bill_identity"] = "The fee-bill page has different claim or vehicle details. Review the fees manually."
                continue

        # Fallback to non-fee lines only for sections that commonly sit inline without
        # a dedicated heading; NEVER allow bank details to read from fees or driver from header.
        if group in {"vehicle", "survey", "accident", "fir", "work_approval"} and not rows:
            rows = non_fee_lines
        elif group == "driver" and not rows:
            rows = non_fee_no_header
        elif group == "assessment" and not rows:
            rows = non_fee_lines

        if group == "driver" and rows is non_fee_no_header:
            for key in list(configured):
                scoped = {"address", "dateofissue", "licenceno", "licenseno", "validtill", "validupto", "dateofbirth", "dob"}
                configured[key] = tuple(a for a in configured[key] if compact(a) not in scoped)

        label_boundaries = tuple(alias for aliases in configured.values() for alias in aliases)
        if group == "driver":
            label_boundaries += IGNORED_DRIVER_LABELS
        label_rows = tuple(_label_rows(rows, label_boundaries))
        rows_by_field = defaultdict(list)
        for row in label_rows:
            specificity = {
                key: match.end()
                for key, aliases in configured.items()
                if (match := _match_label(row.text, aliases))
            }
            if specificity:
                longest = max(specificity.values())
                for key, length in specificity.items():
                    if length == longest:
                        rows_by_field[key].append(row)

        for key, aliases in configured.items():
            # Keep Insured fallback secondary to explicit RC owner name.
            if key == "registered_owner_name" and group == "insured" and claim.registered_owner_name:
                continue
            _read_field(claim, key, rows_by_field[key], aliases, warnings=warnings)

    # Insured mobile/email fallback ONLY if header did not provide surveyor contact details
    if not claim.mobile_no and "mobile_no" not in warnings:
        _read_field(claim, "mobile_no", sections["insured"], ("Contact No", "Mobile No", "Mobile"), warnings=warnings)
    if not claim.email_id and "email_id" not in warnings:
        _read_field(claim, "email_id", sections["insured"], ("Email ID", "E-mail", "Email"), warnings=warnings)

    # Multi-line cause & nature narrative
    for line in non_fee_lines:
        narrative = _after(line.text, ("Cause and Nature of Accident", "Cause & Nature of Accident", "Nature of Accident"))
        if narrative is not None and line in sections["cause"]:
            index = sections["cause"].index(line)
            body = " ".join(filter(None, (narrative, *(row.text for row in sections["cause"][index + 1 :]))))
            if body and line.confidence >= MIN_FIELD_CONFIDENCE:
                _set(claim, "cause_nature_of_accident", body, line.source)
            break

    # Driver inline DOB when placed on same line as driver name
    for line in sections["driver"]:
        if _after(line.text, FIELDS["driver"]["driver_name"]) is not None:
            dob = re.search(r"\b(?:DOB|Date\s+of\s+Birth)\s*[:.-]?\s*(.*)", line.text, re.I)
            if dob and not claim.dob_of_driver and "dob_of_driver" not in warnings and line.confidence >= MIN_FIELD_CONFIDENCE:
                _set(claim, "dob_of_driver", _date(dob.group(1)), line.source)

    # Vehicle inline RTO from "Registration No. / RTO : PB03BH1786 / RTO: RTO FEROZ"
    for line in sections["vehicle"] or non_fee_lines:
        if raw := _after(line.text, FIELDS["vehicle"]["vehicle_registration_number"]):
            reg, office = _registration(raw)
            if (
                reg
                and reg == claim.vehicle_registration_number
                and office
                and not claim.rto_name
                and "rto_name" not in warnings
                and line.confidence >= MIN_FIELD_CONFIDENCE
            ):
                _set(claim, "rto_name", office, line.source)

    # Survey time from "Date & Time of Survey" / "Date & Time of Accident" context
    for line in sections["survey"] or non_fee_lines:
        if _after(line.text, FIELDS["survey"]["date_of_survey"]) is not None and line.confidence >= MIN_FIELD_CONFIDENCE:
            hh, mm = extract_time(line.text)
            if hh:
                claim.time_hh, claim.time_mm = hh, mm
                _set(claim, "time_of_survey", f"{hh}:{mm}", line.source)
                break

    # Place of Survey fallback from explicit "Place of Survey" workshop section
    if not claim.place_of_survey and "place_of_survey" not in warnings:
        _read_field(claim, "place_of_survey", sections["workshop"], FIELDS["survey"]["place_of_survey"], warnings=warnings)
        if not claim.place_of_survey and sections["workshop"]:
            first_workshop_line = next(
                (
                    row
                    for row in sections["workshop"]
                    if not re.fullmatch(r"(?:\d{1,2})?(?:placeofsurvey|workshopdetails)", compact(row.text))
                    and row.confidence >= MIN_FIELD_CONFIDENCE
                ),
                None,
            )
            if first_workshop_line and any(
                re.fullmatch(r"(?:\d{1,2})?placeofsurvey", compact(row.text))
                for row in sections["workshop"]
            ):
                _set(claim, "place_of_survey", first_workshop_line.text, first_workshop_line.source)

    # Compact pipe-delimited FIR line: "9 FIR DETAIL : No: 098 | Dt: 05/07/2025 | PS: PS SECTOR 19"
    for line in non_fee_lines:
        if re.search(r"\bFIR\s*DETAIL\b", line.text, re.I) and line.confidence >= MIN_FIELD_CONFIDENCE:
            m_no = re.search(r"\bNo\.?\s*[:\-]\s*([^|]+)", line.text, re.I)
            m_dt = re.search(r"\bDt\.?\s*[:\-]\s*([^|]+)", line.text, re.I)
            m_ps = re.search(r"\bPS\s*[:\-]\s*([^|]+)", line.text, re.I)
            if m_no and not claim.fir_number and (val := _value("fir_number", m_no.group(1))):
                _set(claim, "fir_number", val, line.source)
            if m_dt and not claim.fir_date and (val := _date(m_dt.group(1))):
                _set(claim, "fir_date", val, line.source)
            if m_ps and not claim.police_station_name and (val := _text(m_ps.group(1)).strip(" .:")):
                if compact(val) not in PLACEHOLDERS:
                    _set(claim, "police_station_name", val, line.source)

    # Workshop / Vendor invoice no & date (explicitly excluding Fee Bill section)
    ws_no_candidates = {}
    ws_dt_candidates = {}
    ws_no_labels = (
        "Vendor/Tax Invoice Number",
        "Tax Invoice Number",
        "Workshop Invoice No",
        "Workshop Invoice Number",
        "Repairer Invoice No",
        "Garage Invoice No",
    )
    ws_dt_labels = (
        "Vendor/Tax Invoice Date",
        "Tax Invoice Date",
        "Workshop Invoice Date",
        "Repairer Invoice Date",
        "Garage Invoice Date",
    )
    for line in non_fee_lines:
        if line.confidence < MIN_FIELD_CONFIDENCE:
            continue
        if raw := _after(line.text, (*ws_no_labels, "Workshop Invoice No", "Repairer Invoice No")):
            date_label = re.search(r"(?:(?<=\d)|(?<!\w))dated?\s*[:.-]?\s*(?=\d)", raw, re.I)
            inv_date = _date(raw[date_label.end() :]) if date_label else ""
            inv_no_raw = raw[: date_label.start()].strip(" :;,-") if date_label else raw.split()[0]
            if (inv_no := _value("vendor_invoice_number", inv_no_raw)) and not _date(inv_no_raw):
                ws_no_candidates.setdefault(compact(inv_no), (inv_no, line.source))
            if inv_date:
                ws_dt_candidates.setdefault(inv_date, (inv_date, line.source))
        if raw_dt := _after(line.text, ws_dt_labels):
            if inv_date := _date(raw_dt):
                ws_dt_candidates.setdefault(inv_date, (inv_date, line.source))

    if len(ws_no_candidates) == 1:
        _set(claim, "vendor_invoice_number", *next(iter(ws_no_candidates.values())))
    elif ws_no_candidates:
        warnings["vendor_invoice_number"] = "Conflicting Workshop/Vendor Invoice Numbers found in survey PDF."
    if len(ws_dt_candidates) == 1:
        _set(claim, "vendor_invoice_date", *next(iter(ws_dt_candidates.values())))
    elif ws_dt_candidates:
        warnings["vendor_invoice_date"] = "Conflicting Workshop/Vendor Invoice Dates found in survey PDF."

    # Payment To / Bank Payment To (never read bank details from fees)
    _read_field(
        claim,
        "payment_to",
        non_fee_lines,
        (
            "The payment to be made in favour of",
            "Payment to be made in favour of",
            "Payment to be made to",
            "Payment made in the favour of",
            "Payment in favour of",
            "Payment To",
            "Payable To",
            "Claim Type",
            "Payment Option",
            "Settlement Type",
        ),
        warnings=warnings,
    )
    if not claim.payment_to and "payment_to" not in warnings:
        for line in non_fee_lines:
            low = line.text.lower()
            if "cashless" in low and "non-cashless" not in low and "non cashless" not in low:
                _set(claim, "payment_to", "REPAIRER", line.source)
                break
            if "reimbursement" in low or "non-cashless" in low or "non cashless" in low or "favour of insured" in low:
                _set(claim, "payment_to", "INSURED", line.source)
                break
            if "favour of repairer" in low:
                _set(claim, "payment_to", "REPAIRER", line.source)
                break

    if claim.payment_to:
        claim.bank_payment_to = "Dealer" if claim.payment_to == "REPAIRER" else "Insured"
        claim._excel_coords["bank_payment_to"] = claim._excel_coords.get("payment_to", "PDF")
    else:
        claim.bank_payment_to = "Insured"

    # Extract New India parts & labour assessment + GST summary from pages
    parts_rows, labour_rows, item_sources, gst_info, assessment_errors = read_newindia_pdf_assessment(
        pages, defaults=defaults,
    )
    claim._newindia_pdf_assessment = (parts_rows, labour_rows)
    claim._newindia_pdf_assessment_sources = item_sources
    claim._newindia_pdf_assessment_error = "; ".join(assessment_errors) if assessment_errors else ""

    if not claim.workshop_gst_amount and "workshop_gst_amount" in gst_info and "workshop_gst_amount" not in warnings:
        gst_val, gst_src = gst_info["workshop_gst_amount"]
        _set(claim, "workshop_gst_amount", format(gst_val, "f"), gst_src)

    # Photo charges use configured Automation Default (matching Excel behavior)
    photo_default = str(defaults.get("photo_charges_default", "200") or "200")
    claim.photo_charges = photo_default
    claim._excel_coords["photo_charges"] = "Automation Defaults"

    # Apply New India defaults/fallbacks for non-conflicting missing fields
    _apply_newindia_defaults(claim, defaults, mapping, warnings)

    # Date ordering sanity checks
    for first, second, first_label, second_label in (
        ("dob_of_driver", "driver_license_issue_date", "Driver DOB", "DL Issue Date"),
        ("driver_license_issue_date", "driver_license_expiry_date", "DL Issue Date", "DL Expiry Date"),
        ("date_of_registration", "date_of_survey", "Date of Registration", "Date of Survey"),
    ):
        earlier, later = getattr(claim, first, ""), getattr(claim, second, "")
        if earlier and later:
            try:
                if datetime.strptime(earlier, "%d/%m/%Y") > datetime.strptime(later, "%d/%m/%Y"):
                    review.append(
                        f"{first_label} ({earlier}) on {claim._excel_coords.get(first, 'PDF')} is later than "
                        f"{second_label} ({later}) on {claim._excel_coords.get(second, 'PDF')}."
                    )
            except ValueError:
                pass

    # Promote uncertain/conflicting critical fields into review errors, optional ones into warnings
    review_warnings: list[str] = []
    for key, msg in warnings.items():
        if key in CRITICAL_KEYS or key in IDENTITY_KEYS:
            review.append(msg)
        else:
            review_warnings.append(msg)

    claim._newindia_pdf_review_errors = list(dict.fromkeys(review))
    claim._newindia_pdf_review_warnings = list(dict.fromkeys(review_warnings))
    claim.calculate_derived_fields()
    return claim


def supplement_newindia_pdf_fees(claim: ClaimData, folder: str, *, stop_cb=None) -> None:
    """Supplement missing New India Survey Fee Bill fields from matching standalone Fee Bill PDFs."""
    from pdfminer.pdfexceptions import PDFException
    from pdfplumber.utils.exceptions import PdfminerException

    defaults = load_automation_defaults(portal_id="newindia")
    fee_fields = [key for key in FEE_FIELDS if not claim._excel_coords.get(key)]
    if not fee_fields or not folder:
        return

    folder_path = Path(folder)
    if not folder_path.is_dir():
        return

    if not hasattr(claim, "_newindia_pdf_review_warnings"):
        claim._newindia_pdf_review_warnings = []

    main_resolved = None
    if getattr(claim, "source_report_path", ""):
        try:
            main_resolved = Path(claim.source_report_path).resolve()
        except OSError:
            main_resolved = None

    verified = {key: getattr(claim, key, "") for key in ("claim_no", "policy_number", "vehicle_registration_number")}
    candidates = defaultdict(list)

    for path in sorted(folder_path.glob("*.pdf")):
        if stop_cb and stop_cb():
            raise InterruptedError("PDF fee bill reading cancelled")
        if main_resolved is not None:
            try:
                if path.resolve() == main_resolved:
                    continue
            except OSError:
                pass
        if is_scan_output(str(path), defaults):
            continue

        name = compact(path.stem)
        is_fee_bill_name = (
            "feebill" in name
            or name.startswith("sfbill")
            or "surveyfee" in name
            or "surveyorfee" in name
            or ("bill" in name and not any(bad in name for bad in ("garage", "towing", "estimate", "invoice")))
        )
        if not is_fee_bill_name:
            continue

        try:
            rows = read_lines(str(path), max_pages=4)
            if len(rows) < 4:
                ocr_pages = read_pages(path, stop_cb=stop_cb, max_pages=4)
                rows = [line for page in ocr_pages for line in page.lines]
        except InterruptedError:
            raise
        except (OSError, ValueError, PDFException, PdfminerException):
            claim._newindia_pdf_review_warnings.append(
                f"Could not read optional fee bill {path.name}. Review or replace the file."
            )
            continue

        identity, conflicts = _document_identity(rows, fee_bill=True)
        if conflicts:
            claim._newindia_pdf_review_warnings.append(
                f"Conflicting claim, policy, or vehicle identifiers in fee bill {path.name}. Review this bill."
            )
            continue
        shared = {key for key, value in identity.items() if value and verified.get(key)}
        if not shared or any(compact(verified[key]) != compact(identity[key]) for key in shared):
            continue

        for key in fee_fields:
            for row in rows:
                if getattr(row, "confidence", 1.0) < MIN_FIELD_CONFIDENCE:
                    continue
                raw = _after(row.text, FIELDS["fees"][key])
                if raw is not None and (val := _value(key, raw)):
                    src = getattr(row, "source", f"PDF p{row.page}")
                    candidates[key].append((val, f"{src} · {path.name}"))

    updated = False
    for key, values in candidates.items():
        unique = {val for val, _ in values}
        if len(unique) == 1:
            _set(claim, key, *values[0])
            updated = True
        else:
            claim._newindia_pdf_review_warnings.append(
                f"Matching fee bills disagree on {key.replace('_', ' ')}. Review the bill amounts."
            )

    missing = [
        label
        for key, label in (("professional_fee", "Professional Fee"), ("traveling_expenses", "Traveling Expenses"))
        if not claim._excel_coords.get(key)
    ]
    if missing:
        claim._newindia_pdf_review_warnings.append(
            f"Fee amounts missing from the survey PDF and matching fee bills: {', '.join(missing)}."
        )
    claim._newindia_pdf_review_warnings = list(dict.fromkeys(claim._newindia_pdf_review_warnings))
    if updated:
        claim.calculate_derived_fields()


def newindia_startup_review_notices(claim) -> dict[str, str]:
    """Return advisory startup review notices for New India PDF-only runs."""
    source_path = str(getattr(claim, "source_report_path", "") or "").lower()
    if not source_path.endswith(".pdf"):
        return {}

    notices: dict[str, str] = {}
    pdf_errors = list(getattr(claim, "_newindia_pdf_review_errors", ()) or ())
    assessment_err = str(getattr(claim, "_newindia_pdf_assessment_error", "") or "").strip()
    assessment_missing = not bool((getattr(claim, "assessment_files", {}) or {}).get("assessment_excel"))

    validation_errors, _ = claim.validate() if hasattr(claim, "validate") else ([], [])
    extra_errors = [
        err
        for err in validation_errors
        if err != assessment_err and err not in pdf_errors
    ]
    combined_pdf_issues = list(dict.fromkeys([*pdf_errors, *extra_errors]))
    if combined_pdf_issues:
        notices["New India Survey PDF Needs Review"] = "\n".join(combined_pdf_issues)

    if assessment_missing and assessment_err:
        notices["New India Primary Assessment Excel Needs Review"] = assessment_err

    pdf_warnings = list(getattr(claim, "_newindia_pdf_review_warnings", ()) or ())
    if pdf_warnings:
        notices["New India Survey PDF Warnings"] = "\n".join(pdf_warnings)

    return notices
