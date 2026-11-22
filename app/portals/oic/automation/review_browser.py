"""Launch an isolated Chrome browser that can outlive the automation connection."""

import asyncio
import shutil
import subprocess
import sys
import tempfile
import threading
from contextlib import suppress
from pathlib import Path


def bring_browser_window_to_front(pid: int | None) -> bool:
    """Best-effort OS raise for the Chrome window owning *pid* without touching Qt focus."""
    if not pid or sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        chrome_matches = []
        other_matches = []

        def _visit(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            if user32.GetWindowTextLengthW(hwnd) <= 0:
                return True
            owner = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value != pid:
                return True
            buf = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(hwnd, buf, 128)
            if "Chrome_WidgetWin" in buf.value:
                chrome_matches.append(hwnd)
            else:
                other_matches.append(hwnd)
            return True

        user32.EnumWindows(enum_proc(_visit), 0)
        targets = chrome_matches or other_matches
        if not targets:
            return False
        hwnd = targets[0]
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        else:
            user32.ShowWindow(hwnd, 5)  # SW_SHOW
        fg = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        tgt_tid = user32.GetWindowThreadProcessId(hwnd, None)
        cur_tid = kernel32.GetCurrentThreadId()
        attached_fg = bool(fg_tid and fg_tid != cur_tid and user32.AttachThreadInput(cur_tid, fg_tid, True))
        attached_tgt = bool(tgt_tid and tgt_tid != cur_tid and user32.AttachThreadInput(cur_tid, tgt_tid, True))
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached_tgt:
                user32.AttachThreadInput(cur_tid, tgt_tid, False)
            if attached_fg:
                user32.AttachThreadInput(cur_tid, fg_tid, False)
        return True
    except Exception:
        return False


async def focus_chrome(page, pid: int | None = None) -> None:
    """Bring the review Chrome window and active tab to the front safely."""
    with suppress(Exception):
        bring_browser_window_to_front(pid)
    if page and not page.is_closed():
        with suppress(Exception):
            await asyncio.wait_for(page.bring_to_front(), timeout=2)


async def launch_review_browser(browser_type, args, slow_mo, stopped, *, portal_name="OIC"):
    executable = Path(browser_type.executable_path)
    if not executable.is_file():
        raise FileNotFoundError(f"Playwright Chromium was not found at {executable}. Run playwright install chromium.")
    profile = Path(tempfile.mkdtemp(prefix=f"{portal_name.lower().replace(' ', '-')}-review-"))
    try:
        process = subprocess.Popen(
            [str(executable), *args, "--remote-debugging-port=0",
             "--remote-debugging-address=127.0.0.1", f"--user-data-dir={profile}",
             "--no-first-run", "--no-default-browser-check", "about:blank"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    except BaseException:
        shutil.rmtree(profile, ignore_errors=True)
        raise

    def clean_profile_after_close():
        process.wait()
        shutil.rmtree(profile, ignore_errors=True)

    threading.Thread(target=clean_profile_after_close, daemon=True).start()
    port_file = profile / "DevToolsActivePort"
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 25
    while loop.time() < deadline:
        if stopped():
            with suppress(Exception):
                process.terminate()
            raise asyncio.CancelledError
        if process.poll() is not None:
            raise RuntimeError(f"Chrome exited before {portal_name} automation could connect.")
        try:
            port = int(port_file.read_text(encoding="utf-8").splitlines()[0])
        except (OSError, ValueError, IndexError):
            await asyncio.sleep(0.1)
            continue
        try:
            browser = await browser_type.connect_over_cdp(
                f"http://127.0.0.1:{port}", timeout=5000, slow_mo=slow_mo,
            )
        except Exception:
            await asyncio.sleep(0.25)
            continue
        ctx_deadline = min(deadline, loop.time() + 3.0)
        while not browser.contexts and loop.time() < ctx_deadline:
            if stopped():
                with suppress(Exception):
                    await browser.close()
                with suppress(Exception):
                    process.terminate()
                raise asyncio.CancelledError
            await asyncio.sleep(0.1)
        browser._app3_review_pid = process.pid
        return browser
    with suppress(Exception):
        process.terminate()
    raise RuntimeError(f"{portal_name} automation could not connect to Chrome. Check the open window.")
