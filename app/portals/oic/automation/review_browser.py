"""Launch an isolated OIC browser that can outlive the automation connection."""

import asyncio
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path


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
        profile.rmdir()
        raise

    def clean_profile_after_close():
        process.wait()
        shutil.rmtree(profile, ignore_errors=True)

    threading.Thread(target=clean_profile_after_close, daemon=True).start()
    port_file = profile / "DevToolsActivePort"
    deadline = asyncio.get_running_loop().time() + 15
    while asyncio.get_running_loop().time() < deadline:
        if stopped():
            raise asyncio.CancelledError
        if process.poll() is not None:
            raise RuntimeError(f"Chrome exited before {portal_name} automation could connect.")
        try:
            port = int(port_file.read_text(encoding="utf-8").splitlines()[0])
        except (OSError, ValueError, IndexError):
            await asyncio.sleep(0.1)
            continue
        return await browser_type.connect_over_cdp(
            f"http://127.0.0.1:{port}", timeout=5000, slow_mo=slow_mo,
        )
    raise RuntimeError(f"{portal_name} automation could not connect to Chrome. Check the open window.")
