"""arXiv Fetcher — fetch papers for a single announcement date.

Wraps the arxiv 3.x ``Client``/``Search`` API and writes a ``DateRecord``
for every possible outcome before returning.

Usage::

    fetcher = Fetcher()
    result = await fetcher.fetch_papers(date, session)

Pass *client* and *search* explicitly in tests to avoid hitting the real API
and reading settings at construction time.
"""

import asyncio
import datetime
import inspect
import time
from dataclasses import dataclass, field

import arxiv
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.db import constants
from src.db.models import DateRecord
from src.utils.funcs import logger, with_retry

_ARXIV_PAGE_SIZE = 100
_ARXIV_DELAY_SECONDS = 3.0
_ARXIV_NUM_RETRIES = 3
_FETCH_MAX_RESULTS = 500
_RETRY_ATTEMPTS = 3


@dataclass
class FetchResult:
    """Result of a single fetch_papers call.

    Args:
        status: One of the four DateRecord status values.
        papers: Populated only when status is ``published``.
    """

    status: str
    papers: list[arxiv.Result] = field(default_factory=list)


class Fetcher:
    """Stateful arXiv fetcher that owns the API client and search template.

    Create once and reuse across multiple ``fetch_papers`` calls.  Pass
    *client* and *search* explicitly in tests to avoid hitting the real API
    and reading settings at construction time.
    """

    class_name: str = inspect.currentframe().f_code.co_name

    def __init__(
        self,
        client: arxiv.Client | None = None,
        search: arxiv.Search | None = None,
    ) -> None:
        self._client: arxiv.Client = client or arxiv.Client(
            page_size=_ARXIV_PAGE_SIZE,
            delay_seconds=_ARXIV_DELAY_SECONDS,
            num_retries=_ARXIV_NUM_RETRIES,
        )
        self._search: arxiv.Search = search or self._build_search()

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_search() -> arxiv.Search:
        """Build the Search template from the configured category list."""
        settings = get_settings()
        category_query = " OR ".join(f"cat:{cat}" for cat in settings.ARXIV_CATEGORIES)
        return arxiv.Search(
            query=category_query,
            max_results=_FETCH_MAX_RESULTS,
            sort_by=arxiv.SortCriterion.SubmittedDate,
        )

    # ------------------------------------------------------------------
    # Private methods — one responsibility each
    # ------------------------------------------------------------------

    @with_retry(max_retries=_RETRY_ATTEMPTS, base_seconds=1.0)
    async def _fetch_with_retry(self) -> list[arxiv.Result]:
        """Fetch raw results from arXiv; retry logic is handled by ``with_retry``.

        Returns:
            List of arxiv.Result objects (may span multiple announcement dates).

        Raises:
            Exception: Re-raises the last error after all attempts are exhausted.
        """
        t0 = time.monotonic()
        results = await asyncio.to_thread(
            lambda: list(self._client.results(self._search))
        )
        logger.info("got %d results in %.2fs", len(results), time.monotonic() - t0)
        return results

    @staticmethod
    async def _postprocess_fetched_results(
        results: list[arxiv.Result], date: datetime.date, session: AsyncSession
    ) -> FetchResult:
        """Keep only papers whose published date matches *date*.

        The category feed spans multiple announcement days (timezone boundary
        effects), so client-side filtering is required — see research.md §1.
        """
        papers = [r for r in results if r.published.date() == date]

        if not papers:
            record = DateRecord(date=date, status=constants.DATE_STATUS_NO_PAPERS_SKIP)
            session.add(record)
            await session.commit()
            logger.info(
                "no papers matched %s, wrote %s",
                date,
                constants.DATE_STATUS_NO_PAPERS_SKIP,
            )
            return FetchResult(status=constants.DATE_STATUS_NO_PAPERS_SKIP)

        record = DateRecord(
            date=date,
            status=constants.DATE_STATUS_PUBLISHED,
            paper_count=len(papers),
        )
        session.add(record)
        await session.commit()
        logger.info("wrote published for %s with %d papers", date, len(papers))
        return FetchResult(status=constants.DATE_STATUS_PUBLISHED, papers=papers)

    # ------------------------------------------------------------------
    # Public method
    # ------------------------------------------------------------------

    async def fetch_papers(
        self, date: datetime.date, session: AsyncSession
    ) -> FetchResult:
        """Fetch arXiv papers for *date* and persist a DateRecord for the outcome.

        Fri/Sat dates are recorded as ``no_announcement`` without touching the
        API.  Announcement days (Sun-Thu) are attempted up to ``_RETRY_ATTEMPTS``
        times.

        Args:
            date: Calendar date to fetch papers for.
            session: Async SQLAlchemy session used to persist the DateRecord.

        Returns:
            FetchResult whose ``status`` reflects the outcome and whose
            ``papers`` list is non-empty only for ``published`` dates.
        """
        logger.debug("start for %s", date)

        # Fri/Sat guard — arXiv never announces on these days
        if date.weekday() in (4, 5):  # 4=Friday, 5=Saturday
            record = DateRecord(date=date, status=constants.DATE_STATUS_NO_ANNOUNCEMENT)
            session.add(record)
            await session.commit()
            logger.info("no_announcement for %s (Fri/Sat)", date)
            return FetchResult(status=constants.DATE_STATUS_NO_ANNOUNCEMENT)

        # Fetch with retry
        try:
            raw_results = await self._fetch_with_retry()
            return await Fetcher._postprocess_fetched_results(
                raw_results, date, session
            )
        except Exception as exc:
            logger.error("all retries failed for %s: %s", date, exc)
            record = DateRecord(
                date=date, status=constants.DATE_STATUS_FETCH_FAILURE_SKIP
            )
            session.add(record)
            await session.commit()
            return FetchResult(status=constants.DATE_STATUS_FETCH_FAILURE_SKIP)
