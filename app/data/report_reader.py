"""Facade for the existing Excel reader and the local survey-report PDF reader."""

from pathlib import Path
from typing import Optional


def extract_claim_data_from_report(report_path: str, portal_id: str = "uiic", *, stop_cb=None):
    ext = Path(report_path).suffix.lower()
    if ext in {".xls", ".xlsx", ".xlsm"}:
        from app.data.excel_reader import extract_claim_data
        return extract_claim_data(report_path, portal_id=portal_id)
    if ext == ".pdf":
        if portal_id == "oic":
            from app.portals.oic.pdf_report import read_oic_pdf_report
            return read_oic_pdf_report(report_path, stop_cb=stop_cb)
        if portal_id == "newindia":
            from app.portals.newindia.pdf_report import read_newindia_pdf_report
            return read_newindia_pdf_report(report_path, stop_cb=stop_cb)
        from app.data.pdf_report_reader import read_pdf_report
        return read_pdf_report(report_path, portal_id=portal_id)
    raise ValueError(f"Unsupported survey report format: {ext or 'unknown'}")


def find_main_report_source(folder: str, scan_result, portal_id: str = "uiic", *, stop_cb=None) -> Optional[str]:
    """Prefer the existing main Excel; otherwise find the most likely survey-report PDF."""
    excel_path = getattr(scan_result, "excel_path", None)
    if excel_path:
        return excel_path

    assessment_files = getattr(scan_result, "assessment_files", {}) or {}
    preferred = assessment_files.get("survey_report")
    if portal_id == "oic":
        from app.portals.oic.pdf_report import find_oic_report
        return find_oic_report(folder, preferred=preferred, stop_cb=stop_cb)
    if portal_id == "newindia":
        from app.portals.newindia.pdf_report import find_newindia_report
        return find_newindia_report(folder, preferred=preferred, stop_cb=stop_cb)

    from app.data.pdf_report_reader import find_pdf_survey_report
    return find_pdf_survey_report(folder, preferred=preferred)
