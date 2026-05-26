import sys

# Add project root to sys.path
sys.path.append(r"c:\Users\jadav\Coding\Automation\UIIC\uiic_automation")

from app.utils import load_automation_defaults

def main():
    defaults = load_automation_defaults(portal_id="newindia")
    print("--- Loaded New India Automation Defaults ---")
    print(f"assessment_parts_hsn_code: {defaults.get('assessment_parts_hsn_code')}")
    print(f"assessment_labour_hsn_code: {defaults.get('assessment_labour_hsn_code')}")
    print(f"hsn_code: {defaults.get('hsn_code')}")

if __name__ == "__main__":
    main()
