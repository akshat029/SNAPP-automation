"""
SNAPP Keywords -- Tag Management
==================================
Handles adding keywords/tags to editor profiles.

HOW THE SNAPP TAGS WIDGET WORKS (from reference images 17-20):
──────────────────────────────────────────────────────────────
  Step 17: Tags input is empty ("You can add 20 more tags")
  Step 18: Type text → autocomplete dropdown appears with suggestions
  Step 19: Click a suggestion → tag chip appears ("tech ×")
  Step 20: If keyword doesn't exist → create it on Manage Keywords page

CRITICAL RULES:
  - Tags are AUTOCOMPLETE-ONLY. You CANNOT press Enter to add free text.
  - If the keyword doesn't appear in autocomplete suggestions, you MUST
    first create it on the internal Manage Keywords page, then come back
    and select it from the autocomplete.
  - The internal URL has a self-signed SSL cert (needs bypass).
  - The Tags input needs real keyboard events to trigger suggestions
    (same as affiliation → use press_sequentially, NOT fill).

INTERNAL KEYWORDS URL:
  https://usermanager.snpaas.private.nature.com/internal/keywords
  - Input: "Please enter the keyword to search and add"
  - Button: "Add"
  - Success toast: "[keyword] added successfully"
"""

from __future__ import annotations

import asyncio
import logging

from playwright.async_api import TimeoutError as PlaywrightTimeout

from agents.base import AgentContext
from agents.snapp.selectors import INTERNAL_KEYWORDS_URL

logger = logging.getLogger("snapp_agent")


class SnappKeywords:
    """Keyword/tag management for SNAPP editor profiles."""

    def __init__(self, ctx: AgentContext) -> None:
        self.ctx = ctx

    # ── Public entry point ────────────────────────────────────────────────

    async def add_keywords(self, keywords_csv: str) -> None:
        """Add keywords/tags to the editor's profile one by one."""
        page = self.ctx.page
        assert page is not None
        keywords = [k.strip() for k in keywords_csv.split(",") if k.strip()]
        if not keywords:
            return
        logger.info("Adding keywords: %s", keywords)

        # Wait for the tag input to become visible (JS widget needs time to init)
        tag_input = await self._find_visible_tag_input()
        if tag_input is None:
            logger.error("Tag input not found — cannot add keywords")
            await self.ctx.dump_page("no_tag_input")
            return

        for keyword in keywords:
            added = await self._add_single_keyword(keyword, tag_input)
            if not added:
                # Keyword not in autocomplete → create it on the internal page
                logger.info("Keyword '%s' not in suggestions — creating on internal URL", keyword)
                created = await self.create_keyword_on_internal(keyword)
                if created:
                    # Go back to the editor form and retry
                    # The tag input reference may be stale after navigation,
                    # so re-find it
                    tag_input = await self._find_visible_tag_input()
                    if tag_input:
                        added = await self._add_single_keyword(keyword, tag_input)
                if not added:
                    logger.warning("Could not add keyword '%s' even after creating it", keyword)

    # ── Find the visible tag input ────────────────────────────────────────

    async def _find_visible_tag_input(self):
        """
        Find the VISIBLE tag input for the Tags widget on Step 2.

        The wizard keeps ALL elements in the DOM at all times — step 1
        and step 2 fields alike. We MUST wait for visibility (not just
        attachment) to confirm we're actually on step 2.
        """
        page = self.ctx.page
        assert page is not None

        # Exact SNAPP selectors (from actual page HTML)
        candidates = [
            page.locator("#addEditorKeywords"),
            page.locator("#editEditorKeywords"),
            page.locator("[data-component-keywords-input]"),
            page.locator("input.c-keywords--tags-input"),
        ]

        # Wait for any of these to become VISIBLE (not just attached)
        for locator in candidates:
            try:
                await locator.first.wait_for(state="visible", timeout=5_000)
                ident = await locator.first.evaluate("el => el.id || el.className")
                logger.info("Found visible tag input: %s", ident)
                return locator.first
            except (PlaywrightTimeout, Exception):
                continue

        logger.warning("No visible tag input found after waiting")
        return None

    # ── Add a single keyword via autocomplete ─────────────────────────────

    async def _add_single_keyword(self, keyword: str, tag_input=None) -> bool:
        """
        Type a keyword in the tag input and select from autocomplete.

        Tags are AUTOCOMPLETE-ONLY — you must click a suggestion.
        Pressing Enter does NOT add free-text tags.
        """
        page = self.ctx.page
        assert page is not None
        try:
            if tag_input is None:
                tag_input = await self._find_visible_tag_input()
            if tag_input is None:
                logger.warning("Tag input not found — cannot add '%s'", keyword)
                return False

            # Click to focus (force=True because input may have zero dimensions)
            await tag_input.click(force=True)
            await asyncio.sleep(0.2)
            await tag_input.fill("")
            await asyncio.sleep(0.1)

            # Type using press_sequentially so keyboard events fire
            # and the autocomplete dropdown triggers
            await tag_input.press_sequentially(keyword, delay=30)
            logger.info("Typed keyword via keyboard: '%s'", keyword)

            # Wait for autocomplete suggestions to appear
            # SNAPP uses <div class="c-results-container__result"> (NOT <li>)
            await asyncio.sleep(1.0)
            suggestion_locator = page.locator(
                "#keywords-autocomplete-holder .c-results-container__result"
            )

            try:
                await suggestion_locator.first.wait_for(state="visible", timeout=5_000)
                count = await suggestion_locator.count()
                logger.info("  Keyword suggestions appeared (%d items)", count)
            except PlaywrightTimeout:
                count = 0

            if count > 0:
                # Try to find exact match first, then partial match
                best_match = None
                first_visible = None
                for i in range(min(count, 15)):
                    item = suggestion_locator.nth(i)
                    try:
                        if not await item.is_visible():
                            continue
                        text = (await item.text_content() or "").strip()
                        if first_visible is None:
                            first_visible = item
                        if text.lower() == keyword.lower():
                            best_match = item
                            break  # Exact match
                        if best_match is None and keyword.lower() in text.lower():
                            best_match = item  # Partial match
                    except Exception:
                        continue

                target = best_match or first_visible
                if target is not None:
                    text = (await target.text_content() or keyword).strip()
                    await target.click()
                    logger.info("  Selected keyword from suggestion: '%s'", text)
                    await asyncio.sleep(0.3)
                    return True

            # No suggestion found — keyword doesn't exist in SNAPP's database
            logger.info("  No autocomplete suggestion for '%s'", keyword)
            # Clear the input so it doesn't interfere with next keyword
            await tag_input.fill("")
            return False

        except PlaywrightTimeout:
            logger.warning("Timeout adding keyword '%s'", keyword)
            return False
        except Exception as exc:
            logger.error("Error adding keyword '%s': %s", keyword, exc, exc_info=True)
            return False

    # ── Create keyword on internal Manage Keywords page ───────────────────

    async def create_keyword_on_internal(self, keyword: str) -> bool:
        """
        Navigate to the internal Manage Keywords page, create a keyword,
        then return to the editor form.

        From reference docs (steps 17-20):
          URL: https://usermanager.snpaas.private.nature.com/internal/keywords
          - Has self-signed SSL cert → must bypass cert error
          - Page title: "Manage keywords"
          - Section: "Add a new keyword"
          - Input placeholder: "Please enter the keyword to search and add"
          - Button: "Add" (dark button next to input)
          - On type: system checks if keyword exists
          - If "This keyword doesn't exist in the database" → click Add
          - Success: toast "[keyword] added successfully" in top-right
        """
        page = self.ctx.page
        ctx = self.ctx.context
        assert page is not None and ctx is not None

        # Guard: check that the browser context is still alive
        try:
            _ = ctx.pages
        except Exception:
            logger.error("Browser context is closed — cannot open internal keyword tab")
            return False

        logger.info("Creating keyword '%s' on internal URL", keyword)

        try:
            new_page = await ctx.new_page()
            try:
                await new_page.goto(INTERNAL_KEYWORDS_URL, wait_until="domcontentloaded", timeout=15_000)
            except Exception:
                # Expected: cert error page loads instead
                pass

            # Handle SSL certificate error page
            advanced_btn = new_page.locator("#details-button, button:has-text('Advanced')")
            if await advanced_btn.count() > 0:
                await advanced_btn.first.click()
                await asyncio.sleep(0.5)
                proceed_link = new_page.locator("#proceed-link, a:has-text('Proceed')")
                if await proceed_link.count() > 0:
                    await proceed_link.first.click()
                    # CRITICAL: Wait for the actual Manage Keywords page to fully load
                    try:
                        await new_page.wait_for_load_state("networkidle", timeout=15_000)
                    except PlaywrightTimeout:
                        pass
                    await asyncio.sleep(1.0)
                    logger.info("Bypassed cert error — on Manage Keywords page")
                else:
                    logger.warning("'Proceed' link not found on cert error page")
                    await new_page.close()
                    return False

            # Wait for the keyword input to appear
            # But first — the internal page may require login
            # Try to detect a login form and fill with SNAPP credentials
            await asyncio.sleep(1.0)

            # Check if there's a login form (email/username input)
            login_input = (
                new_page.locator("input[type='email'], input[name='email'], input[name='username']")
                .or_(new_page.get_by_placeholder("email"))
                .or_(new_page.get_by_placeholder("username"))
                .or_(new_page.get_by_label("Email"))
            )
            if await login_input.count() > 0 and await login_input.first.is_visible():
                import os
                username = os.getenv("SNAPP_INTERNAL_USERNAME") or os.getenv("SNAPP_USERNAME", "")
                password = os.getenv("SNAPP_PASSWORD", "")
                if username and password:
                    logger.info("Login form detected on internal keywords page — filling credentials")
                    await login_input.first.fill(username)

                    # Submit email / click next
                    submit_btn = (
                        new_page.get_by_role("button", name="Submit")
                        .or_(new_page.get_by_role("button", name="Next"))
                        .or_(new_page.get_by_role("button", name="Sign in"))
                        .or_(new_page.get_by_role("button", name="Log in"))
                        .or_(new_page.locator("button[type='submit']"))
                    )
                    if await submit_btn.count() > 0:
                        await submit_btn.first.click()
                        await asyncio.sleep(2.0)

                    # Check for password field
                    pw_input = (
                        new_page.locator("input[type='password']")
                        .or_(new_page.get_by_placeholder("password"))
                        .or_(new_page.get_by_label("Password"))
                    )
                    if await pw_input.count() > 0 and await pw_input.first.is_visible():
                        await pw_input.first.fill(password)
                        # Submit password
                        if await submit_btn.count() > 0:
                            await submit_btn.first.click()
                        await asyncio.sleep(2.0)

                    # Wait for the actual Manage Keywords page
                    try:
                        await new_page.wait_for_load_state("networkidle", timeout=10_000)
                    except PlaywrightTimeout:
                        pass
                    await asyncio.sleep(1.0)
                    logger.info("Login submitted on internal keywords page")
                else:
                    logger.warning("Login form found but SNAPP_USERNAME/SNAPP_PASSWORD not set in .env")

            # Now look for the keyword input
            # Placeholder: "Please enter the keyword to search and add"
            kw_input = new_page.get_by_placeholder("Please enter the keyword to search and add")

            try:
                await kw_input.wait_for(state="visible", timeout=8_000)
            except PlaywrightTimeout:
                # Fallback selectors
                kw_input = (
                    new_page.get_by_placeholder("keyword")
                    .or_(new_page.get_by_role("textbox").first)
                    .or_(new_page.locator("input[type='text']").first)
                )

            if await kw_input.count() > 0:
                await kw_input.first.click()
                await kw_input.first.fill(keyword)
                await asyncio.sleep(1.0)  # Let the system search for existing keyword
                logger.info("Typed '%s' in keyword input", keyword)

                # Click the "Add" button
                add_btn = new_page.get_by_role("button", name="Add")
                if await add_btn.count() > 0:
                    await add_btn.first.click()
                    await asyncio.sleep(1.5)

                    # Check for success toast: "[keyword] added successfully"
                    try:
                        toast = new_page.locator("text=added successfully")
                        await toast.first.wait_for(state="visible", timeout=5_000)
                        logger.info("Keyword '%s' created successfully (toast confirmed)", keyword)
                    except PlaywrightTimeout:
                        logger.info("Keyword '%s' — Add clicked (no toast seen)", keyword)
                else:
                    logger.warning("'Add' button not found on Manage Keywords page")
            else:
                logger.warning("Keyword input not found on Manage Keywords page")

            await new_page.close()

            # Re-acquire the main editor page from context.pages[]
            # (the stale `page` reference may no longer be the active tab)
            try:
                pages = ctx.pages
                if pages:
                    # The first page is always the original editor form
                    main_page = pages[0]
                    self.ctx.page = main_page
                    await main_page.bring_to_front()
                    await asyncio.sleep(0.5)
                    logger.info("Re-acquired main editor page after closing keyword tab")
            except Exception as bring_exc:
                logger.warning("Could not bring main page to front: %s", bring_exc)

            return True

        except Exception as exc:
            logger.error("Error creating keyword on internal URL: %s", exc, exc_info=True)
            return False
