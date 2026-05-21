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
        self._search: arxiv.Search | None = search  # None → build per date

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    def _build_search(self, date: datetime.date) -> arxiv.Search:
        """Build a date-specific arXiv search for the given announcement date.

        Constructs a submittedDate range matching arXiv's 14:00 ET cutoff so that
        only papers actually announced on *date* are returned. When a search is
        injected at construction time (test override), returns that instead.

        Args:
            date: Announcement date to build the search for.

        Returns:
            arxiv.Search configured for *date*'s submission window.
        """
        if self._search is not None:
            return self._search
        settings = get_settings()
        category_query = " OR ".join(f"cat:{cat}" for cat in settings.ARXIV_CATEGORIES)
        weekday = date.weekday()  # 0=Mon … 6=Sun
        if weekday == 0:  # Monday — covers Fri+Sat+Sun+Mon-morning
            days_back = 3
        elif weekday == 6:  # Sunday — covers Thu+Fri+Sat+Sun-morning
            days_back = 3
        else:  # Tue-Sat: previous day
            days_back = 1
        from_date = date - datetime.timedelta(days=days_back)
        from_ts = from_date.strftime("%Y%m%d1400")
        to_ts = date.strftime("%Y%m%d1400")
        return arxiv.Search(
            query=f"({category_query}) AND submittedDate:[{from_ts} TO {to_ts}]",
            max_results=_FETCH_MAX_RESULTS,
            sort_by=arxiv.SortCriterion.SubmittedDate,
        )

    # ------------------------------------------------------------------
    # Private methods — one responsibility each
    # ------------------------------------------------------------------

    @with_retry(max_retries=_RETRY_ATTEMPTS, base_seconds=1.0)
    async def _fetch_with_retry(self, date: datetime.date) -> list[arxiv.Result]:
        """Fetch raw arXiv results for *date*; retry logic handled by ``with_retry``.

        Args:
            date: Announcement date whose submission window should be fetched.

        Returns:
            List of arxiv.Result objects (may span multiple announcement dates).

        Raises:
            Exception: Re-raises the last error after all attempts are exhausted.
        """
        t0 = time.monotonic()
        search = self._build_search(date)
        results = await asyncio.to_thread(
            lambda: list(self._client.results(search))
        )
        logger.info("got %d results in %.2fs", len(results), time.monotonic() - t0)
        return results

    @staticmethod
    async def _postprocess_fetched_results(
        results: list[arxiv.Result], date: datetime.date, session: AsyncSession
    ) -> FetchResult:
        """Keep only papers whose published date falls within *date*'s window.

        arXiv announces at 20:00 ET. During EDT (UTC-4, ~Mar-Nov) that is
        00:00 UTC the **next** calendar day, so a paper announced on *date*
        may have ``r.published.date() == date + 1`` in UTC.  Accepting both
        *date* and *date + 1* handles the midnight-offset case without
        admitting papers from unrelated announcement windows, because
        ``_build_search`` already constrains the query to *date*'s submission
        window via ``submittedDate``.
        """
        papers = [
            r for r in results
            if r.published.date() == date
            or r.published.date() == date + datetime.timedelta(days=1)
        ]

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
        logger.debug("fetch_papers entry date=%s", date)
        t0 = time.perf_counter()

        # Fri/Sat guard — arXiv never announces on these days
        if date.weekday() in (4, 5):  # 4=Friday, 5=Saturday
            record = DateRecord(date=date, status=constants.DATE_STATUS_NO_ANNOUNCEMENT)
            session.add(record)
            await session.commit()
            logger.info(
                "fetch_papers done date=%s status=no_announcement elapsed_s=%.3f",
                date,
                time.perf_counter() - t0,
            )
            return FetchResult(status=constants.DATE_STATUS_NO_ANNOUNCEMENT)

        # Fetch with retry
        try:
            raw_results = await self._fetch_with_retry(date)
            result = await Fetcher._postprocess_fetched_results(
                raw_results, date, session
            )
            logger.info(
                "fetch_papers done date=%s status=%s papers=%d elapsed_s=%.3f",
                date,
                result.status,
                len(result.papers),
                time.perf_counter() - t0,
            )
            return result
        except Exception as exc:
            logger.error(
                "fetch_papers failed date=%s elapsed_s=%.3f error=%s",
                date,
                time.perf_counter() - t0,
                exc,
            )
            record = DateRecord(
                date=date, status=constants.DATE_STATUS_FETCH_FAILURE_SKIP
            )
            session.add(record)
            await session.commit()
            return FetchResult(status=constants.DATE_STATUS_FETCH_FAILURE_SKIP)
