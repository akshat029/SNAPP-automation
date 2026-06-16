#!/usr/bin/env python3
"""
Run the SNAPP agent for the FIRST pending ticket from Smartsheet.
Uses --no-save mode so you can review before committing.
"""

import asyncio
import json
import sys
import logging
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from smartsheet_reader import SmartsheetReader
from snapp_agent import SnappAgent, LOG_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "snapp_agent.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("snapp_agent")


async def main():
    # Fetch pending requests from Smartsheet
    reader = SmartsheetReader()
    all_requests = reader.fetch_pending_requests()

    if not all_requests:
        print("\nNo pending requests found in Smartsheet.")
        return

    # Show all pending tickets for context
    print(f"\n{'=' * 60}")
    print(f"  {len(all_requests)} pending ticket(s) in Smartsheet:")
    for i, r in enumerate(all_requests):
        marker = " -->" if i == 1 else "    "
        print(f"{marker} [{i}] {r.get('_ticket_id', '?'):15s} | {r.get('action', '?'):20s} | {r.get('editor_name', '?')}")
    print(f"{'=' * 60}\n")

    # Pick the ticket to process (change index to target a different ticket)
    TICKET_INDEX = 0  # 0-indexed: 0=first, 1=second, etc.
    if TICKET_INDEX >= len(all_requests):
        print(f"Ticket index {TICKET_INDEX} out of range (only {len(all_requests)} tickets)")
        return

    target = all_requests[TICKET_INDEX]
    ticket_id = target.get("_ticket_id", "unknown")

    print(f"\n{'=' * 60}")
    print(f"  FIRST PENDING TICKET: {ticket_id}")
    print(f"  Action:       {target.get('action')}")
    print(f"  Editor:       {target.get('editor_name')}")
    print(f"  Journal:      {target.get('journal_name')}")
    print(f"  Role:         {target.get('role')}")
    print(f"  Affiliation:  {target.get('affiliation')}")
    print(f"  Keywords:     {target.get('keywords')}")
    print(f"  Email:        {target.get('email', '(none)')}")
    print(f"  Country:      {target.get('_country', '(none)')}")
    print(f"  Explain:      {target.get('_explain_update', '(none)')}")
    print(f"{'=' * 60}\n")

    # Run with --no-save so you can review before saving
    agent = SnappAgent(target, dry_run=False, no_save=True)
    result = await agent.run()

    status = result.get("status", "unknown")
    print(f"\n{'=' * 60}")
    print(f"  Result: {status}")
    if result.get("error"):
        print(f"  Error:  {result['error']}")
    print(f"{'=' * 60}\n")

    # Save result
    summary_path = LOG_DIR / f"single_ticket_{ticket_id}.json"
    summary_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"Summary saved to: {summary_path}")


if __name__ == "__main__":
    asyncio.run(main())
