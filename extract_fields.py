"""Extract form fields from SNAPP page dump.

Usage:
    python extract_fields.py                          # uses default path
    python extract_fields.py path/to/page_dump.html   # custom path
"""
import re
import sys

DEFAULT_PATH = r"d:\AUTOMATION AGENT\logs\page_dump_add_editor_form_20260309_155851.html"


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: File not found: {path}")
        sys.exit(1)

    # Find all input/select/textarea elements
    for m in re.finditer(r'<(input|select|textarea)[^>]*>', content, re.IGNORECASE):
        tag = m.group()
        if 'type="hidden"' in tag.lower():
            continue
        if len(tag) > 400:
            tag = tag[:400] + "..."
        print(tag)
        print("---")

    # Also find labels
    print("\n=== LABELS ===")
    for m in re.finditer(r'<label[^>]*>([^<]{1,100})</label>', content, re.IGNORECASE):
        print(f"Label: {m.group(1).strip()}  | Full: {m.group()[:200]}")


if __name__ == "__main__":
    main()
