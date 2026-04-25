import asyncio
import logging
import os
from typing import Callable, List, Optional, Tuple

MAX_FILE_MB = 2.0

logger = logging.getLogger(__name__)


class DocumentUploadService:
    """Encapsulates upload panel interaction and row/file lifecycle."""

    def __init__(self, page, log_cb: Callable[[str], None]):
        self.page = page
        self.log_cb = log_cb

    async def get_upload_panel(self):
        panel = self.page.locator(".panel.panel-yellow").filter(
            has=self.page.locator(".panel-title", has_text="Upload Document")
        ).first
        return panel

    async def wait_for_upload_section(self, timeout_ms: int) -> None:
        panel = await self.get_upload_panel()
        await panel.wait_for(state="visible", timeout=timeout_ms)
        await panel.locator('select[name^="docType"]').first.wait_for(
            state="visible", timeout=timeout_ms
        )
        await panel.locator('input[type="file"][name^="fileToUpload"]').first.wait_for(
            state="attached", timeout=timeout_ms
        )

    async def get_row_handles(self, row_index: int, timeout_ms: int = 10000):
        panel = await self.get_upload_panel()
        row_select = panel.locator('select[name^="docType"]').nth(row_index)
        await row_select.wait_for(state="visible", timeout=timeout_ms)
        row_container = row_select.locator(
            "xpath=ancestor::*[.//input[@type='file' and starts-with(@name,'fileToUpload')]][1]"
        )
        row_file = row_container.locator('input[type="file"][name^="fileToUpload"]').first
        await row_file.wait_for(state="attached", timeout=timeout_ms)
        return panel, row_select, row_container, row_file

    async def row_shows_expected_file(
        self, row_index: int, expected_name: str, timeout_ms: int = 3000
    ) -> bool:
        try:
            _, _, row_container, row_file = await self.get_row_handles(row_index, timeout_ms=timeout_ms)
            row_text = (await row_container.inner_text(timeout=1000)).strip().lower()
            if expected_name.lower() in row_text and "no file chosen" not in row_text:
                return True
            try:
                selected_name = await row_file.evaluate(
                    """
                    el => {
                        if (!el || !el.files || !el.files.length) return '';
                        return el.files[0].name || '';
                    }
                    """
                )
                return bool(selected_name and selected_name.lower() == expected_name.lower())
            except Exception:
                return False
        except Exception:
            return False

    async def dismiss_upload_popup(self, timeout_ms: int = 4000) -> bool:
        dismiss_selectors = [
            "div.modal.in button:has-text('OK')",
            "div.modal.show button:has-text('OK')",
            "div[role='dialog'] button:has-text('OK')",
            ".modal-dialog button:has-text('OK')",
            ".modal-footer .btn-primary",
            ".modal-footer button",
            ".bootbox button:has-text('OK')",
            ".swal-button",
            ".swal2-confirm",
            "button:has-text('OK')",
            "button:has-text('Yes')",
            "button:has-text('Close')",
        ]

        dismissed = False
        end_time = asyncio.get_running_loop().time() + max(timeout_ms, 1000) / 1000.0
        while asyncio.get_running_loop().time() < end_time:
            for sel in dismiss_selectors:
                try:
                    btn = self.page.locator(sel).first
                    if await btn.is_visible(timeout=250):
                        label = (await btn.inner_text(timeout=250)).strip() or "button"
                        await btn.click(force=True, timeout=1000)
                        self.log_cb(f"    ℹ️  Closed upload popup via '{label[:40]}'")
                        dismissed = True
                        await asyncio.sleep(0.6)
                        break
                except Exception:
                    continue
            else:
                try:
                    clicked = await self.page.evaluate(
                        """
                        () => {
                            const isVisible = (el) => {
                                if (!el) return false;
                                const style = window.getComputedStyle(el);
                                const rect = el.getBoundingClientRect();
                                return style.visibility !== 'hidden' &&
                                       style.display !== 'none' &&
                                       rect.width > 0 &&
                                       rect.height > 0;
                            };

                            const candidates = Array.from(document.querySelectorAll('button, a, span'))
                                .filter(isVisible)
                                .filter(el => /^(ok|yes|close)$/i.test((el.textContent || '').trim()));

                            candidates.sort((a, b) => {
                                const az = Number(window.getComputedStyle(a).zIndex) || 0;
                                const bz = Number(window.getComputedStyle(b).zIndex) || 0;
                                return bz - az;
                            });

                            const target = candidates[0];
                            if (!target) return null;
                            target.click();
                            return (target.textContent || '').trim();
                        }
                        """
                    )
                    if clicked:
                        self.log_cb(f"    ℹ️  Closed upload popup via DOM '{clicked[:40]}'")
                        dismissed = True
                        await asyncio.sleep(0.6)
                        continue
                except Exception:
                    pass
                break

        try:
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.2)
        except Exception:
            pass

        return dismissed

    async def wait_after_upload(self, row_index: int, wait_ms: int) -> None:
        deadline = asyncio.get_running_loop().time() + max(wait_ms, 2000) / 1000.0

        while asyncio.get_running_loop().time() < deadline:
            await self.dismiss_upload_popup(timeout_ms=900)
            try:
                await self.page.wait_for_load_state("networkidle", timeout=1000)
            except Exception:
                pass
            try:
                _, _, _, file_input = await self.get_row_handles(row_index, timeout_ms=1000)
                await file_input.wait_for(state="attached", timeout=500)
            except Exception:
                pass
            await asyncio.sleep(0.4)

        await self.dismiss_upload_popup(timeout_ms=1200)

    async def select_doc_and_set_file(
        self, row_index: int, doc_label: str, file_path: str, timeout_ms: int
    ) -> bool:
        _, row_select, row_container, row_file = await self.get_row_handles(
            row_index, timeout_ms=timeout_ms
        )
        await row_select.wait_for(state="visible", timeout=timeout_ms)

        dropdown_set = False
        try:
            await row_select.select_option(label=doc_label, timeout=5000)
            self.log_cb(f"      ✅ Doc type (label): {doc_label}")
            dropdown_set = True
        except Exception as e1:
            logger.debug("Label select failed for '%s': %s", doc_label, str(e1)[:60])
            try:
                await row_select.select_option(value=f"string:{doc_label}", timeout=5000)
                self.log_cb(f"      ✅ Doc type (value): {doc_label}")
                dropdown_set = True
            except Exception as e2:
                logger.debug("Value select failed for '%s': %s", doc_label, str(e2)[:60])
                js_ok = await self.page.evaluate(
                    f"""
                    (function() {{
                        var selects = document.querySelectorAll('select[name^="docType"]');
                        var target = selects[{row_index}];
                        if (!target) return null;
                        var opts = Array.from(target.options);
                        var search = '{doc_label.lower()[:30]}';
                        var match = opts.find(o => o.text.toLowerCase().includes(search));
                        if (!match) {{
                            var words = search.split(' ');
                            for (var w of words) {{
                                if (w.length > 3) {{
                                    match = opts.find(o => o.text.toLowerCase().includes(w));
                                    if (match) break;
                                }}
                            }}
                        }}
                        if (match) {{
                            target.value = match.value;
                            target.dispatchEvent(new Event('change', {{bubbles: true}}));
                            return match.text;
                        }}
                        return null;
                    }})();
                    """
                )
                if not js_ok:
                    self.log_cb(f"      ❌ Doc type FAILED for '{doc_label}' — not found in portal dropdown")
                    logger.error("Dropdown set failed: '%s' not found in portal options", doc_label)
                    return False
                self.log_cb(f"      ✅ Doc type (JS fallback): '{js_ok}'")
                dropdown_set = True

        if not dropdown_set:
            return False

        abs_path = str(os.path.abspath(file_path))
        expected_name = os.path.basename(file_path)
        is_large_file = os.path.getsize(file_path) / (1024 * 1024) > MAX_FILE_MB
        max_attempts = 1 if is_large_file else 2

        for attempt in range(1, max_attempts + 1):
            try:
                _, _, row_container, row_file = await self.get_row_handles(row_index, timeout_ms=timeout_ms)
                await row_file.set_input_files(abs_path)
                await asyncio.sleep(0.4)
                await self.dismiss_upload_popup(timeout_ms=2500)
                await asyncio.sleep(0.8)
                row_text = (await row_container.inner_text(timeout=1000)).strip().lower()
                selected_name = await row_file.evaluate(
                    """
                    el => {
                        if (!el || !el.files || !el.files.length) return '';
                        return el.files[0].name || '';
                    }
                    """
                )
                if (
                    expected_name.lower() in row_text and "no file chosen" not in row_text
                ) or (selected_name and selected_name.lower() == expected_name.lower()):
                    if attempt > 1:
                        self.log_cb(f"      ℹ️  File attach succeeded on retry {attempt}")
                    return True

                self.log_cb(
                    f"      ⚠️  File attach did not stick for '{doc_label}' "
                    f"(attempt {attempt}/{max_attempts}, got '{selected_name or 'empty'}')"
                )
            except Exception as exc:
                self.log_cb(f"      ⚠️  File attach retry {attempt}/{max_attempts} failed: {str(exc)[:70]}")

            await asyncio.sleep(0.8)

        self.log_cb(f"      ❌ File input did not retain '{expected_name}'")
        logger.error("File input did not retain file for row %d (%s)", row_index, doc_label)
        return False

    async def click_plus(self, timeout_ms: int = 10000) -> bool:
        panel = await self.get_upload_panel()
        before_count = await panel.locator('select[name^="docType"]').count()

        try:
            plus_img = panel.locator('img[src*="plus-4-xxl"]').first
            if await plus_img.count() > 0:
                await plus_img.click(timeout=5000)
                await asyncio.sleep(0.8)
        except Exception:
            pass

        try:
            await self.page.evaluate(
                """
                (function() {
                    var all = document.querySelectorAll('[ng-click],[data-ng-click]');
                    for (var el of all) {
                        var nc = (el.getAttribute('ng-click') || el.getAttribute('data-ng-click') || '').toLowerCase();
                        if (nc.includes('add') && (nc.includes('row') || nc.includes('document'))) {
                            el.click();
                            return nc;
                        }
                    }
                    return null;
                })();
                """
            )
            await asyncio.sleep(0.8)
        except Exception:
            pass

        css_selectors = [
            "a[ng-click*='addDocumentRow']",
            "a[ng-click*='addDocument']",
            "a[ng-click*='addRow']",
            "button[ng-click*='addDocument']",
            "button[ng-click*='addRow']",
            "button.btn-warning",
            "a:has(img[src*='plus'])",
        ]
        for sel in css_selectors:
            try:
                btn = self.page.locator(sel).last
                if await btn.is_visible(timeout=1000):
                    await btn.click(timeout=3000)
                    await asyncio.sleep(0.8)
                    break
            except Exception:
                continue

        try:
            await self.page.evaluate(
                """
                (function() {
                    var imgs = document.querySelectorAll('img[src*="plus"]');
                    for (var img of imgs) {
                        var p = img.parentElement;
                        if (p && (p.tagName === 'A' || p.tagName === 'BUTTON')) {
                            p.click();
                            return true;
                        }
                    }
                    return false;
                })();
                """
            )
        except Exception:
            pass

        await asyncio.sleep(1.0)
        after_count = await panel.locator('select[name^="docType"]').count()
        if after_count > before_count:
            self.log_cb("    ➕ New row added to DOM successfully")
            return True

        self.log_cb("    ⚠️  PLUS button click failed to add new row")
        return False

    async def set_doc_type_by_index(self, row_idx: int, option_index: int) -> None:
        result = await self.page.evaluate(
            f"""
            (function() {{
                var selects = document.querySelectorAll('select[name^="docType"]');
                var target = selects[{row_idx}];
                if (!target || target.options.length <= {option_index}) return null;
                target.selectedIndex = {option_index};
                target.dispatchEvent(new Event('change', {{bubbles:true}}));
                return target.options[{option_index}].text;
            }})();
            """
        )
        if result:
            self.log_cb(f"      ℹ️  No file — set dropdown to option {option_index}: '{result}'")
        else:
            self.log_cb(f"      ⚠️  Could not set fallback dropdown option {option_index}")

    async def upload_queue(
        self,
        queue: List[Tuple[str, Optional[str]]],
        wait_timeout_ms: int,
        fallback_option_index: int,
    ) -> Tuple[List[Tuple[str, str, str, str]], List[Tuple[int, str, str]]]:
        upload_results: List[Tuple[str, str, str, str]] = []
        uploaded_rows: List[Tuple[int, str, str]] = []

        for idx, (doc_type, file_path) in enumerate(queue):
            fname = os.path.basename(file_path) if file_path else "[no file]"
            self.log_cb(f"\n  [{idx+1}/{len(queue)}] '{doc_type}' → {fname}")

            if idx == 0:
                panel = await self.get_upload_panel()
                existing = await panel.locator('select[name^="docType"]').count()
                if existing == 0:
                    self.log_cb("    ⚠️  No pre-existing row found — adding first row")
                    await self.click_plus(timeout_ms=wait_timeout_ms)
                else:
                    self.log_cb(f"    ℹ️  Using pre-existing row (row count: {existing})")
            else:
                self.log_cb("    ➕ Clicking PLUS for new row...")
                added = await self.click_plus(timeout_ms=wait_timeout_ms)
                if not added:
                    self.log_cb(f"    ❌ Could not add row — skipping '{doc_type}'")
                    logger.error("PLUS button failed for row %d (doc: %s)", idx, doc_type)
                    upload_results.append((doc_type, fname, "FAILED", "Could not add upload row"))
                    continue

            row_idx = idx

            if file_path:
                try:
                    ok = await self.select_doc_and_set_file(
                        row_idx, doc_type, file_path, wait_timeout_ms
                    )
                    if ok:
                        await self.wait_after_upload(row_idx, wait_timeout_ms)
                        self.log_cb(f"    ✅ Uploaded: {fname}")
                        logger.info("Upload OK: [%s] → %s", doc_type, fname)
                        upload_results.append((doc_type, fname, "OK", "Uploaded successfully"))
                        uploaded_rows.append((row_idx, doc_type, file_path))
                    else:
                        self.log_cb(f"    ❌ Upload FAILED for: {fname}")
                        logger.error("Upload FAILED: [%s] → %s — dropdown or file set failed", doc_type, fname)
                        upload_results.append((doc_type, fname, "FAILED", "Dropdown selection or file upload failed"))
                except Exception as e:
                    self.log_cb(f"    ❌ Upload error: {str(e)[:80]}")
                    logger.error("Upload exception: [%s] → %s — %s", doc_type, fname, str(e)[:120])
                    upload_results.append((doc_type, fname, "FAILED", f"Exception: {str(e)[:80]}"))
            else:
                await self.set_doc_type_by_index(row_idx, fallback_option_index)
                logger.warning("No file for [%s] — set fallback dropdown", doc_type)
                upload_results.append((doc_type, fname, "SKIPPED", "File not found"))

        return upload_results, uploaded_rows
