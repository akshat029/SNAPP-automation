import re

html = open(r'logs/page_dump_add_editor_form_20260619_093709.html', encoding='utf-8').read()

# Find all button elements
buttons = re.findall(r'<button[^>]*>.*?</button>', html)
print(f'=== BUTTON ELEMENTS ({len(buttons)}) ===')
for i, btn in enumerate(buttons[:20]):
    print(f'{i}: {btn[:200]}')

print()
# Find links with 'add' or 'editor' or 'new' or 'onboard' or 'create'
links = re.findall(r'<a[^>]*(?:add|editor|new|onboard|create)[^>]*>.*?</a>', html, re.IGNORECASE)
print(f'=== RELEVANT LINKS ({len(links)}) ===')
for i, lnk in enumerate(links[:20]):
    print(f'{i}: {lnk[:300]}')

print()
# Check for 'add editor' text anywhere
add_ed = [(m.start(), html[max(0,m.start()-100):m.end()+100]) for m in re.finditer(r'add.{0,5}editor', html, re.IGNORECASE)]
print(f'=== "Add Editor" occurrences ({len(add_ed)}) ===')
for pos, ctx in add_ed[:10]:
    print(f'  @{pos}: ...{ctx}...')

print()
# Check for form elements
forms = re.findall(r'<form[^>]*>', html)
print(f'=== FORM ELEMENTS ({len(forms)}) ===')
for f in forms[:10]:
    print(f'  {f[:200]}')

print()
# Check the main content area
# find div with class containing 'content' or 'main'
sections = re.findall(r'<(?:section|div)[^>]*class="[^"]*(?:content|main|editor)[^"]*"[^>]*>', html)
print(f'=== MAIN SECTIONS ({len(sections)}) ===')
for s in sections[:15]:
    print(f'  {s[:200]}')

print()
# Check for step-related elements
steps = [(m.start(), html[max(0,m.start()-50):m.end()+50]) for m in re.finditer(r'step.?1|step.?2|wizard|stepper', html, re.IGNORECASE)]
print(f'=== STEP/WIZARD ({len(steps)}) ===')
for pos, ctx in steps[:10]:
    print(f'  @{pos}: {ctx[:200]}')
