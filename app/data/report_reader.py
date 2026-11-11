"""Facade for the existing Excel reader and the local survey-report PDF reader."""

from pathlib import Path
from typing import Optional


def extract_claim_data_from_report(report_path: str, portal_id: str = "uiic"):
    ext = Path(report_path).suffix.lower()
    if ext in {".xls", ".xlsx", ".xlsm"}:
        from app.data.excel_reader import extract_claim_data
        return extract_claim_data(report_path, portal_id=portal_id)
    if ext == ".pdf":
        from app.data.pdf_report_reader import read_pdf_report
        return read_pdf_report(report_path, portal_id=portal_id)
    raise ValueError(f"Unsupported survey report format: {ext or 'unknown'}")


def find_main_report_source(folder: str, scan_result) -> Optional[str]:
    """Prefer the existing main Excel; otherwise find the most likely survey-report PDF."""
    excel_path = getattr(scan_result, "excel_path", None)
    if excel_path:
        return excel_path

    assessment_files = getattr(scan_result, "assessment_files", {}) or {}
    preferred = assessment_files.get("survey_report")

    from app.data.pdf_report_reader import find_pdf_survey_report
    return find_pdf_survey_report(folder, preferred=preferred)
