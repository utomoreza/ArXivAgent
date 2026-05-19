"""Unit tests for src/pipeline/fetcher.py.

Covers all four DateRecord outcomes:
- no_announcement: Fri/Sat input → no API call, record written
- published: successful fetch → record + papers returned
- fetch_failure_skip: 3 consecutive API failures → record written
- no_papers_skip: API returns empty list → record written
"""

import asyncio
import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import arxiv
import pytest

from src.db import constants
from src.pipeline.fetcher import Fetcher

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(date: datetime.date) -> MagicMock:
    """Return a mock arxiv.Result published on *date*."""
    r = MagicMock(spec=arxiv.Result)
    r.published = datetime.datetime(
        date.year, date.month, date.day, tzinfo=datetime.UTC
    )
    r.title = f"Test Paper {date}"
    r.entry_id = f"http://arxiv.org/abs/2604.{date.day:05d}v1"
    return r


def _make_session() -> AsyncMock:
    """Return a minimal mock AsyncSession."""
    session = AsyncMock()
    session.add = MagicMock()  # session.add is synchronous
    session.commit = AsyncMock()
    return session


def _make_fetcher(mock_client: MagicMock) -> Fetcher:
    """Return a Fetcher with injected mock client and search."""
    return Fetcher(client=mock_client, search=MagicMock(spec=arxiv.Search))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace asyncio.sleep with a no-op so retry tests finish instantly."""
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())


@pytest.fixture
def mock_client() -> MagicMock:
    """Return a mock arxiv.Client instance."""
    return MagicMock()


@pytest.fixture
def fetcher(mock_client: MagicMock) -> Fetcher:
    """Return a Fetcher with injected mocks — never hits the real arXiv API."""
    return _make_fetcher(mock_client)


# ---------------------------------------------------------------------------
# Fri/Sat → no_announcement (no API call)
# ---------------------------------------------------------------------------


async def test_friday_writes_no_announcement_without_api_call(
    fetcher: Fetcher,
    mock_client: MagicMock,
) -> None:
    """Friday input records no_announcement and does not call the arXiv API."""
    friday = datetime.date(2026, 5, 1)  # confirmed Friday
    assert friday.weekday() == 4
    session = _make_session()

    result = await fetcher.fetch_papers(friday, session)

    assert result.status == constants.DATE_STATUS_NO_ANNOUNCEMENT
    assert result.papers == []
    mock_client.results.assert_not_called()
    session.add.assert_called_once()
    record = session.add.call_args[0][0]
    assert record.date == friday
    assert record.status == constants.DATE_STATUS_NO_ANNOUNCEMENT
    session.commit.assert_awaited_once()


async def test_saturday_writes_no_announcement_without_api_call(
    fetcher: Fetcher,
    mock_client: MagicMock,
) -> None:
    """Saturday input records no_announcement and does not call the arXiv API."""
    saturday = datetime.date(2026, 5, 2)  # confirmed Saturday
    assert saturday.weekday() == 5
    session = _make_session()

    result = await fetcher.fetch_papers(saturday, session)

    assert result.status == constants.DATE_STATUS_NO_ANNOUNCEMENT
    assert result.papers == []
    mock_client.results.assert_not_called()


# ---------------------------------------------------------------------------
# Successful fetch → published
# ---------------------------------------------------------------------------


async def test_successful_fetch_writes_published_and_returns_papers(
    fetcher: Fetcher,
    mock_client: MagicMock,
) -> None:
    """Successful API response writes a published DateRecord and returns papers."""
    monday = datetime.date(2026, 4, 27)  # confirmed Monday
    assert monday.weekday() == 0
    paper = _make_result(monday)
    mock_client.results.return_value = [paper]
    session = _make_session()

    result = await fetcher.fetch_papers(monday, session)

    assert result.status == constants.DATE_STATUS_PUBLISHED
    assert len(result.papers) == 1
    assert result.papers[0] is paper
    session.add.assert_called_once()
    record = session.add.call_args[0][0]
    assert record.date == monday
    assert record.status == constants.DATE_STATUS_PUBLISHED
    assert record.paper_count == 1
    session.commit.assert_awaited_once()


async def test_paper_count_on_date_record_matches_returned_papers(
    fetcher: Fetcher,
    mock_client: MagicMock,
) -> None:
    """paper_count on the DateRecord equals the number of matching papers."""
    monday = datetime.date(2026, 4, 28)
    mock_client.results.return_value = [_make_result(monday) for _ in range(5)]
    session = _make_session()

    result = await fetcher.fetch_papers(monday, session)

    assert len(result.papers) == 5
    record = session.add.call_args[0][0]
    assert record.paper_count == 5


async def test_papers_from_other_dates_in_api_response_are_excluded(
    fetcher: Fetcher,
    mock_client: MagicMock,
) -> None:
    """The arXiv category feed can include papers from adjacent dates (timezone
    boundary effects). The fetcher must return only papers whose published date
    matches the requested date; papers from other dates are silently dropped.
    """
    monday = datetime.date(2026, 4, 28)
    tuesday = datetime.date(2026, 4, 29)
    paper_monday = _make_result(monday)
    paper_tuesday = _make_result(tuesday)
    # API returns both; fetcher should keep only Monday's paper
    mock_client.results.return_value = [paper_monday, paper_tuesday]
    session = _make_session()

    result = await fetcher.fetch_papers(monday, session)

    assert result.status == constants.DATE_STATUS_PUBLISHED
    assert len(result.papers) == 1
    assert result.papers[0] is paper_monday


# ---------------------------------------------------------------------------
# Three consecutive failures → fetch_failure_skip
# ---------------------------------------------------------------------------


async def test_three_failures_write_fetch_failure_skip(
    fetcher: Fetcher,
    mock_client: MagicMock,
    fast_sleep: None,
) -> None:
    """Three consecutive API errors write fetch_failure_skip and retry 3 times."""
    monday = datetime.date(2026, 4, 28)
    mock_client.results.side_effect = Exception("arXiv API down")
    session = _make_session()

    result = await fetcher.fetch_papers(monday, session)

    assert result.status == constants.DATE_STATUS_FETCH_FAILURE_SKIP
    assert result.papers == []
    assert mock_client.results.call_count == 3
    session.add.assert_called_once()
    record = session.add.call_args[0][0]
    assert record.date == monday
    assert record.status == constants.DATE_STATUS_FETCH_FAILURE_SKIP
    session.commit.assert_awaited_once()


async def test_retry_succeeds_on_second_attempt(
    fetcher: Fetcher,
    mock_client: MagicMock,
) -> None:
    """One failure followed by a success writes published (retry recovery)."""
    monday = datetime.date(2026, 4, 27)
    paper = _make_result(monday)
    mock_client.results.side_effect = [Exception("transient error"), [paper]]
    session = _make_session()

    result = await fetcher.fetch_papers(monday, session)

    assert result.status == constants.DATE_STATUS_PUBLISHED
    assert len(result.papers) == 1
    assert mock_client.results.call_count == 2


async def test_retry_uses_exponential_backoff(
    monkeypatch: pytest.MonkeyPatch,
    fetcher: Fetcher,
    mock_client: MagicMock,
) -> None:
    """Exponential backoff sleep is called between retry attempts.

    3 attempts → 2 inter-attempt sleeps (no sleep after the final failure).
    Delays must be 2**0=1 s then 2**1=2 s.
    """
    sleep_mock = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep_mock)

    monday = datetime.date(2026, 4, 27)
    mock_client.results.side_effect = Exception("fail")
    session = _make_session()

    await fetcher.fetch_papers(monday, session)

    assert sleep_mock.call_count == 2
    delays = [call.args[0] for call in sleep_mock.call_args_list]
    assert delays == [1, 2]


# ---------------------------------------------------------------------------
# Empty list → no_papers_skip
# ---------------------------------------------------------------------------


async def test_empty_api_response_writes_no_papers_skip(
    fetcher: Fetcher,
    mock_client: MagicMock,
) -> None:
    """API returning an empty list writes no_papers_skip DateRecord."""
    monday = datetime.date(2026, 4, 28)
    mock_client.results.return_value = []
    session = _make_session()

    result = await fetcher.fetch_papers(monday, session)

    assert result.status == constants.DATE_STATUS_NO_PAPERS_SKIP
    assert result.papers == []
    session.add.assert_called_once()
    record = session.add.call_args[0][0]
    assert record.date == monday
    assert record.status == constants.DATE_STATUS_NO_PAPERS_SKIP
    session.commit.assert_awaited_once()


async def test_all_papers_from_wrong_date_treated_as_no_papers_skip(
    fetcher: Fetcher,
    mock_client: MagicMock,
) -> None:
    """If the API returns papers but all are from a different date, treat the
    result the same as an empty response: write no_papers_skip.
    """
    monday = datetime.date(2026, 4, 27)
    tuesday = datetime.date(2026, 4, 28)
    mock_client.results.return_value = [_make_result(tuesday)]
    session = _make_session()

    result = await fetcher.fetch_papers(monday, session)

    assert result.status == constants.DATE_STATUS_NO_PAPERS_SKIP
    assert result.papers == []
    record = session.add.call_args[0][0]
    assert record.status == constants.DATE_STATUS_NO_PAPERS_SKIP


# ---------------------------------------------------------------------------
# _build_search — lazy initialisation via DI
# ---------------------------------------------------------------------------


def test_build_search_constructs_arxiv_search_from_settings() -> None:
    """Fetcher._build_search(date) creates an arxiv.Search using ARXIV_CATEGORIES
    from settings when no search is injected at construction time.
    """
    fake_settings = MagicMock()
    fake_settings.ARXIV_CATEGORIES = ["cs.LG", "cs.CV"]

    with patch("src.pipeline.fetcher.get_settings", return_value=fake_settings):
        f = Fetcher(client=MagicMock())
        result = f._build_search(datetime.date(2026, 5, 20))  # Tuesday

    assert isinstance(result, arxiv.Search)
    assert "cat:cs.LG" in result.query
    assert "submittedDate:" in result.query


def test_injected_search_skips_build_search() -> None:
    """When search= is injected, _build_search() must not call get_settings."""
    injected = MagicMock(spec=arxiv.Search)

    with patch("src.pipeline.fetcher.get_settings", side_effect=AssertionError("should not call get_settings")):
        f = Fetcher(client=MagicMock(), search=injected)

    assert f._search is injected
    assert f._build_search(datetime.date(2026, 5, 20)) is injected


def test_build_search_monday_uses_3_day_lookback() -> None:
    """Monday announcement window covers Fri+Sat+Sun+Mon (3 days back)."""
    fake_settings = MagicMock()
    fake_settings.ARXIV_CATEGORIES = ["cs.LG"]

    monday = datetime.date(2026, 5, 18)  # Monday
    with patch("src.pipeline.fetcher.get_settings", return_value=fake_settings):
        f = Fetcher(client=MagicMock())
        result = f._build_search(monday)

    # from_date = 2026-05-15 (Friday), to_date = 2026-05-18 (Monday)
    assert "20260515" in result.query
    assert "20260518" in result.query


def test_build_search_sunday_uses_3_day_lookback() -> None:
    """Sunday announcement window covers Thu+Fri+Sat+Sun (3 days back)."""
    fake_settings = MagicMock()
    fake_settings.ARXIV_CATEGORIES = ["cs.LG"]

    sunday = datetime.date(2026, 5, 17)  # Sunday
    with patch("src.pipeline.fetcher.get_settings", return_value=fake_settings):
        f = Fetcher(client=MagicMock())
        result = f._build_search(sunday)

    # from_date = 2026-05-14 (Thursday), to_date = 2026-05-17 (Sunday)
    assert "20260514" in result.query
    assert "20260517" in result.query
