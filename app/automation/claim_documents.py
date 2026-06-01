import logging
import os
from typing import Callable, List, Optional, Tuple

from app.automation.services.document_upload_service import (
    MAX_FILE_MB,
    DocumentUploadService,
)
from app.automation.tab_utils import click_tab
from app.data.data_model import ClaimData
from app.automation.automation_logger import AutomationLogger

logger = logging.getLogger(__name__)

# Fallback dropdown index when file is missing (0-based option index)
FALLBACK_OPTION_INDEX = 3


async def _click_doc_radios(page, log) -> None:
    """Set Claim Documents verification radios to Yes using Angular-friendly events."""
    if isinstance(log, AutomationLogger):
        log.info("Setting 'Yes' radios for verification...")
    else:
        log("  🔘 Setting verification radios to Yes...")
        
    radio_names = [
        "ynRCBookVerified",
        "ynRelevantDamage",
        "ynDrivingLicense",
    ]
    js_result = await page.evaluate(
        """
        (function() {
            var names = ['ynRCBookVerified', 'ynRelevantDamage', 'ynDrivingLicense'];
            var clicked = [];
            names.forEach(function(name) {
                var selectors = [
                    'input[name="' + name + '"][value="Y"]',
                    'input[ng-model*="' + name + '"][value="Y"]',
                    'input[data-ng-model*="' + name + '"][value="Y"]',
                    'input[name="' + name + '"]',
                    'input[ng-model*="' + name + '"]',
                ];
                var found = false;
                for (var s of selectors) {
                    var r = document.querySelector(s);
                    if (r) {
                        r.checked = true;
                        r.dispatchEvent(new Event('change', {bubbles: true}));
                        try { r.click(); } catch(e) {}
                        clicked.push(name);
                        found = true;
                        break;
                    }
                }
                if (!found) {
                    var nameLower = name.toLowerCase();
                    var allRadios = document.querySelectorAll('input[type="radio"]');
                    for (var radio of allRadios) {
                        var rname = (radio.name || radio.getAttribute('ng-model') || '').toLowerCase();
                        if (rname.includes(nameLower.substring(2).toLowerCase()) && radio.value === 'Y') {
                            radio.checked = true;
                            radio.dispatchEvent(new Event('change', {bubbles: true}));
                            try { radio.click(); } catch(e) {}
                            clicked.push(name + '(partial)');
                            break;
                        }
                    }
                }
            });

            var allRadios = document.querySelectorAll('input[type="radio"][value="Y"]');
            var extraClicked = 0;
            for (var radio of allRadios) {
                if (!radio.checked) {
                    var parent = radio.closest('tr,div.row,div.form-group');
                    if (parent) {
                        var hasNo = parent.querySelector('input[value="N"],input[value="n"]');
                        if (hasNo) {
                            radio.checked = true;
                            radio.dispatchEvent(new Event('change', {bubbles: true}));
                            try { radio.click(); } catch(e) {}
                            extraClicked++;
                        }
                    }
                }
            }
            return {clicked: clicked, extra: extraClicked};
        })();
        """
    )
    result = js_result or {}
    clicked = result.get("clicked", []) if isinstance(result, dict) else (result or [])
    extra = result.get("extra", 0) if isinstance(result, dict) else 0
    
    if isinstance(log, AutomationLogger):
        log.success(f"Radios set: {len(clicked)} named + {extra} extra")
    else:
        log(f"  🔘 Doc radios: {len(clicked)}/{len(radio_names)} named + {extra} auto-YES")


async def _click_payment_option(page, claim: ClaimData, log) -> None:
    """Set payment option based on payment_to: insured -> reimbursement else cashless."""
    payment_raw = str(claim.payment_to).strip().lower()
    source = claim._excel_coords.get("payment_to", "")
    target = "reimbursement" if "insured" in payment_raw else "cashless"

    result = await page.evaluate(
        f"""
        (function() {{
            var target = '{target}';
            var vals = target === 'cashless'
                ? ['CASHLESS', 'Cashless', 'cashless', 'C']
                : ['REIMBURSEMENT', 'Reimbursement', 'reimbursement', 'R'];
            for (var v of vals) {{
                var r = document.querySelector('input[type="radio"][value="' + v + '"]');
                if (r) {{
                    r.checked = true;
                    r.click();
                    r.dispatchEvent(new Event('change', {{bubbles:true}}));
                    return v;
                }}
            }}

            var checkboxes = document.querySelectorAll('input[type="checkbox"]');
            for (var cb of checkboxes) {{
                var label = '';
                var parent = cb.closest('label,td,div');
                if (parent) label = parent.textContent.trim().toLowerCase();
                if (label.includes(target)) {{
                    if (!cb.checked) {{
                        cb.click();
                        cb.dispatchEvent(new Event('change', {{bubbles:true}}));
                    }}
                    return 'checkbox:' + target;
                }}
            }}

            var labels = document.querySelectorAll('label');
            for (var l of labels) {{
                if (l.textContent.trim().toLowerCase().includes(target)) {{
                    l.click();
                    return 'label:' + target;
                }}
            }}
            return null;
        }})();
        """
    )

    display = target.capitalize()
    if result:
        if isinstance(log, AutomationLogger):
            log.success(f"Payment Option: {display}")
        else:
            log(f"  ✅ Payment: {display}")
    else:
        if isinstance(log, AutomationLogger):
            log.warning(f"Payment Option: {display} not found on page")
        else:
            log(f"  ⚠️  Payment: {display} not found on page")


def _build_queue(claim: ClaimData, log) -> List[Tuple[str, Optional[str]]]:
    """Build upload queue preserving all mapped doc types, including missing-file placeholders."""
    queue = []
    for doc_type, file_path in claim.claim_doc_files.items():
        fname = os.path.basename(file_path) if file_path else "?"
        if not file_path or not os.path.isfile(file_path):
            if isinstance(log, AutomationLogger):
                log.document_mapped(doc_type, fname, status="File Not Found", source="Folder Scan")
                log.warning(f"File not found: {fname} (type '{doc_type}')")
            else:
                log(f"  ⚠️  Not found: {fname} → type '{doc_type}' will be skipped")
            logger.warning("Document file not found: %s (type: %s)", fname, doc_type)
            queue.append((doc_type, None))
            continue

        mb = os.path.getsize(file_path) / (1024 * 1024)
        if isinstance(log, AutomationLogger):
            log.document_mapped(doc_type, fname, status="Matched Successfully", source="Folder Scan")
            size_tag = " [LARGE]" if mb > MAX_FILE_MB else ""
            log.info(f"Queueing: [{doc_type}] → {fname} ({mb:.1f}MB){size_tag}")
        else:
            size_warn = " ⚠️ LARGE" if mb > MAX_FILE_MB else ""
            log(f"  📎 [{doc_type}]: {fname} ({mb:.1f}MB){size_warn}")
            
        if mb > MAX_FILE_MB:
            logger.info("Large file (%.1fMB): %s — portal alert will be auto-accepted", mb, fname)
        queue.append((doc_type, file_path))

    return queue


async def fill_claim_documents(page, claim: ClaimData, log_cb, settings: dict = None) -> bool:
    """Main orchestrator for the Claim Documents tab."""
    log = log_cb
    if isinstance(log, AutomationLogger):
        log.section = "Claim Documents"
        log.section_start("PHASE 4: CLAIM DOCUMENTS")
    else:
        log("\n" + "="*60 + "\nPHASE 4: CLAIM DOCUMENTS\n" + "="*60)

    # 1. Click Tab
    from app.automation.selectors import TABS
    if await click_tab(page, "documents", log=log) is False:
        return False

    if isinstance(log, AutomationLogger):
        log.info("Filling Claim Documents section...")
        log.indent()
        log.step(1, 3, "Verification & Payment")
    else:
        log("🔘 Setting verification radios...")
        
    await _click_doc_radios(page, log)
    await _click_payment_option(page, claim, log)

    if isinstance(log, AutomationLogger):
        log.step(2, 3, "Building Queue")
        log.info("Building upload queue...")
        log.indent()
    else:
        log("\n📎 Building upload queue...")
        
    queue = _build_queue(claim, log)
    if isinstance(log, AutomationLogger): log.outdent()
    
    if not queue:
        if isinstance(log, AutomationLogger):
            log.warning("No documents to process.")
            log.outdent()
        else:
            log("  ℹ️  No documents to process.")
        logger.warning("No documents in upload queue — claim_doc_files was empty")
        return True

    if isinstance(log, AutomationLogger):
        log.step(3, 3, "Uploading Documents")
        log.info(f"Processing {len(queue)} document rows...")
        log.indent()
    else:
        log(f"\n📤 Processing {len(queue)} document rows...")

    async def _handle_dialog(dialog):
        dialog_msg = (dialog.message[:80] + "...") if dialog.message and len(dialog.message) > 80 else (dialog.message or "(empty)")
        if isinstance(log, AutomationLogger):
            log.info(f"Portal alert: '{dialog_msg}' auto-accepted")
        else:
            log(f"    ℹ️  Portal alert: '{dialog_msg}' → auto-accepted")
        logger.info("Auto-accepted dialog: %s", dialog_msg)
        try:
            await dialog.accept()
        except Exception:
            pass

    page.on("dialog", _handle_dialog)

    # Use explicitly passed settings or empty dict
    cfg = settings or {}
    wait_timeout_ms = int(cfg.get("upload_timeout_ms", cfg.get("upload_wait_ms", 10000)))
    panel_ready_timeout = max(15000, wait_timeout_ms)

    service = DocumentUploadService(page=page, log_cb=log)

    try:
        await service.wait_for_upload_section(panel_ready_timeout)
        if isinstance(log, AutomationLogger):
            log.success("Upload panel ready")
        else:
            log("  ✅ Upload panel ready")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.warning(f"Upload panel wait failed: {str(e)[:80]}")
        else:
            log(f"  ⚠️  Upload panel wait failed: {str(e)[:80]}")
        logger.error("Upload panel not visible: %s", str(e)[:120])
        if isinstance(log, AutomationLogger):
            log.info("Proceeding anyway...")
        else:
            log("  ℹ️  Proceeding anyway...")

    upload_results, uploaded_rows = await service.upload_queue(
        queue=queue,
        wait_timeout_ms=wait_timeout_ms,
        fallback_option_index=FALLBACK_OPTION_INDEX,
    )

    if uploaded_rows:
        if isinstance(log, AutomationLogger):
            log.info("Verifying visible upload rows...")
        else:
            log("\n🔎 Verifying visible upload rows...")

    for row_idx, doc_type, file_path in uploaded_rows:
        expected_name = os.path.basename(file_path)
        if await service.row_shows_expected_file(row_idx, expected_name, timeout_ms=2000):
            continue

        if isinstance(log, AutomationLogger):
            log.warning(f"Row lost file after upload: [{doc_type}] → retrying")
        else:
            log(f"  ⚠️  Row lost file after upload: [{doc_type}] → retrying visible row")
            
        retry_ok = await service.select_doc_and_set_file(
            row_index=row_idx,
            doc_label=doc_type,
            file_path=file_path,
            timeout_ms=wait_timeout_ms,
        )
        if retry_ok:
            await service.wait_after_upload(row_index=row_idx, wait_ms=wait_timeout_ms)
            if await service.row_shows_expected_file(row_idx, expected_name, timeout_ms=2000):
                if isinstance(log, AutomationLogger):
                    log.success(f"Row restored: [{doc_type}] → {expected_name}")
                else:
                    log(f"  ✅ Row restored: [{doc_type}] → {expected_name}")
                continue

        for idx_result, (r_doc_type, r_fname, r_status, _) in enumerate(upload_results):
            if r_doc_type == doc_type and r_fname == expected_name and r_status == "OK":
                upload_results[idx_result] = (
                    r_doc_type, r_fname, "FAILED", "Visible row still shows no file after retry"
                )
                break
        logger.error("Visible row verification failed for [%s] → %s", doc_type, expected_name)

    ok_count = sum(1 for _, _, s, _ in upload_results if s == "OK")
    fail_count = sum(1 for _, _, s, _ in upload_results if s == "FAILED")
    skip_count = sum(1 for _, _, s, _ in upload_results if s == "SKIPPED")

    if isinstance(log, AutomationLogger):
        log.outdent()
        log.info(f"Upload Summary: {ok_count} OK, {fail_count} Failed, {skip_count} Skipped")
        log.indent()
        for doc_type, fname, status, detail in upload_results:
            msg = f"[{doc_type}] → {fname}: {detail}"
            if status == "OK": log.success(msg)
            elif status == "FAILED": log.error(msg)
            else: log.info(f"(Skipped) {msg}")
        log.outdent()
    else:
        log(f"\n{'═' * 50}")
        log(f"📊 UPLOAD SUMMARY: {ok_count} uploaded, {fail_count} failed, {skip_count} skipped")
        log(f"{'═' * 50}")
        for doc_type, fname, status, detail in upload_results:
            icon = "✅" if status == "OK" else "❌" if status == "FAILED" else "⏭️"
            log(f"  {icon} [{doc_type}] → {fname} — {detail}")

    if fail_count > 0:
        if isinstance(log, AutomationLogger):
            log.error(f"{fail_count} document(s) failed to upload")
        else:
            log(f"\n  ⚠️  {fail_count} document(s) failed to upload — check file names and portal dropdown values")
        logger.error("%d document(s) failed to upload", fail_count)

    if isinstance(log, AutomationLogger):
        log.success("Claim Documents section complete.")
        log.outdent()
    else:
        log(f"\n✅ Claim Documents complete — {len(queue)} rows processed.")
    
    return fail_count == 0
