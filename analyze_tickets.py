"""
Analyze tickets from Smartsheet using a specific filter.
Sheet ID: 907937332547460
Filter ID: 6979120898723716 (SNAPP + Received/Uncomplete)
"""
import os
import json
import smartsheet
from dotenv import load_dotenv
from collections import Counter

load_dotenv()
token = os.getenv("SMARTSHEET_TOKEN")
client = smartsheet.Smartsheet(token)
client.errors_as_exceptions(True)

SHEET_ID = int(os.getenv("SMARTSHEET_SHEET_ID", "907937332547460"))
FILTER_ID = int(os.getenv("SMARTSHEET_FILTER_ID", "6979120898723716"))
print(f"Using Sheet ID: {SHEET_ID}")

# ── Fetch sheet with filter ────────────────────────────────────────────
print("Fetching sheet with filter...")
try:
    sheet = client.Sheets.get_sheet(SHEET_ID, filter_id=FILTER_ID)
except Exception as e:
    print(f"Filter fetch failed ({e}), trying without filter...")
    sheet = client.Sheets.get_sheet(SHEET_ID)

col_map = {col.id: col.title for col in sheet.columns}
col_titles = [col.title for col in sheet.columns]

print(f"\nSheet: {sheet.name}")
print(f"Total rows (after filter): {len(sheet.rows)}")
print(f"Total columns: {len(sheet.columns)}")

# ── Build structured rows ──────────────────────────────────────────────
rows_data = []
for row in sheet.rows:
    raw = {}
    for cell in row.cells:
        col_title = col_map.get(cell.column_id, "")
        raw[col_title] = cell.value
    raw["_row_id"] = row.id
    rows_data.append(raw)

# ── Save raw data for reference ────────────────────────────────────────
output_path = os.path.join(os.path.dirname(__file__), "data", "filter_analysis_raw.json")
os.makedirs(os.path.dirname(output_path), exist_ok=True)
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(rows_data, f, indent=2, default=str, ensure_ascii=False)
print(f"\nRaw data saved to: {output_path}")

# ── Key columns for analysis ──────────────────────────────────────────
KEY_COLS = {
    "service":     "Service Needed",
    "status":      "Status",
    "systems":     "SUMMARY: System(s)",
    "count":       "SUMMARY: One or Multiple",
    "ticket":      "Ticket Number",
    "editor":      "SUMMARY: Editor's Name",
    "journal":     "Journal Title",
    "role_update": "Updated Snapp Role (if applicable)",
    "role_onboard":"New Snapp Role (onboarding)",
    "explain":     "Explain Update",
    "keywords":    "Keywords",
    "affiliation": "Institution / Affiliation",
    "unavail_from":"Unavailable From",
    "unavail_to":  "Unavailable To",
    "assigned":    "Assigned To",
    "collection":  "Collection Title",
    "section":     "Section",
    "editor_role": "Editor Role",
}

def _v(row, key):
    col = KEY_COLS.get(key, key)
    val = row.get(col)
    return str(val).strip() if val else ""

# ── Analysis ───────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("  TICKET ANALYSIS")
print("=" * 70)

# 1. Service type distribution
services = Counter(_v(r, "service").lower() for r in rows_data if _v(r, "service"))
print(f"\n1. SERVICE TYPES ({sum(services.values())} tickets):")
for svc, cnt in services.most_common():
    print(f"   {cnt:4d}  {svc}")

# 2. Status distribution
statuses = Counter(_v(r, "status").lower() for r in rows_data if _v(r, "status"))
print(f"\n2. STATUS DISTRIBUTION:")
for st, cnt in statuses.most_common():
    print(f"   {cnt:4d}  {st}")

# 3. System distribution
systems = Counter(_v(r, "systems").lower() for r in rows_data if _v(r, "systems"))
print(f"\n3. SYSTEMS:")
for sys_, cnt in systems.most_common():
    print(f"   {cnt:4d}  {sys_}")

# 4. One vs Multiple
counts = Counter(_v(r, "count").lower() for r in rows_data if _v(r, "count"))
print(f"\n4. ONE vs MULTIPLE:")
for c, cnt in counts.most_common():
    print(f"   {cnt:4d}  {c}")

# 5. Assigned To
assigned = Counter(_v(r, "assigned").lower() for r in rows_data if _v(r, "assigned"))
print(f"\n5. ASSIGNED TO:")
for a, cnt in assigned.most_common():
    print(f"   {cnt:4d}  {a}")

# 6. Ticket variation analysis — classify each ticket
print(f"\n6. TICKET TYPE VARIATIONS:")
print("-" * 70)

variations = []
for r in rows_data:
    service = _v(r, "service").lower()
    explain = _v(r, "explain")
    keywords = _v(r, "keywords")
    affiliation = _v(r, "affiliation")
    role_u = _v(r, "role_update")
    role_o = _v(r, "role_onboard")
    unavail_from = _v(r, "unavail_from")
    unavail_to = _v(r, "unavail_to")
    collection = _v(r, "collection")
    section = _v(r, "section")
    editor_role = _v(r, "editor_role")
    count_type = _v(r, "count").lower()

    # Classify the variation
    tags = []

    # Base action
    if "on-boarding" in service or "onboard" in service:
        tags.append("ONBOARD")
    elif "off-boarding" in service or "offboard" in service or "deactivat" in service:
        tags.append("OFFBOARD")
    elif "update" in service or "edit" in service or "change" in service:
        tags.append("UPDATE")
    elif "unavailab" in service:
        tags.append("UNAVAILABILITY")
    else:
        tags.append(f"OTHER({service})")

    # Sub-variations
    if collection:
        tags.append("+COLLECTION")
    if keywords:
        tags.append("+KEYWORDS")
    if affiliation:
        tags.append("+AFFILIATION")
    if role_u or role_o:
        tags.append("+ROLE")
    if unavail_from or unavail_to:
        tags.append("+UNAVAIL_DATES")
    if section:
        tags.append("+SECTION")
    if explain:
        tags.append("+EXPLAIN_UPDATE")
    if count_type == "multiple":
        tags.append("+MULTIPLE_EDITORS")

    variation = " | ".join(tags)
    variations.append({
        "ticket_id": _v(r, "ticket"),
        "variation": variation,
        "service": service,
        "editor": _v(r, "editor"),
        "journal": _v(r, "journal"),
        "explain": explain[:100] if explain else "",
        "tags": tags,
    })

# Count unique variations
var_counter = Counter(v["variation"] for v in variations)
print(f"\nFound {len(var_counter)} unique ticket type variations:\n")
for i, (var, cnt) in enumerate(var_counter.most_common(), 1):
    print(f"   Type {i:2d} ({cnt:3d} tickets): {var}")
    # Show one example
    example = next(v for v in variations if v["variation"] == var)
    print(f"            Example: {example['ticket_id']} | {example['editor']} | {example['journal']}")
    if example["explain"]:
        print(f"            Explain: {example['explain']}")
    print()

# Save analysis
analysis_path = os.path.join(os.path.dirname(__file__), "data", "ticket_variations.json")
with open(analysis_path, "w", encoding="utf-8") as f:
    json.dump({
        "total_tickets": len(rows_data),
        "service_types": dict(services),
        "status_distribution": dict(statuses),
        "unique_variations": len(var_counter),
        "variation_counts": dict(var_counter.most_common()),
        "all_tickets": variations,
    }, f, indent=2, default=str, ensure_ascii=False)
print(f"\nFull analysis saved to: {analysis_path}")
print("=" * 70)
