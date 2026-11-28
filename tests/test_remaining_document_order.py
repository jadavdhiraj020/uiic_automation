"""Remaining-document merge order for New India and OIC."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pypdfium2
import pytest

from app.automation.services.document_order import order_remaining_documents
from app.data import folder_scanner
from app.portals.oic import generated_files


def _pdf(path, width):
    document = pypdfium2.PdfDocument.new()
    page = document.new_page(width=width, height=100)
    page.close()
    document.save(str(path))
    document.close()


def test_requested_categories_are_ordered_and_unknown_files_are_last():
    expected = [
        "survey report.pdf", "re-inspection survey report.pdf", "survey fee bill.pdf",
        "estimate.pdf", "tax invoice.pdf", "payment receipt.pdf",
        "RC registration certificate.pdf", "DL merged.pdf", "tax receipt.pdf",
        "fitness certificate.pdf", "permit.pdf", "claim form.pdf", "voucher.pdf",
        "cancel cheque.pdf", "PAN card.pdf", "adhar card.pdf", "KYC.pdf", "other.pdf",
    ]
    assert order_remaining_documents(list(reversed(expected))) == expected


@pytest.mark.parametrize("portal", ["newindia", "oic"])
def test_scan_merges_only_remaining_documents_in_the_requested_order(tmp_path, monkeypatch, portal):
    folder = tmp_path / "claim"
    folder.mkdir()
    widths = {"z_estimate.pdf": 101, "m_tax.pdf": 102, "a_kyc.pdf": 103,
              "b_other.pdf": 104, "rc.pdf": 105}
    for name, width in widths.items():
        _pdf(folder / name, width)

    monkeypatch.setattr(generated_files, "user_data_dir", lambda *parts: str(tmp_path.joinpath("app", *parts)))
    monkeypatch.setattr(
        folder_scanner, "get_doc_mapping_tuple",
        lambda **kwargs: ({}, {}, [], [], {"registration_certificate": ["rc"]}, []),
    )
    monkeypatch.setattr("app.utils.load_automation_defaults", lambda **kwargs: {})
    monkeypatch.setattr("app.portals.registry.get_portal", lambda portal_id: SimpleNamespace(requires_document_merge=True))

    # A second scan must preserve the same order and must not merge the old
    # output into itself.
    for _ in range(2):
        result = folder_scanner.scan_folder(str(folder), portal_id=portal)
        assert result.upload_doc_files["registration_certificate"] == str(folder / "rc.pdf")
        assert [Path(path).name for path in result.claim_related_files] == [
            "z_estimate.pdf", "m_tax.pdf", "a_kyc.pdf", "b_other.pdf",
        ]
        document = pypdfium2.PdfDocument(result.claim_related_merged_pdf)
        try:
            assert [round(document[index].get_width()) for index in range(len(document))] == [101, 102, 103, 104]
        finally:
            document.close()
    assert len(list(folder.glob("claim_others_documents*.pdf"))) == 1


def test_uiic_does_not_start_a_remaining_document_merge(tmp_path, monkeypatch):
    _pdf(tmp_path / "misc.pdf", 101)
    monkeypatch.setattr(folder_scanner, "get_doc_mapping_tuple", lambda **kwargs: ({}, {}, [], [], {}, []))
    monkeypatch.setattr("app.utils.load_automation_defaults", lambda **kwargs: {})
    monkeypatch.setattr("app.portals.registry.get_portal", lambda portal_id: SimpleNamespace(requires_document_merge=False))
    result = folder_scanner.scan_folder(str(tmp_path), portal_id="uiic")
    assert result.claim_related_files == []
    assert result.claim_related_merged_pdf is None


def test_oic_runtime_merge_fallback_orders_the_current_scan(tmp_path, monkeypatch):
    from app.portals.oic.automation import document_upload_module as module

    names = ["z_kyc.pdf", "a_tax.pdf", "m_estimate.pdf"]
    for name in names:
        _pdf(tmp_path / name, 100)
    data = SimpleNamespace(_scan_result=SimpleNamespace(
        claim_related_merged_pdf=None,
        claim_related_files=[str(tmp_path / name) for name in names],
    ))
    seen = []

    def merge(paths, output, config, log=None):
        seen.extend(Path(path).name for path in paths)
        _pdf(output, 100)
        return output

    monkeypatch.setattr(module.PdfMergeService, "merge", merge)
    monkeypatch.setattr(module, "_compress_if_needed", lambda path, *args, **kwargs: path)
    monkeypatch.setattr(module, "_attach_document", AsyncMock(return_value=True))
    monkeypatch.setattr(module, "dismiss_portal_popup", AsyncMock())
    assert asyncio.run(module._upload_other_documents(MagicMock(), data, MagicMock(), set()))
    assert seen == ["m_estimate.pdf", "a_tax.pdf", "z_kyc.pdf"]
