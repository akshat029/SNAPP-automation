#!/usr/bin/env python3
"""Quick script to list all pending/received tickets from Smartsheet."""

import os
import sys
from dotenv import load_dotenv
load_dotenv()

import smartsheet

TOKEN = os.getenv("SMARTSHEET_TOKEN", "")
SHEET_ID = int(os.getenv("SMARTSHEET_SHEET_ID", "0"))

client = smartsheet.Smartsheet(TOKEN)
client.errors_as_exceptions(True)

sheet = client.Sheets.get_sheet(SHEET_ID)
col_map = {col.id: col.title for col in sheet.columns}

# Print column names for reference
# print("=== COLUMNS ===")
# for cid, title in col_map.items():
#     print(f"  {title}")

PENDING_STATUSES = {"received", "recieved", "pending", "new", ""}

print(f"\nSheet: {sheet.name}")
print(f"Total rows: {len(sheet.rows)}")
print("=" * 100)

pending_rows = []

for row in sheet.rows:
    raw = {}
    for cell in row.cells:
        col_title = col_map.get(cell.column_id, "")
        raw[col_title] = cell.value

    status = str(raw.get("Status", "") or "").strip().lower()
    if status not in PENDING_STATUSES:
        continue

    # Check if SNAPP is involved
    systems = str(raw.get("SUMMARY: System(s)", "") or "").strip().lower()
    sys_onboard = str(raw.get("System(s) onboarding One", "") or "").strip().lower()
    sys_update = str(raw.get("System(s) updating One", "") or "").strip().lower()
    is_snapp = "snapp" in systems or "snapp" in sys_onboard or "snapp" in sys_update

    ticket_id = str(raw.get("Ticket Number", "") or "").strip()
    assigned_to = str(raw.get("Assigned To", "") or "").strip()
    service = str(raw.get("Service Needed", "") or "").strip()
    editor_name = (raw.get("Editor's Full Name") or raw.get("SUMMARY: Editor's Name")
                   or raw.get("Editor's Concatenated Name") or "")
    editor_name = str(editor_name or "").strip()
    journal = str(raw.get("Journal Title", "") or "").strip()
    explain = str(raw.get("Explain Update", "") or "").strip()
    summary_count = str(raw.get("SUMMARY: One or Multiple", "") or "").strip()
    date_created = str(raw.get("Date Created", "") or "").strip()

    pending_rows.append({
        "ticket_id": ticket_id,
        "status": status or "(blank)",
        "assigned_to": assigned_to,
        "service": service,
        "editor_name": editor_name,
        "journal": journal,
        "systems": systems,
        "is_snapp": is_snapp,
        "count": summary_count,
        "explain": explain[:80] if explain else "",
        "date_created": date_created,
        "row_id": row.id,
    })

print(f"\nFound {len(pending_rows)} rows with pending/received status\n")

# Separate SNAPP vs non-SNAPP
snapp_rows = [r for r in pending_rows if r["is_snapp"]]
other_rows = [r for r in pending_rows if not r["is_snapp"]]

# Filter for assigned to Akshat
akshat_rows = [r for r in snapp_rows if "akshat" in r["assigned_to"].lower()]
other_snapp = [r for r in snapp_rows if "akshat" not in r["assigned_to"].lower()]

print(f"  SNAPP tickets assigned to you: {len(akshat_rows)}")
print(f"  SNAPP tickets assigned to others: {len(other_snapp)}")
print(f"  Non-SNAPP tickets: {len(other_rows)}")

if akshat_rows:
    print("\n" + "=" * 100)
    print("  YOUR SNAPP TICKETS (assigned to akshat.jaiswal)")
    print("=" * 100)
    for i, r in enumerate(akshat_rows, 1):
        print(f"\n  [{i}] Ticket: {r['ticket_id']}")
        print(f"      Status:    {r['status']}")
        print(f"      Service:   {r['service']}")
        print(f"      Editor:    {r['editor_name']}")
        print(f"      Journal:   {r['journal']}")
        print(f"      Systems:   {r['systems']}")
        print(f"      Count:     {r['count']}")
        print(f"      Created:   {r['date_created']}")
        if r['explain']:
            print(f"      Explain:   {r['explain']}")

if other_snapp:
    print("\n" + "=" * 100)
    print("  OTHER SNAPP TICKETS (assigned to someone else)")
    print("=" * 100)
    for i, r in enumerate(other_snapp, 1):
        print(f"\n  [{i}] Ticket: {r['ticket_id']}  |  Assigned: {r['assigned_to']}")
        print(f"      Service: {r['service']}  |  Editor: {r['editor_name']}")
        print(f"      Journal: {r['journal']}  |  Count: {r['count']}")
        if r['explain']:
            print(f"      Explain: {r['explain']}")

print("\n" + "=" * 100)
