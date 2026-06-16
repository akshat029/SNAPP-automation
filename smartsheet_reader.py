"""
SNAPP Agent — Smartsheet Integration
=====================================
Reads pending editor requests from a Smartsheet and converts them into
the structured dict format that SnappAgent expects.

Uses actual column names from the Trial Cases sheet.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import smartsheet
from dotenv import load_dotenv

from helpers import parse_editor_name

logger = logging.getLogger("snapp_agent")

# Action type mapping — translate raw Smartsheet values to agent actions
ACTION_TYPE_MAP: dict[str, str] = {
    "on-boarding (only)": "onboard",
    "on-boarding": "onboard",
    "onboard": "onboard",
    "onboarding": "onboard",
    "off-boarding": "offboard",
    "off-boarding an editor": "offboard",
    "offboard": "offboard",
    "offboarding": "offboard",
    "deactivate": "offboard",
    "deactivation": "offboard",
    "update": "update",
    "updating editor information": "update",
    "edit": "update",
    "change": "update",
    "unavailability": "set_unavailability",
    "set unavailability": "set_unavailability",
    "recording editor unavailability": "set_unavailability",
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

    def fetch_pending_requests(self, max_rows: int = 50) -> list[dict[str, str]]:
        """
        Fetch all rows whose status is 'Received' / blank (i.e. pending).
        Returns a list of structured request dicts ready for SnappAgent.
        """
        sheet = self.client.Sheets.get_sheet(self.sheet_id)
        col_map = {col.id: col.title for col in sheet.columns}

        requests: list[dict[str, str]] = []
        skipped_multi = 0
        skipped_other = 0

        for row in sheet.rows:
            if len(requests) >= max_rows:
                logger.info("Reached fetch limit of %d -- stopping", max_rows)
                break

            # Build raw cell dict using actual column names
            raw: dict[str, Any] = {}
            for cell in row.cells:
                col_title = col_map.get(cell.column_id, "")
                raw[col_title] = cell.value

            # Skip already-processed rows
            status = str(raw.get("Status", "") or "").strip().lower()
            if status not in ("received", "recieved", "pending", "new", ""):
                continue

            # Skip rows with no action
            service = str(raw.get("Service Needed", "") or "").strip()
            if not service:
                continue

            # Skip multiple-editor rows
            count = str(raw.get("SUMMARY: One or Multiple", "") or "").strip().lower()
            if count == "multiple":
                skipped_multi += 1
                continue

            # Check that SNAPP is involved
            systems = str(raw.get("SUMMARY: System(s)", "") or "").strip().lower()
            sys_onboard = str(raw.get("System(s) onboarding One", "") or "").strip().lower()
            if "snapp" not in systems and "snapp" not in sys_onboard:
                skipped_other += 1
                continue

            request = self._structure_row(raw, row.id)
            if request:
                requests.append(request)

        logger.info(
            "Fetched %d pending request(s) from Smartsheet (skipped %d multiple-editor, %d other)",
            len(requests), skipped_multi, skipped_other,
        )
        return requests

    def _structure_row(self, raw: dict[str, Any], row_id: int) -> dict[str, str]:
        """
        Convert a raw Smartsheet row (using actual column names) into
        the structured dict that SnappAgent.run() expects.
        """
        def _v(col: str) -> str:
            val = raw.get(col)
            if val is None:
                return ""
            return str(val).strip()

        # Determine the action type
        service = _v("Service Needed").lower()
        action = ACTION_TYPE_MAP.get(service, "")
        if not action:
            for key, mapped in ACTION_TYPE_MAP.items():
                if key in service:
                    action = mapped
                    break
        if not action:
            logger.warning("Row %s: unrecognised service '%s' -- skipping", row_id, _v("Service Needed"))
            return {}

        # Editor name
        editor_name = _v("Editor's Full Name")
        if not editor_name:
            fn = _v("First Name")
            ln = _v("Last Name")
            if fn or ln:
                editor_name = f"{fn} {ln}".strip()

        first_name, last_name = parse_editor_name(editor_name)
        # Override with explicit columns if present
        if _v("First Name"):
            first_name = _v("First Name")
        if _v("Last Name"):
            last_name = _v("Last Name")

        # Collection (guest editor)
        collection_name = _v("Collection Title")
        collection_id = _v("Collection ID")

        # Role: try multiple columns
        role = _v("New Snapp Role (onboarding)") or _v("Editor Role") or _v("Updated Snapp Role (if applicable)")

        # Explain Update
        explain = _v("Explain Update")
        if explain and action == "update":
            explain_lower = explain.lower()
            if any(kw in explain_lower for kw in ["email updated", "change email", "update email", "primary email"]):
                logger.warning(
                    "[!] Row %s / %s: 'Explain Update' contains a name or primary email change request. "
                    "THIS CANNOT BE DONE IN SNAPP. Text: '%s'",
                    row_id, _v("Ticket Number"), explain
                )

        request = {
            "editor_name":      editor_name,
            "first_name":       first_name,
            "last_name":        last_name,
            "action":           action,
            "journal_name":     _v("Journal Title"),
            "journal_id":       _v("JournalID"),
            "affiliation":      _v("Institution / Affiliation"),
            "email":            _v("Editor's Email"),
            "role":             role,
            "keywords":         _v("Keywords"),
            "collection_name":  collection_name,
            "collection_id":    collection_id,
            "sections":         _v("Section"),
            "status":           "",
            "unavailable_from": _v("Unavailable From"),
            "unavailable_to":   _v("Unavailable To"),
            # Metadata
            "_row_id":          str(row_id),
            "_ticket_id":       _v("Ticket Number"),
            "_requester":       _v("Submitter's Name"),
            "_department":      _v("Publishing Unit Lookup"),
            "_explain_update":  explain,
            "_qualification":   _v("Salutation"),
            "_country":         _v("Country"),
            "_city":            _v("City"),
        }

        logger.info("Structured request from row %s: action=%s, editor=%s, journal=%s",
                     row_id, action, editor_name, _v("Journal Title"))
        if explain:
            logger.info("  -> Explain Update: %s", explain)

        return request

    def mark_row_done(self, row_id: int, result_status: str) -> None:
        """
        Update the row status in Smartsheet to mark it as processed.
        Writes back to the 'Status' column.
        """
        try:
            sheet = self.client.Sheets.get_sheet(self.sheet_id)
            status_col_id = None
            for col in sheet.columns:
                if col.title == "Status":
                    status_col_id = col.id
                    break
            if not status_col_id:
                logger.warning("Cannot find 'Status' column to update")
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

    def fetch_ticket_by_id(self, ticket_id: str) -> dict[str, str] | None:
        """
        Fetch a specific ticket by its ticket number/ID from Smartsheet,
        regardless of its status.
        """
        logger.info("Fetching ticket '%s' from Smartsheet...", ticket_id)
        sheet = self.client.Sheets.get_sheet(self.sheet_id)
        col_map = {col.id: col.title for col in sheet.columns}

        for row in sheet.rows:
            raw: dict[str, Any] = {}
            for cell in row.cells:
                col_title = col_map.get(cell.column_id, "")
                raw[col_title] = cell.value

            ticket = str(raw.get("Ticket Number", "") or "").strip()
            if ticket.lower() == ticket_id.strip().lower():
                logger.info("Found ticket '%s' in Smartsheet on row %s", ticket, row.id)
                return self._structure_row(raw, row.id)

        logger.warning("Ticket '%s' not found in Smartsheet.", ticket_id)
        return None
