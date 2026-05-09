"""Unit tests for src/pipeline/weekly_generator.py.

Covers (per T022):
- fetch_failure_skip dates appear in fetch_failure_skips and NOT in no_papers_skips.
- A week with zero daily digests returns None.
- All three Markdown sections are non-empty when daily digests exist.
- week_start must be a Sunday (ValueError for any other weekday).
- days_with_content, no_papers_skips, and fetch_failure_skips each contain
  exactly the dates that match their corresponding status.
"""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.constants import (
    DATE_STATUS_FETCH_FAILURE_SKIP,
    DATE_STATUS_NO_PAPERS_SKIP,
    DATE_STATUS_PUBLISHED,
)
from src.db.models import DailyDigest, DateRecord, TopicSection
from src.pipeline.weekly_generator import WeeklyDigestGenerator

_WEEK_START = datetime.date(2026, 4, 19)  # Sunday
_WEEK_END = datetime.date(2026, 4, 23)    # Thursday


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_section(body: str = "## Research\n\nSome findings.") -> MagicMock:
    s = MagicMock(spec=TopicSection)
    s.name = "Large Language Models"
    s.paper_count = 3
    s.body = body
    return s


def _make_digest(
    date: datetime.date,
    paper_count: int = 5,
    groundbreaking_count: int = 1,
) -> MagicMock:
    d = MagicMock(spec=DailyDigest)
    d.date = date
    d.paper_count = paper_count
    d.groundbreaking_count = groundbreaking_count
    d.topic_sections = [_make_section()]
    return d


def _make_date_record(date: datetime.date, status: str) -> MagicMock:
    dr = MagicMock(spec=DateRecord)
    dr.date = date
    dr.status = status
    return dr


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


def _make_execute_result(items: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


def _make_section_result(content: str = "## Synthesis\n\nDetails.") -> MagicMock:
    m = MagicMock()
    m.content = content
    return m


# ---------------------------------------------------------------------------
# Tests: week_start validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "non_sunday",
    [
        datetime.date(2026, 4, 20),  # Monday
        datetime.date(2026, 4, 21),  # Tuesday
        datetime.date(2026, 4, 22),  # Wednesday
        datetime.date(2026, 4, 23),  # Thursday
        datetime.date(2026, 4, 24),  # Friday
        datetime.date(2026, 4, 25),  # Saturday
    ],
)
async def test_non_sunday_week_start_raises(non_sunday: datetime.date) -> None:
    """ValueError is raised for any week_start that is not a Sunday."""
    session = _make_session()
    with pytest.raises(ValueError, match="Sunday"):
        await WeeklyDigestGenerator().generate(non_sunday, session)


# ---------------------------------------------------------------------------
# Tests: zero daily digests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_daily_digests_returns_none() -> None:
    """A week with no daily digests produces no WeeklyDigest."""
    session = _make_session()
    session.execute = AsyncMock(return_value=_make_execute_result([]))

    with patch("src.pipeline.weekly_generator.parse_structured", new=AsyncMock()):
        result = await WeeklyDigestGenerator().generate(_WEEK_START, session)

    assert result is None
    session.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests: three synthesis sections non-empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_three_sections_non_empty_when_digests_exist() -> None:
    """benchmark_comparisons, trend_synthesis, cross_paper_analysis are all non-empty."""
    digests = [_make_digest(_WEEK_START)]
    date_records = [_make_date_record(_WEEK_START, DATE_STATUS_PUBLISHED)]

    session = _make_session()
    session.execute = AsyncMock(
        side_effect=[
            _make_execute_result(digests),
            _make_execute_result(date_records),
        ]
    )

    with patch(
        "src.pipeline.weekly_generator.parse_structured",
        new=AsyncMock(return_value=_make_section_result()),
    ):
        result = await WeeklyDigestGenerator().generate(_WEEK_START, session)

    assert result is not None
    assert result.benchmark_comparisons
    assert result.trend_synthesis
    assert result.cross_paper_analysis


# ---------------------------------------------------------------------------
# Tests: coverage arrays — individual status routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_failure_skip_in_correct_array() -> None:
    """fetch_failure_skip dates go into fetch_failure_skips, not no_papers_skips."""
    failure_date = datetime.date(2026, 4, 22)  # Wednesday

    digests = [_make_digest(_WEEK_START)]
    date_records = [
        _make_date_record(_WEEK_START, DATE_STATUS_PUBLISHED),
        _make_date_record(failure_date, DATE_STATUS_FETCH_FAILURE_SKIP),
    ]

    session = _make_session()
    session.execute = AsyncMock(
        side_effect=[
            _make_execute_result(digests),
            _make_execute_result(date_records),
        ]
    )

    with patch(
        "src.pipeline.weekly_generator.parse_structured",
        new=AsyncMock(return_value=_make_section_result()),
    ):
        result = await WeeklyDigestGenerator().generate(_WEEK_START, session)

    assert result is not None
    assert failure_date in result.fetch_failure_skips
    assert failure_date not in result.no_papers_skips


@pytest.mark.asyncio
async def test_no_papers_skip_in_correct_array() -> None:
    """no_papers_skip dates go into no_papers_skips, not fetch_failure_skips."""
    skip_date = datetime.date(2026, 4, 21)  # Tuesday

    digests = [_make_digest(_WEEK_START)]
    date_records = [
        _make_date_record(_WEEK_START, DATE_STATUS_PUBLISHED),
        _make_date_record(skip_date, DATE_STATUS_NO_PAPERS_SKIP),
    ]

    session = _make_session()
    session.execute = AsyncMock(
        side_effect=[
            _make_execute_result(digests),
            _make_execute_result(date_records),
        ]
    )

    with patch(
        "src.pipeline.weekly_generator.parse_structured",
        new=AsyncMock(return_value=_make_section_result()),
    ):
        result = await WeeklyDigestGenerator().generate(_WEEK_START, session)

    assert result is not None
    assert skip_date in result.no_papers_skips
    assert skip_date not in result.fetch_failure_skips


# ---------------------------------------------------------------------------
# Tests: all three coverage arrays populated correctly in one week
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_coverage_arrays_correctly_populated() -> None:
    """days_with_content, no_papers_skips, and fetch_failure_skips each hold
    exactly the dates matching their corresponding status across a full week."""
    # Sun: published digest, Mon: no_papers_skip, Tue: fetch_failure_skip
    sunday = datetime.date(2026, 4, 19)
    monday = datetime.date(2026, 4, 20)
    tuesday = datetime.date(2026, 4, 21)

    digests = [_make_digest(sunday)]
    date_records = [
        _make_date_record(sunday, DATE_STATUS_PUBLISHED),
        _make_date_record(monday, DATE_STATUS_NO_PAPERS_SKIP),
        _make_date_record(tuesday, DATE_STATUS_FETCH_FAILURE_SKIP),
    ]

    session = _make_session()
    session.execute = AsyncMock(
        side_effect=[
            _make_execute_result(digests),
            _make_execute_result(date_records),
        ]
    )

    with patch(
        "src.pipeline.weekly_generator.parse_structured",
        new=AsyncMock(return_value=_make_section_result()),
    ):
        result = await WeeklyDigestGenerator().generate(_WEEK_START, session)

    assert result is not None

    assert sunday in result.days_with_content
    assert monday not in result.days_with_content
    assert tuesday not in result.days_with_content

    assert monday in result.no_papers_skips
    assert sunday not in result.no_papers_skips
    assert tuesday not in result.no_papers_skips

    assert tuesday in result.fetch_failure_skips
    assert sunday not in result.fetch_failure_skips
    assert monday not in result.fetch_failure_skips
