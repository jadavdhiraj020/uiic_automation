"""OIC PDF-only intake. Read the right section before interpreting a label."""

from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from pathlib import Path
import hashlib
import re
import unicodedata

from app.data.data_model import ClaimData
from app.data.excel_reader import _initial_loss_75_percent
from app.data.pdf_report_reader import DATE_RX, EMAIL_RX, MOBILE_RX, extract_time
from app.utils import load_field_mapping
from .license_type_mapping import resolve_license_type
from .pdf_assessment import amount, read_assessment
from .pdf_layout import Line, compact, read_pages


REPORT_HEADING = re.compile(r"\b(?:final\s+(?:motor\s+)?survey|(?:motor\s+(?:od\s+)?)?(?:final\s+)?survey\s+(?:and\s+assessment|assessment)|(?:motor\s+(?:od\s+)?)?final\s+survey)\s+report\b", re.I)
SUPPORTING_REPORT_HEADING = re.compile(
    r"^(?:private|confidential|motor|vehicle|od|final)*"
    r"(?:reinspection(?:survey)?|spotsurvey|supplementarysurvey)report"
)
REGISTRATION = re.compile(r"^([A-Z]{2}\s*\d{1,2}\s*[A-Z]{0,3}\s*\d{1,4})(?=$|[\s,;/])", re.I)
BH_REGISTRATION = re.compile(r"^(\d{2}\s*BH\s*\d{4}\s*[A-Z]{1,2})(?=$|[\s,;/])", re.I)
IDENTIFIER = re.compile(r"^[A-Z0-9][A-Z0-9/*._-]*", re.I)
SURVEYOR_EXPIRY_LABEL = re.compile(r"(?<![A-Za-z])(?:expiry|expirey|expires|valid\s*until)\s*[:.-]?\s*", re.I)
PLACEHOLDERS = {"", "na", "nil", "none", "notapplicable", "notavailable", "nana"}
IGNORED_DRIVER_LABELS = ("Charges Filed", "Criminal Charges")
SECTION_PATTERNS = (
    ("insured", r"insured\b(?!\s+vehicle)"),
    ("vehicle", r"(?:vehicle|registration)\s+(?:particulars|details)\b"),
    ("driver", r"driver(?:'s|s)?\s+(?:particulars|details)\b"),
    ("accident", r"accident\s+(?:history|particulars|details)\b"),
    ("survey", r"(?:details?\s+of\s+survey|survey\s+(?:details|particulars))\b"),
    ("workshop", r"(?:place\s+of\s+survey|workshop\s+details)\s*[:.]?$"),
    ("cause", r"(?:cause\s+(?:and|&)\s+nature|nature|cause)\s+of\s+accident\b"),
    ("notes", r"(?:observations?|notes|fir\s+detail|injury/third\s+party\s+loss)\b"),
    ("assessment", r"(?:details?\s+of\s+assessment|assessment\s+of\s+loss|summary\s+of\s+assessment|parts\s+details)\b"),
    ("fees", r"(?:(?:surveyor(?:'s)?|survey|professional|sf)\s+fee\s+bill|bill\s+of\s+survey\s+fees)\b"),
)
SECTIONS = tuple(
    (section, re.compile(r"^(?:\d{1,2}[.)]?\s*)?" + expression.replace(r"\s+", r"\s*"), re.I))
    for section, expression in SECTION_PATTERNS
)

# Specific aliases for PDF labels and known exports. Settings labels are also
# accepted within their sections. Spreadsheet offsets have no meaning here.
FIELDS = {
    "header": {
        "claim_no": ("Claim No", "Claim Number", "Claim Reference", "Claim #"),
        "policy_number": ("Cover Note/Policy No", "Policy No", "Policy Number"),
        "surveyor_name": ("Surveyor Name", "Name of Surveyor", "Name of the Surveyor"),
        "surveyor_license_number": ("Surveyor Licence No", "Licence No", "License No", "Surveyor License Number"),
        "surveyor_license_expiry_date": ("Surveyor License Expiry Date", "License Expiry Date", "Expiry Date", "Expiry", "Expirey"),
        "surveyor_email": ("Surveyor Email", "Email", "E-mail"),
        "surveyor_mobile": ("Surveyor Mobile", "Mobile No", "Mob"),
        "surveyor_address": ("Surveyor Address",),
        "surveyor_pan": ("Surveyor PAN", "PAN No", "PAN Number"),
        "expected_completion_date": ("Submission Date", "Final Report Date", "Date of Final Submission", "Date"),
    },
    "insured": {
        "mobile_no": ("Contact No", "Contact Number", "Claimant Mobile", "Mobile Number", "Mobile"),
        "email_id": ("Claimant Email", "Email ID", "Email", "E-mail"),
    },
    "vehicle": {
        "vehicle_registration_number": ("Registration No / RTO", "Registration No", "Vehicle Registration Number", "Regn No", "Vehicle No"),
        "rto_name": ("RTO Office", "RTO Name", "Registration Authority", "Registering Authority"),
        "vehicle_make": ("Make & Model", "Make and Model", "Make / Model", "Make & Year of Manufacture", "Make"),
        "date_of_registration": ("Date of Registration Issue", "Date of Registration", "Registration Date"),
        "chassis_no": ("Chassis No", "Chassis Number"),
        "engine_no": ("Engine No", "Engine Number"),
        "cubic_capacity": ("Cubic Capacity", "Engine Capacity", "CC"),
        "year_of_manufacture": ("Year of Manufacture", "Manufacturing Year", "Mfg Year"),
        "type_of_body": ("Type of Body", "Body Type"),
        "class_of_vehicle": ("Class of Vehicle", "Vehicle Class"),
        "type_of_fuel": ("Fuel Used", "Fuel Type", "Type of Fuel"),
        "vehicle_color": ("Color", "Colour", "Vehicle Color"),
        "registered_owner_name": ("Name of Regd Owner as per RC", "Name of Registered Owner", "Registered Owner Name"),
        "registered_laden_weight": ("Laden weight GVW", "Registered Laden Weight", "GVW"),
        "unladen_weight": ("Unladen Weight ULW", "Unladen Weight", "ULW"),
        "seating_capacity": ("Seating Capacity",),
        "road_tax_paid_upto": ("Road Tax Paid Upto", "Tax Valid Upto"),
        "fitness_valid_upto": ("Fitness Cert Valid upto", "Fitness Valid Upto", "Fitness Expiry Date"),
        "permit_number": ("Route Permit No", "Permit Number", "Permit No"),
        "type_of_permit": ("Type of Permit", "Permit Type"),
        "permit_valid_upto": ("Route Permit Validity", "Permit Validity", "Permit Expiry"),
        "authorization_number": ("Authorization No", "Authorization Number"),
        "validity_of_authorization": ("Authorization Validity", "Validity of Authorization"),
        "road_area_of_operation": ("Route/Area of Operation", "Road/Area of Operation", "Area of Operation"),
    },
    "driver": {
        "driver_name": ("Name of Driver", "Driver Name", "Name of the Driver"),
        "dob_of_driver": ("DOB", "Driver DOB", "Date of Birth"),
        "driver_license_number": ("DL No", "Driving Licence Number", "Driving License Number", "Licence No", "License No"),
        "driver_license_issue_date": ("Date of Issue", "Date of lssue", "DL Issue Date", "Licence Issue Date"),
        "driver_license_expiry_date": ("Valid Till", "Valid Up To", "DL Expiry Date", "Licence Expiry Date"),
        "license_type_of_driver": ("Type of Licence", "Type of License", "License Type"),
        "driver_address": ("Address of Driver", "Driver Address", "Address"),
        "driver_city_state": ("City/State", "City and State"),
        "driver_pin_code": ("Pincode", "Pin Code"),
        "badge_number": ("Badge No", "Badge Number"),
        "badge_issue_date": ("Badge Issue Date", "Badge Date"),
        "driver_qualification": ("Qualification", "Driver Qualification"),
        "license_issuing_authority": ("Issuing Authority", "Licence Issuing Authority"),
    },
    "accident": {"date_of_accident": ("Date & Time of Accident", "Date and Time of Accident", "Accident Date", "Date of Accident")},
    "survey": {
        "date_of_allotment": ("Date of Allotment of Survey", "Date of Allotment", "Survey Appointment Date"),
        "date_of_survey": ("Date and Time of Survey", "Date & Time of Survey", "Date of Survey", "Survey Date"),
        "place_of_survey": ("Place of Survey", "Survey Location", "Inspection Place"),
        "initial_loss_amount": ("Initial Loss Assessment Amount", "Initial Loss Assessment", "Initial Loss"),
    },
    "workshop": {
        "workshop_name": ("Workshop Name", "Name of Workshop", "Repairer Name", "Workshop"),
        "workshop_estimate_amount": ("Workshop Estimate Amount", "Repair Estimate Amount", "Estimated Repair Cost", "Estimate Amount"),
        "workshop_estimate_date": ("Workshop Estimate Date", "Estimate Date", "Date of Estimate"),
        "gst_number": ("Workshop GSTIN", "Workshop GST Number", "GST Number", "GSTIN"),
    },
    "assessment": {
        "nil_depreciation": ("Nil Depreciation Cover", "Nil Depreciation", "Zero Depreciation", "Nil Dep"),
        "age_of_vehicle": ("Life of Vehicle (in years)", "Life of Vehicle", "Age of Vehicle"),
        "compulsory_excess": ("Compulsory Excess", "Less Compulsory Excess", "SO, Excess Clause (in Rs.)", "Less Excess Clause"),
        "voluntary_excess": ("Voluntary Excess", "Less Voluntary Excess"),
        "imposed_excess": ("Imposed Excess", "Less Imposed Excess"),
        "salvage_amount": ("Salvage Amount", "Less Salvage Value", "Salvage Value"),
    },
    "fees": {
        "professional_fee": ("Professional Fee", "Professional Fees", "Survey Fee", "Survey Fees"),
        "traveling_expenses": ("Travelling Expenses", "Traveling Expenses", "Conveyance Charges", "Conveyance"),
        "daily_allowance": ("Daily Allowance", "Daily Allowances"),
        "photo_charges": ("Photo Charges", "Photograph Charges", "Photography Charges"),
        "re_inspection_charges": ("Re Inspection Charges", "Re-inspection Charges", "Reinspection Charges"),
        "misc_charge": ("Misc Charge", "Misc Charges", "Miscellaneous Charges"),
        "oicl_gst_number": ("OICL GST Number", "OICL GST No", "GST No of OICL"),
    },
}
FEE_FIELDS = tuple(FIELDS["fees"])
REQUIRED = {
    "vehicle_registration_number": "Vehicle Registration Number",
    "vehicle_make": "Vehicle Make",
    "chassis_no": "Chassis Number",
    "engine_no": "Engine Number",
    "cubic_capacity": "Cubic Capacity",
    "driver_name": "Driver Name",
    "dob_of_driver": "Driver Date of Birth",
    "driver_license_number": "Driving Licence Number",
    "driver_license_issue_date": "Driving Licence Issue Date",
    "driver_license_expiry_date": "Driving Licence Expiry Date",
    "driver_address": "Driver Address",
    "workshop_name": "Workshop Name",
    "workshop_estimate_amount": "Workshop Estimate Amount",
    "workshop_invoice_no": "Workshop Invoice Number",
    "workshop_invoice_date": "Workshop Invoice Date",
    "nil_depreciation": "Nil Depreciation",
    "invoice_gst_amount": "Invoice GST Amount",
    "date_of_survey": "Survey Date",
    "place_of_survey": "Place of Survey",
    "initial_loss_amount": "Initial Loss Assessment Amount",
    "expected_completion_date": "Submission Date",
    "surveyor_license_number": "Surveyor Licence Number",
    "surveyor_license_expiry_date": "Surveyor Licence Expiry Date",
    "payment_to": "Claim Type / Payment To",
}
IDENTITY_KEYS = {"claim_no", "policy_number", "driver_license_number", "vehicle_registration_number", "workshop_invoice_no"}
MIN_FIELD_CONFIDENCE = .84


def _text(value):
    value = unicodedata.normalize("NFKC", value).replace("’", "'")
    return " ".join(value.replace("–", "-").replace("—", "-").split())


def _alias_patterns(aliases):
    for alias in sorted(set(aliases), key=lambda label: (-len(label), label)):
        if alias and "_" not in alias and (words := re.findall(r"[\w%#]+", alias)):
            yield r"[\s.:/&(),'\-]*".join(map(re.escape, words))


def _match_label(text, aliases):
    for pattern in _alias_patterns(aliases):
        match = re.match(r"^(?:\d{1,2}[.)]?\s+)?" + pattern + r"(?![\w])", text, flags=re.I)
        if match:
            return match


def _after(text, aliases):
    match = _match_label(text, aliases)
    return text[match.end():].lstrip(" .:=/-") if match else None


def _label_rows(rows, aliases):
    """Split side-by-side labels at column boundaries or explicit label separators."""
    patterns = tuple(_alias_patterns(aliases))
    if not patterns:
        yield from rows
        return
    labels = "|".join(patterns)
    cell_label = re.compile(rf"^(?:{labels})\s*\.?(?=[:=]|$)", re.I)
    inline_label = re.compile(rf"(?<!\S)(?:{labels})\s*\.?(?=[:=])", re.I)
    first_label = re.compile(rf"^(?:\d{{1,2}}[.)]?\s+)?(?:{labels})(?!\w)", re.I)
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
            # Some OCR engines return the whole physical row as one box.
            # A second explicit label may still identify an independent field.
            first = first_label.match(text)
            offsets = [match.start() for match in inline_label.finditer(text)
                       if first and match.start() >= first.end()]
            if not offsets:
                yield replace(row, cells=tuple(cells))
                continue
            for start, end in zip([0, *offsets], [*offsets, len(text)]):
                yield replace(row, cells=((cells[0][0], cells[-1][1], text[start:end].strip()),))


def _date(value):
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


def _registration(value):
    match = REGISTRATION.match(value) or BH_REGISTRATION.match(value)
    if not match:
        return "", ""
    return re.sub(r"\s+", "", match[1]).upper(), value[match.end():].strip(" :;/,-")


def _value(key, value):
    value = _text(value).strip(" .:;")
    if compact(value) in PLACEHOLDERS:
        return ""
    if key == "date_of_registration" and re.match(r"expir|valid\b", value, re.I):
        return ""
    if "date" in key or key == "dob_of_driver" or key.endswith(("_upto", "_valid_upto")) or key == "validity_of_authorization":
        return _date(value)
    if key == "vehicle_registration_number":
        return _registration(value)[0]
    if key == "driver_license_number":
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9 /-]{7,28}", value, re.I) or not re.search(r"\d", value):
            return ""
        return value.upper()
    if key == "surveyor_license_number":
        # OCR can run the expiry label into the final digit of the licence.
        value = SURVEYOR_EXPIRY_LABEL.split(value, maxsplit=1)[0]
    if key in IDENTITY_KEYS or key in {"chassis_no", "engine_no", "surveyor_license_number", "authorization_number", "permit_number", "badge_number"}:
        match = IDENTIFIER.match(value)
        token = match[0].strip(" .") if match else ""
        minimum = 8 if key == "chassis_no" else 4
        return token if len(token) >= minimum and any(c.isdigit() for c in token) else ""
    if key.endswith("_email") or key == "email_id":
        result = EMAIL_RX.search(value)
        return result[0] if result else ""
    if "mobile" in key:
        result = MOBILE_RX.search(value)
        return re.sub(r"\D", "", result[1]) if result else ""
    if key.endswith(("gst_number", "oicl_gst_number")):
        return value.upper() if re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]", value.upper()) else ""
    if key == "nil_depreciation":
        match = re.match(r"(yes|no|y|n|true|false|[01])\b", value, re.I)
        return ("Yes" if match[1].casefold() in {"yes", "y", "true", "1"} else "No") if match else ""
    if key == "payment_to":
        if re.match(r"(?:non[- ]?cashless|reimbursement|(?:the\s+)?insured|claimant)\b", value, re.I):
            return "INSURED"
        if re.match(r"(?:cashless|(?:the\s+)?repairer|workshop|dealer)\b", value, re.I):
            return "REPAIRER"
        return ""
    if key in FEE_FIELDS or key.endswith(("_amount", "_excess")):
        result = amount(value)
        return format(result, "f") if result is not None else ""
    if key in {"cubic_capacity", "year_of_manufacture", "seating_capacity", "registered_laden_weight", "unladen_weight", "driver_pin_code"}:
        if key == "driver_pin_code":
            return value if re.fullmatch(r"[1-9]\d{5}", value) else ""
        match = re.fullmatch(r"(\d[\d,]*)(?:\s*(?:cc|kg|kgs|persons))?", value, re.I)
        return match[1].replace(",", "") if match else ""
    if key == "driver_name":
        return re.split(r"\b(?:DOB|date\s+of\s+birth)\b", value, maxsplit=1, flags=re.I)[0].strip(" :,")
    return value


def _set(claim, key, value, source):
    if value != "":
        setattr(claim, key, str(value))
        claim._excel_coords[key] = source


def _split_sections(lines):
    sections = defaultdict(list)
    section = "header"
    for line in lines:
        for group, pattern in SECTIONS:
            if pattern.match(line.text):
                section = group
                break
        sections[section].append(line)
    return sections


def _read_field(claim, key, rows, aliases, *, warnings):
    candidates = {}
    low_conf = {}
    for line in rows:
        if key == "workshop_name" and re.match(r"^workshop\s*(?:details|invoice|estimate|gst)\b", line.text, re.I):
            continue
        raw = _after(line.text, aliases)
        if raw is None:
            continue
        value = _value(key, raw)
        if not value:
            continue
        normalized = compact(value) if key in IDENTITY_KEYS else value.casefold()
        if key in FEE_FIELDS or key.endswith(("_amount", "_excess", "_rate")):
            number = amount(value)
            if number is not None:
                normalized = str(number.normalize())
        if line.confidence < MIN_FIELD_CONFIDENCE:
            low_conf.setdefault(normalized, line.source)
            continue
        candidates.setdefault(normalized, (value, line.source))
    contradicting_ocr = (low_conf.keys() - candidates.keys()) if key in REQUIRED or key in IDENTITY_KEYS else set()
    if len(candidates) == 1 and not contradicting_ocr:
        _set(claim, key, *next(iter(candidates.values())))
    elif candidates:
        label = REQUIRED.get(key, key.replace("_", " ").title())
        sources = ", ".join(dict.fromkeys([*(src for _, src in candidates.values()),
                                          *(low_conf[value] for value in sorted(contradicting_ocr))]))
        warnings[key] = f"Conflicting values for {label} on {sources}."
    elif low_conf:
        label = REQUIRED.get(key, key.replace("_", " ").title())
        warnings[key] = f"Check {label} on {', '.join(sorted(set(low_conf.values())))}; the OCR reading is uncertain."


def _values_in_summary(text):
    return [result for token in text.split() if (result := amount(token)) is not None]


def _summary_estimate_by_totals(summary):
    """Recover the estimate from printed summary totals without x-position dependence.

    This is intentionally conservative: it only returns a value when Parts +
    Labour + optional Towing exactly reconciles to the printed Sub Total.
    """
    rows = {}
    for line in summary:
        if not line.cells:
            continue
        label = compact(line.cells[0][2])
        if label in rows:
            continue
        if label in {"parts", "labour", "labor", "towingcharges", "subtotal"}:
            rows[label] = line

    parts = rows.get("parts")
    labour = rows.get("labour") or rows.get("labor")
    subtotal = rows.get("subtotal")
    if not (parts and labour and subtotal):
        return None

    def first_amount(line):
        values = _values_in_summary(line.text)
        return values[0] if values else None

    part_value = first_amount(parts)
    labour_value = first_amount(labour)
    subtotal_value = first_amount(subtotal)
    towing = rows.get("towingcharges")
    zero = amount("0")
    towing_value = first_amount(towing) if towing else zero
    if None in (part_value, labour_value, subtotal_value):
        return None
    return (
        subtotal_value
        if abs(subtotal_value - part_value - labour_value - (towing_value or zero)) <= amount("0.02")
        else None
    )


def _aligned_estimate(lines, index):
    """Read the estimate side of a reconciled two-column assessment summary."""
    net = lines[index]
    summary = []
    for line in reversed(lines[:index]):
        if line.page != net.page:
            return None
        if compact(line.text) == "summaryofassessment":
            break
        summary.append(line)
    else:
        return None

    columns = [(right, value) for _, right, text in net.cells if (value := amount(text)) is not None]
    if len(columns) < 2:
        return None

    def at_column(line, column):
        values = [value for _, right, text in line.cells
                  if abs(right - column) <= 5 and (value := amount(text)) is not None]
        return values[0] if len(values) == 1 else None

    rows = {}
    for line in summary:
        label = compact(line.cells[0][2])
        if label in rows:
            return None
        if label in {"parts", "labour", "labor", "towingcharges", "subtotal", "lessexcessclause"}:
            rows[label] = line
    parts = rows.get("parts")
    labour = rows.get("labour") or rows.get("labor")
    subtotal = rows.get("subtotal")
    deduction = rows.get("lessexcessclause")
    if not (parts and labour and subtotal and deduction):
        return None
    if any(row.confidence < MIN_FIELD_CONFIDENCE for row in (parts, labour, subtotal, deduction)):
        return None
    towing = rows.get("towingcharges")
    reconciled = []
    # Some PDFs print an extra numeric value on Net Payable. Rather than
    # requiring exactly two numbers, test every column pair and accept only a
    # uniquely reconciled estimate/assessed pair.
    for estimate_x, estimate in columns:
        part_value, labour_value, subtotal_value = (
            at_column(row, estimate_x) for row in (parts, labour, subtotal)
        )
        towing_value = at_column(towing, estimate_x) if towing else None
        if part_value is None or labour_value is None or subtotal_value != estimate:
            continue
        if at_column(deduction, estimate_x) is not None:
            continue
        if abs(estimate - part_value - labour_value - (towing_value or 0)) > amount("0.02"):
            continue
        for assessed_x, _ in columns:
            if assessed_x == estimate_x:
                continue
            if at_column(deduction, assessed_x) is not None:
                reconciled.append(estimate)
                break
    unique = list(dict.fromkeys(reconciled))
    if len(unique) == 1:
        return unique[0]

    # Geometry can be noisy in printed/scan-derived PDFs even when the summary
    # text itself is perfectly readable. Fall back to arithmetic reconciliation
    # of the printed summary totals.
    return _summary_estimate_by_totals(summary)


def _assessment_fields(claim, lines, labour, warnings):
    invoice_rows = []
    estimate_rows = []
    depreciation_rows = defaultdict(list)
    for index, line in enumerate(lines):
        raw = _after(line.text, ("Workshop Invoice No", "Workshop Invoice Number", "Repairer Invoice No", "Workshop Invoice Date"))
        if raw:
            # OCR can join the invoice number, date label, and date into one token.
            date_label = re.search(r"(?:(?<=\d)|(?<!\w))dated?\s*[:.-]?\s*(?=\d)", raw, re.I)
            invoice_date = _date(raw[date_label.end():]) if date_label else ""
            invoice = raw[:date_label.start()].strip(" :;,-") if invoice_date else raw.split()[0]
            if _value("workshop_invoice_no", invoice) and not _date(invoice):
                invoice_rows.append(Line(line.page, line.top, ((0, 1, f"Invoice ID {invoice}"),), line.confidence, line.extra_page))
                if invoice_date:
                    invoice_rows.append(Line(line.page, line.top, ((0, 1, f"Invoice Date {invoice_date}"),), line.confidence, line.extra_page))
            elif _date(raw):
                invoice_rows.append(Line(line.page, line.top, ((0, 1, f"Invoice Date {_date(raw)}"),), line.confidence, line.extra_page))

        if (not claim.workshop_estimate_amount
                and _after(line.text, ("Net Payable",)) and line.confidence >= MIN_FIELD_CONFIDENCE):
            estimate = _aligned_estimate(lines, index)
            if estimate is not None:
                estimate_rows.append(replace(line, cells=((0, 1, f"Reconciled estimate {estimate:f}"),)))

        if match := re.search(r"\b(?:dep(?:reciation)?\.?\s+on\s+metal|metal\s+dep(?:reciation)?\.?)\s*(?:\(\s*in\s*%\s*\))?\s*[:=\-]?\s*(\d+(?:\.\d+)?)\s*%?", line.text, re.I):
            depreciation_rows["metal_depreciation_rate"].append(
                replace(line, cells=((0, 1, f"Rate {match[1]}"),))
            )
        # A printed amount is not a percentage. A wrapped percentage is
        # accepted when it agrees with the deduction and verified paint total.
        if re.search(r"\bpaint(?:ing)?\s+dep(?:reciation)?\b|less cost of paint material", line.text, re.I):
            rate = re.search(r"\b(\d+(?:\.\d+)?)\s*%\s*(?:$|[;,)])", line.text)
            if rate:
                depreciation_rows["paint_depreciation_rate"].append(
                    replace(line, cells=((0, 1, f"Rate {rate[1]}"),))
                )
            elif index + 1 < len(lines):
                next_line = lines[index + 1]
                wrap = re.fullmatch(r"(\d+(?:\.\d+)?)\s*%?", next_line.text)
                deduction = _values_in_summary(line.text)
                if (wrap and next_line.page == line.page and next_line.top - line.top < 30
                        and next_line.confidence >= MIN_FIELD_CONFIDENCE
                        and deduction and labour["painting"] > 0
                        and abs(labour["painting"] * amount(wrap[1]) / 100 - deduction[-1]) <= amount("0.02")):
                    depreciation_rows["paint_depreciation_rate"].append(
                        replace(line, cells=((0, 1, f"Rate {wrap[1]}"),))
                    )

    _read_field(claim, "workshop_invoice_no", invoice_rows, ("Invoice ID",), warnings=warnings)
    _read_field(claim, "workshop_invoice_date", invoice_rows, ("Invoice Date",), warnings=warnings)
    _read_field(claim, "workshop_estimate_amount", estimate_rows, ("Reconciled estimate",), warnings=warnings)
    if claim.workshop_estimate_amount and estimate_rows:
        # A fully reconciled summary is stronger evidence than a prior
        # low-confidence OCR warning for the same field.
        warnings.pop("workshop_estimate_amount", None)
    for key, rows in depreciation_rows.items():
        _read_field(claim, key, rows, ("Rate",), warnings=warnings)
    if not claim.initial_loss_amount and claim.workshop_estimate_amount:
        _set(claim, "initial_loss_amount", _initial_loss_75_percent(claim.workshop_estimate_amount),
             f"75% of Workshop Estimate · {claim._excel_coords['workshop_estimate_amount']}")
        warnings.pop("initial_loss_amount", None)


def _document_identity(lines):
    fields = defaultdict(dict)
    aliases = (*FIELDS["header"]["claim_no"], *FIELDS["header"]["policy_number"],
               *FIELDS["vehicle"]["vehicle_registration_number"])
    for line in _label_rows(lines, aliases):
        if getattr(line, "confidence", 1) < MIN_FIELD_CONFIDENCE:
            continue
        for key in ("claim_no", "policy_number"):
            configured = FIELDS["header"][key]
            if (raw := _after(line.text, configured)) and (value := _value(key, raw)):
                fields[key].setdefault(compact(value), value)
        if raw := _after(line.text, FIELDS["vehicle"]["vehicle_registration_number"]):
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
    identity, _ = _document_identity(lines)
    return heading, sections, identity


def _is_supporting_report(lines):
    cover = [line for line in lines if line.page == 1]
    for line in cover[:20]:
        if SUPPORTING_REPORT_HEADING.match(compact(line.text)):
            return True
        if REPORT_HEADING.match(line.text) or (
            line.text.casefold().startswith("ref") and REPORT_HEADING.search(line.text)
        ):
            return False
    return False


def find_oic_report(folder, *, preferred=None, stop_cb=None):
    """Prefer a complete report by content, checking up to three pages with OCR when needed."""
    from app.data.pdf_report_reader import read_lines

    files = []
    seen = set()
    for path in sorted(Path(folder).iterdir(), key=lambda p: p.name.casefold()):
        if stop_cb and stop_cb():
            raise InterruptedError("PDF report selection cancelled")
        if not path.is_file() or path.suffix.casefold() != ".pdf":
            continue
        name = compact(path.stem).lstrip("0123456789")
        if (name.startswith(("claimothersdocuments", "vehiclephoto", "reinspection", "spotsurvey", "supplementarysurvey"))
                or "feebill" in name or name.startswith("sfbill")):
            continue
        if not (re.search(r"survey|final|assess|report", name) or (preferred and Path(preferred) == path)):
            # An arbitrary filename can still contain the report, but attachments
            # with explicit names are never alternative main reports.
            if re.search(r"photo|invoice|estimate|policy|license|licence|cheque|receipt|card|claimform|voucher|^rc|^dl", name):
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
            re.search(r"survey.*report|final.*report|assessmentreport|printableassessment", name)
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
                    any("gstsummaryspares" in row or "sparesgstsummary" in row for row in body_labels),
                    any("gstsummarylabour" in row or "labourgstsummary" in row for row in body_labels),
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
            raise ValueError(f"More than one claim report found: {best_path.name} and {path.name}. Keep the PDF for this claim and rescan.")
        if rank == best_rank:
            if best_rank[0] and best_identity == identity and preferred:
                preferred_path = Path(preferred).resolve()
                if best_path.resolve() == preferred_path:
                    continue
                if path.resolve() == preferred_path:
                    best_path = path
                    continue
            raise ValueError(f"Multiple possible survey PDFs: {best_path.name} and {path.name}. Keep the final report and rescan.")
    return str(best_path)


def read_oic_pdf_report(path, *, stop_cb=None):
    pages = read_pages(path, stop_cb=stop_cb)
    lines = [
        replace(line, cells=tuple((left, right, _text(text)) for left, right, text in line.cells))
        for page in pages for line in page.lines
    ]
    if not lines:
        raise ValueError("The survey PDF has no readable text. Try a clearer scan or the original PDF.")
    if _is_supporting_report(lines):
        raise ValueError("This PDF is a supporting survey report. Select the final survey report and rescan.")
    heading, sections, identity = _report_evidence(lines)
    if not (heading or (identity and {"vehicle", "driver", "survey"} & sections.keys())):
        raise ValueError("This PDF does not have readable survey-report headings and claim or vehicle identifiers. Select the final survey report and rescan.")

    claim = ClaimData(
        portal_id="oic", source_report_path=str(path),
        invoice_amount_without_gst="", invoice_gst_amount="",
    )
    for key in FEE_FIELDS:
        setattr(claim, key, "")
    warnings = {}
    mapping = load_field_mapping(portal_id="oic")
    header = sections["header"]
    for group, fields in FIELDS.items():
        configured = {}
        for key, aliases in fields.items():
            custom = mapping.get(key, {}).get("search_labels", [])
            if isinstance(custom, str):
                custom = [custom]
            # Broad labels such as Address, Date and GST are meaningful only
            # inside the correct section. NET PAYABLE needs column context.
            extra = tuple(alias for alias in custom if compact(alias) not in {
                "address", "date", "time", "gst", "route", "insurer", "insured", "netpayable", "totalnetforparts",
                "lessdepreciation", "gstsummaryspares", "gstsummarylabour",
            })
            configured[key] = (*aliases, *extra)
        rows = sections[group]
        if group in {"vehicle", "driver", "workshop", "survey"} and not rows:
            rows = lines
            for key, aliases in configured.items():
                scoped_aliases = {"address", "datestart", "dateofissue", "licenceno", "licenseno", "validtill", "validupto", "gstin", "dateofbirth", "dob"}
                configured[key] = tuple(alias for alias in aliases if compact(alias) not in scoped_aliases)
        label_boundaries = tuple(alias for aliases in configured.values() for alias in aliases)
        if group == "driver":
            label_boundaries += IGNORED_DRIVER_LABELS
        label_rows = tuple(_label_rows(rows, label_boundaries))
        rows_by_field = defaultdict(list)
        for row in label_rows:
            specificity = {
                key: match.end() for key, aliases in configured.items()
                if (match := _match_label(row.text, aliases))
            }
            if specificity:
                longest = max(specificity.values())
                for key, length in specificity.items():
                    if length == longest:
                        rows_by_field[key].append(row)
        for key, aliases in configured.items():
            _read_field(claim, key, rows_by_field[key], aliases, warnings=warnings)

    for line in lines:
        narrative = _after(line.text, ("Cause and Nature of Accident", "Cause & Nature of Accident", "Nature of Accident"))
        if narrative is not None and line in sections["cause"]:
            index = sections["cause"].index(line)
            body = " ".join(filter(None, (narrative, *(row.text for row in sections["cause"][index + 1:]))))
            if body and line.confidence >= MIN_FIELD_CONFIDENCE:
                _set(claim, "cause_nature_of_accident", body, line.source)
            break
    for line in header:
        report_date = re.search(r"\bDate\s*:\s*(.*)", line.text, re.I)
        if (report_date and not claim.expected_completion_date and "expected_completion_date" not in warnings
                and (REPORT_HEADING.search(line.text) or "finalsurveyreport" in compact(line.text))
                and line.confidence >= MIN_FIELD_CONFIDENCE):
            _set(claim, "expected_completion_date", _date(report_date[1]), line.source)
        expiry = SURVEYOR_EXPIRY_LABEL.search(line.text)
        if (expiry and not claim.surveyor_license_expiry_date and "surveyor_license_expiry_date" not in warnings
                and _after(line.text, FIELDS["header"]["surveyor_license_number"]) is not None
                and line.confidence >= MIN_FIELD_CONFIDENCE):
            _set(claim, "surveyor_license_expiry_date", _date(line.text[expiry.end():]), line.source)
    if header and not claim.surveyor_name:
        for previous, line in zip(header, header[1:]):
            if re.match(r"surveyor\s*(?:&|and)\s*loss\s*assessor", line.text, re.I):
                name = re.split(r"\s+\d", previous.text, maxsplit=1)[0]
                if re.fullmatch(r"[A-Za-z][A-Za-z .'-]{5,80}", name) and previous.confidence >= MIN_FIELD_CONFIDENCE:
                    _set(claim, "surveyor_name", name, previous.source)
                break
    for line in sections["driver"]:
        if _after(line.text, FIELDS["driver"]["driver_name"]) is not None:
            dob = re.search(r"\b(?:DOB|Date\s+of\s+Birth)\s*[:.-]?\s*(.*)", line.text, re.I)
            if dob and not claim.dob_of_driver and "dob_of_driver" not in warnings and line.confidence >= MIN_FIELD_CONFIDENCE:
                _set(claim, "dob_of_driver", _date(dob[1]), line.source)
        if claim.driver_address and not claim.driver_pin_code:
            if pin := re.search(r"\b([1-9]\d{5})\b", claim.driver_address):
                _set(claim, "driver_pin_code", pin[1], claim._excel_coords["driver_address"])
    for line in sections["vehicle"]:
        if raw := _after(line.text, FIELDS["vehicle"]["vehicle_registration_number"]):
            registration, office = _registration(raw)
            if (registration == claim.vehicle_registration_number and office
                    and not claim.rto_name and "rto_name" not in warnings
                    and line.confidence >= MIN_FIELD_CONFIDENCE):
                _set(claim, "rto_name", office, line.source)
    for line in sections["survey"]:
        if _after(line.text, FIELDS["survey"]["date_of_survey"]) is not None and line.confidence >= MIN_FIELD_CONFIDENCE:
            hh, mm = extract_time(line.text)
            if hh:
                claim.time_hh, claim.time_mm = hh, mm
                _set(claim, "time_of_survey", f"{hh}:{mm}", line.source)
                break
    if not claim.place_of_survey and "place_of_survey" not in warnings:
        _read_field(claim, "place_of_survey", sections["workshop"], FIELDS["survey"]["place_of_survey"],
                    warnings=warnings)
        # In the original survey layout the Workshop Name is printed inside a
        # section explicitly titled Place of Survey.
        if (not claim.place_of_survey and claim.workshop_name and "place_of_survey" not in warnings
                and any(re.fullmatch(r"(?:\d{1,2})?placeofsurvey", compact(row.text))
                        for row in sections["workshop"])):
            _set(claim, "place_of_survey", claim.workshop_name, claim._excel_coords["workshop_name"])
    _read_field(claim, "payment_to", lines, (
        "The payment to be made in favour of", "Payment to be made in favour of",
        "Payment to be made to", "Payment in favour of", "Payment To", "Payable To",
        "Claim Type", "Payment Option", "Settlement Type",
    ), warnings=warnings)
    if claim.payment_to:
        claim.bank_payment_to = "Dealer" if claim.payment_to == "REPAIRER" else "Insured"

    parts, labour, taxes, sources, review = read_assessment(pages)
    claim._oic_pdf_assessment = (parts, labour)
    claim._oic_pdf_item_sources = sources
    for section, (values, source) in taxes.items():
        for key, value in values.items():
            _set(claim, f"{section}_{'taxable' if key == 'taxable' else key}_amount", format(value, "f"), source)
    if len(taxes) == 2 and all("GST" not in issue for issue in review):
        claim._calculate_oic_invoice_amounts()
        for key in ("invoice_amount_without_gst", "invoice_gst_amount"):
            if claim._excel_coords.get(key):
                claim._excel_coords[key] += " · " + ", ".join(dict.fromkeys(src for _, src in taxes.values()))
    _assessment_fields(claim, sections["assessment"], labour, warnings)
    _, licence_type_source = resolve_license_type(claim.class_of_vehicle, claim.license_type_of_driver)
    if licence_type_source in {"ambiguous", "missing"}:
        review.append("Licence Type could not be determined from the survey PDF. Review the vehicle class and licence type.")
    if claim.driver_license_number:
        from .automation.basic_details_module import _split_license_number

        licence = _split_license_number(claim.driver_license_number)
        if licence is None:
            warnings["driver_licence_format"] = "Review Driving Licence Number. The PDF value cannot fill OIC's two-letter code and two six-digit fields."
        elif licence[3]:
            warnings["driver_licence_format"] = "Review Driving Licence Number. OIC requires confirmation before omitting extra digits."
    if claim.nil_depreciation == "No":
        for key in ("metal_depreciation_rate", "paint_depreciation_rate"):
            if key in warnings:
                review.append(warnings.pop(key))
    for first, second in (
        ("dob_of_driver", "driver_license_issue_date"),
        ("driver_license_issue_date", "driver_license_expiry_date"),
        ("date_of_accident", "date_of_survey"),
    ):
        earlier, later = getattr(claim, first), getattr(claim, second)
        if earlier and later and datetime.strptime(earlier, "%d/%m/%Y") > datetime.strptime(later, "%d/%m/%Y"):
            review.append(
                f"{REQUIRED.get(first, 'Accident Date')} on {claim._excel_coords[first]} is later than "
                f"{REQUIRED[second]} on {claim._excel_coords[second]}."
            )
    for key, label in REQUIRED.items():
        if key in warnings or not str(getattr(claim, key) or "").strip():
            review.append(warnings.pop(key, f"{label} is missing or unreadable in the survey PDF."))
    identity_warnings = [warnings.pop(key) for key in ("claim_no", "policy_number") if key in warnings]
    review.extend(identity_warnings)
    if not claim.claim_no and not claim.policy_number and not identity_warnings:
        review.append("Claim Number or Policy Number is required in the survey PDF.")
    claim._oic_pdf_review_errors = list(dict.fromkeys(review))
    claim._oic_pdf_review_warnings = list(warnings.values())
    claim.calculate_derived_fields()
    return claim


def supplement_oic_pdf_fees(claim, folder, *, stop_cb=None):
    """Use supporting fee bills only when their own identifier matches the report."""
    from pdfminer.pdfexceptions import PDFException
    from pdfplumber.utils.exceptions import PdfminerException

    from app.data.pdf_report_reader import read_lines

    fee_fields = [key for key in FEE_FIELDS if not claim._excel_coords.get(key)]
    if not fee_fields:
        return
    verified = {key: getattr(claim, key, "") for key in ("claim_no", "policy_number", "vehicle_registration_number")}
    candidates = defaultdict(list)
    for path in Path(folder).glob("*.pdf"):
        if stop_cb and stop_cb():
            raise InterruptedError("PDF fee bill reading cancelled")
        name = compact(path.stem)
        if "feebill" not in name and not name.startswith("sfbill"):
            continue
        try:
            rows = read_lines(str(path), max_pages=4)
        except (OSError, ValueError, PDFException, PdfminerException):
            claim._oic_pdf_review_warnings.append(f"Could not read optional fee bill {path.name}. Review or replace the file.")
            continue
        identity, conflicts = _document_identity(rows)
        if conflicts:
            claim._oic_pdf_review_warnings.append(
                f"Conflicting claim, policy, or vehicle identifiers in fee bill {path.name}. Review this bill."
            )
            continue
        shared = {key for key, value in identity.items() if value and verified.get(key)}
        if not shared or any(compact(verified[key]) != compact(identity[key]) for key in shared):
            continue
        for key in fee_fields:
            for row in rows:
                raw = _after(row.text, FIELDS["fees"][key])
                if raw is not None and (value := _value(key, raw)):
                    candidates[key].append((value, f"{row.source} · {path.name}"))
    for key, values in candidates.items():
        unique = {value for value, _ in values}
        if len(unique) == 1:
            _set(claim, key, *values[0])
        else:
            claim._oic_pdf_review_warnings.append(f"Matching fee bills disagree on {key.replace('_', ' ')}. Review the bill amounts.")
    if not claim._excel_coords.get("professional_fee"):
        claim._oic_pdf_review_warnings.append("Professional Fee was not found in the survey PDF or a matching fee bill.")
    if candidates:
        claim.calculate_derived_fields()
