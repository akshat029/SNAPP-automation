"""
SNAPP Agent — Bulk Update Parser
=================================
Parses the `_explain_update` free-text field from a Smartsheet ticket
into individual editor update requests.

Supports any key-value pairs in the format:
    Name - John Doe
    Section - Cardiology
    Tag - Cardiology

Blocks are separated by blank lines. Each block starts with a `Name` key.
"""

from __future__ import annotations

import re
import sys
from typing import Any

from helpers import parse_editor_name

# Map raw keys (case-insensitive) → SnappAgent request field names
FIELD_MAP: dict[str, str] = {
    "name":               "editor_name",
    "editor name":        "editor_name",
    "editor":             "editor_name",
    "section":            "sections",
    "sections":           "sections",
    "board section":      "sections",
    "board sections":     "sections",
    "tag":                "keywords",
    "tags":               "keywords",
    "keyword":            "keywords",
    "keywords":           "keywords",
    "role":               "role",
    "editor role":        "role",
    "affiliation":        "affiliation",
    "institution":        "affiliation",
    "email":              "email",
    "primary email":      "email",
    "email address":      "email",
    "status":             "status",
    "collection":         "collection_name",
    "collection name":    "collection_name",
    "collection id":      "collection_id",
    "country":            "_country",
    "city":               "_city",
    "unavailable from":   "unavailable_from",
    "unavailability from":"unavailable_from",
    "unavailable to":     "unavailable_to",
    "unavailability to":  "unavailable_to",
}

# Keys that signal the start of a new editor block
NAME_KEYS = {"name", "editor name", "editor"}


def parse_bulk_update(
    explain_text: str,
    parent_ticket: dict[str, Any],
) -> list[dict[str, Any]]:
    """Parse free-text `_explain_update` into a list of per-editor request dicts.

    Each returned dict is compatible with SnappAgent's request format and
    inherits shared fields (journal_name, journal_id, action, etc.) from
    the parent ticket.

    Args:
        explain_text: The raw `_explain_update` field content.
        parent_ticket: The full Smartsheet ticket dict (for shared fields).

    Returns:
        A list of request dicts, one per editor.
    """
    if not explain_text or not explain_text.strip():
        return []

    lines = explain_text.splitlines()
    editors: list[dict[str, str]] = []
    current: dict[str, str] = {}

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue  # Skip blank lines (block separators)

        # Try to parse as "Key - Value"
        # Use only the first " - " as separator (value may contain " - " too)
        match = re.match(r"^(.+?)\s*[-–—]\s+(.+)$", line)
        if not match:
            continue  # Skip non-parseable lines (headers, instructions, etc.)

        raw_key = match.group(1).strip()
        raw_value = match.group(2).strip()

        key_lower = raw_key.lower()

        # Is this a name key? → start new editor block
        if key_lower in NAME_KEYS:
            if current:
                editors.append(current)
            current = {}

        # Map to agent field
        field = FIELD_MAP.get(key_lower)
        if field:
            # If field already exists (e.g. multiple tags), append comma-separated
            if field in current and current[field]:
                current[field] = current[field] + ", " + raw_value
            else:
                current[field] = raw_value
        else:
            # Store unknown keys with underscore prefix for debugging
            current[f"_extra_{raw_key.lower().replace(' ', '_')}"] = raw_value

    # Don't forget the last block
    if current:
        editors.append(current)

    # Enrich each editor dict with shared fields from the parent ticket
    shared_fields = {
        "journal_name": parent_ticket.get("journal_name", ""),
        "journal_id":   parent_ticket.get("journal_id", ""),
        "action":       parent_ticket.get("action", "update"),
        "_ticket_id":   parent_ticket.get("_ticket_id", ""),
        "_row_id":      parent_ticket.get("_row_id", ""),
        "_requester":   parent_ticket.get("_requester", ""),
        "_department":  parent_ticket.get("_department", ""),
    }

    result: list[dict[str, Any]] = []
    for editor in editors:
        req: dict[str, Any] = {**shared_fields}

        # Merge editor-specific fields (these override shared fields)
        for k, v in editor.items():
            req[k] = v

        # Split editor_name into first_name + last_name if not already set
        editor_name = req.get("editor_name", "")
        if editor_name and not req.get("first_name") and not req.get("last_name"):
            fname, lname = parse_editor_name(editor_name)
            req["first_name"] = fname
            req["last_name"] = lname

        # Ensure all standard fields exist (even if empty)
        for field in ("editor_name", "first_name", "last_name", "email",
                       "affiliation", "role", "keywords", "sections",
                       "collection_name", "collection_id", "status",
                       "unavailable_from", "unavailable_to"):
            req.setdefault(field, "")

        result.append(req)

    return result


def _safe_str(text: str) -> str:
    """Make a string safe for Windows console output (cp1252)."""
    try:
        text.encode(sys.stdout.encoding or "utf-8")
        return text
    except (UnicodeEncodeError, LookupError):
        return text.encode("ascii", errors="replace").decode("ascii")


def print_parsed_summary(editors: list[dict[str, Any]]) -> None:
    """Print a human-readable summary table of parsed editor requests."""
    if not editors:
        print("  (no editors parsed)")
        return

    # Determine which fields have data
    data_fields = set()
    for ed in editors:
        for key in ("sections", "keywords", "role", "affiliation", "status",
                     "email", "unavailable_from", "unavailable_to"):
            if ed.get(key, "").strip():
                data_fields.add(key)

    # Print header
    header = f"{'#':>3}  {'Editor Name':<35}"
    for f in sorted(data_fields):
        header += f"  {f:<25}"
    print(header)
    print("-" * len(header))

    # Print rows
    for i, ed in enumerate(editors, 1):
        name = _safe_str(ed.get('editor_name', '?'))
        row = f"{i:>3}  {name:<35}"
        for f in sorted(data_fields):
            val = _safe_str(ed.get(f, ""))
            if len(val) > 25:
                val = val[:22] + "..."
            row += f"  {val:<25}"
        print(row)

    print(f"\nTotal: {len(editors)} editor(s)")

