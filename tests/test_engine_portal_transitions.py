import pytest

pytest.importorskip("playwright")

from app.automation.engine import _get_active_page


class FakeLocator:
    def __init__(self, visible):
        self._visible = visible
        self.first = self

    async def is_visible(self, timeout=0):
        return self._visible


class FakePage:
    def __init__(self, url, login_visible=False):
        self.url = url
        self._closed = False
        self._login_visible = login_visible
        self.brought_to_front = False

    def is_closed(self):
        return self._closed

    async def bring_to_front(self):
        self.brought_to_front = True

    async def goto(self, url, wait_until=None, timeout=None):
        self.url = url

    async def wait_for_load_state(self, state, timeout=None):
        return None

    def locator(self, _selector):
        return FakeLocator(self._login_visible)

    async def close(self):
        self._closed = True


class FakeContext:
    def __init__(self, pages=None, new_pages=None):
        self.pages = pages or []
        self._new_pages = list(new_pages or [])
        self.new_page_calls = 0

    async def new_page(self):
        self.new_page_calls += 1
        if self._new_pages:
            page = self._new_pages.pop(0)
        else:
            page = FakePage("about:blank")
        self.pages.append(page)
        return page


@pytest.mark.asyncio
async def test_get_active_page_prefers_existing_surveyor_tab():
    login_tab = FakePage("https://portal.uiic.in/surveyor/home.jsp")
    surveyor_tab = FakePage("https://portal.uiic.in/surveyor/data/Surveyor.html#/Worklist")
    context = FakeContext(pages=[login_tab, surveyor_tab])

    logs = []
    page = await _get_active_page(
        context=context,
        log_cb=logs.append,
        captured_pages=[],
        stop_cb=lambda: False,
    )

    assert page is surveyor_tab
    assert surveyor_tab.brought_to_front is True
    assert context.new_page_calls == 0


@pytest.mark.asyncio
async def test_get_active_page_falls_back_to_new_worklist_page(monkeypatch):
    login_tab = FakePage("https://portal.uiic.in/surveyor/home.jsp", login_visible=True)
    new_worklist_page = FakePage("https://portal.uiic.in/surveyor/data/Surveyor.html#/Worklist", login_visible=False)
    context = FakeContext(pages=[login_tab], new_pages=[new_worklist_page])

    async def _not_login_form(_page):
        return False

    monkeypatch.setattr("app.automation.engine._page_has_login_form", _not_login_form)

    logs = []
    page = await _get_active_page(
        context=context,
        log_cb=logs.append,
        captured_pages=[],
        stop_cb=lambda: False,
    )

    assert page is new_worklist_page
    assert context.new_page_calls >= 1
    assert any("Opening authenticated Worklist page" in line for line in logs)


@pytest.mark.asyncio
async def test_get_active_page_honors_stop_request():
    context = FakeContext(pages=[FakePage("https://portal.uiic.in/surveyor/home.jsp")])

    page = await _get_active_page(
        context=context,
        log_cb=lambda _msg: None,
        captured_pages=[],
        stop_cb=lambda: True,
    )

    assert page is None
