"""Thin non-Qt adapter for the existing App-3 case preparation service."""

from pathlib import Path

from app.ui.services.claim_folder_service import ClaimFolderService
from app.utils import doc_mapping_paths, scan_main_excel


def prepare_uiic_case(staged, stop_requested):
    config_dir = str(Path(doc_mapping_paths(portal_id="uiic")["default"]).parent)
    token = scan_main_excel.set(staged.latest_excel)
    try:
        result = ClaimFolderService(config_dir=config_dir, portal_id="uiic").process_folder(
            str(staged.folder), stop_cb=stop_requested)
    finally:
        scan_main_excel.reset(token)
    if not result.success or result.claim is None:
        raise RuntimeError(result.error or "UIIC case preparation failed")
    return result
