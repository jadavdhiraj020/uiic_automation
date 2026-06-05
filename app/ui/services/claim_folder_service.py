import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from app.portals.registry import get_portal
from app.utils import (
    automation_defaults_paths,
    doc_mapping_paths,
    field_mapping_paths,
    ensure_dir,
    load_settings,
    settings_paths,
    user_data_dir,
)

logger = logging.getLogger(__name__)


@dataclass
class ClaimFolderProcessResult:
    success: bool
    scan_result: Optional[object]
    claim: Optional[object]
    log_lines: List[str]
    error: str = ""


@dataclass
class ScanRunContext:
    portal_id: str
    portal_display_name: str
    claim_folder_path: str
    scan_timestamp: str
    settings_paths: dict
    field_mapping_paths: dict
    doc_mapping_paths: dict
    automation_defaults_paths: dict


class ClaimFolderService:
    """Extracts and prepares claim + document data from a selected folder."""

    def __init__(self, config_dir: str, portal_id: str = "uiic"):
        self.config_dir = config_dir
        self.portal_id = portal_id or "uiic"

    def _write_scan_policy_audit_events(self, events: List[dict]) -> None:
        if not events:
            return
        try:
            log_dir = ensure_dir(user_data_dir("logs", self.portal_id.lower()))
            audit_path = os.path.join(log_dir, "scan_policy_audit.jsonl")
            with open(audit_path, "a", encoding="utf-8") as f:
                for event in events:
                    payload = {
                        "timestamp": datetime.now().isoformat(),
                        "source": "claim_folder_service",
                        **(event or {}),
                    }
                    f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("Failed to write scan policy audit events: %s", exc)

    @staticmethod
    def _is_newindia_generated_assessment(path: str) -> bool:
        name = os.path.basename(path or "").lower()
        return bool(re.fullmatch(r"auto_primary_assessment(?:_\d+)?\.xlsx", name))

    @staticmethod
    def _is_oic_generated_assessment(path: str) -> bool:
        name = os.path.basename(path or "").lower()
        return bool(re.fullmatch(r"auto_oic_assessment(?:_\d+)?\.xlsx", name))

    @staticmethod
    def _audit_path_for(path: str) -> str:
        root, _ext = os.path.splitext(path or "")
        return f"{root}_audit.txt" if root else ""

    def process_folder(
        self, folder: str, stop_cb: Optional[callable] = None
    ) -> ClaimFolderProcessResult:
        from app.data.excel_reader import extract_claim_data
        from app.data.folder_scanner import scan_folder

        logs: List[str] = [f"Scanning folder: {folder}"]
        try:
            if stop_cb and stop_cb():
                return ClaimFolderProcessResult(
                    False, None, None, ["Warning: Scan cancelled."], "Cancelled"
                )

            scan_result = scan_folder(
                folder, portal_id=self.portal_id, stop_cb=stop_cb
            )
            if not hasattr(scan_result, "generated_files"):
                scan_result.generated_files = []
            if not hasattr(scan_result, "policy_events"):
                scan_result.policy_events = []

            def _audit_path_for_generated(path: str) -> str:
                return self._audit_path_for(path)

            def _record_policy_event(event: dict) -> None:
                payload = {
                    "timestamp": datetime.now().isoformat(),
                    "portal_id": self.portal_id,
                    "folder_path": os.path.abspath(folder),
                    **(event or {}),
                }
                scan_result.policy_events.append(payload)
                self._write_scan_policy_audit_events([payload])

            def _mark_generated_file(path: str) -> None:
                if not path or not os.path.exists(path):
                    return
                generated_files = scan_result.generated_files
                norm_existing = {
                    os.path.normcase(os.path.normpath(p))
                    for p in generated_files
                }
                norm_path = os.path.normcase(os.path.normpath(path))
                if norm_path not in norm_existing:
                    generated_files.append(path)

            def _mark_generated_bundle(path: str) -> None:
                _mark_generated_file(path)
                _mark_generated_file(_audit_path_for_generated(path))

            def _mark_generated_paths(paths: List[str]) -> None:
                for path in paths or []:
                    _mark_generated_file(path)

            def _delete_old_generated_bundle(
                old_path: str, new_path: str, document_type: str
            ) -> None:
                deleted = []
                new_paths = {
                    os.path.normcase(os.path.normpath(path))
                    for path in (new_path, self._audit_path_for(new_path))
                    if path
                }
                for path in (old_path, self._audit_path_for(old_path)):
                    norm_path = os.path.normcase(os.path.normpath(path or ""))
                    if norm_path in new_paths:
                        continue
                    if path and os.path.isfile(path):
                        try:
                            os.remove(path)
                            deleted.append(path)
                        except OSError as exc:
                            logger.warning(
                                "Failed to delete old generated assessment file %s: %s",
                                path,
                                exc,
                            )
                if deleted:
                    _record_policy_event(
                        {
                            "event": "old_generated_assessment_deleted",
                            "document_type": document_type,
                            "old_path": old_path,
                            "new_path": new_path,
                            "deleted_files": deleted,
                            "action": "delete_old_app_generated_files_after_success",
                        }
                    )

            def _cleanup_service_generated_files(reason: str) -> int:
                removed = []
                for path in reversed(getattr(scan_result, "generated_files", [])):
                    if not path or not os.path.isfile(path):
                        continue
                    try:
                        os.remove(path)
                        removed.append(path)
                    except OSError as exc:
                        logger.warning(
                            "Cancellation cleanup failed for generated file %s: %s",
                            path,
                            exc,
                        )
                if removed:
                    _record_policy_event(
                        {
                            "event": "scan_generated_files_cleaned",
                            "removed_files": removed,
                            "reason": reason,
                            "action": "delete_current_scan_generated_files",
                        }
                    )
                return len(removed)

            def _cancel_after_service_generation(reason: str) -> ClaimFolderProcessResult:
                scan_result.cancelled = True
                scan_result.cancellation_reason = reason
                removed_count = _cleanup_service_generated_files(reason)
                cancel_logs = list(logs)
                cancel_logs.extend(
                    [
                        "Scan cancelled before completion.",
                        f"Cancellation reason: {reason}",
                        f"Generated files cleaned: {removed_count}",
                        "Please rescan the folder.",
                    ]
                )
                return ClaimFolderProcessResult(
                    False, scan_result, None, cancel_logs, "Cancelled"
                )

            portal_info = get_portal(self.portal_id)
            scan_context = ScanRunContext(
                portal_id=self.portal_id,
                portal_display_name=(
                    portal_info.display_name if portal_info else self.portal_id
                ),
                claim_folder_path=os.path.abspath(folder),
                scan_timestamp=datetime.now().isoformat(timespec="seconds"),
                settings_paths=settings_paths(portal_id=self.portal_id),
                field_mapping_paths=field_mapping_paths(portal_id=self.portal_id),
                doc_mapping_paths=doc_mapping_paths(portal_id=self.portal_id),
                automation_defaults_paths=automation_defaults_paths(
                    portal_id=self.portal_id
                ),
            )
            scan_result.scan_context = scan_context

            if getattr(scan_result, "cancelled", False):
                if getattr(scan_result, "policy_events", None):
                    self._write_scan_policy_audit_events(scan_result.policy_events)
                cleanup_events = [
                    event
                    for event in getattr(scan_result, "policy_events", [])
                    if event.get("event") == "scan_generated_files_cleaned"
                ]
                return ClaimFolderProcessResult(
                    False,
                    scan_result,
                    None,
                    [
                        "Scan cancelled before completion.",
                        f"Cancellation reason: {getattr(scan_result, 'cancellation_reason', '')}",
                        f"Generated cleanup events: {len(cleanup_events)}",
                    ],
                    "Cancelled",
                )

            if stop_cb and stop_cb():
                return ClaimFolderProcessResult(
                    False, scan_result, None, ["Warning: Scan cancelled."], "Cancelled"
                )

            claim_docs = scan_result.claim_doc_files
            assess_docs = scan_result.assessment_files

            if claim_docs:
                logs.append("Claim Documents (matched):")
                for doc_type, fpath in claim_docs.items():
                    mb = (
                        os.path.getsize(fpath) / (1024 * 1024)
                        if os.path.isfile(fpath)
                        else 0
                    )
                    logs.append(f"  Matched: [{doc_type}] -> {Path(fpath).name} ({mb:.1f}MB)")
            else:
                logs.append("Warning: No claim documents matched from folder")

            if assess_docs:
                logs.append("Assessment Files (matched):")
                for doc_type, fpath in assess_docs.items():
                    logs.append(f"  Matched: [{doc_type}] -> {Path(fpath).name}")

            matched_types = set(claim_docs.keys())
            missing_docs = [
                d for d in scan_result.expected_docs if d not in matched_types
            ]
            if missing_docs:
                logs.append("Warning: Missing expected documents:")
                for doc in missing_docs:
                    logs.append(f"  Missing: {doc}")

            if scan_result.skipped_files:
                logs.append("Warning: Skipped Files:")
                for path, reason in scan_result.skipped_files:
                    logs.append(f"  - {Path(path).name} - {reason}")

            if scan_result.unknown_files:
                logs.append("Unrecognized Files (No Mapping):")
                for path in scan_result.unknown_files:
                    logs.append(f"  - {Path(path).name}")
                logs.append(
                    "  Info: rename files to include keywords like chassis, odometer, cheque, caseless, non_caseless, etc."
                )

            if getattr(scan_result, "policy_warnings", None):
                logs.append("Policy Warnings:")
                for warning in scan_result.policy_warnings:
                    logs.append(f"  - {warning}")
                self._write_scan_policy_audit_events(
                    getattr(scan_result, "policy_events", []) or []
                )

            if not scan_result.excel_path:
                logs.append("Warning: No Excel file found in folder!")
                return ClaimFolderProcessResult(
                    False, scan_result, None, logs, error="No Excel file found"
                )

            if stop_cb and stop_cb():
                return ClaimFolderProcessResult(
                    False, scan_result, None, ["Warning: Scan cancelled."], "Cancelled"
                )

            logs.append(f"Excel: {Path(scan_result.excel_path).name}")
            claim = extract_claim_data(scan_result.excel_path, portal_id=self.portal_id)
            claim.portal_id = self.portal_id
            claim._scan_context = scan_context
            claim.claim_doc_files = scan_result.claim_doc_files
            claim.assessment_files = scan_result.assessment_files
            claim.upload_doc_files = scan_result.upload_doc_files
            claim._scan_result = scan_result
            claim.source_excel_path = scan_result.excel_path or ""

            # F6 FIX: import once here, used by printable block, OIC block,
            # and the eager_ocr check further below — no repeated inline imports.
            from app.utils import load_automation_defaults

            # Issue 4: Load once, reuse for printable block + eager_ocr check.
            # OIC block uses its own load with portal_id="oic" (intentional —
            # it always needs OIC defaults regardless of the active portal).
            _portal_defaults = load_automation_defaults(portal_id=self.portal_id)

            # ── Generate Printable Excel copy + PDF ───────────────────────
            if scan_result.excel_path:
                try:
                    from app.data.printable_excel_service import process_printable_output

                    _output_dir = os.path.dirname(os.path.abspath(scan_result.excel_path))
                    process_printable_output(
                        source_excel_path=scan_result.excel_path,
                        output_folder=_output_dir,
                        settings=_portal_defaults,
                        logs=logs,
                    )
                except Exception as print_exc:
                    logs.append(f"⚠️  Printable Excel/PDF generation failed: {print_exc}")
                    logger.warning("Printable generation error: %s", print_exc)

            # SSOT is now fully isolated and calculated directly within excel_reader.py

            # Auto-generate primary assessment Excel if not provided by user, or update if it is app-generated.
            is_auto_generated = False
            if "assessment_excel" in claim.assessment_files:
                fpath = claim.assessment_files["assessment_excel"]
                if self._is_newindia_generated_assessment(fpath):
                    is_auto_generated = True

            if self.portal_id == "newindia" and (
                "assessment_excel" not in claim.assessment_files or is_auto_generated
            ):
                if scan_result.excel_path:
                    try:
                        old_path = (
                            claim.assessment_files.get("assessment_excel", "")
                            if is_auto_generated
                            else ""
                        )

                        from app.data.assessment_generator import (
                            generate_primary_assessment_result,
                        )

                        generation = generate_primary_assessment_result(
                            scan_result.excel_path,
                            os.path.dirname(scan_result.excel_path),
                        )
                        generated_path = generation.output_path
                        _mark_generated_paths(generation.generated_files)
                        if generated_path:
                            claim.assessment_files["assessment_excel"] = generated_path
                            if old_path:
                                _record_policy_event(
                                    {
                                        "event": "generated_assessment_replaced",
                                        "document_type": "assessment_excel",
                                        "old_path": old_path,
                                        "new_path": generated_path,
                                        "action": "switch_mapping_after_success",
                                    }
                                )
                                logs.append(
                                    "Auto-generated assessment replaced after new file was created successfully. "
                                    f"Previous file kept: {Path(old_path).name}; new file: {Path(generated_path).name}"
                                )
                                _delete_old_generated_bundle(
                                    old_path, generated_path, "assessment_excel"
                                )
                            logs.append(
                                f"Auto-generated assessment: {Path(generated_path).name} from {Path(scan_result.excel_path).name}"
                            )
                        else:
                            logs.append(generation.message)
                    except Exception as gen_exc:
                        if is_auto_generated and claim.assessment_files.get(
                            "assessment_excel"
                        ):
                            logs.append(
                                "Existing generated assessment kept because replacement failed."
                            )
                        logs.append(
                            f"Warning: Auto-generation of assessment Excel failed: {gen_exc}"
                        )

            # Auto-generate OIC assessment Excel (Website 3).
            if self.portal_id == "oic" and scan_result.excel_path:
                is_oic_auto_generated = False
                if "oic_assessment_excel" in claim.assessment_files:
                    oic_fpath = claim.assessment_files["oic_assessment_excel"]
                    if self._is_oic_generated_assessment(oic_fpath):
                        is_oic_auto_generated = True

                try:
                    old_oic_path = (
                        claim.assessment_files.get("oic_assessment_excel", "")
                        if is_oic_auto_generated
                        else ""
                    )

                    from app.data.oic_assessment_generator import (
                        generate_oic_assessment_result,
                    )
                    from app.utils import load_automation_defaults as _load_defaults

                    oic_defaults = _load_defaults(portal_id="oic")
                    # Resolve to absolute path to prevent os.path.dirname returning ""
                    # if scan_result.excel_path has no directory component.
                    _abs_excel = os.path.abspath(scan_result.excel_path)
                    _oic_output_dir = os.path.dirname(_abs_excel)
                    logger.debug(
                        "OIC generation: source=%s, output_dir=%s",
                        _abs_excel,
                        _oic_output_dir,
                    )
                    generation = generate_oic_assessment_result(
                        _abs_excel,
                        _oic_output_dir,
                        oic_defaults,
                    )
                    oic_generated_path = generation.output_path
                    _mark_generated_paths(generation.generated_files)
                    if oic_generated_path:
                        claim.assessment_files["oic_assessment_excel"] = (
                            oic_generated_path
                        )
                        if old_oic_path:
                            _record_policy_event(
                                {
                                    "event": "generated_assessment_replaced",
                                    "document_type": "oic_assessment_excel",
                                    "old_path": old_oic_path,
                                    "new_path": oic_generated_path,
                                    "action": "switch_mapping_after_success",
                                }
                            )
                            logs.append(
                                "OIC auto-generated assessment replaced after new file was created successfully. "
                                f"Previous file kept: {Path(old_oic_path).name}; new file: {Path(oic_generated_path).name}"
                            )
                            _delete_old_generated_bundle(
                                old_oic_path, oic_generated_path, "oic_assessment_excel"
                            )
                        logs.append(
                            f"OIC auto-generated assessment: {Path(oic_generated_path).name} from {Path(scan_result.excel_path).name}"
                        )
                    else:
                        logs.append(generation.message)
                except Exception as gen_exc:
                    logs.append(
                        f"Warning: OIC auto-generation of assessment Excel failed: {gen_exc}"
                    )

            if stop_cb and stop_cb():
                return _cancel_after_service_generation("after_assessment_generation")

            # Issue 4: Reuse _portal_defaults loaded above — no second disk read.
            defaults = _portal_defaults
            eager_ocr = defaults.get("eager_folder_ocr", True)

            invoice_pdf = scan_result.assessment_files.get("invoice")
            if eager_ocr:
                if invoice_pdf:
                    self._extract_pdf_invoice_data(
                        scan_result, claim, logs, stop_cb=stop_cb
                    )
            else:
                if invoice_pdf and os.path.exists(invoice_pdf):
                    logs.append(
                        f"Workshop Invoice PDF found: {Path(invoice_pdf).name} - OCR deferred to automation phase (OCR in background)."
                    )
                    claim._pending_invoice_ocr = True
                    claim._pending_invoice_pdf_path = invoice_pdf

            # Run Cheque OCR during folder load if bank details are missing in Excel.
            if not getattr(claim, "ifsc_code", None) or not getattr(
                claim, "account_number", None
            ):
                cheque_path = ""
                all_docs = {**claim.claim_doc_files, **(claim.upload_doc_files or {})}
                for doc_name, file_path in all_docs.items():
                    if "cheque" in doc_name.lower() or "check" in doc_name.lower():
                        if "fallback" in os.path.basename(file_path).lower():
                            logs.append(
                                f"Info: Cheque file is an invoice fallback ({Path(file_path).name}); skipping OCR to prevent hanging."
                            )
                            continue
                        cheque_path = file_path
                        break

                if cheque_path:
                    if eager_ocr:
                        if stop_cb and stop_cb():
                            logs.append("Warning: Scan cancelled before cheque OCR.")
                        else:
                            logs.append(
                                f"Cheque document detected: {Path(cheque_path).name}. Extracting bank details via OCR..."
                            )
                            try:
                                from app.automation.services.cheque_ocr_adapter import (
                                    get_cheque_ocr_adapter,
                                )

                                adapter = get_cheque_ocr_adapter(self.portal_id)
                                ocr_logs = []

                                def ocr_log_fn(msg):
                                    clean_msg = msg.encode(
                                        "ascii", errors="ignore"
                                    ).decode("ascii")
                                    ocr_logs.append(f"  - {clean_msg.strip()}")

                                ocr_result = adapter.extract_details(
                                    cheque_path,
                                    log=ocr_log_fn,
                                    excel_ifsc=getattr(claim, "ifsc_code", None) or "",
                                    excel_account=getattr(claim, "account_number", None)
                                    or "",
                                    stop_cb=stop_cb,
                                )
                                cheque_details = ocr_result.details
                                if ocr_result.status == "unsupported":
                                    logs.append(f"  Info: {ocr_result.message}")
                                    _record_policy_event(
                                        {
                                            "event": "cheque_ocr_unsupported",
                                            "document_type": "cheque",
                                            "source_file": cheque_path,
                                            "ocr_status": "unsupported",
                                            "message": ocr_result.message,
                                            "action": "continue_without_cheque_ocr",
                                        }
                                    )

                                if cheque_details.get("ifsc"):
                                    claim.ifsc_code = cheque_details["ifsc"]
                                    if hasattr(claim, "_excel_coords"):
                                        claim._excel_coords["ifsc_code"] = "Cheque OCR"
                                    if hasattr(claim, "_excel_logs"):
                                        claim._excel_logs.append(
                                            f"  ifsc_code: '{claim.ifsc_code}' (Source: Cheque OCR)"
                                        )
                                if cheque_details.get("account_number"):
                                    claim.account_number = cheque_details[
                                        "account_number"
                                    ]
                                    if hasattr(claim, "_excel_coords"):
                                        claim._excel_coords["account_number"] = (
                                            "Cheque OCR"
                                        )
                                    if hasattr(claim, "_excel_logs"):
                                        claim._excel_logs.append(
                                            f"  account_number: '{claim.account_number}' (Source: Cheque OCR)"
                                        )
                                if cheque_details.get("account_type"):
                                    claim.account_type = cheque_details["account_type"]
                                    if hasattr(claim, "_excel_coords"):
                                        claim._excel_coords["account_type"] = (
                                            "Cheque OCR"
                                        )
                                    if hasattr(claim, "_excel_logs"):
                                        claim._excel_logs.append(
                                            f"  account_type: '{claim.account_type}' (Source: Cheque OCR)"
                                        )

                                logs.extend(ocr_logs)
                            except Exception as ocr_exc:
                                logs.append(f"  Warning: Cheque OCR failed: {ocr_exc}")
                    else:
                        logs.append(
                            f"Cheque document detected: {Path(cheque_path).name} - OCR deferred to automation phase (OCR in background)."
                        )
                        claim._pending_cheque_ocr = True
                        claim._pending_cheque_path = cheque_path

            if hasattr(claim, "_excel_logs") and claim._excel_logs:
                logs.append("Excel Data Sources Map:")
                logs.extend(claim._excel_logs)

            # Production-grade structured logging: write scan logs to claim JSON file immediately
            try:
                # Save the full scanning logs list inside claim object for future engine runs
                claim._scan_logs = list(logs)

                from app.automation.automation_logger import AutomationLogger

                # Create a temporary logger to initialize the structured JSON log file for this claim
                temp_logger = AutomationLogger(
                    "SCANNER", lambda msg: None, portal_id=self.portal_id
                )
                temp_logger.set_claim_context(claim.claim_no, self.portal_id)
                temp_logger.write_historical_logs(logs)
                # Propagate correlation ID to the claim so the automation engine inherits it
                claim.correlation_id = temp_logger.correlation_id

                # Consolidate log path and register temporary pre-compressed files
                claim._scan_log_file = temp_logger._json_log_file
                claim._temporary_files = list(
                    getattr(scan_result, "temporary_files", [])
                )
            except Exception as scan_log_exc:
                logger.warning(
                    f"Could not write structured JSON logs during folder scanning: {scan_log_exc}"
                )

            return ClaimFolderProcessResult(True, scan_result, claim, logs)
        except Exception as exc:
            logs.append(f"ERROR: Failed to read selected folder: {exc}")
            return ClaimFolderProcessResult(False, None, None, logs, error=str(exc))

    # Robust PDF Invoice Extraction Engine

    # Date patterns ordered by specificity (most specific first)
    _DATE_PATTERNS = [
        # DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
        re.compile(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})"),
        # YYYY-MM-DD or YYYY/MM/DD
        re.compile(r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})"),
    ]

    @staticmethod
    def _normalise_date(raw: str) -> Optional[str]:
        """Convert any recognized date string to DD/MM/YYYY for the portal."""
        raw = raw.strip().rstrip(".")
        from datetime import datetime

        # Try DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY
        for fmt in (
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%d.%m.%Y",
            "%m/%d/%Y",
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%d %b %Y",
            "%d %B %Y",
            "%B %d, %Y",
            "%b %d, %Y",
            "%d/%m/%y",
            "%d-%m-%y",
        ):
            try:
                dt = datetime.strptime(raw, fmt)
                # Reject nonsensical dates (year before 2000 or after 2040)
                if 2000 <= dt.year <= 2040:
                    return dt.strftime("%d/%m/%Y")
            except ValueError:
                continue
        return None

    @staticmethod
    def _clean_invoice_no(raw: str) -> Optional[str]:
        """Clean and validate an extracted invoice number string."""
        # Remove surrounding punctuation, parenthetical suffixes
        val = re.sub(r"\(.*$", "", raw).strip()  # Remove "(Credit)" etc.
        val = val.strip(":;,. \t")

        # Split on 2 or more consecutive spaces to prevent column/field leakage
        if "  " in val:
            val = val.split("  ")[0].strip()

        # Truncate at common stop words that mark subsequent fields on the same line
        stop_words = [
            "date",
            "gst",
            "dt",
            "gstin",
            "time",
            "amount",
            "amt",
            "phone",
            "mobile",
            "email",
            "bill",
            "invoice",
            "to",
            "for",
            "name",
            "address",
            "vehicle",
            "reg",
        ]
        for stop_word in stop_words:
            pattern = re.compile(r"\b" + stop_word + r"\b", re.IGNORECASE)
            m = pattern.search(val)
            if m:
                val = val[: m.start()].strip()

        val = val.strip(":;,. \t\\/-")

        # Must have at least one alphanumeric character
        if not val or not re.search(r"[A-Za-z0-9]", val):
            return None
        # Reject if it's just a common label word
        if val.lower() in {
            "no",
            "number",
            "date",
            "time",
            "invoice",
            "bill",
            "tax",
            "na",
            "nil",
            "none",
            "rs",
            "inr",
            ":",
            "-",
        }:
            return None
        return val

    def _extract_pdf_invoice_data(
        self, scan_result, claim, logs: List[str], stop_cb: Optional[callable] = None
    ) -> None:
        invoice_pdf = scan_result.assessment_files.get("invoice")
        if not invoice_pdf or not os.path.exists(invoice_pdf):
            return

        try:
            import pdfplumber
        except ImportError:
            logs.append("  Warning: pdfplumber not installed - cannot extract invoice data")
            return

        settings = load_settings(portal_id=getattr(claim, "portal_id", self.portal_id))
        inv_labels = settings.get(
            "pdf_invoice_no_labels",
            ["Tax Invoice No.", "Invoice No", "Bill No", "Work shop invoice"],
        )
        date_labels = settings.get(
            "pdf_invoice_date_labels",
            ["Invoice Date and Time", "Bill Date", "Invoice Date", "date"],
        )

        logs.append(
            f"Extracting Workshop Invoice details from PDF: {Path(invoice_pdf).name}"
        )

        ext_inv = None
        ext_date = None

        try:
            with pdfplumber.open(invoice_pdf) as pdf:
                # Collect text from all pages.
                all_text = ""
                all_lines: List[str] = []
                for page in pdf.pages:
                    if stop_cb and stop_cb():
                        logs.append("Warning: PDF text extraction cancelled by user.")
                        return
                    page_text = page.extract_text() or ""
                    if page_text:
                        all_text += page_text + "\n"
                        all_lines.extend(page_text.splitlines())

                if not all_text.strip():
                    if stop_cb and stop_cb():
                        logs.append("Warning: PDF text extraction cancelled by user.")
                        return
                    # PDF has no extractable text (scanned images)
                    logs.append(
                        "  Warning: PDF has no extractable text (scanned image?), trying OCR..."
                    )
                    ext_inv, ext_date = self._ocr_extract_invoice(
                        invoice_pdf, inv_labels, date_labels, logs, stop_cb=stop_cb
                    )
                else:
                    # Strategy 1: Label-based inline extraction.
                    ext_inv = self._find_invoice_no(all_text, all_lines, inv_labels)
                    ext_date = self._find_invoice_date(all_text, all_lines, date_labels)

            # Apply OCR/text extraction results.
            if ext_inv:
                claim.workshop_invoice_no = ext_inv
                claim.vendor_invoice_number = ext_inv  # New India mapping
                claim._excel_coords["workshop_invoice_no"] = "PDF Source"
                claim._excel_coords["vendor_invoice_number"] = "PDF Source"
                claim._excel_logs.append(
                    f"  workshop_invoice_no: '{ext_inv}' (Source: PDF Source)"
                )
                logs.append(f"  Matched: WS Invoice No (from PDF): {ext_inv}")
            else:
                logs.append("  Warning: Invoice No not found in PDF")

            if ext_date:
                claim.workshop_invoice_date = ext_date
                claim.vendor_invoice_date = ext_date  # New India mapping
                claim._excel_coords["workshop_invoice_date"] = "PDF Source"
                claim._excel_coords["vendor_invoice_date"] = "PDF Source"
                claim._excel_logs.append(
                    f"  workshop_invoice_date: '{ext_date}' (Source: PDF Source)"
                )
                logs.append(f"  Matched: WS Invoice Date (from PDF): {ext_date}")
            else:
                logs.append("  Warning: Invoice Date not found in PDF")

        except Exception as exc:
            logs.append(f"  Warning: Could not parse invoice PDF: {exc}")

    def _find_invoice_no(
        self, full_text: str, lines: List[str], labels: List[str]
    ) -> Optional[str]:
        """
        Multi-strategy invoice number extraction.

        Strategy 1: "Label<separator>VALUE" on the same line
        Strategy 2: "Label" on one line, value on the next
        Strategy 3: Regex scan for common invoice number patterns near label
        """
        # Sort labels longest-first so "Tax Invoice No." matches before "Invoice No"
        sorted_labels = sorted(labels, key=len, reverse=True)

        for label in sorted_labels:
            label_esc = re.escape(label)

            # Strategy 1: Same-line Label[.:;]?\s*VALUE.
            # Handles: "Tax Invoice No.INZ25-01569(Credit)"
            #          "BILL NO : JDB/1336"
            #          "Invoice No: ABC-123"
            pattern = label_esc + r"[.:\s]*\s*([A-Za-z0-9][A-Za-z0-9/\-_. ]{1,40})"
            m = re.search(pattern, full_text, re.IGNORECASE)
            if m:
                val = self._clean_invoice_no(m.group(1))
                if val:
                    return val

            # Strategy 2: Next-line label on line N, value on line N+1.
            for i, line in enumerate(lines):
                if re.search(label_esc, line, re.IGNORECASE):
                    # Check if value is on the same line AFTER the label
                    after = re.split(label_esc, line, flags=re.IGNORECASE, maxsplit=1)
                    if len(after) > 1:
                        remainder = after[1].strip().lstrip(":;.- ")
                        inv_m = re.match(
                            r"([A-Za-z0-9][A-Za-z0-9/\-_. ]{1,40})", remainder
                        )
                        if inv_m:
                            val = self._clean_invoice_no(inv_m.group(1))
                            if val:
                                return val
                    # Check next line
                    if i + 1 < len(lines):
                        next_line = lines[i + 1].strip()
                        inv_m = re.match(
                            r"([A-Za-z0-9][A-Za-z0-9/\-_. ]{1,40})", next_line
                        )
                        if inv_m:
                            val = self._clean_invoice_no(inv_m.group(1))
                            if val:
                                return val

        return None

    def _find_invoice_date(
        self, full_text: str, lines: List[str], labels: List[str]
    ) -> Optional[str]:
        """
        Multi-strategy invoice date extraction.

        Strategy 1: "Label<separator>DD/MM/YYYY" on the same line
        Strategy 2: "Label" on one line, date on the next
        Strategy 3: Find first plausible date anywhere near a label
        """
        sorted_labels = sorted(labels, key=len, reverse=True)

        # Date regex that matches many formats
        date_rx = r"(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})"

        for label in sorted_labels:
            label_esc = re.escape(label)

            # Strategy 1: Same-line extraction.
            # Handles: "Invoice Date and Time 27/01/2026 16:35"
            #          "Date : 16/12/2025"
            #          "Date:27-01-2026"
            pattern = label_esc + r"[.:\s]*\s*" + date_rx
            m = re.search(pattern, full_text, re.IGNORECASE)
            if m:
                normalised = self._normalise_date(m.group(1))
                if normalised:
                    return normalised

            # Strategy 2: Next-line label on line N, date on line N+1.
            for i, line in enumerate(lines):
                if re.search(label_esc, line, re.IGNORECASE):
                    # Check same line after label
                    after = re.split(label_esc, line, flags=re.IGNORECASE, maxsplit=1)
                    if len(after) > 1:
                        dm = re.search(date_rx, after[1])
                        if dm:
                            normalised = self._normalise_date(dm.group(1))
                            if normalised:
                                return normalised
                    # Check next line
                    if i + 1 < len(lines):
                        dm = re.search(date_rx, lines[i + 1])
                        if dm:
                            normalised = self._normalise_date(dm.group(1))
                            if normalised:
                                return normalised

        return None

    def _ocr_extract_invoice(
        self,
        pdf_path: str,
        inv_labels: List[str],
        date_labels: List[str],
        logs: List[str],
        stop_cb: Optional[callable] = None,
    ) -> tuple:
        """
        OCR fallback for scanned PDFs with no extractable text.

        Engine priority:
          1. PaddleOCR (already bundled - same engine used for cheque OCR & CAPTCHA)
          2. pytesseract (legacy fallback, requires external Tesseract binary)

        PDF pages are rendered to PIL images via pdfplumber's built-in
        `page.to_image()` - no external poppler/pdf2image dependency needed.
        """
        if stop_cb and stop_cb():
            return None, None

        # Step 1: Render PDF pages to PIL images via pdfplumber.
        pil_images = []
        try:
            import pdfplumber

            with pdfplumber.open(pdf_path) as pdf:
                for page_idx, page in enumerate(pdf.pages[:3]):  # First 3 pages max
                    if stop_cb and stop_cb():
                        logs.append("Warning: PDF OCR cancelled by user.")
                        return None, None
                    try:
                        pil_img = page.to_image(resolution=250).original
                        pil_images.append(pil_img)
                    except Exception as render_exc:
                        exc_name = type(render_exc).__name__
                        if (
                            "PDFInfoNotInstalledError" in exc_name
                            or "pdfinfo" in str(render_exc).lower()
                        ):
                            logs.append(
                                "  Warning: PDF page rendering needs Ghostscript. Trying direct PaddleOCR on file..."
                            )
                            break
                        logs.append(
                            f"  Warning: Page {page_idx + 1} render failed: {str(render_exc)[:80]}"
                        )
        except Exception as exc:
            logs.append(f"  Warning: PDF open for rendering failed: {str(exc)[:80]}")

        # Step 2: Try PaddleOCR (primary, already in project).
        all_text = ""
        paddle_ok = False
        if pil_images:
            try:
                from app.automation.ocr_engine import run_shared_ocr
                import tempfile

                for img_idx, pil_img in enumerate(pil_images):
                    if stop_cb and stop_cb():
                        logs.append("Warning: PDF OCR cancelled by user.")
                        return None, None

                    # PaddleOCR needs a file path; save temp PNG.
                    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".png")
                    os.close(tmp_fd)
                    try:
                        pil_img.save(tmp_path)
                        result = run_shared_ocr(tmp_path, cls=True)
                        if result and result[0]:
                            page_text = " ".join(
                                line[1][0]
                                for line in result[0]
                                if line[1] and line[1][0]
                            )
                            all_text += page_text + "\n"
                    finally:
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass

                if all_text.strip():
                    paddle_ok = True
                    logs.append(
                        f"  PaddleOCR extracted {len(all_text)} chars from {len(pil_images)} page(s)."
                    )
                else:
                    logs.append(
                        "  Warning: PaddleOCR produced no text from scanned PDF pages."
                    )
            except Exception as paddle_exc:
                logs.append(
                    f"  Warning: PaddleOCR unavailable ({type(paddle_exc).__name__}: {str(paddle_exc)[:80]}), trying pytesseract..."
                )

        # Step 3: Fallback to pytesseract if PaddleOCR failed.
        if not paddle_ok and pil_images:
            try:
                import pytesseract

                all_text = ""
                for img in pil_images:
                    if stop_cb and stop_cb():
                        logs.append("Warning: PDF OCR cancelled by user.")
                        return None, None
                    all_text += pytesseract.image_to_string(img) + "\n"
                if all_text.strip():
                    logs.append(f"  Tesseract OCR extracted {len(all_text)} chars.")
                else:
                    logs.append("  Warning: Tesseract OCR produced no text from scanned PDF.")
                    return None, None
            except ImportError:
                logs.append(
                    "  Warning: Neither PaddleOCR nor pytesseract could extract text - skipping OCR."
                )
                return None, None
            except Exception as tess_exc:
                exc_name = type(tess_exc).__name__
                if (
                    "TesseractNotFoundError" in exc_name
                    or "tesseract is not installed" in str(tess_exc).lower()
                ):
                    logs.append(
                        "  Warning: Tesseract binary not installed. Install from https://github.com/UB-Mannheim/tesseract/wiki"
                    )
                else:
                    logs.append(f"  Warning: Tesseract fallback failed: {tess_exc}")
                return None, None

        if not all_text.strip():
            if not pil_images:
                logs.append(
                    "  Warning: Could not render PDF pages for OCR - no images produced."
                )
            return None, None

        # Step 4: Extract invoice number/date from OCR text.
        logs.append("  Searching OCR text for invoice number and date...")
        all_lines = all_text.splitlines()
        ext_inv = self._find_invoice_no(all_text, all_lines, inv_labels)
        ext_date = self._find_invoice_date(all_text, all_lines, date_labels)
        return ext_inv, ext_date
