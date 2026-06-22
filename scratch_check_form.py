import re

html = open("d:/AUTOMATION AGENT/logs/new_form_source.html", "r", encoding="utf-8").read()

print("=== Affiliation / Institution elements ===")
for m in re.finditer(r'<[^>]*(addEditor(?:Affiliation|Institution\w*)|editEditor(?:Affiliation|Institution\w*))[^>]*>', html, re.I):
    tag = m.group()[:200]
    print(f"  {tag}")

print("\n=== 'Add manually' ===")
for m in re.finditer(r'<[^>]*>[^<]*Add manually[^<]*<', html, re.I):
    print(f"  {m.group()[:200]}")

# Also check surrounding context
idx = html.lower().find("add manually")
if idx >= 0:
    start = max(0, idx - 200)
    end = min(len(html), idx + 200)
    print(f"\n  Context: ...{html[start:end]}...")

print("\n=== Next / wizard-next buttons ===")
for m in re.finditer(r'<button[^>]*>Next<', html, re.I):
    # Get 200 chars before to see attributes
    start = max(0, m.start() - 200)
    print(f"  {html[start:m.end()]}")

for m in re.finditer(r'<[^>]*wizard-next[^>]*>', html, re.I):
    print(f"  wizard-next: {m.group()[:200]}")

print("\n=== data-component-institution elements ===")
for m in re.finditer(r'<[^>]*data-component-institution[^>]*>', html, re.I):
    print(f"  {m.group()[:200]}")
