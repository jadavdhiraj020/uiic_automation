import sys
sys.stdout.reconfigure(encoding='utf-8')
from app.data.excel_reader import extract_claim_data

claim = extract_claim_data(r"c:\Users\jadav\Coding\Automation\UIIC\uiic_automation\AAA\dummy.xlsx", "newindia")
print("Claim Data Properties:")
for k, v in vars(claim).items():
    if not k.startswith("_"):
        print(f"  {k}: {v!r}")

print("\nExcel Logs:")
for l in claim._excel_logs:
    print(l)
