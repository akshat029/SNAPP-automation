#!/usr/bin/env python3
"""
EE-14350: Simple bulk role update.
One browser. One login. One journal nav. Then loop:
  search → click editor → edit profile → next → role → save → back → repeat
"""
import asyncio
import json
import sys
import logging
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from dotenv import load_dotenv
load_dotenv()

from snapp_agent import SnappAgent, LOG_DIR
from helpers import human_delay, human_click, human_type

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "ee14350_run.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("snapp_agent")

EDITORS = [
    "Zygmunt Kacki", "Peter Kanuch", "Cuneyt Kaya", "Judita Kochjarova",
    "Jan Kosco", "Alexey Kotov", "Lubomir Kovac", "Anton Kristin",
    "Pravindra Kumar", "Anna Kuzemko", "Xin Liu", "Zdenka Lososova",
    "Pedro Martinez-Gomez", "Beata Messyasz", "Gromiha Michael",
    "Le Duc Minh", "Ladislav Mucina", "Miroslav Ovecka", "Ashok Pandey",
    "Peter Parik", "Julio Polaina", "Pavol Prokop", "Mihai Puscas",
    "Naheem Rashid", "Bruno Rossaro", "Enrico Ruzzier", "Alireza Saboori",
    "Terezia Salaj", "Ebrahim Shokoohi", "Worapong Singchat",
    "Barbora Singliarova", "Matthias Sipiczki", "Michal Slezak",
    "Stano Stuchlik", "Hrudayanath Thatoi", "Marek Vaculik",
    "Milan Valachovic", "Yanping Wang", "Matthias Wolf",
    "Fric Zdenek-Faltynek",
]

JOURNAL = "Biologia"
NEW_ROLE = "Recommending Only"

# Already done
DONE = {
    "Zygmunt Kacki", "Peter Kanuch", "Cuneyt Kaya", "Judita Kochjarova",
    "Jan Kosco", "Alexey Kotov", "Lubomir Kovac", "Anton Kristin",
    "Anna Kuzemko", "Xin Liu", "Zdenka Lososova",
    "Pedro Martinez-Gomez", "Beata Messyasz", "Gromiha Michael",
    "Le Duc Minh", "Ladislav Mucina", "Miroslav Ovecka", "Ashok Pandey",
    "Julio Polaina", "Pavol Prokop",
}


async def main():
    total = len(EDITORS)
    results = []

    request = {
        "editor_name": "", "action": "update", "journal_name": JOURNAL,
        "role": NEW_ROLE, "_ticket_id": "EE-14350", "_prefer_normal": True,
        "first_name": "", "last_name": "", "journal_id": "", "affiliation": "",
        "email": "", "keywords": "", "collection_name": "", "collection_id": "",
        "sections": "", "status": "", "unavailable_from": "", "unavailable_to": "",
        "_row_id": "", "_requester": "", "_department": "", "_explain_update": "",
    }
    agent = SnappAgent(request, dry_run=False, no_save=False)

    print(f"\n{'=' * 60}")
    print(f"  EE-14350: Update {total} editors to '{NEW_ROLE}' on '{JOURNAL}'")
    print(f"  Skipping {len(DONE)} already done")
    print(f"{'=' * 60}\n")

    try:
        await agent._launch_browser()
        await agent.login()
        if not await agent.navigate_to_journal(JOURNAL):
            print("FAILED to navigate to journal")
            return

        page = agent.page

        for i, name in enumerate(EDITORS):
            print(f"  [{i+1}/{total}] {name}", end=" ... ", flush=True)

            if name in DONE:
                print("SKIP")
                results.append({"editor": name, "status": "skipped"})
                continue

            try:
                logger.info("--- [%d/%d] %s ---", i+1, total, name)
                # ---- SEARCH ----
                search_box = page.locator("#search_keyword").or_(page.get_by_placeholder("Please enter a search term"))
                await search_box.first.wait_for(state="visible", timeout=10000)
                await search_box.first.click()
                await search_box.first.fill("")     # clear old text
                await human_delay(0.2, 0.3)
                await search_box.first.fill(name)   # type new name
                logger.info("Searching: %s", name)
                search_btn = page.locator("button.btn--search")
                if await search_btn.count() > 0:
                    await search_btn.first.click()
                else:
                    await page.keyboard.press("Enter")
                await human_delay(1.5, 2.5)

                # ---- CLICK EDITOR RESULT ----
                link = page.get_by_role("link", name=name).or_(page.get_by_text(name, exact=False))
                if await link.count() == 0:
                    print("NOT FOUND")
                    results.append({"editor": name, "status": "not_found"})
                    continue

                # If multiple, prefer normal account
                if await link.count() > 1:
                    chosen = None
                    for idx in range(await link.count()):
                        el = link.nth(idx)
                        try:
                            ptxt = await el.evaluate("e => e.closest('tr,div,.card')?.textContent || ''")
                            if "guest editor" not in ptxt.lower():
                                chosen = el
                                break
                        except Exception:
                            chosen = el
                            break
                    if not chosen:
                        chosen = link.first
                    await chosen.click()
                else:
                    await link.first.click()
                await human_delay(1, 2)

                # ---- EDIT PROFILE ----
                edit_btn = (
                    page.locator("[data-test='edit-editor-button']")
                    .or_(page.get_by_role("link", name="Edit profile"))
                    .or_(page.get_by_text("Edit profile"))
                )
                if await edit_btn.count() == 0:
                    print("NO EDIT BTN")
                    results.append({"editor": name, "status": "no_edit_btn"})
                    # Go back to search
                    back = page.get_by_text("Back to all Editors").or_(page.get_by_text("Back to all editors"))
                    if await back.count() > 0:
                        await back.first.click()
                        await human_delay(1, 1.5)
                    continue
                await edit_btn.first.click()
                await human_delay(1.5, 2.5)

                # ---- NEXT (page 1 → page 2) ----
                next_btn = page.get_by_role("button", name="Next").or_(page.get_by_role("link", name="Next"))
                if await next_btn.count() > 0:
                    await next_btn.first.click()
                    await human_delay(1, 1.5)

                # ---- SELECT ROLE ----
                radio = page.locator("#recommendingOnlyEditorRole")
                if await radio.count() > 0:
                    await radio.evaluate("el => { el.scrollIntoView({block:'center'}); el.click(); }")
                else:
                    print("ROLE NOT FOUND")
                    results.append({"editor": name, "status": "role_not_found"})
                    back = page.get_by_text("Back to all Editors").or_(page.get_by_text("Back to all editors"))
                    if await back.count() > 0:
                        await back.first.click()
                        await human_delay(1, 1.5)
                    continue

                # ---- SAVE ----
                for btn_name in ["Save", "Save changes", "Submit", "Update"]:
                    save_btn = page.get_by_role("button", name=btn_name)
                    if await save_btn.count() > 0:
                        await save_btn.first.evaluate("el => el.scrollIntoView({block:'center'})")
                        await save_btn.first.click()
                        await human_delay(2, 3)
                        break

                print("OK")
                results.append({"editor": name, "status": "success"})

                # ---- BACK TO EDITOR LIST ----
                await human_delay(0.5, 1)
                back = page.get_by_text("Back to all Editors").or_(page.get_by_text("Back to all editors"))
                if await back.count() > 0:
                    await back.first.click()
                    await human_delay(1, 1.5)
                else:
                    # fallback: browser back
                    await page.go_back()
                    await human_delay(1, 1.5)
                    await page.go_back()
                    await human_delay(1, 1.5)

            except Exception as exc:
                print(f"ERROR: {exc}")
                results.append({"editor": name, "status": "error", "error": str(exc)})
                try:
                    back = page.get_by_text("Back to all Editors").or_(page.get_by_text("Back to all editors"))
                    if await back.count() > 0:
                        await back.first.click()
                        await human_delay(1, 1.5)
                except Exception:
                    pass

    finally:
        await agent._close_browser()

    # Summary
    ok = sum(1 for r in results if r["status"] == "success")
    skip = sum(1 for r in results if r["status"] == "skipped")
    fail = total - ok - skip
    print(f"\n{'=' * 60}")
    print(f"  DONE: {ok} success, {skip} skipped, {fail} failed")
    print(f"{'=' * 60}")
    if fail:
        for r in results:
            if r["status"] not in ("success", "skipped"):
                print(f"    {r['editor']}: {r['status']}")

    (LOG_DIR / "ee14350_results.json").write_text(
        json.dumps(results, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
