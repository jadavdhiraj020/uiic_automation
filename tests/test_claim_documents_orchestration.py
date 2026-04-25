from types import SimpleNamespace

import pytest

from app.automation import claim_documents


class FakeUploadService:
    instances = []

    def __init__(self, page, log_cb):
        self.page = page
        self.log_cb = log_cb
        self.wait_calls = []
        self.upload_calls = []
        self.retry_calls = []
        FakeUploadService.instances.append(self)

    async def wait_for_upload_section(self, timeout_ms):
        self.wait_calls.append(timeout_ms)

    async def upload_queue(self, queue, wait_timeout_ms, fallback_option_index):
        self.upload_calls.append((queue, wait_timeout_ms, fallback_option_index))
        return (
            [("PAN Card", "pan.pdf", "OK", "Uploaded successfully")],
            [(0, "PAN Card", "C:/tmp/pan.pdf")],
        )

    async def row_shows_expected_file(self, row_idx, expected_name, timeout_ms=2000):
        return True

    async def select_doc_and_set_file(self, row_index, doc_label, file_path, timeout_ms):
        self.retry_calls.append((row_index, doc_label, file_path, timeout_ms))
        return True

    async def wait_after_upload(self, row_idx, wait_ms):
        return None


class FakePage:
    def __init__(self):
        self.dialog_handlers = []

    def on(self, event_name, handler):
        if event_name == "dialog":
            self.dialog_handlers.append(handler)


@pytest.mark.asyncio
async def test_fill_claim_documents_uses_upload_service(monkeypatch, tmp_path):
    FakeUploadService.instances = []

    doc_file = tmp_path / "pan.pdf"
    doc_file.write_text("ok", encoding="utf-8")

    claim = SimpleNamespace(
        payment_to="REPAIRER",
        _excel_coords={},
        claim_doc_files={"PAN Card": str(doc_file)},
    )

    monkeypatch.setattr(claim_documents, "click_tab", _async_noop)
    monkeypatch.setattr(claim_documents, "_click_doc_radios", _async_noop)
    monkeypatch.setattr(claim_documents, "_click_payment_option", _async_noop)
    monkeypatch.setattr(claim_documents, "DocumentUploadService", FakeUploadService)
    monkeypatch.setattr(claim_documents, "load_settings", lambda: {"upload_wait_ms": 3100})

    logs = []
    page = FakePage()

    await claim_documents.fill_claim_documents(page=page, claim=claim, log_cb=logs.append)

    assert len(FakeUploadService.instances) == 1
    service = FakeUploadService.instances[0]
    assert service.wait_calls == [15000]
    assert service.upload_calls
    queued_doc_type = service.upload_calls[0][0][0][0]
    assert queued_doc_type == "PAN Card"
    assert any("UPLOAD SUMMARY" in line for line in logs)


@pytest.mark.asyncio
async def test_fill_claim_documents_handles_empty_queue(monkeypatch):
    claim = SimpleNamespace(payment_to="", _excel_coords={}, claim_doc_files={})

    monkeypatch.setattr(claim_documents, "click_tab", _async_noop)
    monkeypatch.setattr(claim_documents, "_click_doc_radios", _async_noop)
    monkeypatch.setattr(claim_documents, "_click_payment_option", _async_noop)

    logs = []
    await claim_documents.fill_claim_documents(page=FakePage(), claim=claim, log_cb=logs.append)

    assert any("No documents to process" in line for line in logs)


async def _async_noop(*_args, **_kwargs):
    return None
