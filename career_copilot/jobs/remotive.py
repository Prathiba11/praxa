"""Remotive job-board source.

https://remotive.com/api/remote-jobs - free, unauthenticated, and unlike
Arbeitnow it takes a search term server-side and its board is almost entirely
technical. Arbeitnow covers the German market broadly but shallowly on
engineering roles; Remotive covers engineering deeply but remote-only. Neither
is sufficient alone, which is the argument for the source interface rather than
one hard-coded fetcher.

Remotive's terms require attribution when postings are displayed. `LEGAL_NOTICE`
carries the text the API returns and the UI shows it; honouring that is the
price of a free API and it is a cheap price.
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

__all__ = ["API_URL", "LEGAL_NOTICE", "RemotiveSource"]

log = get_logger(__name__)

API_URL = "https://remotive.com/api/remote-jobs"
LEGAL_NOTICE = "Job data provided by Remotive.com - https://remotive.com/remote-jobs"
_TIMEOUT = 20.0
_MAX_LIMIT = 100


class RemotiveSource:
    """Search-driven, so filtering happens server-side and less is wasted."""

    name = "remotive"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def fetch(
        self,
        *,
        limit: int = 50,
        keywords: tuple[str, ...] = (),
        category: str | None = "software-dev",
        location: str | None = None,
    ) -> list[JobPosting]:
        """Return up to `limit` postings.

        `keywords` is passed to the API as a single search term - it treats the
        words as a phrase-ish match, so one broad term returns more than four
        narrow ones. Location filtering is applied here against
        `candidate_required_location`, which is a free-text field like
        "Europe" or "Germany" rather than a city.

        Raises:
            JobSourceError: the API was unreachable or returned nonsense.
        """
        client = self._client or build_client(_TIMEOUT)
        close_after = self._client is None

        params: dict[str, Any] = {"limit": min(limit * 2, _MAX_LIMIT)}
        if keywords:
            params["search"] = " ".join(keywords)
        if category:
            params["category"] = category

        try:
            raw_jobs = self._request(client, params)
        finally:
            if close_after:
                client.close()

        collected: list[JobPosting] = []
        for raw in raw_jobs:
            posting = self._normalise(raw)
            if posting is None:
                continue
            if location and location.lower() not in (posting.location or "").lower():
                continue
            if not self._matches_keywords(posting, keywords):
                continue
            collected.append(posting)
            if len(collected) >= limit:
                break

        log.info(
            "remotive fetch complete",
            extra={"scanned": len(raw_jobs), "returned": len(collected)},
        )
        return collected

    @staticmethod
    def _matches_keywords(posting: JobPosting, keywords: tuple[str, ...]) -> bool:
        """Enforce the search term locally.

        The API accepts `search` and then largely ignores it: asking for
        "kubernetes devops" returned a freelance copywriter, a sales role and an
        office assistant, and a second request with a different term returned
        the same page. Passing the parameter is still worth doing - it may
        narrow the response - but the source cannot rely on it, so the filter
        is applied here where it can be tested.
        """
        if not keywords:
            return True
        haystack = f"{posting.title}\n{posting.description}\n{' '.join(posting.tags)}".lower()
        return any(word.lower() in haystack for word in keywords)

    # ------------------------------------------------------------------ http

    def _request(self, client: httpx.Client, params: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            response = client.get(API_URL, params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise JobSourceError(f"remotive request failed: {type(exc).__name__}: {exc}") from exc
        except ValueError as exc:
            raise JobSourceError("remotive returned a body that was not JSON") from exc

        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs, list):
            raise JobSourceError("remotive response had no 'jobs' list")
        return [item for item in jobs if isinstance(item, dict)]

    # ------------------------------------------------------------ normalise

    def _normalise(self, raw: dict[str, Any]) -> JobPosting | None:
        title = str(raw.get("title") or "").strip()
        company = str(raw.get("company_name") or "").strip()
        if not title or not company:
            return None

        description = html_to_text(str(raw.get("description") or ""))
        tags = tuple(str(tag) for tag in (raw.get("tags") or []) if tag)
        category = str(raw.get("category") or "").strip()
        if category:
            tags = (*tags, category)

        return JobPosting(
            source=self.name,
            title=title,
            company=company,
            description=description,
            location=str(raw.get("candidate_required_location") or "").strip() or None,
            url=str(raw.get("url") or "").strip() or None,
            posted_at=self._published(raw.get("publication_date")),
            language=detect_language(f"{title}\n{description}"),
            profile=classify_profile(title, description, tags),
            tags=tags,
        )

    @staticmethod
    def _published(value: Any) -> datetime | None:
        """ISO 8601, usually without a timezone. Assumed UTC rather than local,
        because a naive local timestamp would drift the 'new today' view by an
        hour twice a year."""
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
