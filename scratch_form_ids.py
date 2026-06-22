"""Extract form field IDs from the guest editor form HTML dump."""
import re
html = open('logs/page_dump_guest_editor_form_20260613_094856.html', encoding='utf-8').read()
ids = re.findall(r'id="([^"]+)"', html)
print("=== All form-related IDs ===")
for i in sorted(set(ids)):
    low = i.lower()
    if any(k in low for k in ['editor', 'add', 'title', 'email', 'name', 'affil', 'country', 'collection', 'role', 'keyword', 'section', 'unavail', 'manual']):
        print(f"  {i}")

print("\n=== All <select> elements ===")
selects = re.findall(r'<select[^>]*>', html)
for s in selects:
    print(f"  {s[:250]}")

print("\n=== Form field order (inputs/selects in form) ===")
fields = re.findall(r'<(?:input|select|textarea)\s[^>]*(?:id|name)="([^"]+)"[^>]*>', html)
seen = set()
for f in fields:
    if f not in seen:
        seen.add(f)
        print(f"  {f}")
