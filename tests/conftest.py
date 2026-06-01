import os
import sys
import pytest
import asyncio

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


@pytest.fixture
def fast_sleep(monkeypatch):
    """Monkeypatch asyncio.sleep to yield control but return instantly in tests.

    This fixture is NOT auto-used. Apply it explicitly to tests that call
    production code containing ``await asyncio.sleep(...)`` and where you want
    those sleeps to complete instantly.
    """
    original_sleep = asyncio.sleep
    async def mock_sleep(delay=0, *args, **kwargs):
        await original_sleep(0)
    monkeypatch.setattr(asyncio, "sleep", mock_sleep)

