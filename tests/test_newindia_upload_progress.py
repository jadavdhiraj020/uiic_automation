"""New India mandatory upload: a partial banner count is progress, not failure.

Run from the project folder:
    uv run pytest tests/test_newindia_upload_progress.py -v

All values are synthetic; no browser is started.
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.portals.newindia.automation import document_upload_module as du  # noqa: E402


def _install_fakes(monkeypatch, banners):
    """banners: list of (success_text, error_text) returned on successive polls."""
    calls = {"n": 0}

    async def fake_popup(*_a, **_k):
        return None

    async def fake_new_text(_page, _previous):
        idx = min(calls["n"], len(banners) - 1)
        calls["n"] += 1
        return banners[idx]

    async def fake_statuses(_page, _rows):
        return 0, 0

    async def fake_staged(_page):
        return {0: ("x", ("a.pdf",))}  # still staged: table fallback must not fire

    async def fake_uploaded(_page):
        return 0

    monkeypatch.setattr(du, "dismiss_portal_popup", fake_popup)
    monkeypatch.setattr(du, "_new_inline_upload_text", fake_new_text)
    monkeypatch.setattr(du, "_count_mandatory_upload_statuses", fake_statuses)
    monkeypatch.setattr(du, "_staged_mandatory_files", fake_staged)
    monkeypatch.setattr(du, "_count_uploaded_documents", fake_uploaded)


def _run(rows, banners, max_wait_s):
    logs = []
    return asyncio.run(
        du._wait_for_mandatory_upload_outcome(
            page=None, row_indices=tuple(range(rows)), log=logs.append,
            stop_cb=lambda: False, previous_banners=(("", 0), ("", 0)),
            max_wait_s=max_wait_s,
        )
    )


def test_counting_up_banner_succeeds(monkeypatch):
    _install_fakes(monkeypatch, [
        ("1 Documents Uploaded Sucessfully", ""),
        ("3 Documents Uploaded Sucessfully", ""),
        ("4 Documents Uploaded Sucessfully", ""),
    ])
    ok, reason = _run(4, None, max_wait_s=5)
    assert ok, reason


def test_stalled_partial_count_fails_with_count(monkeypatch):
    _install_fakes(monkeypatch, [("1 Documents Uploaded Sucessfully", "")])
    ok, reason = _run(4, None, max_wait_s=0.6)
    assert not ok
    assert reason.startswith("Only 1/4 mandatory documents uploaded")


def test_error_banner_fails_immediately(monkeypatch):
    _install_fakes(monkeypatch, [("", "File size exceeded")])
    ok, reason = _run(2, None, max_wait_s=5)
    assert not ok
    assert "upload error" in reason.lower()
