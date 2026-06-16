#!/usr/bin/env python3
"""
EDITH — Editorial Data Intelligence & Tasking Hub
====================================================
CLI entry point for the SNAPP Digital Worker agent.

Usage:
    python main.py              # Process all pending Smartsheet requests
    python main.py --dry-run    # Validate config & print plan, no browser
    python main.py --mock       # Use mock tickets from data/mock_tickets.json
    python main.py --no-save    # Fill fields but don't click Save
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from agents.base import LOG_DIR
from agents.snapp.agent import SnappAgent
from agents.snapp.chains import parse_explain_update
from smartsheet_reader import SmartsheetReader
from ticket_store import TicketStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "snapp_agent.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("snapp_agent")


async def enrich_request_with_llm(request: dict[str, str]) -> dict[str, str]:
    """
    Parse the free-text 'Explain Update' field into structured fields
    using the LangChain structured output chain (with regex fallback).

    Only fills fields that are currently EMPTY in the request.
    """
    explain = request.get("_explain_update", "").strip()
    if not explain:
        return request

    logger.info("[ENRICH] Parsing Explain Update: '%s'", explain)
    parsed = await parse_explain_update(explain)

    # Only fill in fields that are currently EMPTY in the request
    field_map = {
        "role": "role",
        "affiliation": "affiliation",
        "unavailable_from": "unavailable_from",
        "unavailable_to": "unavailable_to",
        "status": "status",
        "keywords": "keywords",
    }
    enriched_fields = []
    for parsed_key, req_key in field_map.items():
        parsed_value = getattr(parsed, parsed_key, "")
        if parsed_value and not request.get(req_key, "").strip():
            request[req_key] = str(parsed_value)
            enriched_fields.append(f"{req_key}='{parsed_value}'")

    if enriched_fields:
        logger.info("[ENRICH] Enriched request: %s", ", ".join(enriched_fields))
    else:
        logger.info("[ENRICH] No new fields to fill")

    return request


async def main() -> None:
    parser = argparse.ArgumentParser(description="SNAPP Digital Worker Agent")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate config and print execution plan (no browser)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock tickets from data/mock_tickets.json",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Fill all fields but do NOT click Save (preview mode)",
    )
    args = parser.parse_args()

    # ── Load / sync ticket store ──────────────────────────────────────────
    store = TicketStore()

    if args.mock:
        store.load_mock()
        logger.info("Using MOCK tickets from data/mock_tickets.json")
    else:
        store.load()
        reader = SmartsheetReader()
        added = store.sync_from_smartsheet(reader)
        logger.info("Synced %d new ticket(s) from Smartsheet", added)

    pending = store.get_pending()
    if not pending:
        logger.info("No pending tickets — nothing to do.")
        print("\n  No pending tickets found. Exiting.\n")
        return

    logger.info("Found %d pending ticket(s) to process", len(pending))

    # ── Process each ticket ───────────────────────────────────────────────
    all_results: list[dict[str, Any]] = []
    skipped_tickets: list[dict[str, Any]] = []

    for i, entry in enumerate(pending, 1):
        ticket_id = entry["ticket_id"]
        request = entry["request"]

        logger.info("=" * 60)
        logger.info("Processing ticket %d of %d  [%s]", i, len(pending), ticket_id)
        logger.info("=" * 60)

        # Skip tickets flagged as name/email change
        skip_reason = request.get("_skip_reason", "")
        if skip_reason == "name_or_email_change":
            editor = request.get("editor_name", "?")
            explain = request.get("_explain_update", "")
            logger.warning(
                "⚠ SKIPPING ticket %s (%s): contains a name or primary email "
                "change request — this CANNOT be done in SNAPP.\n"
                "  Explain Update: %s", ticket_id, editor, explain,
            )
            store.mark_skipped(ticket_id, reason="name_or_email_change")
            skipped_tickets.append(entry)
            continue

        # Mark as processing
        store.mark_processing(ticket_id)

        # Log explain_update if present
        explain_update = request.get("_explain_update", "")
        if explain_update:
            logger.info("[TICKET] Explain Update: %s", explain_update)

        # Enrich: Parse explain_update to fill empty structured fields
        request = await enrich_request_with_llm(request)

        try:
            agent = SnappAgent(request, dry_run=args.dry_run, no_save=args.no_save)
            result = await agent.run()
            all_results.append(result)

            # Write run summary
            from datetime import datetime, timezone
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            summary_path = LOG_DIR / f"run_summary_{ts}.json"
            summary_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
            logger.info("Run summary -> %s", summary_path)

            # Update ticket store
            store.mark_complete(ticket_id, result)

            # Mark row as done in Smartsheet
            if not args.mock and not args.dry_run:
                row_id = request.get("_row_id", "")
                if row_id and "reader" in locals():
                    reader.mark_row_done(int(row_id), result.get("status", "unknown"))

        except Exception as exc:
            logger.error("Ticket %s failed: %s", ticket_id, exc, exc_info=True)
            store.mark_error(ticket_id, str(exc))
            all_results.append({"request": request, "status": "error", "error": str(exc)})

        # Small pause between requests
        if i < len(pending):
            logger.info("Waiting before next ticket...")
            await asyncio.sleep(3)

    # ── Summary ───────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"  Processed {len(all_results)} ticket(s)")
    for r in all_results:
        name = r.get("request", {}).get("editor_name", "?")
        status = r.get("status", "?")
        print(f"    {name:40s}  ->  {status}")
    if skipped_tickets:
        print(f"\n  Skipped {len(skipped_tickets)} ticket(s) (require manual action):")
        for entry in skipped_tickets:
            tid = entry["ticket_id"]
            editor = entry["request"].get("editor_name", "?")
            reason = entry["request"].get("_skip_reason", "?")
            print(f"    {tid}: {editor} ({reason})")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    asyncio.run(main())
