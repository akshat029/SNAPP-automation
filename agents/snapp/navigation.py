"""
SNAPP Navigation — Journal Search, Editor Search, Profile Access
=================================================================
Handles navigating to journals, finding editors, and opening edit forms.
"""

from __future__ import annotations

import logging

from playwright.async_api import TimeoutError as PlaywrightTimeout

from agents.base import AgentContext
from agents.snapp.selectors import SELECTORS
from helpers import retry_async

logger = logging.getLogger("snapp_agent")


class SnappNavigator:
    """Journal and editor navigation on the SNAPP platform."""

    def __init__(self, ctx: AgentContext) -> None:
        self.ctx = ctx

    # ── Journal navigation ────────────────────────────────────────────────

    @retry_async(max_retries=2, exceptions=(PlaywrightTimeout, Exception))
    async def navigate_to_journal(self, journal_name: str) -> bool:
        """
        Use the top-left journal autocomplete input to switch journals.
        Types the journal name character-by-character to trigger JS events,
        then clicks the matching suggestion.
        """
        import asyncio as _aio

        page = self.ctx.page
        assert page is not None
        logger.info("Searching for journal: '%s'", journal_name)
        try:
            journal_input = (
                page.locator(SELECTORS["journal_input"])
                .or_(page.locator(SELECTORS["journal_input_data"]))
                .or_(page.get_by_placeholder("Search by Journal title"))
            )

            if await journal_input.count() == 0:
                logger.error("Journal autocomplete input not found on page")
                await self.ctx.dump_page("no_journal_input")
                await self.ctx.screenshot("no_journal_input")
                return False

            logger.info("Found journal autocomplete input — activating")

            # Triple-click to select all existing text, then delete it
            await journal_input.first.click(click_count=3)
            await _aio.sleep(0.3)
            await page.keyboard.press("Backspace")
            await _aio.sleep(0.3)

            # Verify the field is now empty
            current_val = await journal_input.first.input_value()
            if current_val:
                logger.warning("Input not empty after clear ('%s') — force-clearing", current_val)
                await journal_input.first.evaluate("el => el.value = ''")
                await journal_input.first.dispatch_event("input")
                await _aio.sleep(0.2)

            # Type the journal name character by character to trigger JS events
            # Use press_sequentially (Playwright's keystroke simulation)
            logger.info("Typing journal name character by character...")
            await journal_input.first.press_sequentially(journal_name, delay=50)

            # Also dispatch input/change events as a safety net
            await journal_input.first.dispatch_event("input")
            await journal_input.first.dispatch_event("change")
            await journal_input.first.dispatch_event("keyup")

            # Wait for autocomplete suggestions to appear (with retries)
            suggestion_found = False
            for attempt in range(3):
                wait_ms = 3000 + (attempt * 2000)  # 3s, 5s, 7s
                logger.info("Waiting up to %dms for suggestions (attempt %d/3)", wait_ms, attempt + 1)
                try:
                    await page.locator("li").filter(
                        has_text=journal_name
                    ).first.wait_for(state="visible", timeout=wait_ms)
                    suggestion_found = True
                    break
                except PlaywrightTimeout:
                    if attempt < 2:
                        # Re-trigger: clear and re-type a shorter version
                        logger.info("No suggestions yet — re-triggering autocomplete")
                        await journal_input.first.click(click_count=3)
                        await _aio.sleep(0.2)
                        await page.keyboard.press("Backspace")
                        await _aio.sleep(0.3)
                        # Try typing just the first few words
                        words = journal_name.split()
                        search_term = " ".join(words[:min(3, len(words))])
                        await journal_input.first.press_sequentially(search_term, delay=50)
                        await journal_input.first.dispatch_event("input")

            if not suggestion_found:
                # Last resort: try using fill() + manual event dispatch
                logger.warning("Keystroke typing didn't trigger suggestions — trying fill() + JS dispatch")
                await journal_input.first.click(click_count=3)
                await page.keyboard.press("Backspace")
                await _aio.sleep(0.2)
                await journal_input.first.fill(journal_name)
                # Manually trigger the jQuery/JS event that SNAPP listens to
                await journal_input.first.evaluate("""el => {
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('keyup', {bubbles: true}));
                    el.dispatchEvent(new KeyboardEvent('keydown', {bubbles: true}));
                    // Also try jQuery trigger if available
                    if (typeof jQuery !== 'undefined') {
                        jQuery(el).trigger('input').trigger('keyup').trigger('change');
                    }
                }""")
                try:
                    await page.locator("li").filter(
                        has_text=journal_name
                    ).first.wait_for(state="visible", timeout=8_000)
                    suggestion_found = True
                except PlaywrightTimeout:
                    pass

            # Click the matching suggestion
            suggestion = (
                page.get_by_role("option", name=journal_name)
                .or_(page.get_by_role("listitem").filter(has_text=journal_name))
                .or_(page.locator("li, a, [class*='autocomplete-suggestion']").filter(has_text=journal_name))
            )

            if await suggestion.count() > 0:
                await suggestion.first.click()
                await page.wait_for_load_state("networkidle", timeout=15_000)
                logger.info("Opened journal: '%s'", journal_name)
                return True

            # Fallback: any visible text match (but not the input itself)
            text_match = page.locator("li, a, [role='option']").filter(has_text=journal_name)
            if await text_match.count() > 0:
                await text_match.first.click()
                await page.wait_for_load_state("networkidle", timeout=15_000)
                logger.info("Opened journal (text match): '%s'", journal_name)
                return True

            # Fallback 2: truncated name (first 3 words)
            words = journal_name.split()
            if len(words) > 3:
                short_name = " ".join(words[:3])
                logger.info("Retrying with truncated name: '%s'", short_name)
                await journal_input.first.click(click_count=3)
                await page.keyboard.press("Backspace")
                await _aio.sleep(0.3)
                await journal_input.first.press_sequentially(short_name, delay=50)
                await journal_input.first.dispatch_event("input")

                try:
                    await page.locator("li").filter(has_text=journal_name).first.wait_for(
                        state="visible", timeout=5_000
                    )
                except PlaywrightTimeout:
                    pass

                short_suggestion = (
                    page.get_by_role("option").filter(has_text=journal_name)
                    .or_(page.locator("li, a, [class*='autocomplete-suggestion']").filter(has_text=journal_name))
                )
                if await short_suggestion.count() > 0:
                    await short_suggestion.first.click()
                    await page.wait_for_load_state("networkidle", timeout=15_000)
                    logger.info("Opened journal (truncated match): '%s'", journal_name)
                    return True

            logger.error("Journal '%s' not found in suggestions", journal_name)
            await self.ctx.dump_page("journal_not_found")
            await self.ctx.screenshot("journal_not_found")
            return False

        except PlaywrightTimeout:
            logger.error("Timeout searching for journal '%s'", journal_name)
            await self.ctx.dump_page("journal_search_timeout")
            return False
        except Exception as exc:
            logger.error("Error navigating to journal: %s", exc, exc_info=True)
            await self.ctx.dump_page("journal_error")
            return False

    # ── Editor search ─────────────────────────────────────────────────────

    @retry_async(max_retries=2, exceptions=(PlaywrightTimeout, Exception))
    async def search_editor(self, editor_name: str) -> bool:
        """Search for an editor within the journal. Tries name variants."""
        page = self.ctx.page
        assert page is not None
        variants = self.name_variants(editor_name)
        for variant in variants:
            logger.info("Trying editor search: '%s'", variant)
            found = await self._do_editor_search(variant)
            if found:
                return True
            logger.warning("No match for '%s' — trying next variant", variant)
        logger.error("Editor '%s' not found (tried %d variants)", editor_name, len(variants))
        await self.ctx.dump_page("editor_not_found")
        await self.ctx.screenshot("editor_not_found")
        return False

    @staticmethod
    def name_variants(name: str) -> list[str]:
        """
        Generate search variations for the editor search box.

        IMPORTANT: SNAPP's search box does NOT return results when salutations
        (Professor, Dr., Mr., etc.) are included. The clean name (first + last
        only) is ALWAYS tried first.

        Order of variants tried:
          1. "Kazuhiko Yamamoto"          (clean, no title — most likely to hit)
          2. "Yamamoto, Kazuhiko"         (last, first)
          3. "Yamamoto Kazuhiko"          (reversed)
          4. "Yamamoto"                   (last name only — broadest fallback)
          5. "Professor Kazuhiko Yamamoto" (original, only if different)
        """
        # Strip all salutations/titles
        clean = name
        for title in ("Professor", "Prof.", "Prof", "Dr.", "Dr",
                      "Mr.", "Mr", "Mrs.", "Mrs", "Ms.", "Ms",
                      "Sir", "PhD"):
            clean = clean.replace(title, "").strip()
        # Collapse multiple spaces left after stripping
        clean = " ".join(clean.split())

        # Build variants — clean name FIRST
        variants: list[str] = [clean]

        parts = clean.split()
        if len(parts) >= 2:
            first, last = " ".join(parts[:-1]), parts[-1]
            variants.append(f"{last}, {first}")
            variants.append(f"{last} {first}")
            variants.append(last)  # last name only as broadest fallback

        # Original (with salutation) as last resort, only if different
        if name != clean:
            variants.append(name)

        return list(dict.fromkeys(variants))

    async def _do_editor_search(self, query: str) -> bool:
        """
        Execute an editor search within the current journal page.

        IMPORTANT: After clicking search, the page echoes the query in a
        "Results for 'XYZ'" header. We must NOT click that header text.
        We look for actual editor card links (a[href*='/editor/']) only.
        """
        page = self.ctx.page
        assert page is not None
        try:
            search = (
                page.locator(SELECTORS["editor_search"])
                .or_(page.get_by_placeholder("Please enter a search term"))
                .or_(page.get_by_role("searchbox"))
            )
            if await search.count() == 0:
                logger.warning("No editor search input found on page")
                await self.ctx.dump_page("no_editor_search")
                return False

            await search.first.click()
            await search.first.clear()
            await search.first.fill(query)

            # Click search button or press Enter
            search_btn = page.locator(SELECTORS["search_btn"])
            if await search_btn.count() > 0:
                await search_btn.first.click()
            else:
                await page.keyboard.press("Enter")

            # Wait for results to load
            await page.wait_for_load_state("networkidle", timeout=10_000)

            # ── CHECK 1: "Sorry, we couldn't find any results" ────────────
            no_results = page.get_by_text("Sorry, we couldn't find any results")
            if await no_results.count() > 0:
                logger.info("Search returned 0 results for: '%s'", query)
                return False

            # ── CHECK 2: Look for actual editor card links ────────────────
            # SNAPP editor cards have links like: /editors/281/editor/281/XXXX/edit
            editor_links = page.locator(SELECTORS["editor_card_link"])
            if await editor_links.count() > 0:
                # Click the first editor profile link
                href = await editor_links.first.get_attribute("href") or ""
                await editor_links.first.click()
                await page.wait_for_load_state("networkidle", timeout=10_000)
                logger.info("Editor found via profile link: '%s' -> %s", query, href)
                return True

            # ── CHECK 3: Look for editor card containers ──────────────────
            editor_cards = page.locator(SELECTORS["editor_card"])
            if await editor_cards.count() > 0:
                # Click a link inside the first card
                card_link = editor_cards.first.locator("a").first
                if await card_link.count() > 0:
                    await card_link.click()
                    await page.wait_for_load_state("networkidle", timeout=10_000)
                    logger.info("Editor found via card link: '%s'", query)
                    return True

            # ── CHECK 4: Any <a> link that contains the query text ────────
            # But EXCLUDE the search echo ("Results for 'X'") and header nav
            name_link = page.locator(
                "section a, .editors-list-page a, main a"
            ).filter(has_text=query)
            if await name_link.count() > 0:
                for i in range(min(await name_link.count(), 5)):
                    link = name_link.nth(i)
                    href = await link.get_attribute("href") or ""
                    # Only click links that go to an editor profile (not /add)
                    if ("/editor" in href or "/edit" in href) and "/add" not in href:
                        await link.click()
                        await page.wait_for_load_state("networkidle", timeout=10_000)
                        logger.info("Editor found via name link: '%s' -> %s", query, href)
                        return True

            logger.info("No editor links found for: '%s'", query)
            return False

        except PlaywrightTimeout:
            logger.error("Timeout during editor search")
            await self.ctx.dump_page("editor_search_timeout")
            return False
        except Exception as exc:
            logger.error("Editor search error: %s", exc, exc_info=True)
            await self.ctx.dump_page("editor_search_error")
            return False

    # ── Edit profile ──────────────────────────────────────────────────────

    async def click_edit_profile(self) -> bool:
        """Click the 'Edit profile' button on the editor's card.

        If the search result link already navigated to the /edit page,
        we're already in the form — no button click needed.
        """
        page = self.ctx.page
        assert page is not None

        # Check if we're already on the edit page (search result linked directly)
        current_url = page.url
        if "/edit" in current_url and "/editor/" in current_url:
            logger.info("Already on editor edit page (direct link) -- skipping Edit profile button")
            return True

        try:
            edit_btn = (
                page.locator(SELECTORS["edit_profile_btn"])
                .or_(page.get_by_role("link", name="Edit profile"))
                .or_(page.get_by_text("Edit profile"))
            )
            if await edit_btn.count() > 0:
                await edit_btn.first.click()
                await page.wait_for_load_state("networkidle", timeout=10_000)
                logger.info("Edit profile form opened")
                return True
            logger.error("'Edit profile' button not found")
            await self.ctx.dump_page("no_edit_profile_btn")
            return False
        except Exception as exc:
            logger.error("Error clicking Edit profile: %s", exc, exc_info=True)
            await self.ctx.dump_page("edit_profile_error")
            return False
