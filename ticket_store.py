"""
Ticket Store — Local JSON-backed ticket persistence
=====================================================
Manages ``data/tickets.json`` as an intermediate layer between
Smartsheet and the SNAPP agent.

Tickets fetched from Smartsheet are written here (max 10 pending per pull).
After processing, tickets are marked ``complete`` — never removed.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("snapp_agent")

DATA_DIR = Path(__file__).parent / "data"
TICKETS_FILE = DATA_DIR / "tickets.json"
MOCK_FILE = DATA_DIR / "mock_tickets.json"

MAX_PENDING_PER_PULL = 10


# ── Store schema helpers ─────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_store() -> dict[str, Any]:
    return {"last_fetched": None, "tickets": []}


# ── Public API ────────────────────────────────────────────────────────────────

class TicketStore:
    """
    JSON-backed ticket store.

    Each ticket entry:
        ticket_id   : str
        status      : pending | processing | complete | skipped | error
        fetched_at  : ISO timestamp
        completed_at: ISO timestamp or null
        result      : dict or null
        request     : dict  (the structured request for SnappAgent)
    """

    def __init__(self, path: Path = TICKETS_FILE) -> None:
        self.path = path
        self._store: dict[str, Any] = _empty_store()

    # ── I/O ───────────────────────────────────────────────────────────────

    def load(self) -> None:
        """Read the store from disk. Creates an empty store if file is missing."""
        if self.path.exists():
            try:
                self._store = json.loads(self.path.read_text(encoding="utf-8"))
                logger.info("Loaded ticket store: %d ticket(s)", len(self._store.get("tickets", [])))
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Corrupt ticket store, resetting: %s", exc)
                self._store = _empty_store()
        else:
            self._store = _empty_store()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.save()
            logger.info("Created empty ticket store at %s", self.path)

    def save(self) -> None:
        """Persist the store to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._store, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Smartsheet sync ───────────────────────────────────────────────────

    def sync_from_smartsheet(self, reader: Any) -> int:
        """
        Pull up to MAX_PENDING_PER_PULL pending tickets from Smartsheet.
        Skips tickets that already exist in the store (by ticket_id).

        Returns the number of newly added tickets.
        """
        raw_requests = reader.fetch_pending_requests(limit=MAX_PENDING_PER_PULL)
        existing_ids = {t["ticket_id"] for t in self._store["tickets"]}

        added = 0
        for req in raw_requests:
            tid = req.get("_ticket_id", "")
            if not tid or tid in existing_ids:
                continue

            entry = {
                "ticket_id": tid,
                "status": "pending",
                "fetched_at": _ts(),
                "completed_at": None,
                "result": None,
                "request": req,
            }
            self._store["tickets"].append(entry)
            existing_ids.add(tid)
            added += 1

        self._store["last_fetched"] = _ts()
        self.save()
        logger.info("Synced from Smartsheet: %d new ticket(s) added, %d total in store",
                     added, len(self._store["tickets"]))
        return added

    # ── Queries ────────────────────────────────────────────────────────────

    def get_pending(self) -> list[dict[str, Any]]:
        """Return all ticket entries with status == 'pending'."""
        return [t for t in self._store["tickets"] if t["status"] == "pending"]

    def get_all(self) -> list[dict[str, Any]]:
        """Return all ticket entries."""
        return list(self._store["tickets"])

    # ── Status updates ─────────────────────────────────────────────────────

    def _find(self, ticket_id: str) -> dict[str, Any] | None:
        for t in self._store["tickets"]:
            if t["ticket_id"] == ticket_id:
                return t
        return None

    def mark_processing(self, ticket_id: str) -> None:
        """Mark a ticket as currently being processed."""
        entry = self._find(ticket_id)
        if entry:
            entry["status"] = "processing"
            self.save()

    def mark_complete(self, ticket_id: str, result: dict[str, Any] | None = None) -> None:
        """Mark a ticket as successfully completed."""
        entry = self._find(ticket_id)
        if entry:
            entry["status"] = "complete"
            entry["completed_at"] = _ts()
            entry["result"] = result
            self.save()
            logger.info("Ticket %s marked complete", ticket_id)

    def mark_skipped(self, ticket_id: str, reason: str = "") -> None:
        """Mark a ticket as skipped (e.g. name/email change)."""
        entry = self._find(ticket_id)
        if entry:
            entry["status"] = "skipped"
            entry["completed_at"] = _ts()
            entry["result"] = {"skip_reason": reason}
            self.save()
            logger.info("Ticket %s marked skipped: %s", ticket_id, reason)

    def mark_error(self, ticket_id: str, error: str) -> None:
        """Mark a ticket as failed with an error message."""
        entry = self._find(ticket_id)
        if entry:
            entry["status"] = "error"
            entry["completed_at"] = _ts()
            entry["result"] = {"error": error}
            self.save()
            logger.warning("Ticket %s marked error: %s", ticket_id, error)

    # ── Mock loading ──────────────────────────────────────────────────────

    def load_mock(self) -> None:
        """Load tickets from the mock file instead of Smartsheet."""
        if not MOCK_FILE.exists():
            raise FileNotFoundError(f"Mock file not found: {MOCK_FILE}")

        mock_data = json.loads(MOCK_FILE.read_text(encoding="utf-8"))
        self._store = {
            "last_fetched": _ts(),
            "tickets": mock_data.get("tickets", []),
        }
        logger.info("Loaded %d mock ticket(s) from %s",
                     len(self._store["tickets"]), MOCK_FILE.name)
