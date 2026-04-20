import os
import re

def fix_assessment():
    with open('app/automation/claim_assessment.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # Strategy 0 (target el)
    content = re.sub(
        r'await el\.set_input_files\(abs_path\)\s+try:\s+await page\.wait_for_load_state\("networkidle", timeout=\d+\)\s+except Exception:\s+await asyncio\.sleep\(1\.5\)',
        r'''await el.set_input_files(abs_path)
                try:
                    await page.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))", arg=el)
                except Exception:
                    pass
                await asyncio.sleep(3.0)''',
        content
    )

    # Strategy 1 (target element)
    content = re.sub(
        r'await element\.set_input_files\(abs_path\)\s+try:\s+await page\.wait_for_load_state\("networkidle", timeout=\d+\)\s+except Exception:\s+await asyncio\.sleep\(1\.5\)',
        r'''await element.set_input_files(abs_path)
                try:
                    await page.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))", arg=element)
                except Exception:
                    pass
                await asyncio.sleep(3.0)''',
        content
    )

    # Strategy 2 (target file_input)
    content = re.sub(
        r'await file_input\.set_input_files\(abs_path\)\s+try:\s+await page\.wait_for_load_state\("networkidle", timeout=\d+\)\s+except Exception:\s+await asyncio\.sleep\(1\.5\)',
        r'''await file_input.set_input_files(abs_path)
                try:
                    await page.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))", arg=file_input)
                except Exception:
                    pass
                await asyncio.sleep(3.0)''',
        content
    )

    # Strategy 3 parent (target sibling_input.first)
    content = re.sub(
        r'await sibling_input\.first\.set_input_files\(abs_path\)\s+try:\s+await page\.wait_for_load_state\("networkidle", timeout=\d+\)\s+except Exception:\s+await asyncio\.sleep\(1\.5\)',
        r'''await sibling_input.first.set_input_files(abs_path)
                try:
                    await page.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))", arg=sibling_input.first)
                except Exception:
                    pass
                await asyncio.sleep(3.0)''',
        content
    )

    # Strategy 3 gp (target gp_input.first)
    content = re.sub(
        r'await gp_input\.first\.set_input_files\(abs_path\)\s+try:\s+await page\.wait_for_load_state\("networkidle", timeout=\d+\)\s+except Exception:\s+await asyncio\.sleep\(1\.5\)',
        r'''await gp_input.first.set_input_files(abs_path)
                try:
                    await page.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))", arg=gp_input.first)
                except Exception:
                    pass
                await asyncio.sleep(3.0)''',
        content
    )

    # Strategy 4 (target inp.first)
    content = re.sub(
        r'await inp\.first\.set_input_files\(abs_path\)\s+try:\s+await page\.wait_for_load_state\("networkidle", timeout=\d+\)\s+except Exception:\s+await asyncio\.sleep\(1\.5\)',
        r'''await inp.first.set_input_files(abs_path)
                try:
                    await page.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))", arg=inp.first)
                except Exception:
                    pass
                await asyncio.sleep(3.0)''',
        content
    )

    with open('app/automation/claim_assessment.py', 'w', encoding='utf-8') as f:
        f.write(content)

def fix_docs():
    with open('app/automation/claim_documents.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    content = re.sub(
        r'await file_input\.set_input_files\(abs_path\)\s+try:\s+await page\.wait_for_load_state\("networkidle", timeout=\d+\)\s+except Exception:\s+await asyncio\.sleep\(1\.5\)',
        r'''await file_input.set_input_files(abs_path)
                try:
                    await page.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))", arg=file_input)
                except Exception:
                    pass
                await asyncio.sleep(3.0)''',
        content
    )
    
    with open('app/automation/claim_documents.py', 'w', encoding='utf-8') as f:
        f.write(content)

fix_assessment()
fix_docs()
print("Fixed files.")
