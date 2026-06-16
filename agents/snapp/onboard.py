"""
SNAPP Onboarding — New Editor & Guest Editor Flows
=====================================================
Handles all onboarding workflows: regular editors (2-step wizard)
and guest editors (with collection selection).
"""

from __future__ import annotations

import logging

from agents.base import AgentContext
from agents.snapp.forms import SnappForms
from agents.snapp.keywords import SnappKeywords
from agents.snapp.selectors import SELECTORS
from helpers import parse_editor_name

logger = logging.getLogger("snapp_agent")


class SnappOnboarder:
    """Onboarding flows for new regular and guest editors."""

    def __init__(self, ctx: AgentContext, forms: SnappForms, keywords: SnappKeywords) -> None:
        self.ctx = ctx
        self.forms = forms
        self.keywords = keywords

    async def onboard_editor(self) -> bool:
        """Onboard a new editor — delegates to step1 + step2 + save."""
        page = self.ctx.page
        assert page is not None
        req = self.ctx.request
        collection = (
            req.get("collection_name", "").strip()
            or req.get("collection_id", "").strip()
        )
        if collection:
            return await self._onboard_guest_editor(collection)
        try:
            if not await self._step1():
                return False
            if not await self._step2():
                return False
            return await self.forms.click_save(["Save and invite editor", "Save", "Submit"])
        except Exception as exc:
            logger.error("Onboard error: %s", exc, exc_info=True)
            await self.ctx.dump_page("onboard_error")
            return False

    # ── Step 1 — personal details ─────────────────────────────────────────

    async def _step1(self) -> bool:
        """Navigate to Add Editor form, fill personal details, click Next."""
        page = self.ctx.page
        assert page is not None
        req = self.ctx.request

        try:
            logger.info("Onboarding new editor (regular) — Step 1")

            # Navigate to the Add Editor form page
            add_btn = page.locator(SELECTORS["add_editor_btn"])
            add_url = None

            if await add_btn.count() > 0:
                add_url = await add_btn.first.get_attribute("href")
                logger.info("Found #add_new_btn with href: %s", add_url)
            else:
                link = (
                    page.get_by_role("link", name="Add new Editor")
                    .or_(page.get_by_text("Add new Editor", exact=True))
                )
                if await link.count() > 0:
                    add_url = await link.first.get_attribute("href")
                    logger.info("Found 'Add new Editor' link with href: %s", add_url)
                else:
                    logger.error("'Add new Editor' button/link not found")
                    await self.ctx.dump_page("no_add_editor_btn")
                    return False

            if add_url and add_url.startswith("/"):
                origin = page.url.split("/editors")[0]
                add_url = origin + add_url
            elif not add_url:
                current = page.url.rstrip("/")
                journal_id = current.split("/")[-1]
                add_url = f"{current}/editor/{journal_id}/add"
                logger.info("Constructed Add Editor URL: %s", add_url)

            logger.info("Navigating to Add Editor form: %s", add_url)
            await page.goto(add_url, wait_until="networkidle", timeout=30_000)
            logger.info("Add Editor page — URL: %s", page.url)

            # Wait for email field to confirm form loaded
            try:
                await page.locator(SELECTORS["email_field"]).wait_for(
                    state="visible", timeout=15_000
                )
                logger.info("Add Editor form loaded — email field is visible")
            except Exception:
                logger.warning("Email field not visible after 15s — dumping page")
                await self.ctx.dump_page("add_editor_form_not_loaded")

            await self.ctx.dump_page("add_editor_form")

            # Fill personal fields
            email = req.get("email", "").strip()
            if email:
                if not await self.forms.fill_by_id("addEditorPrimaryEmail", email):
                    await self.forms.fill_field_by_labels(["Primary email address", "Email"], email)

            fname = req.get("first_name", "").strip()
            lname = req.get("last_name", "").strip()
            if not fname and not lname:
                fname, lname = parse_editor_name(req.get("editor_name", ""))
            if fname:
                if not await self.forms.fill_by_id("addEditorGivenName", fname):
                    await self.forms.fill_field_by_labels(["Given name", "First name"], fname)
            if lname:
                if not await self.forms.fill_by_id("addEditorFamilyName", lname):
                    await self.forms.fill_field_by_labels(["Family name", "Last name"], lname)

            # ── Check for "Record already exists in system" ──────────────
            # After filling email, SNAPP may auto-submit and redirect to a
            # page showing: "Record already exists in system. Continue editing
            # below if you wish to add this Editor to your journal."
            # URL pattern: .../save/<id>/new_user
            import asyncio as _aio
            await _aio.sleep(1.0)

            record_exists = False
            exists_banner = page.locator("text=Record already exists in system")
            if await exists_banner.count() > 0:
                record_exists = True
                logger.info("'Record already exists' detected — verifying affiliation")
            elif "/save/" in page.url and "new_user" in page.url:
                record_exists = True
                logger.info("Redirected to existing-record page (URL: %s)", page.url)

            if record_exists:
                # Scroll down to see the affiliation section
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await _aio.sleep(0.5)
                await self.ctx.dump_page("record_exists")

                # Verify affiliation matches the ticket — if not, fill it
                ticket_affiliation = req.get("affiliation", "").strip()
                country = req.get("_country", "").strip()
                if ticket_affiliation:
                    # Extract the first meaningful part (institution name)
                    aff_check = ticket_affiliation.split(",")[0].strip()
                    aff_on_page = page.get_by_text(aff_check, exact=False)
                    if await aff_on_page.count() > 0:
                        logger.info(
                            "Affiliation verified on existing-record page: '%s'",
                            aff_check,
                        )
                    else:
                        logger.warning(
                            "Affiliation '%s' NOT found on existing-record page — "
                            "filling the correct affiliation now",
                            aff_check,
                        )
                        await self.ctx.dump_page("affiliation_mismatch_before_fill")

                        # Fill the correct affiliation using the autocomplete field
                        # Try the full onboard affiliation field first, then the
                        # generic autocomplete as fallback
                        aff_filled = False
                        aff_field = page.locator(SELECTORS["affiliation"])
                        if await aff_field.count() > 0:
                            await self.forms.fill_affiliation_field(
                                ticket_affiliation, country
                            )
                            aff_filled = True
                            logger.info(
                                "Filled affiliation on existing-record page: '%s'",
                                ticket_affiliation,
                            )
                        else:
                            # Fallback: try the generic affiliation autocomplete
                            aff_filled = await self.forms.fill_affiliation_autocomplete(
                                ticket_affiliation
                            )

                        if aff_filled:
                            logger.info(
                                "Affiliation corrected on existing-record page"
                            )
                        else:
                            logger.error(
                                "Could not fill affiliation on existing-record page "
                                "— affiliation field not found"
                            )
                            await self.ctx.dump_page("affiliation_fill_failed")

                # Click Next to proceed to Step 2
                if not await self.forms.click_next():
                    logger.warning("'Next' button not found on existing-record page")
                    await self.ctx.dump_page("existing_record_no_next")

                return True

            # ── Normal flow: fill affiliation and click Next ─────────────
            # Affiliation
            affiliation = req.get("affiliation", "").strip()
            country = req.get("_country", "").strip()
            if affiliation:
                await self.forms.fill_affiliation_field(affiliation, country)
            elif country:
                await self.forms.select_dropdown_by_id("addEditorInstitutionCountry", country)

            # Click Next to step 2
            if not await self.forms.click_next():
                logger.warning("'Next' button not found — trying to continue")
                await self.ctx.dump_page("onboard_no_next_btn")

            return True

        except Exception as exc:
            logger.error("Step 1 error: %s", exc, exc_info=True)
            await self.ctx.dump_page("step1_error")
            return False

    # ── Step 2 — journal-specific info ────────────────────────────────────

    async def _step2(self) -> bool:
        """Fill role, sections, keywords on step 2 of the wizard."""
        page = self.ctx.page
        assert page is not None
        req = self.ctx.request

        try:
            logger.info("Onboarding — Step 2 (role & journal-specific)")
            await self.ctx.dump_page("step2_form")

            role = req.get("role", "").strip()
            if role:
                await self.forms.select_role_radio(role)

            sections = req.get("sections", "").strip()
            if sections:
                await self.forms.fill_board_sections(sections)

            keywords = req.get("keywords", "").strip()
            if keywords:
                await self.keywords.add_keywords(keywords)

            unavail_from = req.get("unavailable_from", "").strip()
            unavail_to = req.get("unavailable_to", "").strip()
            if unavail_from and unavail_to:
                await self.forms.set_unavailability(unavail_from, unavail_to)

            return True

        except Exception as exc:
            logger.error("Step 2 error: %s", exc, exc_info=True)
            await self.ctx.dump_page("step2_error")
            return False

    # ── Guest Editor onboarding ───────────────────────────────────────────

    async def _onboard_guest_editor(self, collection: str) -> bool:
        """Onboard a guest editor via 'Add Guest Editor' (2-step flow)."""
        page = self.ctx.page
        assert page is not None
        req = self.ctx.request

        try:
            logger.info("Onboarding guest editor (collection: '%s')", collection)
            btn = (
                page.locator(SELECTORS["add_guest_btn"])
                .or_(page.get_by_role("link", name="Add Guest Editor"))
                .or_(page.get_by_text("Add Guest Editor"))
            )
            if await btn.count() == 0:
                logger.error("'Add Guest Editor' button not found")
                await self.ctx.dump_page("no_add_guest_btn")
                return False

            await btn.first.click()
            await page.wait_for_load_state("networkidle", timeout=15_000)

            # Step 1: Personal information
            email = req.get("email", "").strip()
            if email:
                await self.forms.fill_field_by_labels(
                    ["Primary email address", "Email", "Email address"], email
                )

            fname = req.get("first_name", "").strip()
            lname = req.get("last_name", "").strip()
            if not fname and not lname:
                fname, lname = parse_editor_name(req.get("editor_name", ""))

            if fname:
                await self.forms.fill_field_by_labels(["Given name", "First name"], fname)
            if lname:
                await self.forms.fill_field_by_labels(["Family name", "Last name", "Surname"], lname)

            affiliation = req.get("affiliation", "").strip()
            if affiliation:
                await self.forms.fill_affiliation_autocomplete(affiliation)

            if not await self.forms.click_next():
                return False

            # Step 2: Collection-specific information
            logger.info("Guest Editor step 2 — selecting collection")
            collection_dropdown = (
                page.get_by_label("Choose collection")
                .or_(page.get_by_text("Please select collection"))
                .or_(page.get_by_role("combobox"))
            )
            if await collection_dropdown.count() > 0:
                await collection_dropdown.first.click()
                option = (
                    page.get_by_role("option", name=collection)
                    .or_(page.get_by_text(collection, exact=False))
                )
                if await option.count() > 0:
                    await option.first.click()
                    logger.info("Selected collection: '%s'", collection)
                else:
                    logger.warning("Collection '%s' not found in dropdown", collection)

            role = req.get("role", "").strip()
            if role:
                await self.forms.select_role_radio(role)

            keywords = req.get("keywords", "").strip()
            if keywords:
                await self.keywords.add_keywords(keywords)

            return await self.forms.click_save(["Save and invite editor", "Save", "Submit"])

        except Exception as exc:
            logger.error("Guest editor onboard error: %s", exc, exc_info=True)
            await self.ctx.dump_page("guest_onboard_error")
            return False
