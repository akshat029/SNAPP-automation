"""Check EE-14350 data from Smartsheet."""
import os, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from dotenv import load_dotenv
load_dotenv()
import smartsheet

c = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
s = c.Sheets.get_sheet(int(os.getenv("SMARTSHEET_SHEET_ID")))
col_map = {col.id: col.title for col in s.columns}

for row in s.rows:
    raw = {}
    for cell in row.cells:
        title = col_map.get(cell.column_id, "")
        raw[title] = cell.value
    ticket = str(raw.get("Ticket Number", "") or "").strip()
    if ticket == "EE-14350":
        print("=== EE-14350 Row Data ===")
        for k, v in sorted(raw.items()):
            if v:
                print(f"  {k:45s} = {v}")
        break
