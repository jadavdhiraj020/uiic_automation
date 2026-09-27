"""ZIP-only case intake, reusing App-3's verified archive and filename rules."""

import json
from pathlib import Path
import shutil
import tempfile
import zipfile

from app.web_sync.manifest import validate_staged_case
from app.web_sync.storage import atomic_json
from app.web_sync.zip_downloads import (
    _extract_local_case_zip, _extract_verified, _inspect_archive,
    _plan_files, _read_embedded_manifest, ZipIntegrityError,
)


class PreparedCase:
    def __init__(self, folder, case_id, latest_excel, file_count):
        self.folder = Path(folder)
        self.case_id = case_id
        self.latest_excel = latest_excel
        self.file_count = file_count


class ZipIntake:
    def __init__(self, root, client):
        self.root = Path(root)
        self.client = client

    def stage(self, context, stop_requested=lambda: False, progress=None):
        cases_root = self.root / "cases"
        cases_root.mkdir(parents=True, exist_ok=True)
        # The run ID is already constrained, and this directory is owned only by this run.
        final = cases_root / f"{context.run_id}_{context.dispatch_id}"
        if final.exists():
            manifest_path = final / "web_sync_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            validate_staged_case(final, manifest["case_id"], context.dispatch_id,
                                 manifest["latest_excel"], verify_md5=True)
            return PreparedCase(final, manifest["case_id"], manifest["latest_excel"], len(manifest["files"]))
        work = Path(tempfile.mkdtemp(prefix="helper-stage-", dir=cases_root))
        archive_path = work / "case.zip.download"
        extracted = work / "extracted"
        try:
            self.client.download_zip(context, archive_path, stop_requested)
            if stop_requested():
                raise InterruptedError("case intake stopped")
            if not zipfile.is_zipfile(archive_path):
                raise ZipIntegrityError("Base44 returned a corrupt ZIP")
            with zipfile.ZipFile(archive_path) as archive:
                members = _inspect_archive(archive)
                if "manifest.json" in members:
                    # The launch contract has no case_id. The signed ZIP manifest
                    # supplies it; dispatch identity is checked before extraction.
                    manifest_bytes = archive.read(members["manifest.json"][1])
                    embedded = json.loads(manifest_bytes.decode("utf-8"))
                    case_id = embedded.get("case_id")
                    if not isinstance(case_id, str) or not case_id:
                        raise ZipIntegrityError("Drive ZIP manifest has no case_id")
                    _manifest, files = _read_embedded_manifest(
                        archive, members, case_id, context.dispatch_id)
                    planned, latest_excel = _plan_files(files, members)
                    mapping = _extract_verified(archive, planned, extracted, progress)
                else:
                    # The local-case bundle has no embedded case identifier. Use the
                    # redeemed run identity for the generated local stage manifest.
                    case_id = context.case_ref
                    mapping, latest_excel = _extract_local_case_zip(
                        archive, members, extracted, progress)
            if stop_requested():
                raise InterruptedError("case intake stopped")
            atomic_json(extracted / "web_sync_manifest.json", {
                "case_id": case_id, "automation_dispatch_id": context.dispatch_id,
                "latest_excel": latest_excel, "complete": True,
                "download_mode": "helper_zip", "files": mapping,
            })
            validate_staged_case(extracted, case_id, context.dispatch_id,
                                 latest_excel, verify_md5=True)
            extracted.replace(final)
            return PreparedCase(final, case_id, latest_excel, len(mapping))
        finally:
            # Only this temporary directory is removed; completed cases survive.
            shutil.rmtree(work, ignore_errors=True)
