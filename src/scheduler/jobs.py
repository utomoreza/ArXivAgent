"""Scheduler jobs and inception backfill for ArXivAgent.

setup_scheduler: registers daily and weekly pipeline cron jobs.
run_inception_backfill: on first startup, processes all historical dates
from INCEPTION_DATE through yesterday before handing off to the scheduler.
"""

import datetime

import sqlalchemy as sa
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from src.config import get_settings
from src.db.constants import DATE_STATUS_NO_ANNOUNCEMENT, DATE_STATUS_PUBLISHED
from src.db.models import DailyDigest, DateRecord
from src.pipeline.daily_generator import DailyDigestGenerator
from src.pipeline.detector import detect_groundbreaking
from src.pipeline.fetcher import Fetcher
from src.pipeline.processor import process_paper
from src.pipeline.weekly_generator import WeeklyDigestGenerator
from src.utils.funcs import logger

_FRI = 4  # datetime.date.weekday() value for Friday
_SAT = 5  # datetime.date.weekday() value for Saturday


def _today() -> datetime.date:
    """Return today's date; isolated so tests can patch it."""
    return datetime.date.today()


def _is_no_announcement_day(d: datetime.date) -> bool:
    """Return True if d is Friday or Saturday (no arXiv announcement).

    Args:
        d: Calendar date to check.

    Returns:
        True for Friday and Saturday; False for all other days.
    """
    return d.weekday() in (_FRI, _SAT)


def _get_week_start(d: datetime.date) -> datetime.date:
    """Return the Sunday that opens the arXiv week containing d.

    arXiv weeks run Sun-Thu. For any date d this returns the most recent
    Sunday (equal to d when d is itself a Sunday).

    Args:
        d: Any calendar date.

    Returns:
        The Sunday on or before d that starts its arXiv announcement week.
    """
    # weekday(): Mon=0 … Sat=5, Sun=6 → days_since_sunday = (weekday + 1) % 7
    days_since_sunday = (d.weekday() + 1) % 7
    return d - datetime.timedelta(days=days_since_sunday)


async def _run_pipeline_for_date(date: datetime.date, session) -> None:
    """Run fetch → process → detect → daily digest for one announcement date.

    Skips further work when the fetch outcome is not ``published``.
    Skips ``detect_groundbreaking`` when ``process_paper`` returns None
    (e.g. duplicate arXiv ID already in the DB).

    Args:
        date: The arXiv announcement date to process.
        session: Async SQLAlchemy session for all DB operations.
    """
    fetcher = Fetcher()
    result = await fetcher.fetch_papers(date, session)
    if result.status != DATE_STATUS_PUBLISHED:
        return
    for arxiv_result in result.papers:
        paper = await process_paper(arxiv_result, session)
        if paper:
            await detect_groundbreaking(paper, session)
    generator = DailyDigestGenerator()
    await generator.generate(date, session)


async def _run_daily_job(session_factory) -> None:
    """Scheduled daily job: process today's arXiv announcement.

    Silently exits on Fri/Sat when arXiv does not publish. Otherwise
    runs the full pipeline (fetch → process → detect → daily digest).

    Args:
        session_factory: Async session factory from the DB engine.
    """
    date = _today()
    if _is_no_announcement_day(date):
        return
    async with session_factory() as session:
        await _run_pipeline_for_date(date, session)


async def _run_weekly_job(session_factory) -> None:
    """Scheduled weekly job: generate the weekly digest for the ended week.

    Only runs on Friday (the first full day after a Sun-Thu announcement
    week). On any other weekday the function exits immediately without
    calling the generator. Week start is computed as the most recent Sunday.

    Args:
        session_factory: Async session factory from the DB engine.
    """
    if _today().weekday() != _FRI:
        return
    week_start = _get_week_start(_today())
    async with session_factory() as session:
        generator = WeeklyDigestGenerator()
        await generator.generate(week_start, session)


async def run_inception_backfill(session_factory) -> None:
    """Run a resumable historical backfill from INCEPTION_DATE through yesterday.

    Safe to call on every service startup. Each date is processed
    idempotently: already-complete dates are skipped, and interrupted dates
    (``DateRecord`` written but ``DailyDigest`` missing) are resumed at the
    digest-generation step without re-fetching papers.

    Processing order:

    1. **Daily pass** — iterates INCEPTION_DATE → yesterday.
       - Fri/Sat: writes a ``no_announcement`` DateRecord if not already present.
       - Announcement days (Sun-Thu):
         - No ``DateRecord`` → run the full pipeline.
         - ``DateRecord`` with ``status=published`` but no ``DailyDigest`` →
           resume by running digest generation only (papers already processed).
         - Any other status → already handled (skip/failure); do nothing.
    2. **Weekly pass** — calls WeeklyDigestGenerator for every Sun-Thu week
       that overlaps the backfill range (complete or partial), in order.
       A ``None`` return (no daily digests found) does not halt iteration.

    Args:
        session_factory: Async session factory from the DB engine.
    """
    settings = get_settings()
    inception: datetime.date = settings.INCEPTION_DATE
    yesterday = _today() - datetime.timedelta(days=1)

    logger.info("starting inception backfill from %s to %s", inception, yesterday)

    # --- Daily pass ---
    current = inception
    while current <= yesterday:
        async with session_factory() as session:
            if _is_no_announcement_day(current):
                existing = await session.scalar(
                    select(DateRecord).where(DateRecord.date == current)
                )
                if existing is None:
                    record = DateRecord(
                        date=current, status=DATE_STATUS_NO_ANNOUNCEMENT
                    )
                    session.add(record)
                    await session.commit()
                    logger.debug(
                        "wrote %s for %s", DATE_STATUS_NO_ANNOUNCEMENT, current
                    )
            else:
                existing = await session.scalar(
                    select(DateRecord).where(DateRecord.date == current)
                )
                if existing is None:
                    # Not started — run full pipeline
                    await _run_pipeline_for_date(current, session)
                elif existing.status == DATE_STATUS_PUBLISHED:
                    # Fetch+process done but digest may be missing — check
                    digest = await session.scalar(
                        select(DailyDigest).where(DailyDigest.date == current)
                    )
                    if digest is None:
                        # Interrupted after fetch — run generator only
                        generator = DailyDigestGenerator()
                        await generator.generate(current, session)
                        logger.info("resumed digest generation for %s", current)
                    else:
                        logger.debug(
                            "date already fully processed, skipping %s", current
                        )
                # else: status is skip/failure — nothing to do
        current += datetime.timedelta(days=1)

    # --- Weekly pass ---
    week_start = _get_week_start(inception)
    weekly_generator = WeeklyDigestGenerator()
    while week_start <= yesterday:
        async with session_factory() as session:
            await weekly_generator.generate(week_start, session)
            logger.info("weekly digest done for week starting %s", week_start)
        week_start += datetime.timedelta(weeks=1)

    logger.info("inception backfill complete")
    await _create_hnsw_index_if_needed(session_factory)


async def _create_hnsw_index_if_needed(session_factory) -> None:
    """Create the HNSW vector index on paper_embeddings after backfill.

    Only runs when the table has at least one row and the index does not
    already exist.  Uses CREATE INDEX IF NOT EXISTS so concurrent startup
    races are safe.

    Args:
        session_factory: Async session factory from the DB engine.
    """
    _hnsw_sql = (
        "CREATE INDEX IF NOT EXISTS ix_paper_embeddings_embedding_hnsw "
        "ON paper_embeddings "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    async with session_factory() as session:
        row_count = await session.scalar(
            sa.text("SELECT COUNT(*) FROM paper_embeddings")
        )
        if row_count and row_count > 0:
            await session.execute(sa.text(_hnsw_sql))
            await session.commit()
            logger.info("HNSW index created on paper_embeddings.embedding")
        else:
            logger.info(
                "HNSW index skipped: paper_embeddings is empty after backfill"
            )


def setup_scheduler(scheduler: AsyncIOScheduler, session_factory) -> None:
    """Register daily and weekly pipeline jobs on the scheduler.

    Both triggers use ``CronTrigger.from_crontab`` with the America/New_York
    timezone so ET/EDT transitions are handled automatically.

    Args:
        scheduler: An AsyncIOScheduler instance (not yet started).
        session_factory: Async session factory passed to each job at fire time.
    """
    settings = get_settings()
    scheduler.add_job(
        _run_daily_job,
        trigger=CronTrigger.from_crontab(
            settings.DAILY_SCHEDULER_TIME,
            timezone="America/New_York",
        ),
        args=[session_factory],
    )
    scheduler.add_job(
        _run_weekly_job,
        trigger=CronTrigger.from_crontab(
            settings.WEEKLY_SCHEDULER_TIME,
            timezone="America/New_York",
        ),
        args=[session_factory],
    )
