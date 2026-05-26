import sys
import os
import time

# Ensure console supports UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Add project root to sys.path
sys.path.append(r"c:\Users\jadav\Coding\Automation\UIIC\uiic_automation")

def verify():
    print("--- Verifying Shared OCR Singleton and Warmup ---")
    
    # 1. Test imports
    try:
        from app.automation.ocr_engine import get_shared_ocr, warmup_ocr_background
        print("✅ Imports successful.")
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return

    # 2. Test singleton behavior
    print("\nInitializing shared OCR for the first time...")
    t0 = time.perf_counter()
    try:
        ocr1 = get_shared_ocr()
        t1 = time.perf_counter()
        print(f"✅ Initialized successfully in {t1 - t0:.2f} seconds.")
    except Exception as e:
        print(f"❌ First init failed: {e}")
        return

    print("\nFetching shared OCR for the second time...")
    t2 = time.perf_counter()
    try:
        ocr2 = get_shared_ocr()
        t3 = time.perf_counter()
        print(f"✅ Retrieved in {t3 - t2:.6f} seconds.")
    except Exception as e:
        print(f"❌ Second fetch failed: {e}")
        return

    # 3. Assert identity
    if ocr1 is ocr2:
        print(f"\n✅ SUCCESS: Both instances are identical! (ID: {id(ocr1)})")
    else:
        print(f"\n❌ FAILURE: Instances are not identical! (ID1: {id(ocr1)}, ID2: {id(ocr2)})")

    # 4. Test run a sample text or image if possible
    print("\n--- Verifying that CAPTCHA solver uses the shared engine ---")
    try:
        from app.automation.captcha_solver import _get_ocr
        captcha_ocr = _get_ocr()
        if captcha_ocr is ocr1:
            print("✅ CAPTCHA solver successfully uses the exact same shared OCR singleton instance!")
        else:
            print("❌ CAPTCHA solver uses a DIFFERENT OCR instance!")
    except Exception as e:
        print(f"❌ CAPTCHA solver engine retrieval failed: {e}")

    # 5. Test run ocr_helper to ensure it uses the shared engine
    print("\n--- Verifying that ocr_helper uses the shared engine ---")
    try:
        from app.portals.newindia.automation.ocr_helper import _get_doc_ocr
        doc_ocr = _get_doc_ocr()
        if doc_ocr is ocr1:
            print("✅ doc_ocr in ocr_helper successfully uses the exact same shared OCR singleton instance!")
        else:
            print("❌ doc_ocr in ocr_helper uses a DIFFERENT OCR instance!")
    except Exception as e:
        print(f"❌ ocr_helper engine retrieval failed: {e}")

if __name__ == "__main__":
    verify()
