"""Unit tests for src/scheduler/jobs.py (T024).

Covers per the Definition of Done:
- Backfill writes ``no_announcement`` for every Fri/Sat in the range without
  calling the pipeline.
- Backfill is idempotent: exits immediately when DateRecord rows already exist.
- Backfill runs the full pipeline (fetch → process → detect → daily digest)
  for announcement days with published papers.
- ``process_paper`` returning None does not call ``detect_groundbreaking``.
- Non-published fetch result skips paper processing.
- DailyDigestGenerator returning None does not halt the backfill; subsequent
  dates are still processed.
- WeeklyDigestGenerator returning None does not halt the backfill; subsequent
  weeks are still processed.
- Weekly generator called once per complete or partial Sun-Thu week.
- ``_run_daily_job`` exits early on Fri/Sat; runs pipeline otherwise.
- ``_run_weekly_job`` only runs on Friday; on all other weekdays it exits early
  without calling WeeklyDigestGenerator.
- ``setup_scheduler``: daily and weekly job cron strings match the
  ``DAILY_SCHEDULER_TIME`` / ``WEEKLY_SCHEDULER_TIME`` env vars.

Note on fetch status in backfill tests: the scheduler does not distinguish
between the four non-published DateRecord statuses (no_papers_skip,
fetch_failure_skip, no_announcement, …). All non-published outcomes skip
paper processing identically. Status-level behaviour is covered in
test_fetcher.py. We use ``no_papers_skip`` as the representative non-published
status throughout these tests.
"""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.constants import DATE_STATUS_NO_ANNOUNCEMENT
from src.scheduler.jobs import (
    _run_daily_job,
    _run_weekly_job,
    _today,
    run_inception_backfill,
    setup_scheduler,
)

# ---------------------------------------------------------------------------
# _today helper
# ---------------------------------------------------------------------------


def test_today_returns_a_date():
    """_today() must return an actual datetime.date (line-coverage for the helper)."""
    result = _today()
    assert isinstance(result, datetime.date)


# ---------------------------------------------------------------------------
# Shared test dates (all verified against the week containing 2026-04-19 Sun)
# ---------------------------------------------------------------------------
_SUN_APR_12 = datetime.date(2026, 4, 12)  # Sunday   (week before _SUN_APR_19)
_MON_APR_13 = datetime.date(2026, 4, 13)  # Monday   (weekday=0)
_TUE_APR_14 = datetime.date(2026, 4, 14)  # Tuesday  (weekday=1)
_WED_APR_15 = datetime.date(2026, 4, 15)  # Wednesday (weekday=2)
_THU_APR_16 = datetime.date(2026, 4, 16)  # Thursday (weekday=3)
_FRI_APR_17 = datetime.date(2026, 4, 17)  # Friday   (weekday=4)
_SAT_APR_18 = datetime.date(2026, 4, 18)  # Saturday (weekday=5)
_SUN_APR_19 = datetime.date(2026, 4, 19)  # Sunday   (weekday=6)
_SUN_APR_26 = datetime.date(2026, 4, 26)  # Sunday   (next week)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(has_records: bool = False) -> AsyncMock:
    """Return a mock AsyncSession.

    Args:
        has_records: When True, scalars().first() is truthy — simulating an
            existing DateRecord row that triggers the idempotency exit.
    """
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()

    scalars_mock = MagicMock()
    scalars_mock.first.return_value = MagicMock() if has_records else None
    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_mock
    session.execute = AsyncMock(return_value=execute_result)
    return session


def _make_session_factory(session: AsyncMock) -> MagicMock:
    """Return a callable session factory that always yields *session*.

    Args:
        session: The mock AsyncSession returned by every context entry.
    """
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


def _make_fetch_result(status: str, papers: list | None = None) -> MagicMock:
    """Return a mock FetchResult.

    Args:
        status: One of the four DateRecord status strings.
        papers: arXiv result objects; only populated when status='published'.
    """
    r = MagicMock()
    r.status = status
    r.papers = papers or []
    return r


# ---------------------------------------------------------------------------
# Backfill: no_announcement for Fri/Sat
# ---------------------------------------------------------------------------


class TestBackfillNoAnnouncementDays:
    """Fri/Sat days get a no_announcement record; pipeline is never called."""

    async def test_no_announcement_written_for_fri_sat(self):
        # Range: Fri Apr 17 → Sat Apr 18; today = Sun Apr 19
        session = _make_session(has_records=False)
        factory = _make_session_factory(session)

        with (
            patch("src.scheduler.jobs.get_settings") as mock_settings,
            patch("src.scheduler.jobs._today", return_value=_SUN_APR_19),
            patch("src.scheduler.jobs.Fetcher") as mock_fetcher_cls,
            patch("src.scheduler.jobs.process_paper", new_callable=AsyncMock) as mock_process,
            patch("src.scheduler.jobs.detect_groundbreaking", new_callable=AsyncMock) as mock_detect,
            patch("src.scheduler.jobs.DailyDigestGenerator") as mock_daily_cls,
            patch("src.scheduler.jobs.WeeklyDigestGenerator") as mock_weekly_cls,
        ):
            mock_weekly_cls.return_value.generate = AsyncMock(return_value=None)
            settings = MagicMock()
            settings.INCEPTION_DATE = _FRI_APR_17
            mock_settings.return_value = settings

            await run_inception_backfill(factory)

        mock_fetcher_cls.return_value.fetch_papers.assert_not_called()
        mock_process.assert_not_called()
        mock_detect.assert_not_called()
        mock_daily_cls.return_value.generate.assert_not_called()

        added = [c.args[0] for c in session.add.call_args_list]
        statuses = [r.status for r in added]
        assert statuses.count(DATE_STATUS_NO_ANNOUNCEMENT) == 2

    async def test_no_announcement_dates_match_fri_sat(self):
        session = _make_session(has_records=False)
        factory = _make_session_factory(session)

        with (
            patch("src.scheduler.jobs.get_settings") as mock_settings,
            patch("src.scheduler.jobs._today", return_value=_SUN_APR_19),
            patch("src.scheduler.jobs.Fetcher"),
            patch("src.scheduler.jobs.process_paper", new_callable=AsyncMock),
            patch("src.scheduler.jobs.detect_groundbreaking", new_callable=AsyncMock),
            patch("src.scheduler.jobs.DailyDigestGenerator"),
            patch("src.scheduler.jobs.WeeklyDigestGenerator") as mock_weekly_cls,
        ):
            mock_weekly_cls.return_value.generate = AsyncMock(return_value=None)
            settings = MagicMock()
            settings.INCEPTION_DATE = _FRI_APR_17
            mock_settings.return_value = settings

            await run_inception_backfill(factory)

        added = [c.args[0] for c in session.add.call_args_list]
        dates = sorted(r.date for r in added)
        assert dates == [_FRI_APR_17, _SAT_APR_18]


# ---------------------------------------------------------------------------
# Backfill: idempotency
# ---------------------------------------------------------------------------


class TestBackfillIdempotency:
    """Backfill exits immediately when DateRecord rows already exist."""

    async def test_no_pipeline_called_when_records_exist(self):
        session = _make_session(has_records=True)
        factory = _make_session_factory(session)

        with (
            patch("src.scheduler.jobs.get_settings") as mock_settings,
            patch("src.scheduler.jobs._today", return_value=_SUN_APR_19),
            patch("src.scheduler.jobs.Fetcher") as mock_fetcher_cls,
            patch("src.scheduler.jobs.DailyDigestGenerator") as mock_daily_cls,
            patch("src.scheduler.jobs.WeeklyDigestGenerator") as mock_weekly_cls,
        ):
            settings = MagicMock()
            settings.INCEPTION_DATE = _MON_APR_13
            mock_settings.return_value = settings

            await run_inception_backfill(factory)

        mock_fetcher_cls.return_value.fetch_papers.assert_not_called()
        mock_daily_cls.return_value.generate.assert_not_called()
        mock_weekly_cls.return_value.generate.assert_not_called()
        session.add.assert_not_called()


# ---------------------------------------------------------------------------
# Backfill: pipeline for announcement days
# ---------------------------------------------------------------------------


class TestBackfillPipeline:
    """Full pipeline runs correctly for published announcement days."""

    async def test_process_and_detect_called_for_published_papers(self):
        # Range: Mon Apr 13 only (today = Tue Apr 14)
        mock_arxiv_result = MagicMock()
        mock_paper = MagicMock()

        session = _make_session(has_records=False)
        factory = _make_session_factory(session)

        with (
            patch("src.scheduler.jobs.get_settings") as mock_settings,
            patch("src.scheduler.jobs._today", return_value=_TUE_APR_14),
            patch("src.scheduler.jobs.Fetcher") as mock_fetcher_cls,
            patch("src.scheduler.jobs.process_paper", new_callable=AsyncMock, return_value=mock_paper) as mock_process,
            patch("src.scheduler.jobs.detect_groundbreaking", new_callable=AsyncMock) as mock_detect,
            patch("src.scheduler.jobs.DailyDigestGenerator") as mock_daily_cls,
            patch("src.scheduler.jobs.WeeklyDigestGenerator") as mock_weekly_cls,
        ):
            mock_daily_cls.return_value.generate = AsyncMock(return_value=None)
            mock_weekly_cls.return_value.generate = AsyncMock(return_value=None)
            fetch_result = _make_fetch_result("published", papers=[mock_arxiv_result])
            mock_fetcher_cls.return_value.fetch_papers = AsyncMock(return_value=fetch_result)

            settings = MagicMock()
            settings.INCEPTION_DATE = _MON_APR_13
            mock_settings.return_value = settings

            await run_inception_backfill(factory)

        mock_process.assert_called_once_with(mock_arxiv_result, session)
        mock_detect.assert_called_once_with(mock_paper, session)
        mock_daily_cls.return_value.generate.assert_called_once_with(_MON_APR_13, session)

    async def test_detect_skipped_when_process_returns_none(self):
        # process_paper returns None (e.g. duplicate arXiv ID) — detect skipped
        mock_arxiv_result = MagicMock()

        session = _make_session(has_records=False)
        factory = _make_session_factory(session)

        with (
            patch("src.scheduler.jobs.get_settings") as mock_settings,
            patch("src.scheduler.jobs._today", return_value=_TUE_APR_14),
            patch("src.scheduler.jobs.Fetcher") as mock_fetcher_cls,
            patch("src.scheduler.jobs.process_paper", new_callable=AsyncMock, return_value=None),
            patch("src.scheduler.jobs.detect_groundbreaking", new_callable=AsyncMock) as mock_detect,
            patch("src.scheduler.jobs.DailyDigestGenerator") as mock_daily_cls,
            patch("src.scheduler.jobs.WeeklyDigestGenerator") as mock_weekly_cls,
        ):
            mock_daily_cls.return_value.generate = AsyncMock(return_value=None)
            mock_weekly_cls.return_value.generate = AsyncMock(return_value=None)
            fetch_result = _make_fetch_result("published", papers=[mock_arxiv_result])
            mock_fetcher_cls.return_value.fetch_papers = AsyncMock(return_value=fetch_result)

            settings = MagicMock()
            settings.INCEPTION_DATE = _MON_APR_13
            mock_settings.return_value = settings

            await run_inception_backfill(factory)

        mock_detect.assert_not_called()

    async def test_pipeline_skipped_for_non_published_fetch(self):
        # Non-published fetch → process/detect/daily must not be called
        session = _make_session(has_records=False)
        factory = _make_session_factory(session)

        with (
            patch("src.scheduler.jobs.get_settings") as mock_settings,
            patch("src.scheduler.jobs._today", return_value=_TUE_APR_14),
            patch("src.scheduler.jobs.Fetcher") as mock_fetcher_cls,
            patch("src.scheduler.jobs.process_paper", new_callable=AsyncMock) as mock_process,
            patch("src.scheduler.jobs.detect_groundbreaking", new_callable=AsyncMock) as mock_detect,
            patch("src.scheduler.jobs.DailyDigestGenerator") as mock_daily_cls,
            patch("src.scheduler.jobs.WeeklyDigestGenerator") as mock_weekly_cls,
        ):
            mock_daily_cls.return_value.generate = AsyncMock(return_value=None)
            mock_weekly_cls.return_value.generate = AsyncMock(return_value=None)
            mock_fetcher_cls.return_value.fetch_papers = AsyncMock(
                return_value=_make_fetch_result("no_papers_skip")
            )
            settings = MagicMock()
            settings.INCEPTION_DATE = _MON_APR_13
            mock_settings.return_value = settings

            await run_inception_backfill(factory)

        mock_process.assert_not_called()
        mock_detect.assert_not_called()
        mock_daily_cls.return_value.generate.assert_not_called()

    async def test_daily_generator_none_does_not_halt_backfill(self):
        # Two announcement days (Mon 13, Tue 14); first generate returns None,
        # second must still run. Fetch returns published so the generator is reached.
        mock_arxiv_result = MagicMock()

        session = _make_session(has_records=False)
        factory = _make_session_factory(session)

        with (
            patch("src.scheduler.jobs.get_settings") as mock_settings,
            # today = Wed Apr 15 → yesterday = Tue Apr 14; range = Mon 13, Tue 14
            patch("src.scheduler.jobs._today", return_value=_WED_APR_15),
            patch("src.scheduler.jobs.Fetcher") as mock_fetcher_cls,
            patch("src.scheduler.jobs.process_paper", new_callable=AsyncMock, return_value=MagicMock()),
            patch("src.scheduler.jobs.detect_groundbreaking", new_callable=AsyncMock),
            patch("src.scheduler.jobs.DailyDigestGenerator") as mock_daily_cls,
            patch("src.scheduler.jobs.WeeklyDigestGenerator") as mock_weekly_cls,
        ):
            # First call → None; second call → a mock digest object
            mock_daily_cls.return_value.generate = AsyncMock(
                side_effect=[None, MagicMock()]
            )
            mock_weekly_cls.return_value.generate = AsyncMock(return_value=None)
            # published so _run_pipeline_for_date reaches DailyDigestGenerator.generate
            mock_fetcher_cls.return_value.fetch_papers = AsyncMock(
                return_value=_make_fetch_result("published", papers=[mock_arxiv_result])
            )
            settings = MagicMock()
            settings.INCEPTION_DATE = _MON_APR_13
            mock_settings.return_value = settings

            await run_inception_backfill(factory)

        # generate called for both Mon Apr 13 and Tue Apr 14
        assert mock_daily_cls.return_value.generate.call_count == 2


# ---------------------------------------------------------------------------
# Backfill: weekly generator call count and graceful None handling
# ---------------------------------------------------------------------------


class TestBackfillWeeklyGenerator:
    """Weekly generator called once per complete or partial Sun-Thu week."""

    async def test_weekly_generator_called_once_for_one_week(self):
        # Range: Sun Apr 19 → Sat Apr 25; today = Sun Apr 26
        session = _make_session(has_records=False)
        factory = _make_session_factory(session)

        with (
            patch("src.scheduler.jobs.get_settings") as mock_settings,
            patch("src.scheduler.jobs._today", return_value=_SUN_APR_26),
            patch("src.scheduler.jobs.Fetcher") as mock_fetcher_cls,
            patch("src.scheduler.jobs.process_paper", new_callable=AsyncMock),
            patch("src.scheduler.jobs.detect_groundbreaking", new_callable=AsyncMock),
            patch("src.scheduler.jobs.DailyDigestGenerator") as mock_daily_cls,
            patch("src.scheduler.jobs.WeeklyDigestGenerator") as mock_weekly_cls,
        ):
            mock_daily_cls.return_value.generate = AsyncMock(return_value=None)
            mock_weekly_inst = mock_weekly_cls.return_value
            mock_weekly_inst.generate = AsyncMock(return_value=None)
            mock_fetcher_cls.return_value.fetch_papers = AsyncMock(
                return_value=_make_fetch_result("no_papers_skip")
            )
            settings = MagicMock()
            settings.INCEPTION_DATE = _SUN_APR_19
            mock_settings.return_value = settings

            await run_inception_backfill(factory)

        assert mock_weekly_inst.generate.call_count == 1
        assert mock_weekly_inst.generate.call_args_list[0].args[0] == _SUN_APR_19

    async def test_weekly_generator_called_twice_for_two_weeks(self):
        # Range: Sun Apr 19 → Thu Apr 30; today = Fri May 1 → two weeks
        session = _make_session(has_records=False)
        factory = _make_session_factory(session)

        with (
            patch("src.scheduler.jobs.get_settings") as mock_settings,
            patch("src.scheduler.jobs._today", return_value=datetime.date(2026, 5, 1)),
            patch("src.scheduler.jobs.Fetcher") as mock_fetcher_cls,
            patch("src.scheduler.jobs.process_paper", new_callable=AsyncMock),
            patch("src.scheduler.jobs.detect_groundbreaking", new_callable=AsyncMock),
            patch("src.scheduler.jobs.DailyDigestGenerator") as mock_daily_cls,
            patch("src.scheduler.jobs.WeeklyDigestGenerator") as mock_weekly_cls,
        ):
            mock_daily_cls.return_value.generate = AsyncMock(return_value=None)
            mock_weekly_inst = mock_weekly_cls.return_value
            mock_weekly_inst.generate = AsyncMock(return_value=None)
            mock_fetcher_cls.return_value.fetch_papers = AsyncMock(
                return_value=_make_fetch_result("no_papers_skip")
            )
            settings = MagicMock()
            settings.INCEPTION_DATE = _SUN_APR_19
            mock_settings.return_value = settings

            await run_inception_backfill(factory)

        assert mock_weekly_inst.generate.call_count == 2
        week_starts = [c.args[0] for c in mock_weekly_inst.generate.call_args_list]
        assert week_starts[0] == _SUN_APR_19
        assert week_starts[1] == _SUN_APR_26

    async def test_weekly_called_for_partial_week_starting_before_inception(self):
        # inception = Mon Apr 13 (mid-week); derived week_start = Sun Apr 12
        session = _make_session(has_records=False)
        factory = _make_session_factory(session)

        with (
            patch("src.scheduler.jobs.get_settings") as mock_settings,
            patch("src.scheduler.jobs._today", return_value=_SUN_APR_19),
            patch("src.scheduler.jobs.Fetcher") as mock_fetcher_cls,
            patch("src.scheduler.jobs.process_paper", new_callable=AsyncMock),
            patch("src.scheduler.jobs.detect_groundbreaking", new_callable=AsyncMock),
            patch("src.scheduler.jobs.DailyDigestGenerator") as mock_daily_cls,
            patch("src.scheduler.jobs.WeeklyDigestGenerator") as mock_weekly_cls,
        ):
            mock_daily_cls.return_value.generate = AsyncMock(return_value=None)
            mock_weekly_inst = mock_weekly_cls.return_value
            mock_weekly_inst.generate = AsyncMock(return_value=None)
            mock_fetcher_cls.return_value.fetch_papers = AsyncMock(
                return_value=_make_fetch_result("no_papers_skip")
            )
            settings = MagicMock()
            settings.INCEPTION_DATE = _MON_APR_13
            mock_settings.return_value = settings

            await run_inception_backfill(factory)

        assert mock_weekly_inst.generate.call_count == 1
        assert mock_weekly_inst.generate.call_args_list[0].args[0] == _SUN_APR_12

    async def test_weekly_generator_none_does_not_halt_backfill(self):
        # Two weeks; first generate returns None, second should still run.
        session = _make_session(has_records=False)
        factory = _make_session_factory(session)

        with (
            patch("src.scheduler.jobs.get_settings") as mock_settings,
            patch("src.scheduler.jobs._today", return_value=datetime.date(2026, 5, 1)),
            patch("src.scheduler.jobs.Fetcher") as mock_fetcher_cls,
            patch("src.scheduler.jobs.process_paper", new_callable=AsyncMock),
            patch("src.scheduler.jobs.detect_groundbreaking", new_callable=AsyncMock),
            patch("src.scheduler.jobs.DailyDigestGenerator") as mock_daily_cls,
            patch("src.scheduler.jobs.WeeklyDigestGenerator") as mock_weekly_cls,
        ):
            mock_daily_cls.return_value.generate = AsyncMock(return_value=None)
            mock_weekly_inst = mock_weekly_cls.return_value
            # First week returns None (no daily digests); second week returns a digest
            mock_weekly_inst.generate = AsyncMock(side_effect=[None, MagicMock()])
            mock_fetcher_cls.return_value.fetch_papers = AsyncMock(
                return_value=_make_fetch_result("no_papers_skip")
            )
            settings = MagicMock()
            settings.INCEPTION_DATE = _SUN_APR_19
            mock_settings.return_value = settings

            await run_inception_backfill(factory)

        assert mock_weekly_inst.generate.call_count == 2


# ---------------------------------------------------------------------------
# _run_daily_job
# ---------------------------------------------------------------------------


class TestRunDailyJob:
    """Daily job skips Fri/Sat; runs the pipeline for announcement days."""

    async def test_announcement_day_runs_pipeline(self):
        session = _make_session()
        factory = _make_session_factory(session)

        with (
            patch("src.scheduler.jobs._today", return_value=_MON_APR_13),
            patch("src.scheduler.jobs.Fetcher") as mock_fetcher_cls,
            patch("src.scheduler.jobs.process_paper", new_callable=AsyncMock),
            patch("src.scheduler.jobs.detect_groundbreaking", new_callable=AsyncMock),
            patch("src.scheduler.jobs.DailyDigestGenerator") as mock_daily_cls,
        ):
            mock_daily_cls.return_value.generate = AsyncMock(return_value=None)
            mock_fetcher_cls.return_value.fetch_papers = AsyncMock(
                return_value=_make_fetch_result("no_papers_skip")
            )
            await _run_daily_job(factory)

        mock_fetcher_cls.return_value.fetch_papers.assert_called_once_with(_MON_APR_13, session)

    async def test_friday_skips_pipeline(self):
        factory = _make_session_factory(_make_session())

        with (
            patch("src.scheduler.jobs._today", return_value=_FRI_APR_17),
            patch("src.scheduler.jobs.Fetcher") as mock_fetcher_cls,
        ):
            await _run_daily_job(factory)

        mock_fetcher_cls.return_value.fetch_papers.assert_not_called()

    async def test_saturday_skips_pipeline(self):
        factory = _make_session_factory(_make_session())

        with (
            patch("src.scheduler.jobs._today", return_value=_SAT_APR_18),
            patch("src.scheduler.jobs.Fetcher") as mock_fetcher_cls,
        ):
            await _run_daily_job(factory)

        mock_fetcher_cls.return_value.fetch_papers.assert_not_called()


# ---------------------------------------------------------------------------
# _run_weekly_job
# ---------------------------------------------------------------------------


class TestRunWeeklyJob:
    """Weekly job fires on Friday only; other weekdays exit without running."""

    async def test_friday_calls_generator_with_most_recent_sunday(self):
        # today = Fri Apr 17; _get_week_start(Apr 17) = Sun Apr 12
        session = _make_session()
        factory = _make_session_factory(session)

        with (
            patch("src.scheduler.jobs._today", return_value=_FRI_APR_17),
            patch("src.scheduler.jobs.WeeklyDigestGenerator") as mock_weekly_cls,
        ):
            mock_weekly_cls.return_value.generate = AsyncMock(return_value=None)
            await _run_weekly_job(factory)

        mock_weekly_cls.return_value.generate.assert_called_once_with(_SUN_APR_12, session)

    @pytest.mark.parametrize(
        "today",
        [
            _MON_APR_13,  # Monday
            _TUE_APR_14,  # Tuesday
            _WED_APR_15,  # Wednesday
            _THU_APR_16,  # Thursday
            _SAT_APR_18,  # Saturday
            _SUN_APR_19,  # Sunday
        ],
        ids=["Monday", "Tuesday", "Wednesday", "Thursday", "Saturday", "Sunday"],
    )
    async def test_non_friday_skips_generator(self, today: datetime.date):
        factory = _make_session_factory(_make_session())

        with (
            patch("src.scheduler.jobs._today", return_value=today),
            patch("src.scheduler.jobs.WeeklyDigestGenerator") as mock_weekly_cls,
        ):
            await _run_weekly_job(factory)

        mock_weekly_cls.return_value.generate.assert_not_called()


# ---------------------------------------------------------------------------
# setup_scheduler
# ---------------------------------------------------------------------------


class TestSetupScheduler:
    """Daily and weekly cron strings are forwarded to CronTrigger.from_crontab."""

    def test_daily_job_cron_matches_daily_scheduler_time(self):
        custom_daily = "0 21 * * 0,1,2,3,4"
        mock_scheduler = MagicMock()

        with (
            patch("src.scheduler.jobs.get_settings") as mock_settings,
            patch("src.scheduler.jobs.CronTrigger") as mock_cron,
        ):
            settings = MagicMock()
            settings.DAILY_SCHEDULER_TIME = custom_daily
            settings.WEEKLY_SCHEDULER_TIME = "0 1 * * 5"
            mock_settings.return_value = settings

            setup_scheduler(mock_scheduler, MagicMock())

        cron_args = [c.args[0] for c in mock_cron.from_crontab.call_args_list]
        assert custom_daily in cron_args

    def test_weekly_job_cron_matches_weekly_scheduler_time(self):
        custom_weekly = "0 3 * * 5"
        mock_scheduler = MagicMock()

        with (
            patch("src.scheduler.jobs.get_settings") as mock_settings,
            patch("src.scheduler.jobs.CronTrigger") as mock_cron,
        ):
            settings = MagicMock()
            settings.DAILY_SCHEDULER_TIME = "30 20 * * 0,1,2,3,4"
            settings.WEEKLY_SCHEDULER_TIME = custom_weekly
            mock_settings.return_value = settings

            setup_scheduler(mock_scheduler, MagicMock())

        cron_args = [c.args[0] for c in mock_cron.from_crontab.call_args_list]
        assert custom_weekly in cron_args

    def test_both_jobs_registered_with_new_york_timezone(self):
        mock_scheduler = MagicMock()

        with (
            patch("src.scheduler.jobs.get_settings") as mock_settings,
            patch("src.scheduler.jobs.CronTrigger") as mock_cron,
        ):
            settings = MagicMock()
            settings.DAILY_SCHEDULER_TIME = "30 20 * * 0,1,2,3,4"
            settings.WEEKLY_SCHEDULER_TIME = "0 1 * * 5"
            mock_settings.return_value = settings

            setup_scheduler(mock_scheduler, MagicMock())

        assert mock_cron.from_crontab.call_count == 2
        assert mock_scheduler.add_job.call_count == 2
        for c in mock_cron.from_crontab.call_args_list:
            assert c.kwargs.get("timezone") == "America/New_York"
