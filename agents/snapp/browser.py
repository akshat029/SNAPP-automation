"""
SNAPP Browser — Launch, Login, SSO & MFA Handling
===================================================
Manages the Playwright browser lifecycle and all authentication flows.
"""

from __future__ import annotations

import asyncio
import logging
import os

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)

from agents.base import AgentContext
from agents.snapp.selectors import SELECTORS

logger = logging.getLogger("snapp_agent")


class SnappBrowser:
    """Playwright browser lifecycle and SNAPP authentication."""

    def __init__(self, ctx: AgentContext) -> None:
        self.ctx = ctx
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    # ── Launch ────────────────────────────────────────────────────────────

    async def launch(self) -> None:
        """Start Playwright and open a Chrome browser."""
        self._playwright = await async_playwright().start()
        # chrome_profile = os.getenv("CHROME_PROFILE_PATH", "")
        chrome_profile = ""  # Use fresh browser (avoids profile lock when Chrome is open)
        stealth_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        stealth_script = "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"

        if chrome_profile:
            # ── Split into User Data dir + profile folder name ─────────
            # CHROME_PROFILE_PATH should be like:
            #   C:\Users\AKSHAT\AppData\Local\Google\Chrome\User Data\Profile 44
            # We need:
            #   user_data_dir = C:\Users\...\User Data
            #   --profile-directory=Profile 44
            from pathlib import Path
            profile_path = Path(chrome_profile)
            user_data_dir = str(profile_path.parent)   # .../User Data
            profile_name = profile_path.name            # Profile 44

            # Chrome binary path
            chrome_exe = os.getenv(
                "CHROME_EXE_PATH",
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            )

            logger.info("Using Chrome profile: %s (dir=%s, profile=%s)",
                        chrome_profile, user_data_dir, profile_name)

            self.ctx.context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                executable_path=chrome_exe,
                headless=False,
                no_viewport=True,
                args=stealth_args + [
                    "--start-maximized",
                    f"--profile-directory={profile_name}",
                ],
                locale="en-GB",
                timezone_id="Europe/London",
            )
            await self.ctx.context.add_init_script(stealth_script)
            self.ctx.page = (
                self.ctx.context.pages[0]
                if self.ctx.context.pages
                else await self.ctx.context.new_page()
            )
            logger.info("Browser launched with existing profile")
        else:
            logger.warning("No CHROME_PROFILE_PATH — using fresh browser")
            self._browser = await self._playwright.chromium.launch(
                headless=False,
                channel="chrome",
                args=stealth_args + ["--start-maximized"],
            )
            self.ctx.context = await self._browser.new_context(
                viewport={"width": 1366, "height": 768},
                locale="en-GB",
                timezone_id="Europe/London",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.6422.112 Safari/537.36"
                ),
            )
            await self.ctx.context.add_init_script(stealth_script)
            self.ctx.page = await self.ctx.context.new_page()
            logger.info("Browser launched (stealth mode, headless=False)")

    async def close(self) -> None:
        """Shut down browser and Playwright."""
        if self.ctx.context:
            await self.ctx.context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Browser closed")

    # ── Login ─────────────────────────────────────────────────────────────

    async def login(self) -> None:
        """
        Authenticate on SNAPP. Handles:
          0) Cookie consent banner
          A) Already logged in (Chrome profile session)
          B) Springer Nature login page (email + password)
          C) 2FA / MFA challenge -> pauses for human
        """
        page = self.ctx.page
        assert page is not None

        logger.info("Navigating to %s", self.ctx.base_url)
        try:
            await page.goto(self.ctx.base_url, wait_until="domcontentloaded", timeout=60_000)
        except PlaywrightTimeout:
            logger.warning("Timeout navigating to base URL — checking if page loaded anyway")
        except Exception as exc:
            if "Timeout" in str(exc):
                logger.warning("Timeout navigating to base URL — checking if page loaded anyway")
            else:
                raise

        # Step 0 — Dismiss cookie consent banner if present
        try:
            cookie_btn = page.get_by_role("button", name="Accept all cookies")
            if await cookie_btn.count() > 0:
                logger.info("Cookie consent banner detected — accepting cookies")
                await cookie_btn.first.click()
        except Exception:
            pass

        # Check if already authenticated
        if "usermanager.nature.com" in page.url and "login" not in page.url.lower():
            journal_input = page.locator(SELECTORS["journal_input"])
            if await journal_input.count() > 0:
                logger.info("Already logged in (session from Chrome profile) — URL: %s", page.url)
                return

        # Scenario A — Springer Nature login page
        try:
            email_loc = (
                page.get_by_label("Email address")
                .or_(page.get_by_placeholder("Email address"))
                .or_(page.get_by_placeholder("Email"))
                .or_(page.get_by_placeholder("Username"))
                .or_(page.get_by_label("Username"))
                .or_(page.get_by_label("Email"))
            )
            if await email_loc.count() > 0:
                logger.info("Login form detected — filling email/username")
                await email_loc.first.fill(self.ctx.username)

                # Look for password field on the same page
                password_loc = (
                    page.get_by_placeholder("Password")
                    .or_(page.get_by_label("Password"))
                )
                if await password_loc.count() > 0:
                    await password_loc.first.fill(self.ctx.password)
                    submit = (
                        page.get_by_role("button", name="Log in")
                        .or_(page.get_by_role("button", name="Sign in"))
                        .or_(page.get_by_role("button", name="Login"))
                        .or_(page.get_by_role("button", name="Submit"))
                        .or_(page.get_by_role("button", name="Continue"))
                    )
                    if await submit.count() > 0:
                        await submit.first.click()
                        logger.info("Credentials submitted")
                        await page.wait_for_load_state("networkidle", timeout=15_000)
                else:
                    # Multi-step: submit email first, then password
                    next_btn = (
                        page.get_by_role("button", name="Continue")
                        .or_(page.get_by_role("button", name="Next"))
                        .or_(page.get_by_role("button", name="Submit"))
                        .or_(page.get_by_role("button", name="Log in"))
                    )
                    if await next_btn.count() > 0:
                        await next_btn.first.click()
                        logger.info("Email submitted — waiting for password step")
                        await page.wait_for_load_state("networkidle", timeout=10_000)

                    # Now look for password field
                    password_loc = (
                        page.get_by_placeholder("Password")
                        .or_(page.get_by_label("Password"))
                    )
                    if await password_loc.count() > 0:
                        await password_loc.first.fill(self.ctx.password)
                        submit = (
                            page.get_by_role("button", name="Log in")
                            .or_(page.get_by_role("button", name="Sign in"))
                            .or_(page.get_by_role("button", name="Submit"))
                            .or_(page.get_by_role("button", name="Continue"))
                            .or_(page.get_by_role("button", name="Verify"))
                        )
                        if await submit.count() > 0:
                            await submit.first.click()
                            logger.info("Password submitted")
                            await page.wait_for_load_state("networkidle", timeout=15_000)
            else:
                logger.info("No login form detected — checking for Google SSO")
                google_btn = (
                    page.get_by_role("button", name="Continue with Google")
                    .or_(page.get_by_text("Continue with Google"))
                )
                if await google_btn.count() > 0:
                    logger.info("'Continue with Google' button found — clicking")
                    await google_btn.first.click()
                    await page.wait_for_load_state("networkidle", timeout=15_000)

        except PlaywrightTimeout:
            logger.warning("Timeout detecting login fields — pausing for human")
            await self.ctx.dump_page("login_timeout")

        # Scenario C — MFA
        await self._wait_for_mfa()

        # Confirm authenticated — wait up to 2 minutes for manual steps
        try:
            await page.wait_for_url("**/usermanager.nature.com/**", timeout=120_000)
            logger.info("Login succeeded — URL: %s", page.url)
        except PlaywrightTimeout:
            if "usermanager" in page.url:
                logger.info("Login appears successful — URL: %s", page.url)
            else:
                await self.ctx.dump_page("login_failed")
                raise RuntimeError(f"Login failed — stuck at: {page.url}")

    async def _wait_for_mfa(self) -> None:
        """Detect and wait for MFA/2FA completion by the human."""
        page = self.ctx.page
        assert page is not None
        mfa_signals = [
            "Enter verification code", "Two-factor authentication",
            "Verify your identity", "We sent a code",
            "Approve sign-in request", "Enter the code",
        ]
        for text in mfa_signals:
            indicator = page.get_by_text(text)
            if await indicator.count() > 0:
                logger.warning("MFA detected — complete it in the browser window")
                print("\n" + "=" * 60)
                print("  ACTION REQUIRED:  Complete 2FA in the browser window")
                print("=" * 60 + "\n")
                while await indicator.count() > 0:
                    await asyncio.sleep(3)
                logger.info("MFA resolved — continuing")
                break
