"""Names and safe replacement for files produced by a New India folder scan."""

import filecmp
import ntpath
import os
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from app.portals.oic.generated_files import has_generated_owner, is_generated_fee_bill, publish_generated


ASSESSMENT_WORKBOOK = "auto_primary_assessment.xlsx"
ASSESSMENT_SHEET = "Primary_Assessment_Template"
CLAIM_RELATED_PDF = "claim_others_documents_current.pdf"
SURVEY_REPORT_PDF = "survey_report.pdf"
_LEGACY_PRINTABLE_PDF = "Printable_Assessment.pdf"
_PRINTABLE_DEFAULTS = ("Printable_Assessment.xlsx", SURVEY_REPORT_PDF)
_LEGACY_PRINTABLE_DEFAULTS = ("Printable_Assessment.xlsx", _LEGACY_PRINTABLE_PDF)
_LEGACY_NAMES = re.compile(
    r"(?:auto_primary_assessment(?:_\d+)?(?:\.xlsx|_audit\.txt)"
    r"|primary_assessment_skipped_audit\.txt"
    r"|claim_others_documents(?:_current|_\d{8}_\d{6})?\.pdf"
    r"|claim_related_document_merged\.pdf"
    r"|reinspection\.xlsx|reinspection_report\.pdf"
    r"|re-inspection report format\.(?:xlsx|pdf)"
    r"|vehicle_photo_[1-4]\.(?:pdf|jpe?g|png|gif|bmp|tiff?)"
    r"|work_approval_fallback\.(?:pdf|jpe?g|png|gif|bmp|tiff?|docx?))",
    re.IGNORECASE,
)


def printable_names(settings):
    names = []
    for key, extension, default in zip(
        ("printable_output_excel_name", "printable_output_pdf_name"), (".xlsx", ".pdf"), _PRINTABLE_DEFAULTS
    ):
        raw_name = ntpath.basename(str(settings.get(key) or default).strip()) or default
        if key == "printable_output_pdf_name" and raw_name.casefold() == _LEGACY_PRINTABLE_PDF.casefold():
            name = SURVEY_REPORT_PDF
        else:
            name = raw_name
        names.append(name if name.lower().endswith(extension) else name + extension)
    return tuple(names)


def _is_legacy_name(name, settings):
    if _LEGACY_NAMES.fullmatch(name):
        return True
    for filename in (*_LEGACY_PRINTABLE_DEFAULTS, *printable_names(settings)):
        # A user-supplied survey_report.pdf is protected unless App3 owns it.
        if filename.casefold() == SURVEY_REPORT_PDF:
            continue
        stem, extension = os.path.splitext(filename)
        if re.fullmatch(re.escape(stem) + r"(?:_\d{8}_\d{6})?" + re.escape(extension), name, re.I):
            return True
    return False


def is_scan_output(path, settings):
    name = Path(path).name
    return (_is_legacy_name(name, settings)
            or name.casefold() == str(settings.get("reinspection_output_filename") or "").casefold()
            or is_generated_fee_bill(path)
            or has_generated_owner(path, portal_id="newindia"))


def staging_folder(output_folder):
    # Use the same filesystem as the final file, and keep intermediate files
    # below the claim folder's top level so a rescan cannot discover them.
    return TemporaryDirectory(prefix=".nia-scan-", dir=output_folder)


def _is_legacy_assessment(path):
    if os.path.islink(path):
        return False
    try:
        with ZipFile(path) as workbook:
            root = ElementTree.fromstring(workbook.read("xl/workbook.xml"))
        return any(sheet.get("name") == ASSESSMENT_SHEET for sheet in root.findall(".//{*}sheet"))
    except (OSError, BadZipFile, KeyError, ElementTree.ParseError):
        return False


def publish_scan_output(staged, target, settings=None, *, stop_cb=None, same_copy=False):
    if stop_cb and stop_cb():
        return None
    target_name = Path(target).name
    legacy = _is_legacy_name(target_name, settings or {})
    if target_name.casefold() == ASSESSMENT_WORKBOOK and os.path.isfile(target):
        legacy = _is_legacy_assessment(target)
    if same_copy and os.path.isfile(target) and not os.path.islink(target):
        # A legacy assessment_report PDF may be user-provided. Only adopt it
        # if it is an exact copy of the current survey, or already tracked.
        legacy = filecmp.cmp(staged, target, shallow=False)
    return publish_generated(staged, target, portal_id="newindia", allow_legacy=legacy, stop_cb=stop_cb)


def refresh_printable_output(source_excel_path, output_folder, settings, logs, stop_cb=None):
    from app.data.printable_excel_service import process_printable_output

    excel_name, pdf_name = printable_names(settings)
    fixed_settings = {**settings, "printable_output_excel_name": excel_name,
                      "printable_output_pdf_name": pdf_name, "printable_use_timestamp": False}
    with staging_folder(output_folder) as stage:
        created = process_printable_output(source_excel_path, stage, fixed_settings, logs, stop_cb=stop_cb)
        published_pdf = False
        for staged in map(Path, created or ()):
            if staged.name.casefold() != pdf_name.casefold():
                # The workbook is only a temporary step in rendering the PDF.
                continue
            name = staged.name
            try:
                target = Path(output_folder) / name
                if target.exists() and os.path.samefile(target, source_excel_path):
                    raise FileExistsError("This filename is used by the source workbook.")
                published_pdf = bool(publish_scan_output(staged, target, settings, stop_cb=stop_cb))
            except (OSError, ValueError) as exc:
                logs.append(f"Warning: {name} skipped. {exc}")
        if not published_pdf and not (stop_cb and stop_cb()):
            logs.append("Warning: Printable survey PDF could not be prepared.")
