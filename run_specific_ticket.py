#!/usr/bin/env python3
"""
Run the SNAPP agent for a SPECIFIC ticket ID.
"""

import argparse
import asyncio
import json
import logging
import sys
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
    parser = argparse.ArgumentParser(description="Run SNAPP agent for a specific ticket")
    parser.add_argument("ticket_id", help="The ticket ID to run (e.g. EE-14350)")
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Fill all fields but do NOT click Save (preview/review mode)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate config and print execution plan (no browser)",
    )
    args = parser.parse_args()

    reader = SmartsheetReader()
    target = reader.fetch_ticket_by_id(args.ticket_id)

    if not target:
        print(f"\nTicket '{args.ticket_id}' was not found in Smartsheet.")
        return

    # Skip tickets flagged as name/email change
    explain = target.get("_explain_update", "")
    explain_lower = explain.lower()
    if any(kw in explain_lower for kw in ["email updated", "change email", "update email", "primary email"]):
        logger.warning(
            "⚠ SKIPPING ticket %s: contains a name or primary email "
            "change request — this CANNOT be done in SNAPP.\n"
            "  Explain Update: %s", args.ticket_id, explain,
        )
        return

    print(f"\n{'=' * 60}")
    print(f"  TARGET TICKET: {args.ticket_id}")
    print(f"  Action:       {target.get('action')}")
    print(f"  Editor:       {target.get('editor_name')}")
    print(f"  Journal:      {target.get('journal_name')}")
    print(f"  Role:         {target.get('role')}")
    print(f"  Affiliation:  {target.get('affiliation')}")
    print(f"  Keywords:     {target.get('keywords')}")
    print(f"  Email:        {target.get('email', '(none)')}")
    print(f"  Country:      {target.get('_country', '(none)')}")
    print(f"  Explain:      {explain or '(none)'}")
    print(f"{'=' * 60}\n")

    # Run SnappAgent
    agent = SnappAgent(target, dry_run=args.dry_run, no_save=args.no_save)
    result = await agent.run()

    status = result.get("status", "unknown")
    print(f"\n{'=' * 60}")
    print(f"  Result: {status}")
    if result.get("error"):
        print(f"  Error:  {result['error']}")
    print(f"{'=' * 60}\n")

    # Save result summary
    summary_path = LOG_DIR / f"single_ticket_{args.ticket_id}.json"
    summary_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"Summary saved to: {summary_path}")

    # Mark row as done in Smartsheet if successful and not dry-run / no-save
    if not args.dry_run and not args.no_save and status == "success":
        row_id = target.get("_row_id", "")
        if row_id:
            reader.mark_row_done(int(row_id), status)


if __name__ == "__main__":
    asyncio.run(main())
