"""Arbeitnow job-board source.

A free, unauthenticated API over a German-market job board:
https://www.arbeitnow.com/api/job-board-api

Chosen for three reasons. It needs no key, so the repository stays runnable by
anyone who clones it. It covers the German market, which is the one being
searched. And its terms permit this, which the big boards' do not.

The API returns whole pages rather than search results, so filtering happens
here. That is fine at this volume and it keeps the source honest: it fetches
and normalises, it does not rank.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from career_copilot.core.logging import get_logger
from career_copilot.jobs.base import (
    JobPosting,
    JobSourceError,
    build_client,
    classify_profile,
    detect_language,
    html_to_text,
)

__all__ = ["API_URL", "ArbeitnowSource"]

log = get_logger(__name__)

API_URL = "https://www.arbeitnow.com/api/job-board-api"
_TIMEOUT = 20.0
_MAX_PAGES = 5


class ArbeitnowSource:
    """Fetches and normalises postings. Does not decide what is relevant."""

    name = "arbeitnow"

    def __init__(self, client: httpx.Client | None = None) -> None:
        # Injected for tests, which drive it with httpx.MockTransport rather
        # than hitting the network.
        self._client = client

    def fetch(
        self,
        *,
        limit: int = 50,
        keywords: tuple[str, ...] = (),
        location: str | None = None,
        remote_only: bool = False,
        pages: int = 2,
    ) -> list[JobPosting]:
        """Return up to `limit` postings matching the filters.

        Raises:
            JobSourceError: the API was unreachable or returned nonsense.
        """
        client = self._client or build_client(_TIMEOUT)
        close_after = self._client is None
        collected: list[JobPosting] = []

        try:
            for page in range(1, min(pages, _MAX_PAGES) + 1):
                for raw in self._page(client, page):
                    posting = self._normalise(raw)
                    if posting is None or not self._matches(
                        posting, keywords, location, remote_only, raw
                    ):
                        continue
                    collected.append(posting)
                    if len(collected) >= limit:
                        return collected
        finally:
            if close_after:
                client.close()

        log.info("arbeitnow fetch complete", extra={"returned": len(collected)})
        return collected

    # ------------------------------------------------------------------ http

    def _page(self, client: httpx.Client, page: int) -> list[dict[str, Any]]:
        try:
            response = client.get(API_URL, params={"page": page})
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise JobSourceError(f"arbeitnow request failed: {type(exc).__name__}: {exc}") from exc
        except ValueError as exc:
            raise JobSourceError("arbeitnow returned a body that was not JSON") from exc

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise JobSourceError("arbeitnow response had no 'data' list")
        return [item for item in data if isinstance(item, dict)]

    # ------------------------------------------------------------ normalise

    def _normalise(self, raw: dict[str, Any]) -> JobPosting | None:
        title = str(raw.get("title") or "").strip()
        company = str(raw.get("company_name") or "").strip()
        if not title or not company:
            return None  # a posting we cannot fingerprint is not worth storing

        description = html_to_text(str(raw.get("description") or ""))
        tags = tuple(str(tag) for tag in (raw.get("tags") or []) if tag)

        return JobPosting(
            source=self.name,
            title=title,
            company=company,
            description=description,
            location=str(raw.get("location") or "").strip() or None,
            url=str(raw.get("url") or "").strip() or None,
            posted_at=self._posted_at(raw.get("created_at")),
            language=detect_language(f"{title}\n{description}"),
            profile=classify_profile(title, description, tags),
            tags=tags,
        )

    @staticmethod
    def _posted_at(value: Any) -> datetime | None:
        """The API sends a unix timestamp. Anything else is ignored rather than
        guessed at - a wrong date silently corrupts the 'new today' view."""
        if isinstance(value, int | float) and value > 0:
            try:
                return datetime.fromtimestamp(float(value), tz=UTC)
            except (OverflowError, OSError, ValueError):
                return None
        return None

    # --------------------------------------------------------------- filter

    @staticmethod
    def _matches(
        posting: JobPosting,
        keywords: tuple[str, ...],
        location: str | None,
        remote_only: bool,
        raw: dict[str, Any],
    ) -> bool:
        if remote_only and not raw.get("remote"):
            return False
        if location and location.lower() not in (posting.location or "").lower():
            return False
        if keywords:
            haystack = f"{posting.title}\n{posting.description}\n{' '.join(posting.tags)}".lower()
            return any(word.lower() in haystack for word in keywords)
        return True
