#!/usr/bin/env python3
"""
SNAPP Agent — Bulk Update Runner
=================================
Processes multi-editor update tickets from Smartsheet. Parses the
`_explain_update` field, loops through each editor using a single
browser session, and produces a detailed per-editor results report.

Usage:
    python run_bulk_update.py EE-15465                  # Full run with save
    python run_bulk_update.py EE-15465 --no-save        # Fill only, no save
    python run_bulk_update.py EE-15465 --dry-run        # Parse & print plan only
    python run_bulk_update.py EE-15465 --start-from 5   # Resume from editor #5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from bulk_update_parser import parse_bulk_update, print_parsed_summary
from smartsheet_reader import SmartsheetReader
from snapp_agent import SnappAgent, LOG_DIR
import helpers
helpers.SPEED_FACTOR = 0.5  # 2x faster for bulk, keyword section overrides to 1.0

# ── Logging ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "snapp_agent.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("snapp_agent")

# Directory for bulk reports
BULK_LOG_DIR = LOG_DIR / "bulk"
BULK_LOG_DIR.mkdir(exist_ok=True)


def _safe_str(text: str) -> str:
    """Make a string safe for Windows console output (cp1252)."""
    try:
        text.encode(sys.stdout.encoding or "utf-8")
        return text
    except (UnicodeEncodeError, LookupError):
        return text.encode("ascii", errors="replace").decode("ascii")


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def print_results_table(
    editors: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> None:
    """Print a human-readable summary table of results."""
    # Figure out which field columns to show
    all_fields: set[str] = set()
    for r in results:
        all_fields.update(r.get("fields_requested", {}).keys())
    field_cols = sorted(all_fields)

    # Header
    header = f"{'#':>3}  {'Editor Name':<32}  {'Status':<12}"
    for f in field_cols:
        header += f"  {f:<12}"
    header += f"  {'Error'}"
    print("\n" + header)
    print("-" * len(header))

    # Rows
    for i, r in enumerate(results, 1):
        name = _safe_str(r.get("editor_name", "?"))
        if len(name) > 30:
            name = name[:27] + "..."
        status = r.get("status", "?")
        row = f"{i:>3}  {name:<32}  {status:<12}"

        completed = r.get("fields_completed", {})
        requested = r.get("fields_requested", {})
        for f in field_cols:
            if f in requested:
                row += f"  {'OK' if completed.get(f) else 'FAIL':<12}"
            else:
                row += f"  {'-':<12}"

        error = r.get("error", "") or ""
        if len(error) > 50:
            error = error[:47] + "..."
        row += f"  {error}"
        print(row)

    # Summary
    total = len(results)
    success = sum(1 for r in results if r.get("status") == "success")
    partial = sum(1 for r in results if r.get("status") == "partial")
    failed = sum(1 for r in results if r.get("status") == "failed")
    not_found = sum(1 for r in results if r.get("status") == "not_found")
    errors = sum(1 for r in results if r.get("status") == "error")
    skipped = total - success - partial - failed - not_found - errors

    print(f"\n  Total: {total}  |  OK: {success}  |  Partial: {partial}"
          f"  |  FAIL: {failed}  |  Not Found: {not_found}"
          f"  |  Error: {errors}")
    if skipped > 0:
        print(f"  Skipped (--start-from): {len(editors) - len(results)}")


async def run_bulk(
    ticket_id: str,
    *,
    no_save: bool = False,
    dry_run: bool = False,
    start_from: int = 1,
) -> None:
    """Main bulk update workflow."""

    # ── 1. Fetch ticket ──────────────────────────────────────────────────
    reader = SmartsheetReader()
    logger.info("Fetching ticket '%s' from Smartsheet...", ticket_id)
    ticket = reader.fetch_ticket_by_id(ticket_id)
    if not ticket:
        print(f"\nTicket '{ticket_id}' was not found in Smartsheet.")
        return

    explain = ticket.get("_explain_update", "")
    if not explain.strip():
        print(f"\nTicket '{ticket_id}' has no _explain_update content.")
        print("This ticket may not be a bulk update. Use run_specific_ticket.py instead.")
        return

    # ── 2. Parse into per-editor requests ────────────────────────────────
    editors = parse_bulk_update(explain, ticket)
    if not editors:
        print(f"\nCould not parse any editor requests from _explain_update.")
        print("Raw content:")
        print(explain)
        return

    journal = ticket.get("journal_name", "?")
    journal_id = str(int(float(ticket.get("journal_id", "0"))))

    print(f"\n{'=' * 70}")
    print(f"  BULK UPDATE: {ticket_id}")
    print(f"  Journal:     {journal} (ID: {journal_id})")
    print(f"  Editors:     {len(editors)}")
    print(f"  Mode:        {'DRY-RUN' if dry_run else 'NO-SAVE' if no_save else 'LIVE (will save)'}")
    if start_from > 1:
        print(f"  Starting at: Editor #{start_from}")
    print(f"{'=' * 70}")
    print("\nParsed editor requests:")
    print_parsed_summary(editors)

    if dry_run:
        print("\n[OK] Dry-run complete. No browser actions taken.")
        # Save dry-run report
        report = {
            "ticket_id": ticket_id,
            "journal": journal,
            "journal_id": journal_id,
            "mode": "dry_run",
            "total_editors": len(editors),
            "editors": [
                {
                    "index": i + 1,
                    "editor_name": ed.get("editor_name", "?"),
                    "fields_requested": {
                        k: ed.get(k, "")
                        for k in ("sections", "keywords", "role", "affiliation",
                                  "status", "unavailable_from", "unavailable_to")
                        if ed.get(k, "").strip()
                    },
                }
                for i, ed in enumerate(editors)
            ],
        }
        report_path = BULK_LOG_DIR / f"{ticket_id}_dryrun_{_ts()}.json"
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nDry-run report saved to: {report_path}")
        return

    # ── 3. Launch browser & login (once) ─────────────────────────────────
    # Create agent with the first editor's request
    first_req = editors[start_from - 1] if start_from <= len(editors) else editors[0]
    agent = SnappAgent(first_req, no_save=no_save)

    run_start = time.time()
    results: list[dict[str, Any]] = []

    try:
        await agent._launch_browser()
        logger.info("=== STEP 1: Login ===")
        await agent.login()

        logger.info("=== STEP 2: Navigate to journal '%s' (ID: %s) ===", journal, journal_id)

        # Use direct URL navigation with journal_id (more reliable than autocomplete)
        if journal_id and journal_id != "0":
            journal_url = f"https://usermanager.nature.com/editors/{journal_id}"
            logger.info("Navigating directly to journal via URL: %s", journal_url)
            await agent.page.goto(journal_url, wait_until="domcontentloaded", timeout=30_000)
            await agent._wait_for_journal_page_load()
            logger.info("Journal page loaded via direct URL")
        elif not await agent.navigate_to_journal(journal):
            print(f"\nFailed to navigate to journal '{journal}'")
            return

        # ── 4. Loop through editors ──────────────────────────────────────
        for i, editor_req in enumerate(editors, 1):
            if i < start_from:
                results.append({
                    "index": i,
                    "editor_name": editor_req.get("editor_name", "?"),
                    "status": "skipped",
                    "fields_requested": {},
                    "fields_completed": {},
                    "error": f"Skipped (--start-from {start_from})",
                    "duration_seconds": 0,
                })
                continue

            editor_name = editor_req.get("editor_name", "?")
            print(f"\n{'-' * 60}")
            print(f"  [{i}/{len(editors)}]  {_safe_str(editor_name)}")
            print(f"{'-' * 60}")

            # Update agent's request to this editor
            agent.request = editor_req
            editor_start = time.time()

            try:
                # Check if browser/page is still alive
                browser_alive = True
                try:
                    if agent.page is None or agent.page.is_closed():
                        browser_alive = False
                    else:
                        await agent.page.title()  # quick liveness check
                except Exception:
                    browser_alive = False

                if not browser_alive:
                    logger.warning("Browser/page died -- relaunching for editor #%d", i)
                    try:
                        await agent._close_browser()
                    except Exception:
                        pass
                    await agent._launch_browser()
                    await agent.login()
                    journal_url = f"https://usermanager.nature.com/editors/{journal_id}"
                    await agent.page.goto(
                        journal_url, wait_until="domcontentloaded", timeout=30_000
                    )
                    await agent._wait_for_journal_page_load()
                elif i > start_from:
                    # Navigate back to journal editor list between editors
                    journal_url = f"https://usermanager.nature.com/editors/{journal_id}"
                    logger.info("Navigating back to journal page: %s", journal_url)
                    await agent.page.goto(
                        journal_url, wait_until="domcontentloaded", timeout=30_000
                    )
                    await agent._wait_for_journal_page_load()

                # Run the single update
                r = await agent.run_single_update()
                r["index"] = i
                r["duration_seconds"] = round(time.time() - editor_start, 1)
                results.append(r)

                status_icon = {"success": "OK", "partial": "~~", "failed": "FAIL",
                               "not_found": "??", "error": "!!"}.get(r["status"], "??")
                print(f"  {status_icon} {r['status']}"
                      f"{'  -- ' + r['error'] if r.get('error') else ''}")

            except Exception as exc:
                logger.error("Fatal error for editor '%s': %s", editor_name, exc, exc_info=True)
                results.append({
                    "index": i,
                    "editor_name": editor_name,
                    "status": "error",
                    "fields_requested": {},
                    "fields_completed": {},
                    "error": str(exc),
                    "duration_seconds": round(time.time() - editor_start, 1),
                })

    except Exception as exc:
        logger.error("Fatal bulk update error: %s", exc, exc_info=True)
        print(f"\nFatal error: {exc}")
    finally:
        await agent._close_browser()

    # ── 5. Save report ───────────────────────────────────────────────────
    run_end = time.time()
    report = {
        "ticket_id": ticket_id,
        "journal": journal,
        "journal_id": journal_id,
        "mode": "no_save" if no_save else "live",
        "started_at": datetime.fromtimestamp(run_start, tz=timezone.utc).isoformat(),
        "completed_at": datetime.fromtimestamp(run_end, tz=timezone.utc).isoformat(),
        "total_duration_seconds": round(run_end - run_start, 1),
        "total_editors": len(editors),
        "succeeded": sum(1 for r in results if r.get("status") == "success"),
        "partial": sum(1 for r in results if r.get("status") == "partial"),
        "failed": sum(1 for r in results if r.get("status") == "failed"),
        "not_found": sum(1 for r in results if r.get("status") == "not_found"),
        "errors": sum(1 for r in results if r.get("status") == "error"),
        "skipped": sum(1 for r in results if r.get("status") == "skipped"),
        "editors": results,
    }

    report_path = BULK_LOG_DIR / f"{ticket_id}_{_ts()}.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ── 6. Print summary ─────────────────────────────────────────────────
    active_results = [r for r in results if r.get("status") != "skipped"]
    print_results_table(editors, active_results)

    print(f"\n  Total time: {report['total_duration_seconds']:.0f}s"
          f" ({report['total_duration_seconds'] / 60:.1f} min)")
    print(f"\n  Report saved to: {report_path}")

    # Mark Smartsheet row as done if all succeeded
    if not no_save and report["succeeded"] == report["total_editors"]:
        row_id = ticket.get("_row_id", "")
        if row_id:
            reader.mark_row_done(int(row_id), "success")
            print(f"  Smartsheet row marked as 'Done - success'")
    elif not no_save:
        print(f"  WARNING: Not all editors succeeded -- Smartsheet NOT marked as done.")
        print(f"    Review the report and re-run with --start-from N if needed.")


def main():
    parser = argparse.ArgumentParser(
        description="Run SNAPP bulk update for a multi-editor ticket"
    )
    parser.add_argument("ticket_id", help="The ticket ID (e.g. EE-15465)")
    parser.add_argument(
        "--no-save", action="store_true",
        help="Fill all fields but do NOT click Save (preview mode)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Parse the ticket and print plan only (no browser)",
    )
    parser.add_argument(
        "--start-from", type=int, default=1,
        help="Start processing from editor number N (1-indexed, for resuming)",
    )
    args = parser.parse_args()

    asyncio.run(run_bulk(
        args.ticket_id,
        no_save=args.no_save,
        dry_run=args.dry_run,
        start_from=args.start_from,
    ))


if __name__ == "__main__":
    main()
