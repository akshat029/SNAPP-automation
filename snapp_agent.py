#!/usr/bin/env python3
"""
SNAPP Digital Worker — Editor Onboarding / Offboarding Agent  (v4)
===================================================================
A fault-tolerant, stealth Playwright automation agent that reads a request
queue and applies editor-profile changes on the SNAPP User Manager platform
(https://usermanager.nature.com).

Usage:
    python snapp_agent.py              # Normal run (visible browser)
    python snapp_agent.py --dry-run    # Validate config & print plan, no browser

Environment variables (see .env.example):
    SNAPP_USERNAME       — SNAPP / Springer Nature login username
    SNAPP_PASSWORD       — SNAPP / Springer Nature login password
    SNAPP_URL            — Base URL (default: https://usermanager.nature.com)
    CHROME_PROFILE_PATH  — Path to Chrome user-data dir (required for session reuse)
    SMARTSHEET_TOKEN     — Smartsheet API access token
    SMARTSHEET_SHEET_ID  — Smartsheet sheet ID to read requests from
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)

from helpers import human_click, human_delay, human_type, parse_editor_name, retry_async
from smartsheet_reader import SmartsheetReader

# Internal keywords management URL
INTERNAL_KEYWORDS_URL = "https://usermanager.snpaas.private.nature.com/internal/keywords"

# Email template for name/email change requests (cannot be done by team)
NAME_EMAIL_CHANGE_TEMPLATE = """
Dear [Editor name],
The easiest way to update your email address is to change it via your profile.
You can access your profile and learn how to update your email address on
https://my-profile.springernature.com/ .
"""

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "snapp_agent.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("snapp_agent")

# Overall run timeout (10 minutes) to prevent stuck runs
RUN_TIMEOUT_SECONDS = 600


# ──────────────────────────────────────────────────────────────────────────────
# SnappAgent
# ──────────────────────────────────────────────────────────────────────────────
class SnappAgent:
    """Playwright-powered Digital Worker for SNAPP editor management."""

    def __init__(self, request: dict[str, str], *, dry_run: bool = False, no_save: bool = False) -> None:
        load_dotenv()
        self.request = request
        self.dry_run = dry_run
        self.no_save = no_save
        self.base_url: str = os.getenv("SNAPP_URL", "https://usermanager.nature.com")
        self.username: str | None = os.getenv("SNAPP_USERNAME")
        self.password: str | None = os.getenv("SNAPP_PASSWORD")
        if not self.username or not self.password:
            logger.error("SNAPP_USERNAME and SNAPP_PASSWORD must be set in .env")
            raise EnvironmentError("Missing SNAPP credentials in environment.")
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        logger.info("SnappAgent initialised  |  request=%s  dry_run=%s  no_save=%s",
                     json.dumps(request, ensure_ascii=False), dry_run, no_save)

    # ── Utility ───────────────────────────────────────────────────────────

    def _ts(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    async def _screenshot(self, prefix: str = "confirmation") -> Path:
        out = Path("screenshots")
        out.mkdir(exist_ok=True)
        path = out / f"{prefix}_{self._ts()}.png"
        if self.page:
            await self.page.screenshot(path=str(path), full_page=True)
            logger.info("Screenshot -> %s", path)
        return path

    async def _dump_page(self, ctx: str = "error") -> Path:
        if not self.page:
            return Path("nul")
        html = await self.page.content()
        path = LOG_DIR / f"page_dump_{ctx}_{self._ts()}.html"
        path.write_text(html, encoding="utf-8")
        logger.warning("Page HTML dumped -> %s", path)
        return path

    # ── Browser lifecycle ─────────────────────────────────────────────────

    async def _launch_browser(self) -> None:
        self.playwright = await async_playwright().start()
        chrome_profile = os.getenv("CHROME_PROFILE_PATH", "")
        stealth_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        stealth_script = "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"

        if chrome_profile:
            logger.info("Using Chrome profile: %s", chrome_profile)
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=chrome_profile,
                headless=False,
                channel="chrome",
                no_viewport=True,
                args=stealth_args + ["--start-maximized"],
                locale="en-GB",
                timezone_id="Europe/London",
            )
            await self.context.add_init_script(stealth_script)
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
            logger.info("Browser launched with existing profile")
        else:
            logger.warning("No CHROME_PROFILE_PATH — using fresh browser")
            self.browser = await self.playwright.chromium.launch(
                headless=False,
                channel="chrome",
                args=stealth_args + ["--start-maximized"],
            )
            self.context = await self.browser.new_context(
                viewport={"width": 1366, "height": 768},
                locale="en-GB",
                timezone_id="Europe/London",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.6422.112 Safari/537.36"
                ),
            )
            await self.context.add_init_script(stealth_script)
            self.page = await self.context.new_page()
            logger.info("Browser launched (stealth mode, headless=False)")

    async def _close_browser(self) -> None:
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("Browser closed")

    # ── Login ─────────────────────────────────────────────────────────────

    async def login(self) -> None:
        """
        Authenticate on SNAPP. Handles:
          0) Cookie consent banner (clicks "Accept all cookies")
          A) Already logged in (Chrome profile has active session)
          B) Springer Nature login page (Email address + password, or Google SSO)
          C) 2FA / MFA challenge -> pauses for human
        """
        assert self.page is not None
        logger.info("Navigating to %s", self.base_url)
        try:
            await self.page.goto(self.base_url, wait_until="domcontentloaded", timeout=60_000)
        except PlaywrightTimeout:
            logger.warning("Timeout navigating to base URL -- checking if page loaded anyway")
        except Exception as exc:
            if "Timeout" in str(exc):
                logger.warning("Timeout navigating to base URL -- checking if page loaded anyway")
            else:
                raise

        # Wait for whatever page we landed on to fully load
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except Exception:
            pass
        try:
            await self.page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass

        # Step 0 — Dismiss cookie consent banner if present
        try:
            cookie_btn = self.page.get_by_role("button", name="Accept all cookies")
            if await cookie_btn.count() > 0:
                logger.info("Cookie consent banner detected — accepting cookies")
                await human_click(cookie_btn.first)
                await human_delay(1, 2)
        except Exception:
            pass  # no cookie banner, that's fine

        # Check if already authenticated (Chrome profile skipped login)
        if "usermanager.nature.com" in self.page.url and "login" not in self.page.url.lower():
            # Look for the journal autocomplete input as proof we're on the dashboard
            journal_input = self.page.locator("input.c-journal-autocomplete")
            if await journal_input.count() > 0:
                logger.info("Already logged in (session from Chrome profile) — URL: %s", self.page.url)
                return

        # Scenario A — Springer Nature login page
        # The page shows "Log in, or register a new account to continue"
        # with an "Email address" label/field
        try:
            email_loc = (
                self.page.get_by_label("Email address")
                .or_(self.page.get_by_placeholder("Email address"))
                .or_(self.page.get_by_placeholder("Email"))
                .or_(self.page.get_by_placeholder("Username"))
                .or_(self.page.get_by_label("Username"))
                .or_(self.page.get_by_label("Email"))
            )
            if await email_loc.count() > 0:
                logger.info("Login form detected — filling email/username")
                await human_type(self.page, email_loc.first, self.username)
                await human_delay(0.8, 1.5)

                # Look for password field on the same page
                password_loc = (
                    self.page.get_by_placeholder("Password")
                    .or_(self.page.get_by_label("Password"))
                )
                if await password_loc.count() > 0:
                    # Password visible on same page — fill and submit
                    await human_type(self.page, password_loc.first, self.password)
                    await human_delay(0.6, 1.2)
                    submit = (
                        self.page.get_by_role("button", name="Log in")
                        .or_(self.page.get_by_role("button", name="Sign in"))
                        .or_(self.page.get_by_role("button", name="Login"))
                        .or_(self.page.get_by_role("button", name="Submit"))
                        .or_(self.page.get_by_role("button", name="Continue"))
                    )
                    if await submit.count() > 0:
                        await human_click(submit.first)
                        logger.info("Credentials submitted")
                        await human_delay(3, 5)
                else:
                    # Multi-step: submit email first, then password appears
                    next_btn = (
                        self.page.get_by_role("button", name="Continue")
                        .or_(self.page.get_by_role("button", name="Next"))
                        .or_(self.page.get_by_role("button", name="Submit"))
                        .or_(self.page.get_by_role("button", name="Log in"))
                    )
                    if await next_btn.count() > 0:
                        await human_click(next_btn.first)
                        logger.info("Email submitted — waiting for password step")
                        await human_delay(2, 4)

                    # Now look for password field
                    password_loc = (
                        self.page.get_by_placeholder("Password")
                        .or_(self.page.get_by_label("Password"))
                    )
                    if await password_loc.count() > 0:
                        await human_type(self.page, password_loc.first, self.password)
                        await human_delay(0.6, 1.2)
                        submit = (
                            self.page.get_by_role("button", name="Log in")
                            .or_(self.page.get_by_role("button", name="Sign in"))
                            .or_(self.page.get_by_role("button", name="Submit"))
                            .or_(self.page.get_by_role("button", name="Continue"))
                            .or_(self.page.get_by_role("button", name="Verify"))
                        )
                        if await submit.count() > 0:
                            await human_click(submit.first)
                            logger.info("Password submitted")
                            await human_delay(3, 5)
            else:
                logger.info("No login form detected — checking for Google SSO or already logged in")
                # Try "Continue with Google" button
                google_btn = (
                    self.page.get_by_role("button", name="Continue with Google")
                    .or_(self.page.get_by_text("Continue with Google"))
                )
                if await google_btn.count() > 0:
                    logger.info("'Continue with Google' button found — clicking")
                    await human_click(google_btn.first)
                    await human_delay(3, 5)

        except PlaywrightTimeout:
            logger.warning("Timeout detecting login fields — pausing for human")
            await self._dump_page("login_timeout")

        # Scenario C — MFA
        await self._wait_for_mfa()

        # Confirm authenticated — wait up to 2 minutes for user to complete any manual steps
        try:
            await self.page.wait_for_url("**/usermanager.nature.com/**", timeout=120_000)
            logger.info("Login succeeded — URL: %s", self.page.url)
        except PlaywrightTimeout:
            if "usermanager" in self.page.url:
                logger.info("Login appears successful — URL: %s", self.page.url)
            else:
                await self._dump_page("login_failed")
                raise RuntimeError(f"Login failed — stuck at: {self.page.url}")

    async def _wait_for_mfa(self) -> None:
        assert self.page is not None
        mfa_signals = [
            "Enter verification code", "Two-factor authentication",
            "Verify your identity", "We sent a code",
            "Approve sign-in request", "Enter the code",
        ]
        for text in mfa_signals:
            indicator = self.page.get_by_text(text)
            if await indicator.count() > 0:
                logger.warning("MFA detected — complete it in the browser window")
                print("\n" + "=" * 60)
                print("  ACTION REQUIRED:  Complete 2FA in the browser window")
                print("=" * 60 + "\n")
                while await indicator.count() > 0:
                    await asyncio.sleep(3)
                logger.info("MFA resolved — continuing")
                await human_delay(1, 2)
                break

    # ── Journal navigation ────────────────────────────────────────────────

    @retry_async(max_retries=2, exceptions=(PlaywrightTimeout, Exception))
    async def navigate_to_journal(self, journal_name: str) -> bool:
        """
        Use the top-left journal autocomplete input to switch journals.

        The SNAPP UI has an <input> at the top with:
          class="c-journal-autocomplete"
          placeholder="Search by Journal title"
          data-component-journal-autocomplete-input
        Clicking it selects the current journal name so you can type a new one.
        """
        assert self.page is not None
        logger.info("Searching for journal: '%s'", journal_name)
        try:
            # Primary selector — exact match from SNAPP HTML
            journal_input = self.page.locator(
                "input.c-journal-autocomplete"
            ).or_(
                self.page.locator("input[data-component-journal-autocomplete-input]")
            ).or_(
                self.page.get_by_placeholder("Search by Journal title")
            )

            if await journal_input.count() == 0:
                logger.error("Journal autocomplete input not found on page")
                await self._dump_page("no_journal_input")
                await self._screenshot("no_journal_input")
                return False

            logger.info("Found journal autocomplete input -- clicking to activate")
            await human_click(journal_input.first)

            # Clear existing text
            await self.page.keyboard.press("Control+a")
            await self.page.keyboard.press("Backspace")
            await human_delay(0.2, 0.3)

            # Paste journal name via clipboard (fast) to trigger autocomplete
            words = journal_name.split()
            short_name = " ".join(words[:min(4, len(words))])
            await self.page.evaluate(
                "text => navigator.clipboard.writeText(text)", short_name
            )
            await self.page.keyboard.press("Control+v")
            logger.info("Pasted journal search: '%s'", short_name)

            # Wait for autocomplete suggestions (quick check)
            suggestion = (
                self.page.get_by_role("option", name=journal_name)
                .or_(self.page.get_by_role("listitem").filter(has_text=journal_name))
                .or_(self.page.locator("li, a, [class*='autocomplete-suggestion']").filter(has_text=journal_name))
            )
            try:
                await suggestion.first.wait_for(state="visible", timeout=5_000)
            except Exception:
                pass

            if await suggestion.count() > 0:
                await suggestion.first.click()
                await self._wait_for_journal_page_load()
                logger.info("Opened journal: '%s'", journal_name)
                return True

            # Fallback: look for the text anywhere clickable on the page
            text_match = self.page.get_by_text(journal_name, exact=False)
            if await text_match.count() > 0:
                await text_match.first.click()
                await self._wait_for_journal_page_load()
                logger.info("Opened journal (text match): '%s'", journal_name)
                return True

            logger.error("Journal '%s' not found in suggestions", journal_name)
            await self._dump_page("journal_not_found")
            await self._screenshot("journal_not_found")
            return False

        except PlaywrightTimeout:
            logger.error("Timeout searching for journal '%s'", journal_name)
            await self._dump_page("journal_search_timeout")
            return False
        except Exception as exc:
            logger.error("Error navigating to journal: %s", exc, exc_info=True)
            await self._dump_page("journal_error")
            return False
    # ── Journal page load helper ────────────────────────────────────────────

    async def _wait_for_journal_page_load(self) -> None:
        """Wait for the journal page to finish loading after selecting a journal."""
        assert self.page is not None
        try:
            await self.page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        # Wait for add_new_btn or search_keyword as confirmation
        try:
            await self.page.locator("#add_new_btn").or_(
                self.page.locator("#search_keyword")
            ).first.wait_for(state="visible", timeout=10_000)
        except Exception:
            pass

    # ── Form field helpers ─────────────────────────────────────────────────

    async def _fill_by_id(self, element_id: str, value: str) -> bool:
        """Fill a form field by its HTML ID attribute."""
        assert self.page is not None
        field = self.page.locator(f"#{element_id}")
        if await field.count() > 0:
            await field.first.click()
            await field.first.fill(value)
            logger.info("Filled #%s = '%s'", element_id, value)
            return True
        logger.warning("Field #%s not found", element_id)
        return False

    async def _select_country_dropdown(self, country: str) -> bool:
        """Select a country from a native <select> dropdown."""
        assert self.page is not None
        # Try common SNAPP country select IDs
        for sel_id in ["addEditorInstitutionCountry", "country", "institutionCountry"]:
            sel = self.page.locator(f"#{sel_id}")
            if await sel.count() > 0:
                try:
                    await sel.select_option(label=country)
                    logger.info("Selected country: '%s'", country)
                    return True
                except Exception:
                    # Try JS fallback
                    try:
                        await sel.evaluate(
                            """(el, c) => {
                                for (const opt of el.options) {
                                    if (opt.textContent.trim() === c) {
                                        el.value = opt.value;
                                        el.dispatchEvent(new Event('change', {bubbles: true}));
                                        return;
                                    }
                                }
                            }""", country
                        )
                        logger.info("Selected country via JS: '%s'", country)
                        return True
                    except Exception as e2:
                        logger.warning("Country select failed: %s", e2)
        logger.warning("Country dropdown not found")
        return False

    # ── Editor search ─────────────────────────────────────────────────────

    @retry_async(max_retries=2, exceptions=(PlaywrightTimeout, Exception))
    async def search_editor(self, editor_name: str) -> bool:
        """Search for an editor within the journal. Tries name variants."""
        assert self.page is not None
        variants = self._name_variants(editor_name)
        for variant in variants:
            logger.info("Trying editor search: '%s'", variant)
            found = await self._do_editor_search(variant)
            if found:
                return True
            logger.warning("No match for '%s' — trying next variant", variant)
            await human_delay(1, 2)
        logger.error("Editor '%s' not found (tried %d variants)", editor_name, len(variants))
        await self._dump_page("editor_not_found")
        await self._screenshot("editor_not_found")
        return False

    @staticmethod
    def _name_variants(name: str) -> list[str]:
        """Generate search variations for typo/ordering robustness."""
        variants: list[str] = [name]
        clean = name
        for title in ("Dr.", "Prof.", "Mr.", "Mrs.", "Ms.", "Sir", "Dr", "Professor"):
            clean = clean.replace(title, "").strip()
        if clean != name:
            variants.append(clean)
        parts = clean.split()
        if len(parts) >= 2:
            first, last = " ".join(parts[:-1]), parts[-1]
            variants.append(f"{last}, {first}")
            variants.append(f"{last} {first}")
            variants.append(last)  # last name only as fallback
        return list(dict.fromkeys(variants))

    async def _do_editor_search(self, query: str) -> bool:
        """Execute an editor search within the current journal page."""
        assert self.page is not None
        try:
            # The search input is <input id="search_keyword" placeholder="Please enter a search term">
            search = (
                self.page.locator("#search_keyword")
                .or_(self.page.get_by_placeholder("Please enter a search term"))
                .or_(self.page.get_by_role("searchbox"))
            )
            if await search.count() == 0:
                logger.warning("No editor search input found on page")
                await self._dump_page("no_editor_search")
                return False

            await search.first.click()
            await human_delay(0.3, 0.6)
            await search.first.clear()
            await human_type(self.page, search.first, query)
            # Click the search button (adjacent to the input)
            search_btn = self.page.locator("button.btn--search")
            if await search_btn.count() > 0:
                await human_click(search_btn.first)
            else:
                await self.page.keyboard.press("Enter")
            await human_delay(2, 4)

            # Look for clickable result rows
            result = (
                self.page.get_by_role("link", name=query)
                .or_(self.page.get_by_text(query, exact=False))
            )
            result_count = await result.count()
            if result_count > 0:
                # If multiple results, prefer normal account over guest
                if result_count > 1 and self.request.get("_prefer_normal", False):
                    logger.info("Multiple results (%d) found — preferring normal (non-guest) account", result_count)
                    chosen = None
                    for i in range(result_count):
                        el = result.nth(i)
                        # Check if the parent row/card contains "Guest Editor"
                        try:
                            parent_text = await el.evaluate("el => el.closest('tr, .card, .editor-row, div')?.textContent || ''")
                            if "guest editor" in parent_text.lower():
                                logger.info("  Result %d: GUEST account — skipping", i)
                                continue
                            else:
                                logger.info("  Result %d: normal account — selecting", i)
                                chosen = el
                                break
                        except Exception:
                            chosen = el
                            break
                    if chosen is None:
                        logger.warning("All results appear to be guest accounts — using first result")
                        chosen = result.first
                    await human_click(chosen)
                else:
                    await human_click(result.first)
                await human_delay(1.5, 3)
                logger.info("Editor found: '%s'", query)
                return True

            no_hit = (
                self.page.get_by_text("No results")
                .or_(self.page.get_by_text("not found"))
                .or_(self.page.get_by_text("0 results"))
            )
            if await no_hit.count() > 0:
                return False
            return False

        except PlaywrightTimeout:
            logger.error("Timeout during editor search")
            await self._dump_page("editor_search_timeout")
            return False
        except Exception as exc:
            logger.error("Editor search error: %s", exc, exc_info=True)
            await self._dump_page("editor_search_error")
            return False

    # ── Click "Edit profile" ──────────────────────────────────────────────

    async def click_edit_profile(self) -> bool:
        """Click the 'Edit profile' button on the editor's card."""
        assert self.page is not None
        try:
            # "Edit profile" is an <a> with data-test="edit-editor-button"
            edit_btn = (
                self.page.locator("[data-test='edit-editor-button']")
                .or_(self.page.get_by_role("link", name="Edit profile"))
                .or_(self.page.get_by_text("Edit profile"))
            )
            if await edit_btn.count() > 0:
                await human_click(edit_btn.first)
                await human_delay(2, 4)
                logger.info("Edit profile form opened")
                return True
            logger.error("'Edit profile' button not found")
            await self._dump_page("no_edit_profile_btn")
            return False
        except Exception as exc:
            logger.error("Error clicking Edit profile: %s", exc, exc_info=True)
            await self._dump_page("edit_profile_error")
            return False

    # ── Helpers: fill fields ──────────────────────────────────────────────

    async def _fill_field_by_labels(self, labels: list[str], value: str) -> bool:
        """Try multiple label/placeholder strings for a field and fill the first match."""
        assert self.page is not None
        for label in labels:
            loc = self.page.get_by_label(label).or_(self.page.get_by_placeholder(label))
            if await loc.count() > 0:
                el = loc.first
                try:
                    input_type = await el.get_attribute("type") or "text"
                    if input_type.lower() in ("radio", "checkbox", "submit", "button"):
                        continue
                except Exception:
                    pass

                try:
                    await el.click()
                except Exception:
                    pass
                await human_delay(0.2, 0.5)
                # clear text field
                try:
                    await el.clear()
                except Exception:
                    pass  # ignore if clear() fails for any reason
                await human_type(self.page, el, value)
                logger.info("Filled '%s' = '%s'", label, value)
                return True
        logger.warning("Field not found for labels: %s", labels)
        return False

    async def _fill_affiliation_autocomplete(self, value: str) -> bool:
        """Fill the affiliation field using manual typing to trigger autocomplete.

        Flow:
          1. Type affiliation name → autocomplete dropdown appears
          2. If match found → click it
          3. If no match → scroll dropdown → click 'Add manually'
          4. After 'Add manually': select country → click 'Add' button
        """
        assert self.page is not None
        # Try the known SNAPP ID first, then label-based fallbacks
        loc = self.page.locator("#addEditorAffiliation")
        if await loc.count() == 0:
            loc = self.page.locator("#editEditorAffiliation")
        if await loc.count() == 0:
            labels = ["Add an affiliated institution", "Affiliation", "Institution",
                      "affiliated institution"]
            for label in labels:
                loc = (
                    self.page.get_by_label(label)
                    .or_(self.page.get_by_placeholder(label))
                    .or_(self.page.get_by_placeholder("Start typing to see suggestions"))
                )
                if await loc.count() > 0:
                    break
            else:
                logger.warning("Affiliation field not found")
                return False

        # Scroll into view (may be below modal fold)
        await loc.first.evaluate("el => el.scrollIntoView({block: 'center'})")
        await loc.first.click()
        await loc.first.clear()
        await human_delay(0.1, 0.2)

        # Type character by character to trigger SNAPP autocomplete JS
        await loc.first.press_sequentially(value, delay=30)
        logger.info("Typed affiliation: '%s'", value)

        # Wait for suggestions to appear
        await human_delay(1.5, 2.5)

        # Try to click a matching suggestion from the dropdown
        suggestion = (
            self.page.get_by_role("option", name=value)
            .or_(self.page.locator("li, .autocomplete-suggestion, [class*='suggestion']").filter(has_text=value))
        )
        if await suggestion.count() > 0:
            try:
                await suggestion.first.click()
                logger.info("Selected affiliation from suggestions: '%s'", value)
                return True
            except Exception:
                logger.warning("Could not click suggestion — will try 'Add manually'")

        # No exact match — scroll dropdown and click "Add manually"
        logger.info("Affiliation not in suggestions — looking for 'Add manually'")

        # Scroll the dropdown container to reveal "Add manually" at the bottom
        dropdown = (
            self.page.locator("[class*='autocomplete'], [class*='dropdown'], [class*='suggestion']")
            .or_(self.page.locator("[data-component-institution-autocomplete]")
            .or_(self.page.locator(".c-institution")))
        )
        if await dropdown.count() > 0:
            try:
                await dropdown.first.evaluate("el => el.scrollTo(0, el.scrollHeight)")
                await human_delay(0.3, 0.5)
            except Exception:
                pass

        # Click "Add manually"
        add_manually = (
            self.page.get_by_text("Add manually", exact=False)
            .or_(self.page.get_by_role("button", name="Add manually"))
            .or_(self.page.get_by_role("link", name="Add manually"))
            .or_(self.page.locator("[class*='add-manual'], [data-component*='manual']"))
        )
        if await add_manually.count() > 0:
            try:
                await add_manually.first.scroll_into_view_if_needed()
                await human_delay(0.2, 0.3)
                await human_click(add_manually.first)
                logger.info("Clicked 'Add manually'")
                await human_delay(0.5, 1.0)

                # After clicking "Add manually", a form appears:
                # The affiliation name should already be filled from typing.
                # We need to: 1) Select country  2) Click "Add" button

                # Select country from the dropdown in the manual-add form
                country = self.request.get("_country", "").strip()
                if country:
                    country_select = (
                        self.page.locator("#addEditorInstitutionCountry")
                        .or_(self.page.locator("#editEditorInstitutionCountry"))
                        .or_(self.page.locator("select[name='institutionCountry']")
                        .or_(self.page.get_by_label("Country")))
                    )
                    if await country_select.count() > 0:
                        try:
                            await country_select.first.select_option(label=country)
                            logger.info("Selected country in manual affiliation: '%s'", country)
                        except Exception:
                            # JS fallback for hidden selects
                            await country_select.first.evaluate(
                                """(el, label) => {
                                    for (const opt of el.options) {
                                        if (opt.textContent.trim().includes(label)) {
                                            el.value = opt.value;
                                            el.dispatchEvent(new Event('change', {bubbles: true}));
                                            break;
                                        }
                                    }
                                }""", country
                            )
                            logger.info("Selected country via JS: '%s'", country)

                # Click the "Add" button to confirm the affiliation
                add_btn = (
                    self.page.get_by_role("button", name="Add")
                    .or_(self.page.locator("button[data-component-institution-add]")
                    .or_(self.page.locator(".c-institution button")))
                )
                if await add_btn.count() > 0:
                    await human_click(add_btn.first)
                    logger.info("Clicked 'Add' to confirm affiliation: '%s'", value)
                    await human_delay(0.5, 1.0)
                else:
                    logger.warning("'Add' button not found after 'Add manually'")

                return True
            except Exception as exc:
                logger.warning("Error in 'Add manually' flow: %s", exc)

        logger.info("No suggestion match and no 'Add manually' — typed value stays: '%s'", value)
        return True

    async def _select_role_radio(self, role: str) -> bool:
        """Select a role radio button using actual SNAPP HTML element IDs."""
        assert self.page is not None
        # Map role text to actual HTML radio button IDs from the SNAPP form
        role_id_map = {
            "lead editor": "leadEditorRole",
            "deciding editor": "decidingEditorRole",
            "recommending & request revision editor": "recommendingAndRequestRevisionEditorRole",
            "recommending editor & request revision editor": "recommendingAndRequestRevisionEditorRole",
            "recommending only editor": "recommendingOnlyEditorRole",
            "recommending only": "recommendingOnlyEditorRole",
            "assigning editor": "assigningEditorRole",
        }
        role_lower = role.lower().strip()
        radio_id = role_id_map.get(role_lower)
        try:
            if radio_id:
                radio = self.page.locator(f"#{radio_id}")
                if await radio.count() > 0:
                    # Scroll the modal container and use JS click (element is below fold)
                    await radio.evaluate("el => { el.scrollIntoView({block: 'center'}); el.click(); }")
                    logger.info("Selected role by ID (JS click): #%s", radio_id)
                    return True
            # Fallback: try by label/text
            radio = (
                self.page.get_by_role("radio", name=role)
                .or_(self.page.get_by_label(role))
            )
            if await radio.count() > 0:
                await radio.first.click(force=True)
                logger.info("Selected role: '%s'", role)
                return True
            logger.warning("Role radio '%s' not found (tried ID: %s)", role, radio_id)
            return False
        except Exception as exc:
            logger.error("Error selecting role: %s", exc, exc_info=True)
            return False

    async def _fill_board_sections(self, sections_csv: str) -> None:
        """Handle the Board section dropdown (select for each comma-separated value)."""
        assert self.page is not None
        sections = [s.strip() for s in sections_csv.split(",") if s.strip()]
        if not sections:
            return
        logger.info("Filling board sections: %s", sections)
        board_box = (
            self.page.get_by_label("Board section")
            .or_(self.page.get_by_text("Please select section"))
            .or_(self.page.get_by_role("combobox", name="Board section"))
        )
        if await board_box.count() == 0:
            logger.warning("Board section field not found — skipping")
            return
        for section in sections:
            await human_click(board_box.first)
            await human_delay(0.5, 1.0)
            option = (
                self.page.get_by_role("option", name=section)
                .or_(self.page.get_by_text(section, exact=False))
            )
            if await option.count() > 0:
                await human_click(option.first)
                logger.info("  Selected section: '%s'", section)
            else:
                logger.warning("  Section '%s' not found in dropdown", section)
            await human_delay(0.5, 1.0)

    # ── Keyword / Tag management ──────────────────────────────────────────

    async def add_keywords(self, keywords_csv: str) -> None:
        """Add keywords/tags to the editor's profile one by one."""
        assert self.page is not None
        keywords = [k.strip() for k in keywords_csv.split(",") if k.strip()]
        if not keywords:
            return
        logger.info("Adding keywords: %s", keywords)
        for keyword in keywords:
            added = await self._add_single_keyword(keyword)
            if not added:
                logger.info("Keyword '%s' not in suggestions — creating on internal URL", keyword)
                await self.create_keyword_on_internal(keyword)
                # Retry after creation
                await self._add_single_keyword(keyword)

    async def _add_single_keyword(self, keyword: str) -> bool:
        """Type a keyword in the Tags input and select from suggestions."""
        assert self.page is not None
        try:
            # Use the visible keyword input, NOT the hidden input[name='keywords']
            tag_input = (
                self.page.locator("#addEditorKeywords")
                .or_(self.page.locator("#keywords-autocomplete-holder input[type='text']"))
                .or_(self.page.locator(".tagify__input"))
                .or_(self.page.get_by_placeholder("Add a tag"))
                .or_(self.page.get_by_label("Tags"))
            )
            if await tag_input.count() == 0:
                logger.warning("Tags input not found on page")
                return False

            # Scroll into view and click via JS (element may be below modal fold)
            await tag_input.first.evaluate("el => { el.scrollIntoView({block: 'center'}); el.focus(); el.click(); }")
            await human_delay(0.2, 0.4)
            # Type the keyword
            for ch in keyword:
                await self.page.keyboard.type(ch, delay=random.randint(30, 80))
            await human_delay(1.0, 1.5)

            # Look for a suggestion matching this keyword
            suggestion = (
                self.page.get_by_role("option", name=keyword)
                .or_(self.page.get_by_text(keyword, exact=True))
            )
            if await suggestion.count() > 0:
                await human_click(suggestion.first)
                logger.info("  Added keyword: '%s'", keyword)
                await human_delay(0.5, 1.0)
                return True

            # Clear the typed text if not found
            await self.page.keyboard.press("Control+a")
            await self.page.keyboard.press("Backspace")
            return False

        except Exception as exc:
            logger.error("Error adding keyword '%s': %s", keyword, exc, exc_info=True)
            return False

    async def create_keyword_on_internal(self, keyword: str) -> bool:
        """Navigate to the internal keywords page, create a keyword, then return."""
        assert self.page is not None and self.context is not None
        logger.info("Creating keyword '%s' on internal URL", keyword)
        try:
            # Open in a new tab
            new_page = await self.context.new_page()
            await new_page.goto(INTERNAL_KEYWORDS_URL, wait_until="domcontentloaded", timeout=30_000)
            await human_delay(2, 4)

            # Find the keyword input and add button
            kw_input = (
                new_page.get_by_placeholder("Enter keyword")
                .or_(new_page.get_by_label("Keyword"))
                .or_(new_page.get_by_placeholder("keyword"))
                .or_(new_page.get_by_role("textbox").first)
            )
            if await kw_input.count() > 0:
                await human_type(new_page, kw_input.first, keyword)
                await human_delay(1, 2)
                add_btn = (
                    new_page.get_by_role("button", name="Add")
                    .or_(new_page.get_by_role("button", name="Create"))
                    .or_(new_page.get_by_role("button", name="Save"))
                    .or_(new_page.get_by_role("button", name="Submit"))
                )
                if await add_btn.count() > 0:
                    await human_click(add_btn.first)
                    await human_delay(2, 3)
                    logger.info("Keyword '%s' created on internal URL", keyword)
                else:
                    logger.warning("Add/Create button not found on internal keywords page")
            else:
                logger.warning("Keyword input not found on internal keywords page")

            await new_page.close()
            # Bring focus back to the main page
            if self.page:
                await self.page.bring_to_front()
                await human_delay(1, 2)
            return True

        except Exception as exc:
            logger.error("Error creating keyword on internal URL: %s", exc, exc_info=True)
            return False

    # ── Future onboarding unavailability (inline, during onboard form) ────

    async def _fill_onboarding_unavailability(self) -> None:
        """If the onboarding date is in the future, fill unavailability on the current form.

        Called during onboarding (Step 2 of the form) BEFORE clicking Save.
        Sets temporary unavailability: From = today, To = onboarding_date - 1 day.

        If onboarding date is today, in the past, or missing — this is a no-op.
        Wrapped in try/except so it never breaks the onboarding.
        """
        onboarding_date_str = self.request.get("_onboarding_date", "").strip()
        if not onboarding_date_str:
            return

        try:
            from datetime import date, timedelta

            onboarding_date_normalized = self._normalize_date(onboarding_date_str)
            onboarding_date = date.fromisoformat(onboarding_date_normalized)
            today = date.today()

            if onboarding_date <= today:
                logger.info(
                    "[ONBOARD-UNAVAIL] Onboarding date %s is today or past — "
                    "no unavailability needed",
                    onboarding_date,
                )
                return

            unavail_from = today.isoformat()
            unavail_to = (onboarding_date - timedelta(days=1)).isoformat()

            logger.info(
                "[ONBOARD-UNAVAIL] Onboarding date is %s (future). "
                "Setting unavailability on form: %s to %s",
                onboarding_date, unavail_from, unavail_to,
            )

            # The unavailability dates are on the NEXT wizard step (Step 3).
            # Click Next to advance to the step with date fields.
            logger.info("[ONBOARD-UNAVAIL] Clicking Next to reach unavailability step")
            if await self._click_next():
                await self.set_unavailability(unavail_from, unavail_to)
            else:
                logger.warning("[ONBOARD-UNAVAIL] No Next button — trying to set dates on current page")
                await self.set_unavailability(unavail_from, unavail_to)

        except Exception as exc:
            logger.warning(
                "[ONBOARD-UNAVAIL] Could not set unavailability: %s", exc,
            )

    # ── Status change (offboard) ──────────────────────────────────────────

    async def _select_status_radio(self, status: str) -> bool:
        """Select a status radio button (Active, Resigned but handling papers, Retired, Deactivated)."""
        assert self.page is not None
        status_map = {
            "active": "Active",
            "resigned_handling": "Resigned but handling papers",
            "resigned but handling papers": "Resigned but handling papers",
            "retired": "Retired",
            "deactivated": "Deactivated",
            "inactive": "Deactivated",
        }
        display_status = status_map.get(status.lower().strip(), status)
        try:
            radio = (
                self.page.get_by_role("radio", name=display_status)
                .or_(self.page.get_by_label(display_status))
                .or_(self.page.get_by_text(display_status, exact=True))
            )
            if await radio.count() > 0:
                await human_click(radio.first)
                logger.info("Selected status: '%s'", display_status)
                return True
            logger.warning("Status radio '%s' not found", display_status)
            return False
        except Exception as exc:
            logger.error("Error selecting status: %s", exc, exc_info=True)
            return False

    # ── Unavailability dates ──────────────────────────────────────────────

    async def set_unavailability(self, from_date: str, to_date: str) -> bool:
        """Fill the temporary unavailability From/To date pickers.

        Handles BOTH form contexts:
          - Edit profile: id="editEditorUnavailableFrom" / "editEditorUnavailableTo"
          - Add (onboard): id="addEditorUnavailableFrom" / "addEditorUnavailableTo"

        For type="date" inputs, .fill() expects YYYY-MM-DD format.
        Falls back to JavaScript if the element is not visible.
        """
        assert self.page is not None
        logger.info("Setting unavailability: %s to %s", from_date, to_date)
        try:
            from_val = self._normalize_date(from_date)
            to_val = self._normalize_date(to_date)

            # Try all known IDs (edit form + add form) plus name fallback
            from_input = (
                self.page.locator("#editEditorUnavailableFrom")
                .or_(self.page.locator("#addEditorUnavailableFrom"))
                .or_(self.page.locator("input[name='unavailableFrom']"))
            )
            to_input = (
                self.page.locator("#editEditorUnavailableTo")
                .or_(self.page.locator("#addEditorUnavailableTo"))
                .or_(self.page.locator("input[name='unavailableTo']"))
            )

            if await from_input.count() == 0 or await to_input.count() == 0:
                logger.warning("Date picker fields not found")
                await self._dump_page("no_date_pickers")
                return False

            # Check if the element is visible
            is_visible = await from_input.first.is_visible()

            if is_visible:
                # Standard approach: click + fill
                await from_input.first.evaluate("el => el.scrollIntoView({block: 'center'})")
                await human_delay(0.3, 0.5)

                await from_input.first.click()
                await human_delay(0.3, 0.5)
                await from_input.first.fill(from_val)
                logger.info("Filled 'From' date: %s", from_val)
                await human_delay(0.5, 1.0)

                await to_input.first.click()
                await human_delay(0.3, 0.5)
                await to_input.first.fill(to_val)
                logger.info("Filled 'To' date: %s", to_val)
                await human_delay(0.5, 1.0)
            else:
                # Element exists but is hidden — use JS directly
                logger.info("Date fields not visible — setting values via JS")

            # Verify/force values via JS (works for both visible and hidden)
            actual_from = await from_input.first.evaluate("el => el.value")
            actual_to = await to_input.first.evaluate("el => el.value")
            if actual_from != from_val or actual_to != to_val:
                await from_input.first.evaluate(
                    f"el => {{ el.value = '{from_val}'; el.dispatchEvent(new Event('change', {{bubbles: true}})); }}"
                )
                await to_input.first.evaluate(
                    f"el => {{ el.value = '{to_val}'; el.dispatchEvent(new Event('change', {{bubbles: true}})); }}"
                )
                logger.info("Set dates via JS: %s to %s", from_val, to_val)

            logger.info("Unavailability dates filled successfully")
            return True

        except Exception as exc:
            logger.error("Error setting unavailability: %s", exc, exc_info=True)
            await self._dump_page("unavailability_error")
            return False

    @staticmethod
    def _normalize_date(date_str: str) -> str:
        """Normalize a date string to YYYY-MM-DD format for HTML date inputs."""
        date_str = date_str.strip()
        if not date_str:
            return ""
        # Already in YYYY-MM-DD format
        if len(date_str) == 10 and date_str[4] == "-" and date_str[7] == "-":
            return date_str
        # Try common formats
        from datetime import datetime
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        logger.warning("Could not parse date '%s' — using as-is", date_str)
        return date_str

    # ── Click Next (for multi-step forms) ─────────────────────────────────

    async def _click_next(self) -> bool:
        assert self.page is not None
        next_btn = (
            self.page.get_by_role("button", name="Next")
            .or_(self.page.get_by_role("button", name="Continue"))
        )
        if await next_btn.count() > 0:
            await human_click(next_btn.first)
            await human_delay(2, 4)
            logger.info("Clicked Next")
            return True
        logger.warning("Next button not found")
        return False

    # ── Save & verify ─────────────────────────────────────────────────────

    async def _click_save(self, button_names: list[str] | None = None) -> bool:
        assert self.page is not None

        # ── No-save preview mode ──────────────────────────────────────
        if self.no_save:
            logger.info("NO-SAVE mode — skipping save. Review the form in the browser.")
            print("\n" + "=" * 60)
            print("  NO-SAVE MODE: All fields have been filled.")
            print("  Review the form in the browser window.")
            print("  Press Enter here when you are done reviewing...")
            print("=" * 60 + "\n")
            await asyncio.get_event_loop().run_in_executor(None, input)
            await self._screenshot("no_save_preview")
            return True

        if button_names is None:
            button_names = ["Save", "Save changes", "Submit", "Update", "Confirm",
                            "Save and invite editor"]
        for name in button_names:
            save = self.page.get_by_role("button", name=name)
            if await save.count() > 0:
                # Scroll into view (may be below modal fold)
                await save.first.evaluate("el => el.scrollIntoView({block: 'center'})")
                await human_click(save.first)
                logger.info("Clicked '%s'", name)
                await human_delay(2, 4)
                return await self._verify_save()
        logger.error("Save button not found (tried: %s)", button_names)
        await self._dump_page("no_save_button")
        return False

    async def _verify_save(self) -> bool:
        assert self.page is not None
        success_phrases = [
            "Saved Successfully", "Successfully", "Success",
            "Changes saved", "Updated successfully", "saved",
            "Editor added", "has been added", "created successfully",
            "invited successfully",
        ]
        # Build a single combined locator for ALL success phrases (fast check)
        combined = self.page.get_by_text(success_phrases[0])
        for phrase in success_phrases[1:]:
            combined = combined.or_(self.page.get_by_text(phrase))

        try:
            await combined.first.wait_for(timeout=5_000, state="visible")
            logger.info("Verified save — success message detected")
            return True
        except PlaywrightTimeout:
            pass

        # Quick error check (no long waits)
        for err in ("Error", "Failed", "Could not save", "Validation error"):
            if await self.page.get_by_text(err).count() > 0:
                logger.error("Save FAILED — error message on page")
                await self._dump_page("save_failed")
                return False

        logger.info("Save completed (no explicit toast)")
        return True

    # ── Profile update (existing editor) ──────────────────────────────────

    async def update_profile(self) -> bool:
        """
        Update an existing editor's profile. Clicks 'Edit profile' first,
        then handles page 1 (affiliation) and page 2 (role, sections, tags,
        unavailability, status). Respects idempotency and name/email restrictions.
        """
        assert self.page is not None
        req = self.request

        # Check for name/email change requests — these CANNOT be done
        for blocked_field in ("first_name", "last_name"):
            if req.get(blocked_field, "").strip():
                logger.warning(
                    "CANNOT change %s — name changes must be done by the editor.",
                    blocked_field
                )
                print("\n" + "=" * 60)
                print("  NOTICE: Name/email changes cannot be done by the team.")
                print("  Send the following email to the editor:")
                print(NAME_EMAIL_CHANGE_TEMPLATE)
                print("=" * 60 + "\n")

        # Click "Edit profile" on the editor card
        if not await self.click_edit_profile():
            return False

        updated_any = False

        # ── Page 1: Affiliation (autocomplete) ────────────────────────
        affiliation = req.get("affiliation", "").strip()
        if affiliation:
            # Idempotency check
            aff_loc = (
                self.page.get_by_label("Add an affiliated institution")
                .or_(self.page.get_by_placeholder("Start typing to see suggestions"))
                .or_(self.page.get_by_label("Affiliation"))
            )
            current_aff = ""
            if await aff_loc.count() > 0:
                try:
                    current_aff = await aff_loc.first.input_value()
                except Exception:
                    current_aff = ""
            if current_aff.strip().lower() != affiliation.strip().lower():
                if await self._fill_affiliation_autocomplete(affiliation):
                    updated_any = True
            else:
                logger.info("Affiliation already correct — skipping")

        # Click Next to go to page 2 (journal-specific information)
        await self._click_next()

        # ── Page 2: Role (radio buttons) ──────────────────────────────
        role = req.get("role", "").strip()
        if role:
            if await self._select_role_radio(role):
                updated_any = True

        # ── Page 2: Board sections ────────────────────────────────────
        sections = req.get("sections", "").strip()
        if sections:
            await self._fill_board_sections(sections)
            updated_any = True

        # ── Page 2: Keywords / Tags ───────────────────────────────────
        keywords = req.get("keywords", "").strip()
        if keywords:
            await self.add_keywords(keywords)
            updated_any = True

        # ── Page 2: Unavailability dates ──────────────────────────────
        uf = req.get("unavailable_from", "").strip()
        ut = req.get("unavailable_to", "").strip()
        if uf and ut:
            if await self.set_unavailability(uf, ut):
                updated_any = True

        # ── Page 2: Status change ─────────────────────────────────────
        status = req.get("status", "").strip()
        if status:
            if await self._select_status_radio(status):
                updated_any = True

        if updated_any:
            return await self._click_save()
        else:
            logger.info("No Action Needed — all fields already correct")
            return True

    # ── Onboarding (new editor) ───────────────────────────────────────────

    async def onboard_editor(self) -> bool:
        """Onboard a new regular editor via 'Add new Editor'."""
        assert self.page is not None
        req = self.request
        collection = req.get("collection_name", "").strip() or req.get("collection_id", "").strip()

        if collection:
            return await self._onboard_guest_editor(collection)

        try:
            logger.info("Onboarding new editor (regular)")
            # The "Add new Editor" is an <a> link with id="add_new_btn"
            btn = (
                self.page.locator("#add_new_btn")
                .or_(self.page.get_by_role("link", name="Add new Editor"))
                .or_(self.page.get_by_text("Add new Editor", exact=True))
            )
            if await btn.count() == 0:
                logger.error("'Add new Editor' button not found")
                await self._dump_page("no_add_editor_btn")
                return False

            await human_click(btn.first)
            # Wait for the Add Editor page/modal to load
            try:
                await self.page.wait_for_load_state("domcontentloaded", timeout=15_000)
            except Exception:
                pass
            await human_delay(3, 5)

            # Diagnostic dump — capture the Add Editor form HTML
            await self._dump_page("add_editor_form")
            logger.info("Add Editor form loaded — URL: %s", self.page.url)

            # ── Step 1: Personal information ──────────────────────────
            email = req.get("email", "").strip()
            if email:
                filled = await self._fill_field_by_labels(
                    ["Primary email address", "Email", "Email address"], email
                )
                if not filled:
                    logger.warning("Could not fill email field — dumping page")
                    await self._dump_page("onboard_email_field_not_found")

            # Name fields
            fname = req.get("first_name", "").strip()
            lname = req.get("last_name", "").strip()
            if not fname and not lname:
                fname, lname = parse_editor_name(req.get("editor_name", ""))

            if fname:
                filled = await self._fill_field_by_labels(["Given name", "First name"], fname)
                if not filled:
                    logger.warning("Could not fill first name field")
            if lname:
                filled = await self._fill_field_by_labels(["Family name", "Last name", "Surname"], lname)
                if not filled:
                    logger.warning("Could not fill last name field")

            # Affiliation
            affiliation = req.get("affiliation", "").strip()
            if affiliation:
                # Try multiple common labels since exact label is unknown
                filled = await self._fill_field_by_labels(
                    ["Affiliation", "Institution", "Organization", "Search affiliations", "University"], 
                    affiliation
                )
                if not filled:
                    # Fallback to autocomplete logic if a specific search field is found
                    filled = await self._fill_affiliation_autocomplete(affiliation)
                if not filled:
                    logger.warning("Affiliation field not found — continuing without it")

            # Click Next to step 2
            if not await self._click_next():
                logger.warning("'Next' button not found — trying to continue anyway")
                await self._dump_page("onboard_no_next_btn")

            # ── Step 2: Journal-specific information ──────────────────
            role = req.get("role", "").strip()
            if role:
                await self._select_role_radio(role)

            sections = req.get("sections", "").strip()
            if sections:
                await self._fill_board_sections(sections)

            keywords = req.get("keywords", "").strip()
            if keywords:
                await self.add_keywords(keywords)

            # Set unavailability if onboarding date is in the future
            await self._fill_onboarding_unavailability()

            return await self._click_save(["Save and invite editor", "Save", "Submit"])

        except Exception as exc:
            logger.error("Onboard error: %s", exc, exc_info=True)
            await self._dump_page("onboard_error")
            return False

    async def _onboard_guest_editor(self, collection: str) -> bool:
        """Onboard a guest editor via 'Add Guest Editor' (2-step wizard).

        Step 1 of 2 — Editor personal information:
        Email -> Title -> Given Name -> Family Name -> Affiliation -> [Next]

        Step 2 of 2 — Journal-specific information:
        Country -> Collection (#addEditorCollection <select>) -> Role (radio) ->
        Keywords -> Unavailability (if future onboarding date) -> [Save]
        """
        assert self.page is not None
        req = self.request

        try:
            logger.info("Onboarding guest editor (collection: '%s')", collection)
            btn = (
                self.page.locator("#add_new_guest_btn")
                .or_(self.page.get_by_role("link", name="Add Guest Editor"))
                .or_(self.page.get_by_text("Add Guest Editor"))
            )
            if await btn.count() == 0:
                logger.error("'Add Guest Editor' button not found")
                await self._dump_page("no_add_guest_btn")
                return False

            logger.info("Clicking 'Add Guest Editor' button (opens modal)")
            await human_click(btn.first)

            # Wait for modal form
            try:
                await self.page.locator("#addEditorPrimaryEmail").wait_for(
                    state="visible", timeout=15_000
                )
                logger.info("Guest Editor modal loaded")
            except Exception:
                logger.warning("Email field not visible after 15s")

            await self._dump_page("guest_editor_form")

            # ── Step 1: Editor personal information ───────────────────

            # 1. Email (REQUIRED field on SNAPP form)
            email = req.get("email", "").strip()
            if email:
                await self._fill_by_id("addEditorPrimaryEmail", email)
                logger.info("Filled email: '%s'", email)
            else:
                logger.warning(
                    "⚠ EMAIL IS MISSING in Smartsheet for ticket %s / %s! "
                    "'Primary email address' is REQUIRED on SNAPP. Form cannot be saved without it.",
                    req.get("_ticket_id", "?"), req.get("editor_name", "?")
                )

            # 2. Given Name & Family Name (using exact SNAPP IDs)
            fname = req.get("first_name", "").strip()
            lname = req.get("last_name", "").strip()
            if not fname and not lname:
                fname, lname = parse_editor_name(req.get("editor_name", ""))
            if fname:
                await self._fill_by_id("addEditorGivenName", fname)
            if lname:
                await self._fill_by_id("addEditorFamilyName", lname)

            # 3. Affiliation
            affiliation = req.get("affiliation", "").strip()
            if affiliation:
                await self._fill_affiliation_autocomplete(affiliation)

            # ── Click Next to advance to Step 2 ──────────────────────
            logger.info("Clicking 'Next' to advance to Step 2 of 2")
            if not await self._click_next():
                logger.warning("'Next' button not found on guest editor form — trying to continue")
                await self._dump_page("guest_onboard_no_next_btn")

            # ── Step 2: Journal-specific information ──────────────────

            # 4. Country (native <select> #addEditorInstitutionCountry)
            country = req.get("_country", "").strip()
            if country:
                await self._select_country_dropdown(country)

            # 5. Collection (native <select> #addEditorCollection)
            logger.info("Selecting collection from #addEditorCollection")
            collection_select = self.page.locator("#addEditorCollection")
            collection_id = req.get("collection_id", "").strip()
            if await collection_select.count() > 0:
                try:
                    await collection_select.evaluate("el => el.scrollIntoView({block: 'center'})")
                    if collection_id:
                        await collection_select.select_option(value=collection_id)
                        logger.info("Selected collection by value: '%s'", collection_id)
                    else:
                        await collection_select.select_option(label=collection)
                        logger.info("Selected collection by label: '%s'", collection)
                except Exception as exc:
                    logger.warning("select_option failed -- using JS: %s", exc)
                    try:
                        if collection_id:
                            await collection_select.evaluate(
                                f"el => {{ el.value = '{collection_id}'; el.dispatchEvent(new Event('change', {{bubbles: true}})); }}"
                            )
                        else:
                            await collection_select.evaluate(
                                """(el, label) => {
                                    for (const opt of el.options) {
                                        if (opt.textContent.includes(label)) {
                                            el.value = opt.value;
                                            el.dispatchEvent(new Event('change', {bubbles: true}));
                                            break;
                                        }
                                    }
                                }""", collection
                            )
                        logger.info("Selected collection via JS: '%s'", collection_id or collection)
                    except Exception as js_exc:
                        logger.error("JS fallback for collection also failed: %s", js_exc)

            # 6. Role
            role = req.get("role", "").strip()
            if role:
                await self._select_role_radio(role)

            # 7. Keywords
            keywords = req.get("keywords", "").strip()
            if keywords:
                await self.add_keywords(keywords)

            # 8. Unavailability (if onboarding date is in the future)
            await self._fill_onboarding_unavailability()

            # 9. Save
            return await self._click_save(["Save and invite editor", "Save", "Submit"])

        except Exception as exc:
            logger.error("Guest editor onboard error: %s", exc, exc_info=True)
            await self._dump_page("guest_onboard_error")
            return False

    # ── Offboarding ───────────────────────────────────────────────────────

    async def offboard_editor(self) -> bool:
        """
        Offboard an editor by changing their status.
        Opens Edit profile -> navigates to page 2 -> selects the status radio.
        """
        assert self.page is not None
        status = self.request.get("status", "deactivated").strip()

        try:
            if not await self.click_edit_profile():
                return False

            # Navigate to page 2
            await self._click_next()

            # Select the status
            if not await self._select_status_radio(status):
                logger.error("Could not set status to '%s'", status)
                await self._dump_page("offboard_status_error")
                return False

            return await self._click_save()

        except Exception as exc:
            logger.error("Offboard error: %s", exc, exc_info=True)
            await self._dump_page("offboard_error")
            return False

    # ── Orchestrator ──────────────────────────────────────────────────────

    async def run(self) -> dict[str, Any]:
        """
        Full workflow:
          1. Login (or skip with Chrome profile)
          2. Navigate to journal
          3. Branch on action: update | onboard | offboard | set_unavailability
          4. Verify & screenshot

        Wrapped in a timeout of RUN_TIMEOUT_SECONDS (default 10 min).
        """
        result: dict[str, Any] = {
            "request": self.request,
            "started_at": self._ts(),
            "status": "unknown",
        }
        if self.dry_run:
            return self._dry_run_report()

        try:
            await asyncio.wait_for(
                self._run_workflow(result),
                timeout=RUN_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            result["status"] = "timeout"
            result["error"] = f"Run exceeded {RUN_TIMEOUT_SECONDS}s timeout"
            logger.critical("Run timed out after %ds", RUN_TIMEOUT_SECONDS)
            if self.page:
                await self._dump_page("timeout")
                await self._screenshot("timeout")
        except Exception as exc:
            result["status"] = "error"
            result["error"] = str(exc)
            logger.critical("Unhandled error: %s", exc, exc_info=True)
            if self.page:
                await self._dump_page("critical_error")
                await self._screenshot("critical_error")
        finally:
            await self._close_browser()

        return result

    async def _run_workflow(self, result: dict[str, Any]) -> None:
        """Inner workflow — called by run() with timeout wrapper."""
        await self._launch_browser()

        logger.info("=== STEP 1: Login ===")
        await self.login()

        logger.info("=== STEP 2: Navigate to journal ===")
        journal = self.request.get("journal_name", "").strip()
        if not journal:
            raise ValueError("journal_name is required in the request")
        if not await self.navigate_to_journal(journal):
            result["status"] = "journal_not_found"
            return

        action = self.request.get("action", "").strip().lower()
        logger.info("=== STEP 3: Execute action '%s' ===", action)

        if action == "onboard":
            success = await self.onboard_editor()

        elif action == "update":
            if not await self.search_editor(self.request["editor_name"]):
                result["status"] = "editor_not_found"
                return
            success = await self.update_profile()

        elif action == "offboard":
            if not await self.search_editor(self.request["editor_name"]):
                result["status"] = "editor_not_found"
                return
            success = await self.offboard_editor()

        elif action == "set_unavailability":
            if not await self.search_editor(self.request["editor_name"]):
                result["status"] = "editor_not_found"
                return
            if not await self.click_edit_profile():
                result["status"] = "edit_profile_failed"
                return
            await self._click_next()
            uf = self.request.get("unavailable_from", "").strip()
            ut = self.request.get("unavailable_to", "").strip()
            if uf and ut:
                success = await self.set_unavailability(uf, ut)
                if success:
                    success = await self._click_save()
            else:
                logger.error("unavailable_from and unavailable_to required")
                success = False

        else:
            logger.error("Unknown action: '%s'", action)
            result["status"] = "unknown_action"
            return

        result["status"] = "success" if success else "action_failed"
        result["completed_at"] = self._ts()
        logger.info("=== DONE ===  status=%s", result["status"])

    # ── Dry-run ───────────────────────────────────────────────────────────

    def _dry_run_report(self) -> dict[str, Any]:
        action = self.request.get("action", "?")
        editor = self.request.get("editor_name", "?")
        journal = self.request.get("journal_name", "?")
        collection = self.request.get("collection_name", "") or self.request.get("collection_id", "")
        keywords = self.request.get("keywords", "")
        sections = self.request.get("sections", "")
        status = self.request.get("status", "")
        uf = self.request.get("unavailable_from", "")
        ut = self.request.get("unavailable_to", "")

        steps: list[str] = [
            f"1. Launch stealth browser -> {self.base_url}",
            f"2. Authenticate as '{self.username}'",
            f"3. Search journal: '{journal}'",
        ]

        if action == "onboard":
            if collection:
                steps.append(f"4. Click 'Add Guest Editor' (collection: '{collection}')")
            else:
                steps.append("4. Click 'Add new Editor'")
            steps.append(f"5. Fill: name='{editor}', email, affiliation, role")
            if keywords:
                steps.append(f"6. Add keywords: {keywords}")
            if sections:
                steps.append(f"7. Select board sections: {sections}")
            steps.append("8. Click Save & verify")

        elif action == "update":
            steps.append(f"4. Search editor: '{editor}' (variants: {self._name_variants(editor)})")
            steps.append("5. Click 'Edit profile'")
            steps.append("6. Idempotency check & update fields")
            if keywords:
                steps.append(f"7. Add keywords: {keywords}")
            if sections:
                steps.append(f"8. Select board sections: {sections}")
            if status:
                steps.append(f"9. Set status: {status}")
            steps.append("10. Click Save & verify")

        elif action == "offboard":
            steps.append(f"4. Search editor: '{editor}'")
            steps.append("5. Click 'Edit profile'")
            steps.append(f"6. Set status: '{status or 'deactivated'}'")
            steps.append("7. Click Save & verify")

        elif action == "set_unavailability":
            steps.append(f"4. Search editor: '{editor}'")
            steps.append("5. Click 'Edit profile'")
            steps.append(f"6. Set unavailability: {uf} to {ut}")
            steps.append("7. Click Save & verify")

        else:
            steps.append(f"4. Unknown action '{action}'")

        print("\n" + "=" * 60)
        print("  DRY-RUN REPORT  (no browser launched)")
        print("=" * 60)
        for s in steps:
            print(f"  {s}")
        print("=" * 60 + "\n")

        logger.info("Dry-run complete")
        return {"request": self.request, "status": "dry_run", "plan": steps}


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────
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
        help="Use a hardcoded mock request instead of Smartsheet API",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Fill all fields but do NOT click Save (preview mode)",
    )
    args = parser.parse_args()

    # ── Fetch requests ────────────────────────────────────────────────
    if args.mock:
        # Fallback mock request for testing without Smartsheet
        requests_queue = [{
            "editor_name": "Professor Kazuhiko Yamamoto",
            "action": "update",
            "journal_name": "Seminars in Immunopathology",
            "affiliation": "RIKEN Center for Integrative Medical Sciences",
            "email": "kazuhiko.yamamoto@riken.jp",
            "role": "Recommending & Request Revision Editor",
            "keywords": "",
            "collection_name": "",
            "collection_id": "",
            "sections": "",
            "status": "",
            "unavailable_from": "",
            "unavailable_to": "",
            "first_name": "",
            "last_name": "",
        }]
        logger.info("Using MOCK request (--mock flag)")
    else:
        # Live Smartsheet integration
        reader = SmartsheetReader()
        requests_queue = reader.fetch_pending_requests()
        if not requests_queue:
            logger.info("No pending requests in Smartsheet — nothing to do.")
            print("\n  No pending requests found in Smartsheet. Exiting.\n")
            return

    # ── Process each request ──────────────────────────────────────────
    all_results: list[dict[str, Any]] = []
    for i, request in enumerate(requests_queue, 1):
        logger.info("═" * 60)
        logger.info("Processing request %d of %d", i, len(requests_queue))
        logger.info("═" * 60)

        agent = SnappAgent(request, dry_run=args.dry_run, no_save=args.no_save)
        result = await agent.run()
        all_results.append(result)

        # Write individual run summary
        summary_path = LOG_DIR / f"run_summary_{agent._ts()}.json"
        summary_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        logger.info("Run summary -> %s", summary_path)

        # Mark row as done in Smartsheet (if not mock/dry-run)
        if not args.mock and not args.dry_run:
            row_id = request.get("_row_id", "")
            if row_id:
                reader.mark_row_done(int(row_id), result.get("status", "unknown"))

        # Small pause between requests
        if i < len(requests_queue):
            logger.info("Waiting before next request...")
            await asyncio.sleep(3)

    # ── Summary ───────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"  Processed {len(all_results)} request(s)")
    for r in all_results:
        name = r.get('request', {}).get('editor_name', '?')
        status = r.get('status', '?')
        print(f"    {name:40s}  →  {status}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    asyncio.run(main())
