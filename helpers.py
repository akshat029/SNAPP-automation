"""
SNAPP Agent — Shared Helpers
============================
Stealth browser helpers, name-parsing utilities, and retry logic.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import random
from typing import Any, Callable, TypeVar

from playwright.async_api import Page

logger = logging.getLogger("snapp_agent")

T = TypeVar("T")


# ──────────────────────────────────────────────────────────────────────────────
# Human-like helpers (stealth)
# ──────────────────────────────────────────────────────────────────────────────

async def human_delay(low: float = 0.1, high: float = 0.3) -> None:
    """Sleep for a minimal duration for maximum speed."""
    await asyncio.sleep(random.uniform(low, high))


async def human_type(page: Page, locator, text: str) -> None:
    """Instantly paste/fill text into a field for maximum speed."""
    await locator.click()
    await human_delay(0.1, 0.2)
    await locator.fill(text)
    await human_delay(0.1, 0.2)


async def human_click(locator) -> None:
    """Click with a tiny pre-click pause."""
    await human_delay(0.2, 0.6)
    await locator.click()
    await human_delay(0.5, 1.2)


# ──────────────────────────────────────────────────────────────────────────────
# Name parsing (shared utility — eliminates 3x duplication)
# ──────────────────────────────────────────────────────────────────────────────

TITLE_TOKENS = frozenset({
    "dr", "dr.", "prof", "prof.", "professor",
    "mr", "mr.", "mrs", "mrs.", "ms", "ms.",
    "sir", "phd",
})


def parse_editor_name(full_name: str) -> tuple[str, str]:
    """
    Parse a full editor name into (first_name, last_name),
    stripping common academic titles.

    >>> parse_editor_name("Professor Kazuhiko Yamamoto")
    ('Kazuhiko', 'Yamamoto')
    >>> parse_editor_name("Dr. Jane Mary Smith")
    ('Jane Mary', 'Smith')
    >>> parse_editor_name("Alice")
    ('Alice', '')
    """
    parts = full_name.split()
    clean = [p for p in parts if p.lower() not in TITLE_TOKENS]
    if not clean:
        return (full_name.strip(), "")
    first = " ".join(clean[:-1]) if len(clean) > 1 else " ".join(clean)
    last = clean[-1] if len(clean) > 1 else ""
    return (first, last)


# ──────────────────────────────────────────────────────────────────────────────
# Retry decorator for flaky async Playwright operations
# ──────────────────────────────────────────────────────────────────────────────

def retry_async(
    max_retries: int = 2,
    backoff_base: float = 2.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable:
    """
    Decorator that retries an async function on failure with exponential backoff.

    Usage:
        @retry_async(max_retries=2)
        async def navigate_to_journal(self, name):
            ...
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: BaseException | None = None
            for attempt in range(1, max_retries + 2):  # +2 because range is exclusive + 1 initial try
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt <= max_retries:
                        wait = backoff_base ** attempt
                        logger.warning(
                            "Retry %d/%d for %s after error: %s (waiting %.1fs)",
                            attempt, max_retries, func.__name__, exc, wait,
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.error(
                            "All %d retries exhausted for %s: %s",
                            max_retries, func.__name__, exc,
                        )
            raise last_exc  # type: ignore[misc]
        return wrapper
    return decorator
