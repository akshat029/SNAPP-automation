"""
SNAPP Agent — Smartsheet Integration
=====================================
Reads pending editor requests from a Smartsheet and converts them into
the structured dict format that SnappAgent expects.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import smartsheet
from dotenv import load_dotenv

from helpers import parse_editor_name

logger = logging.getLogger("snapp_agent")

# ──────────────────────────────────────────────────────────────────────────────
# Column mapping — your Smartsheet uses generic names (Column2, Column3, …).
# This map translates them to meaningful field names based on the actual data.
# If your Smartsheet columns are renamed later, just update this mapping.
# ──────────────────────────────────────────────────────────────────────────────
SMARTSHEET_COLUMN_MAP: dict[str, str] = {
    "Primary Column": "_timestamp",       # request timestamp
    "Column2":  "_requester",             # who submitted the request
    "Column3":  "_ticket_id",             # e.g. EE-2025-07216
    "Column5":  "_status",               # Received / Done / etc.
    "Column8":  "_department",            # e.g. 71 - Mathematics
    "Column9":  "_requester_email",       # requester's email
    "Column10": "_action_raw",            # raw action: "On-boarding (Only)", etc.
    "Column11": "_editor_count",          # "One" / "Multiple"
    "Column12": "_platform",              # "Snapp"
    "Column15": "journal_id",             # journal numeric ID
    "Column16": "journal_name",           # journal title
    "Column19": "editor_name",            # editor full name
    "Column20": "email",                  # editor email
    "Column22": "_title",                 # Dr / PhD / Prof etc.
    "Column23": "affiliation",            # institution
    "Column24": "_country",              # country
    "Column26": "_orcid",                # ORCID or similar ID
    "Column27": "collection_name",        # collection title (Guest Editor)
    "Column31": "_flag1",
    "Column32": "_flag2",
    "Column48": "_editor_type",           # "Guest Editor" / blank
    "Column52": "role",                   # editorial role
    "Column62": "_bu",                    # business unit
    "Column63": "_bu_code",              # BU code
    "Column64": "_flag3",
    "Column66": "_period",               # period (e.g. 2026-02)
    "Column68": "_score1",
    "Column69": "_score2",
}

# Action type mapping — translate raw Smartsheet values to agent actions
ACTION_TYPE_MAP: dict[str, str] = {
    "on-boarding (only)": "onboard",
    "on-boarding": "onboard",
    "onboard": "onboard",
    "onboarding": "onboard",
    "off-boarding": "offboard",
    "offboard": "offboard",
    "offboarding": "offboard",
    "deactivate": "offboard",
    "deactivation": "offboard",
    "update": "update",
    "edit": "update",
    "change": "update",
    "unavailability": "set_unavailability",
    "set unavailability": "set_unavailability",
}


class SmartsheetReader:
    """
    Reads pending requests from a Smartsheet and converts them into
    the structured dict format that SnappAgent expects.
    """

    def __init__(self) -> None:
        load_dotenv()
        self.token = os.getenv("SMARTSHEET_TOKEN", "")
        self.sheet_id = int(os.getenv("SMARTSHEET_SHEET_ID", "0"))
        if not self.token:
            raise EnvironmentError("SMARTSHEET_TOKEN must be set in .env")
        if not self.sheet_id:
            raise EnvironmentError("SMARTSHEET_SHEET_ID must be set in .env")
        self.client = smartsheet.Smartsheet(self.token)
        self.client.errors_as_exceptions(True)

    def fetch_pending_requests(self) -> list[dict[str, str]]:
        """
        Fetch all rows whose status is 'Received' (i.e. pending / not yet done).
        Returns a list of structured request dicts ready for SnappAgent.
        """
        sheet = self.client.Sheets.get_sheet(self.sheet_id)
        col_map = {col.id: col.title for col in sheet.columns}

        requests: list[dict[str, str]] = []
        for row in sheet.rows:
            # Build raw cell dict
            raw: dict[str, Any] = {}
            for cell in row.cells:
                col_title = col_map.get(cell.column_id, "")
                raw[col_title] = cell.value

            # Skip empty rows or already-processed rows
            status = str(raw.get("Column5", "") or "").strip().lower()
            if status not in ("received", "pending", "new", ""):
                logger.info("Skipping row %s (status: '%s')", row.id, status)
                continue

            # Skip rows with no editor name and no action
            if not raw.get("Column19") and not raw.get("Column10"):
                continue

            request = self._structure_row(raw, row.id)
            if request:
                requests.append(request)

        logger.info("Fetched %d pending request(s) from Smartsheet", len(requests))
        return requests

    def _structure_row(self, raw: dict[str, Any], row_id: int) -> dict[str, str]:
        """
        Convert a raw Smartsheet row into the structured dict
        that SnappAgent.run() expects.
        """
        def _v(col: str) -> str:
            """Safely extract a string value from the raw row."""
            val = raw.get(col)
            if val is None:
                return ""
            return str(val).strip()

        # Determine the action type
        action_raw = _v("Column10").lower()
        action = ACTION_TYPE_MAP.get(action_raw, "")
        if not action:
            # Try partial matching
            for key, mapped in ACTION_TYPE_MAP.items():
                if key in action_raw:
                    action = mapped
                    break
        if not action:
            logger.warning("Row %s: unrecognised action '%s' — defaulting to 'update'",
                           row_id, _v("Column10"))
            action = "update"

        # Determine if this is a Guest Editor (collection present or type says so)
        editor_type = _v("Column48").lower()
        collection_name = _v("Column27")
        is_guest = bool(collection_name) or "guest" in editor_type

        # If it's an onboard with a collection name → guest editor onboard
        if action == "onboard" and is_guest and not collection_name:
            collection_name = ""  # will still trigger guest flow via editor_type

        # Use shared name-parsing utility
        editor_name = _v("Column19")
        first_name, last_name = parse_editor_name(editor_name)

        request = {
            "editor_name":      editor_name,
            "first_name":       first_name,
            "last_name":        last_name,
            "action":           action,
            "journal_name":     _v("Column16"),
            "journal_id":       _v("Column15"),
            "affiliation":      _v("Column23"),
            "email":            _v("Column20"),
            "role":             _v("Column52"),
            "keywords":         "",             # add keyword columns here if available
            "collection_name":  collection_name,
            "collection_id":    "",
            "sections":         "",
            "status":           "",             # for offboard status changes
            "unavailable_from": "",
            "unavailable_to":   "",
            # Metadata (not used by agent, for logging/tracking)
            "_row_id":          str(row_id),
            "_ticket_id":       _v("Column3"),
            "_requester":       _v("Column2"),
            "_department":      _v("Column8"),
        }

        logger.info("Structured request from row %s: action=%s, editor=%s, journal=%s",
                    row_id, action, editor_name, _v("Column16"))
        return request

    def mark_row_done(self, row_id: int, result_status: str) -> None:
        """
        Update the row status in Smartsheet to mark it as processed.
        Writes back to Column5 (status column).
        """
        try:
            sheet = self.client.Sheets.get_sheet(self.sheet_id)
            status_col_id = None
            for col in sheet.columns:
                if col.title == "Column5":
                    status_col_id = col.id
                    break
            if not status_col_id:
                logger.warning("Cannot find Column5 to update status")
                return

            new_row = smartsheet.models.Row()
            new_row.id = row_id
            new_cell = smartsheet.models.Cell()
            new_cell.column_id = status_col_id
            new_cell.value = f"Done - {result_status}"
            new_cell.strict = False
            new_row.cells.append(new_cell)

            self.client.Sheets.update_rows(self.sheet_id, [new_row])
            logger.info("Smartsheet row %s marked as 'Done - %s'", row_id, result_status)
        except Exception as exc:
            logger.error("Failed to update Smartsheet row %s: %s", row_id, exc)
