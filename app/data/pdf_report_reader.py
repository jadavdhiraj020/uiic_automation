"""Conservative local PDF survey-report reader.

Uses existing per-portal field mappings and returns the same ClaimData object as
Excel.  Missing/uncertain values stay blank; no cloud AI service is used.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
import logging
import os
import re

from app.data.data_model import ClaimData
from app.data.excel_reader import (
    _calculate_professional_fee,
    _format_date,
    _initial_loss_75_percent,
)
from app.utils import load_automation_defaults, load_field_mapping

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PdfLine:
    page: int
    line: int
    text: str

    @property
    def source(self) -> str:
        return f"PDF p{self.page} line {self.line}"


PDF_ALIASES = {
    "claim_no": ["Claim No.", "Claim No", "Claim Number", "Claim #"],
    "date_of_survey": ["Date & Time of Survey", "Date and Time of Survey", "Date of Survey", "Survey Date"],
    "time_of_survey": ["Time of Survey", "Survey Time"],
    "place_of_survey": ["Place of Survey", "Surveyed At", "Inspection Place"],
    "date_of_accident": ["Date & Time of Accident", "Date and Time of Accident", "Date of Accident", "Accident Date"],
    "vehicle_registration_number": ["Registered Number", "Registration No.", "Registration No", "Regn No", "Vehicle No"],
    "registered_owner_name": ["Registered Owner", "Insured", "Name of Insured"],
    "date_of_registration": ["Date of Registration", "Registration Date", "Regn Date"],
    "chassis_no": ["Chassis Number", "Chassis No.", "Chassis No"],
    "engine_no": ["Engine Number", "Engine No.", "Engine No"],
    "vehicle_make": ["Make / Variant/ Model /Color", "Make / Model", "Make of Vehicle", "Vehicle Make"],
    "type_of_body": ["Type of Body", "Body Type"],
    "class_of_vehicle": ["Class of vehicle", "Class of Vehicle", "Vehicle Class"],
    "odometer_reading": ["Odometer Reading", "Odometer"],
    "driver_name": ["Name of Driver", "Driver Name", "Name of the Driver"],
    "dob_of_driver": ["DOB of Driver", "Driver DOB", "Date of Birth of Driver"],
    "driver_license_number": ["Motor Driver License Number", "Driving License Number", "Licence No.", "License No", "DL No"],
    "driver_license_issue_date": ["Date of Issue", "DL Issue Date", "License Issue Date"],
    "driver_license_expiry_date": ["Valid up to (NTV)", "Valid Till", "License Valid Till", "DL Expiry Date"],
    "cause_nature_of_accident": ["CAUSE & NATURE OF ACCIDENT", "CAUSE AND NATURE OF ACCIDENT", "Nature of Accident"],
    "mobile_no": ["Mobile", "Mob", "Contact No", "Contact Number"],
    "email_id": ["E-mail", "Email", "E mail"],
    "initial_loss_amount": ["Initial Loss Assessment", "Initial Loss", "Net Payable"],
    "towing_charges": ["Add Towing Charges", "Towing Charges", "Towing Charge"],
    "voluntary_excess": ["Voluntary Excess", "Voluntry Excess"],
    "compulsory_excess": ["Less Compulsory Excess", "Compulsory Excess", "(-) Excess", "Less Excess"],
    "less_compulsory_excess": ["Less Compulsory Excess", "Compulsory Excess", "(-) Excess", "Less Excess"],
    "imposed_excess": ["Less Imposed Excess", "Imposed Excess", "(-) Impose Excess"],
    "less_imposed_excess": ["Less Imposed Excess", "Imposed Excess", "(-) Impose Excess"],
    "salvage_value": ["Less Salvage Value", "Salvage Value", "(-) Salvage", "Less Salvage"],
    "salvage_amount": ["Less Salvage Value", "Salvage Value", "(-) Salvage", "Less Salvage"],
    "net_salvage": ["Net Salvage", "Salvage Value", "(-) Salvage"],
    "workshop_invoice_no": ["Workshop Invoice No", "Repairer Invoice No", "Tax Invoice No", "Invoice No"],
    "workshop_invoice_date": ["Workshop Invoice Date", "Repairer Invoice Date", "Tax Invoice Date", "Invoice Date"],
    "final_report_no": ["Ref. No.", "Ref No", "Reference No", "Report No"],
    "final_report_date": ["Report Date", "Final Report Date"],
    "traveling_expenses": ["Travelling Expenses", "Traveling Expenses", "Conveyance", "Conveyance Charges"],
    "professional_fee": ["Professional Fees", "Professional Fee", "Survey Fee", "Survey Fees"],
    "survey_fee": ["Professional Fees", "Professional Fee", "Survey Fee", "Survey Fees"],
    "reinspection_fee": ["Reinspection Fee", "Re-inspection Fee"],
    "daily_allowance": ["Daily Allowance"],
    "photo_charges": ["Photographs", "Photograph", "Photo Charges", "Photography"],
    "workshop_estimate_amount": ["Workshop Estimate Amount", "Estimate Amount", "Net Payable"],
    "surveyor_license_number": ["License No.", "Licence No.", "Surveyor License Number"],
    "surveyor_license_expiry_date": ["Date of Expiry", "License Expiry Date"],
}

DATE_RX = re.compile(r"\b(\d{1,2}[\-/\.]\d{1,2}[\-/\.]\d{2,4})\b")
TIME12_RX = re.compile(r"\b(\d{1,2})[.:](\d{2})\s*([APap]\.?[Mm]\.?)\b")
TIME24_RX = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b")
EMAIL_RX = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
MOBILE_RX = re.compile(r"(?<!\d)(?:\+?91[\s\-]?)?([5-9]\d{9})(?!\d)")
AMOUNT_RX = re.compile(r"(?<![A-Za-z0-9])(?:Rs\.?\s*[:\-]?\s*|INR\s*[:\-]?\s*|₹\s*)?(-?\d[\d,]*(?:\.\d+)?)", re.I)
ID_RX = re.compile(r"([A-Za-z0-9][A-Za-z0-9/_.\-]{1,80})")
UNSAFE_LABELS = {"address", "date", "time", "make", "email", "mobile"}


def norm(text: str) -> str:
    return " ".join((text or "").replace("\u00a0", " ").split())


def norm_label(text: str) -> str:
    return norm(text).lower().rstrip(":").strip()


def labels_for(field_name: str, cfg: dict) -> List[str]:
    raw = cfg.get("search_labels") or cfg.get("search_label") or []
    labels = [raw] if isinstance(raw, str) else list(raw)
    labels += PDF_ALIASES.get(field_name, [])
    seen = {}
    for label in labels:
        key = norm_label(str(label))
        if key and key not in UNSAFE_LABELS:
            seen.setdefault(key, str(label))
    return sorted(seen.values(), key=lambda x: len(norm_label(x)), reverse=True)


def field_type(field_name: str, cfg: dict) -> str:
    low = field_name.lower()
    if "email" in low:
        return "email"
    if "mobile" in low or low.endswith("phone"):
        return "mobile"
    if low == "time_of_survey" or low.endswith("_time"):
        return "time"
    if "date" in low or "dob" in low or "expiry" in low or "valid_upto" in low or "paid_upto" in low:
        return "date"
    if any(x in low for x in ("amount", "fee", "charges", "expense", "excess", "salvage", "gst", "assessment", "allowance", "towing", "parts_", "labour_")):
        return "amount"
    if cfg.get("allow_literal_values"):
        return "literal"
    if any(x in low for x in ("claim_no", "invoice_no", "license_number", "chassis", "engine", "registration_number", "reference_no")):
        return "id"
    return "text"


def after_label(line: str, label: str) -> Optional[str]:
    line2 = norm(line)
    label2 = norm(label).rstrip(":")
    if not label2:
        return None
    m = re.search(re.escape(label2), line2, re.I)
    if not m:
        return None
    before, after = line2[:m.start()], line2[m.end():]
    if before and before[-1:].isalnum() and label2[:1].isalnum():
        return None
    if after and after[:1].isalnum() and label2[-1:].isalnum():
        return None
    return after.lstrip(" \t:;.-–—")


def cut_next_label(text: str, current: str, all_labels: List[str]) -> str:
    best = None
    for other in all_labels:
        if norm_label(other) == norm_label(current):
            continue
        label = norm(other).rstrip(":")
        if not label:
            continue
        m = re.search(r"(?<![A-Za-z0-9])" + re.escape(label) + r"(?![A-Za-z0-9])", text, re.I)
        if m and m.start() > 0 and (best is None or m.start() < best):
            best = m.start()
    return text[:best].strip() if best is not None else text.strip()


def clean_amount(raw: str) -> Optional[str]:
    try:
        val = float(str(raw).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return str(int(val)) if val.is_integer() else f"{val:.2f}".rstrip("0").rstrip(".")


def extract_time(text: str) -> Tuple[str, str]:
    text = norm(text)
    text = re.sub(r"(\d{1,2}[\-/\.]\d{1,2}[\-/\.]\d{4})(?=\d{1,2}[:.]\d{2})", r"\1 ", text)
    text = DATE_RX.sub(" ", text)
    m = TIME12_RX.search(text)
    if m:
        h, mm = int(m.group(1)), int(m.group(2))
        ap = m.group(3).replace(".", "").lower()
        if ap == "pm" and h < 12:
            h += 12
        elif ap == "am" and h == 12:
            h = 0
        return f"{h:02d}", f"{mm:02d}"
    m = TIME24_RX.search(text)
    return (f"{int(m.group(1)):02d}", f"{int(m.group(2)):02d}") if m else ("", "")


def parse_value(text: str, kind: str) -> Optional[str]:
    text = norm(text)
    if not text:
        return None
    if kind == "date":
        m = DATE_RX.search(text)
        return _format_date(m.group(1)) if m else None
    if kind == "time":
        hh, mm = extract_time(text)
        return f"{hh}:{mm}" if hh else None
    if kind == "email":
        m = EMAIL_RX.search(text)
        return m.group(0) if m else None
    if kind == "mobile":
        m = MOBILE_RX.search(text)
        return m.group(1) if m else None
    if kind == "amount":
        matches = list(AMOUNT_RX.finditer(text))
        return clean_amount(matches[-1].group(1)) if matches else None
    if kind == "literal":
        m = re.search(r"\b(yes|no|na|n/a)\b", text, re.I)
        return m.group(1) if m else None
    if kind == "id":
        m = ID_RX.search(text)
        if not m:
            return None
        token = m.group(1).strip(".,:;")
        return None if token.lower() in {"no", "number", "na", "nil", "none"} else token
    value = text.strip(" :;-–—")
    return value or None


def read_lines(pdf_path: str, max_pages: Optional[int] = None) -> List[PdfLine]:
    import pdfplumber
    out: List[PdfLine] = []
    with pdfplumber.open(pdf_path) as pdf:
        pages = pdf.pages[:max_pages] if max_pages else pdf.pages
        for page_no, page in enumerate(pages, 1):
            text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            for line_no, raw in enumerate(text.splitlines(), 1):
                cleaned = norm(raw)
                if cleaned:
                    out.append(PdfLine(page_no, line_no, cleaned))
    return out


def ocr_lines(pdf_path: str, max_pages: int = 6) -> List[PdfLine]:
    """Local scanned-PDF fallback using the RapidOCR engine already bundled in App-3."""
    import tempfile

    try:
        import pypdfium2 as pdfium
        from app.automation.ocr_engine import run_shared_ocr
    except Exception as exc:
        logger.warning("Local scanned-PDF OCR unavailable: %s", exc)
        return []

    out: List[PdfLine] = []
    try:
        pdf = pdfium.PdfDocument(pdf_path)
        page_count = min(len(pdf), max_pages)
        for page_index in range(page_count):
            page = pdf[page_index]
            bitmap = page.render(scale=2.2)
            image = bitmap.to_pil()
            fd, temp_path = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            try:
                image.save(temp_path)
                result = run_shared_ocr(temp_path, cls=True)
                line_no = 0
                if result and result[0]:
                    for item in result[0]:
                        try:
                            text = item[1][0]
                        except Exception:
                            continue
                        cleaned = norm(str(text))
                        if cleaned:
                            line_no += 1
                            out.append(PdfLine(page_index + 1, line_no, cleaned))
            finally:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            try:
                page.close()
            except Exception:
                pass
        try:
            pdf.close()
        except Exception:
            pass
    except Exception as exc:
        logger.warning("Local scanned-PDF OCR failed: %s", exc)
        return []
    return out


def find_value(lines: List[PdfLine], field_name: str, cfg: dict, all_labels: List[str]):
    kind = field_type(field_name, cfg)
    for label in labels_for(field_name, cfg):
        for i, item in enumerate(lines):
            remainder = after_label(item.text, label)
            if remainder is None:
                continue
            remainder = cut_next_label(remainder, label, all_labels)
            value = parse_value(remainder, kind)
            if value:
                return value, item.source, label
            if i + 1 < len(lines) and lines[i + 1].page == item.page:
                value = parse_value(lines[i + 1].text, kind)
                if value:
                    return value, lines[i + 1].source, label
    return None, None, None


def report_date(lines: List[PdfLine]):
    for item in lines:
        if item.page > 1:
            break
        low = item.text.lower()
        if ("ref" in low or "report no" in low) and "date" in low:
            m = DATE_RX.search(item.text[low.rfind("date"):])
            if m:
                return _format_date(m.group(1)), item.source
    return None, None


def survey_time(lines: List[PdfLine]):
    for item in lines:
        if any(after_label(item.text, a) is not None for a in ("Date & Time of Survey", "Date and Time of Survey", "Date of Survey", "Survey Date")):
            hh, mm = extract_time(item.text)
            if hh:
                return hh, mm, item.source
    return "", "", None


def driver_dob(lines: List[PdfLine]):
    for item in lines:
        if re.search(r"\bAge\b", item.text, re.I):
            m = DATE_RX.search(item.text)
            if m:
                return _format_date(m.group(1)), item.source
    return None, None


def payment_to(lines: List[PdfLine]):
    for item in lines:
        low = item.text.lower()
        if "cashless" in low or "payment to repairer" in low or "favour of repairer" in low:
            return "REPAIRER", item.source
        if "reimbursement" in low or "payment to insured" in low:
            return "INSURED", item.source
    return "", None


def read_pdf_report(pdf_path: str, portal_id: str = "uiic") -> ClaimData:
    mapping = load_field_mapping(portal_id=portal_id)
    defaults = load_automation_defaults(portal_id=portal_id)
    lines = read_lines(pdf_path)
    used_ocr = False
    if not lines:
        lines = ocr_lines(pdf_path)
        used_ocr = bool(lines)
    if not lines:
        raise RuntimeError("PDF contains no readable text and local OCR could not read it.")

    claim = ClaimData(portal_id=portal_id or "uiic")
    claim.source_excel_path = ""
    claim.source_report_path = pdf_path

    all_labels: List[str] = []
    for name, cfg in mapping.items():
        if not name.startswith("_") and isinstance(cfg, dict):
            all_labels += labels_for(name, cfg)

    default_keys = {
        "remarks": "remarks_default",
        "fir_number": "missing_text_default",
        "police_station_name": "missing_text_default",
        "charged_us_motor_vehicle_act": "missing_text_default",
        "charged_us_ipc": "missing_text_default",
        "account_type": "account_type",
        "party_payment_method": "payment_method",
        "driver_relationship_with_insured": "relationship_with_insured",
        "re_inspection_required": "reinspection_required",
        "is_gst_applicable": "gst_applicable",
        "payment_invoice_in_name_of_nia": "invoice_in_company_name",
    }

    found = 0
    for field_name, cfg in mapping.items():
        if field_name.startswith("_") or not isinstance(cfg, dict):
            continue

        if field_name == "surveyor_observation":
            value = str(defaults.get("observation_default", "Ok") or "Ok")
            setattr(claim, field_name, value)
            claim._excel_coords[field_name] = "Automation Defaults"
            continue

        if field_name == "final_report_date":
            value, src = report_date(lines)
            label = "header Ref/Date"
        else:
            value, src, label = find_value(lines, field_name, cfg, all_labels)

        if not value and field_name == "dob_of_driver":
            value, src = driver_dob(lines)
            label = "Age/date fallback"

        if value:
            if field_name == "date_of_survey":
                hh, mm, tsrc = survey_time(lines)
                if hh:
                    claim.time_hh, claim.time_mm = hh, mm
                    claim.time_of_survey = f"{hh}:{mm}"
                    claim._excel_coords["time_of_survey"] = tsrc or src or "PDF"
            elif field_name == "time_of_survey":
                hh, mm = extract_time(str(value))
                if hh:
                    claim.time_hh, claim.time_mm = hh, mm
                    value = f"{hh}:{mm}"

            if "date" in field_name or "dob" in field_name:
                value = _format_date(str(value))
            if field_name == "initial_loss_amount":
                value = _initial_loss_75_percent(value)

            setattr(claim, field_name, str(value))
            claim._excel_coords[field_name] = src or "PDF"
            claim._excel_logs.append(f"  [PDF] {field_name}: '{value}' (Source: {src or 'PDF'}; label: {label or 'n/a'})")
            found += 1
        else:
            fallback = cfg.get("fallback_value")
            key = default_keys.get(field_name)
            if key and defaults.get(key) not in (None, ""):
                fallback = defaults.get(key)
            if fallback is not None:
                setattr(claim, field_name, str(fallback))
                claim._excel_logs.append(f"  [PDF DEFAULT] {field_name}: '{fallback}'")

    if not claim.time_hh:
        hh, mm, src = survey_time(lines)
        if hh:
            claim.time_hh, claim.time_mm = hh, mm
            claim.time_of_survey = f"{hh}:{mm}"
            claim._excel_coords["time_of_survey"] = src or "PDF"

    derive_fee = (
        portal_id == "uiic" or ("survey_fee" in mapping or "reinspection_fee" in mapping)
    ) and ("professional_fee" not in mapping or portal_id == "uiic")
    if derive_fee:
        claim.professional_fee = _calculate_professional_fee(
            getattr(claim, "survey_fee", "0"), getattr(claim, "reinspection_fee", "0")
        )

    if portal_id == "newindia":
        claim.photo_charges = str(defaults.get("photo_charges_default", "200") or "200")

    claim.calculate_derived_fields()

    pay, src = payment_to(lines)
    if pay:
        claim.payment_to = pay
        claim.bank_payment_to = "Dealer" if pay == "REPAIRER" else "Insured"
        claim._excel_coords["payment_to"] = src or "PDF"
    elif not claim.bank_payment_to:
        claim.bank_payment_to = "Insured"

    logger.info("PDF report read complete for %s: %s mapped fields found", portal_id, found)
    return claim


def looks_like_survey_report(pdf_path: str) -> int:
    name = Path(pdf_path).name.lower()
    score = 5 if "survey" in name else 0
    if "final" in name and "report" in name:
        score += 3
    if any(x in name for x in ("invoice", "estimate", "reinspection", "re_inspection", "policy", "license", "aadhaar", "aadhar", "pan", "cheque", "photo")):
        score -= 4
    try:
        text = "\n".join(x.text.lower() for x in read_lines(pdf_path, max_pages=3)[:180])
    except Exception:
        text = ""
    for marker, weight in (
        ("motor final survey report", 10),
        ("final survey report", 8),
        ("summary of assessment", 4),
        ("assessment of loss", 4),
        ("vehicle particulars", 3),
        ("accident & survey particulars", 3),
        ("accident and survey particulars", 3),
        ("surveyor & loss assessor", 3),
        ("surveyor and loss assessor", 3),
    ):
        if marker in text:
            score += weight
    if "tax invoice" in text and "survey report" not in text:
        score -= 8
    if "repair estimate" in text and "survey report" not in text:
        score -= 6
    return max(score, 0)


def find_pdf_survey_report(folder: str, preferred: Optional[str] = None) -> Optional[str]:
    if preferred and os.path.isfile(preferred) and Path(preferred).suffix.lower() == ".pdf":
        return preferred
    candidates = []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not os.path.isfile(path) or Path(name).suffix.lower() != ".pdf":
            continue
        score = looks_like_survey_report(path)
        if score > 0:
            candidates.append((score, path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], Path(item[1]).name.lower()))
    return candidates[0][1]
