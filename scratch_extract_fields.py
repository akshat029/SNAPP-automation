import re
html = open('logs/page_dump_add_editor_form_20260608_191030.html', encoding='utf-8').read()

# Find add_new_btn
print("=== add_new_btn ===")
for m in re.finditer(r'add_new_btn', html):
    start = max(0, m.start() - 100)
    end = min(len(html), m.end() + 200)
    print(html[start:end])
    print("---")

# Find add_new_guest_btn
print("\n=== add_new_guest_btn ===")
for m in re.finditer(r'add_new_guest_btn', html):
    start = max(0, m.start() - 100)
    end = min(len(html), m.end() + 200)
    print(html[start:end])
    print("---")

# Check for "Add new Editor" text
print("\n=== 'Add new Editor' text ===")
for m in re.finditer(r'Add new Editor', html):
    start = max(0, m.start() - 150)
    end = min(len(html), m.end() + 100)
    print(html[start:end])
    print("---")

# Check current URL from any meta or canonical
print("\n=== URL indicators ===")
for m in re.finditer(r'(canonical|og:url|action=)[^>]{0,200}', html):
    print(m.group()[:250])
