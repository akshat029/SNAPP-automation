"""Analyze the new SNAPP form HTML to find current element IDs, inputs, buttons, labels."""
import re

html = open(r'd:\AUTOMATION AGENT\logs\new_form_source.html', encoding='utf-8').read()
print(f'Total HTML length: {len(html)} chars')

# 1. Title
titles = re.findall(r'<title>(.*?)</title>', html)
print(f'\nTitle: {titles}')

# 2. ALL element IDs
all_ids = re.findall(r'id="([^"]*)"', html)
print(f'\n=== ALL IDs ({len(set(all_ids))}) ===')
for i in sorted(set(all_ids)):
    print(f'  {i}')

# 3. ALL input/select/textarea elements
inputs = re.findall(r'<(?:input|select|textarea)[^>]*>', html)
print(f'\n=== ALL INPUTS ({len(inputs)}) ===')
for inp in inputs:
    print(f'  {inp[:300]}')

# 4. ALL buttons
buttons = re.findall(r'<button[^>]*>.*?</button>', html, re.DOTALL)
print(f'\n=== ALL BUTTONS ({len(buttons)}) ===')
for btn in buttons:
    clean_text = re.sub(r'<[^>]+>', '', btn).strip()[:100]
    attrs = re.findall(r'(?:class|id|type|data-[a-z-]+|name)="[^"]*"', btn[:500])
    print(f'  text="{clean_text}" attrs={attrs}')

# 5. ALL labels
labels = re.findall(r'<label[^>]*>(.*?)</label>', html, re.DOTALL)
print(f'\n=== ALL LABELS ({len(labels)}) ===')
for lbl in labels:
    clean = re.sub(r'<[^>]+>', '', lbl).strip()[:100]
    if clean:
        print(f'  {clean}')

# 6. Data attributes
data_attrs = re.findall(r'(data-(?:test|component)[^=]*="[^"]*")', html)
print(f'\n=== DATA-TEST / DATA-COMPONENT ({len(set(data_attrs))}) ===')
for attr in sorted(set(data_attrs)):
    print(f'  {attr}')

# 7. Form elements
forms = re.findall(r'<form[^>]*>(.*?)</form>', html, re.DOTALL)
print(f'\n=== FORMS ({len(forms)}) ===')
for idx, form in enumerate(forms):
    form_ids = re.findall(r'id="([^"]*)"', form)
    form_names = re.findall(r'name="([^"]*)"', form)
    print(f'  Form {idx}: ids={form_ids}, names={form_names}')

# 8. Radio buttons
radios = re.findall(r'<input[^>]*type="radio"[^>]*>', html)
print(f'\n=== RADIO BUTTONS ({len(radios)}) ===')
for r in radios:
    print(f'  {r[:300]}')

# 9. Check for "step" or wizard indicators
steps = re.findall(r'[sS]tep.{0,30}', html)
print(f'\n=== STEP INDICATORS ===')
for s in steps[:10]:
    clean = re.sub(r'<[^>]+>', '', s).strip()[:100]
    print(f'  {clean}')
