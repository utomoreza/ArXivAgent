"""Integration tests for GET /digests/daily/{date} and GET /digests/weekly/{week_start_date}.

Requires a real PostgreSQL database — set TEST_DATABASE_URL env var.
All tests share the session-scoped engine/schema; each test rolls back after
itself to stay isolated.

Date legend (all in 2026, INCEPTION_DATE = 2026-01-05 Monday):
  _DATE_PUBLISHED       = 2026-01-12  (Monday)  — DateRecord status=published
  _DATE_NO_PAPERS       = 2026-01-13  (Tuesday)  — DateRecord status=no_papers_skip
  _DATE_FETCH_FAILURE   = 2026-01-14  (Wednesday) — DateRecord status=fetch_failure_skip
  _DATE_NO_ANNOUNCE     = 2026-01-10  (Saturday) — DateRecord status=no_announcement
  _DATE_BEFORE_INCEPTION= 2026-01-04  (Sunday)   — before INCEPTION_DATE
  _DATE_FUTURE          = 2026-12-01  (Tuesday)  — future date

Weekly date legend:
  _WEEK_OK_START        = 2026-04-19  (Sunday)   — WeeklyDigest seeded
  _WEEK_NOT_FOUND_START = 2025-12-28  (Sunday)   — before INCEPTION_DATE
  _WEEK_PENDING_START   = 2026-04-26  (Sunday)   — no WeeklyDigest (pending)
  _WEEK_NON_SUNDAY      = 2026-04-20  (Monday)   — triggers 400
"""

import datetime
import uuid

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.schemas import (
    CoverageNote,
    DailyDigestData,
    WeeklyDigestData,
    WeeklySections,
)
from src.db.models import Base, DailyDigest, DateRecord, TopicSection, WeeklyDigest

# ---------------------------------------------------------------------------
# Date constants
# ---------------------------------------------------------------------------

_INCEPTION_DATE = datetime.date(2026, 1, 5)

_DATE_PUBLISHED = datetime.date(2026, 1, 12)       # Monday
_DATE_NO_PAPERS = datetime.date(2026, 1, 13)       # Tuesday
_DATE_FETCH_FAILURE = datetime.date(2026, 1, 14)   # Wednesday
_DATE_NO_ANNOUNCE = datetime.date(2026, 1, 10)     # Saturday
_DATE_BEFORE_INCEPTION = datetime.date(2026, 1, 4) # Sunday
_DATE_FUTURE = datetime.date(2026, 12, 1)          # Tuesday

_WEEK_OK_START = datetime.date(2026, 4, 19)        # Sunday
_WEEK_OK_END = datetime.date(2026, 4, 23)          # Thursday
_WEEK_NOT_FOUND_START = datetime.date(2025, 12, 28) # Sunday, before inception
_WEEK_PENDING_START = datetime.date(2026, 4, 26)   # Sunday, no digest
_WEEK_NON_SUNDAY = datetime.date(2026, 4, 20)      # Monday

# ---------------------------------------------------------------------------
# Engine / schema fixtures (session-scoped)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Create a test engine, build the schema, yield, then drop it."""
    import os

    url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/arxiv_test",
    )
    eng = create_async_engine(url, echo=False)
    async with eng.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine):
    """Yield a fresh session per test; roll back after each test."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()


# ---------------------------------------------------------------------------
# FastAPI test client fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(session: AsyncSession):
    """Create a minimal FastAPI app with the digests router; override get_session."""
    from unittest.mock import patch

    from fastapi import FastAPI

    from src.api.deps import get_session
    from src.api.routers.digests import router

    app = FastAPI()
    app.include_router(router)

    async def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session

    with patch("src.api.routers.digests.get_settings") as mock_settings:
        mock_settings.return_value.INCEPTION_DATE = _INCEPTION_DATE
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_date_record(session: AsyncSession, date: datetime.date, status: str) -> DateRecord:
    record = DateRecord(date=date, status=status)
    session.add(record)
    await session.flush()
    return record


async def _seed_published_digest(session: AsyncSession) -> DailyDigest:
    """Seed a published DateRecord + DailyDigest + two TopicSections."""
    record = DateRecord(date=_DATE_PUBLISHED, status="published", paper_count=10)
    session.add(record)
    await session.flush()

    digest = DailyDigest(
        id=uuid.uuid4(),
        date=_DATE_PUBLISHED,
        generated_at=datetime.datetime(2026, 1, 12, 21, 5, 0, tzinfo=datetime.UTC),
        paper_count=10,
        groundbreaking_count=2,
    )
    session.add(digest)
    await session.flush()

    topic_a = TopicSection(
        id=uuid.uuid4(),
        digest_id=digest.id,
        name="Large Language Models",
        paper_count=7,
        body="## Large Language Models\n\nSome content.",
    )
    topic_b = TopicSection(
        id=uuid.uuid4(),
        digest_id=digest.id,
        name="Computer Vision",
        paper_count=3,
        body="## Computer Vision\n\nSome content.",
    )
    session.add_all([topic_a, topic_b])
    await session.flush()
    return digest


async def _seed_weekly_digest(session: AsyncSession) -> WeeklyDigest:
    """Seed a WeeklyDigest for _WEEK_OK_START."""
    digest = WeeklyDigest(
        id=uuid.uuid4(),
        week_start=_WEEK_OK_START,
        week_end=_WEEK_OK_END,
        generated_at=datetime.datetime(2026, 4, 24, 1, 5, 0, tzinfo=datetime.UTC),
        paper_count=50,
        groundbreaking_count=3,
        benchmark_comparisons="## Benchmark Comparisons\n\nContent.",
        trend_synthesis="## Trend Synthesis\n\nContent.",
        cross_paper_analysis="## Cross-Paper Analysis\n\nContent.",
        days_with_content=[datetime.date(2026, 4, 19), datetime.date(2026, 4, 20)],
        no_papers_skips=[],
        fetch_failure_skips=[datetime.date(2026, 4, 21)],
    )
    session.add(digest)
    await session.flush()
    return digest


# ---------------------------------------------------------------------------
# GET /digests/daily/{date} — 6 states
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_digest_future_date_returns_not_available(client: httpx.AsyncClient):
    """Future dates must return status=not_available with the standard reason."""
    resp = await client.get(f"/digests/daily/{_DATE_FUTURE}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "not_available"
    assert body["data"] is None
    assert "future" in body["reason"].lower()


@pytest.mark.asyncio
async def test_daily_digest_before_inception_returns_not_found(client: httpx.AsyncClient):
    """Dates before INCEPTION_DATE must return status=not_found."""
    resp = await client.get(f"/digests/daily/{_DATE_BEFORE_INCEPTION}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "not_found"
    assert body["data"] is None
    assert body["reason"] is not None


@pytest.mark.asyncio
async def test_daily_digest_no_announcement(client: httpx.AsyncClient, session: AsyncSession):
    """DateRecord.status=no_announcement must return status=no_announcement."""
    await _seed_date_record(session, _DATE_NO_ANNOUNCE, "no_announcement")
    resp = await client.get(f"/digests/daily/{_DATE_NO_ANNOUNCE}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "no_announcement"
    assert body["data"] is None
    assert "Friday" in body["reason"] or "Saturday" in body["reason"]


@pytest.mark.asyncio
async def test_daily_digest_no_papers_skip_returns_skipped(client: httpx.AsyncClient, session: AsyncSession):
    """DateRecord.status=no_papers_skip must return status=skipped."""
    await _seed_date_record(session, _DATE_NO_PAPERS, "no_papers_skip")
    resp = await client.get(f"/digests/daily/{_DATE_NO_PAPERS}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "skipped"
    assert body["data"] is None
    assert body["reason"] is not None


@pytest.mark.asyncio
async def test_daily_digest_fetch_failure_returns_fetch_failure(client: httpx.AsyncClient, session: AsyncSession):
    """DateRecord.status=fetch_failure_skip must return status=fetch_failure."""
    await _seed_date_record(session, _DATE_FETCH_FAILURE, "fetch_failure_skip")
    resp = await client.get(f"/digests/daily/{_DATE_FETCH_FAILURE}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "fetch_failure"
    assert body["data"] is None
    assert body["reason"] is not None


@pytest.mark.asyncio
async def test_daily_digest_published_returns_ok_with_full_document(
    client: httpx.AsyncClient, session: AsyncSession
):
    """DateRecord.status=published must return status=ok with the full digest."""
    await _seed_published_digest(session)
    resp = await client.get(f"/digests/daily/{_DATE_PUBLISHED}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["reason"] is None

    data = body["data"]
    assert data["type"] == "daily"
    assert data["date"] == str(_DATE_PUBLISHED)
    assert data["paper_count"] == 10
    assert data["groundbreaking_count"] == 2
    assert len(data["topics"]) == 2

    # Topics must be ordered by paper_count DESC
    assert data["topics"][0]["name"] == "Large Language Models"
    assert data["topics"][0]["paper_count"] == 7
    assert data["topics"][1]["name"] == "Computer Vision"
    assert data["topics"][1]["paper_count"] == 3

    for topic in data["topics"]:
        assert "name" in topic
        assert "paper_count" in topic
        assert "body" in topic


# ---------------------------------------------------------------------------
# GET /digests/weekly/{week_start_date} — validation + 3 states
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weekly_digest_non_sunday_returns_400(client: httpx.AsyncClient):
    """A non-Sunday week_start_date must return 400 with a validation_error body."""
    resp = await client.get(f"/digests/weekly/{_WEEK_NON_SUNDAY}")
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "validation_error"
    assert "Sunday" in body["message"]


@pytest.mark.asyncio
async def test_weekly_digest_before_inception_returns_not_found(client: httpx.AsyncClient):
    """A Sunday before INCEPTION_DATE must return status=not_found."""
    resp = await client.get(f"/digests/weekly/{_WEEK_NOT_FOUND_START}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "not_found"
    assert body["data"] is None
    assert body["reason"] is not None


@pytest.mark.asyncio
async def test_weekly_digest_no_digest_returns_pending(client: httpx.AsyncClient):
    """A valid Sunday with no WeeklyDigest row must return status=pending."""
    resp = await client.get(f"/digests/weekly/{_WEEK_PENDING_START}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["data"] is None
    assert body["reason"] is not None


@pytest.mark.asyncio
async def test_weekly_digest_exists_returns_ok_with_full_document(
    client: httpx.AsyncClient, session: AsyncSession
):
    """An existing WeeklyDigest must return status=ok with all three sections and coverage arrays."""
    await _seed_weekly_digest(session)
    resp = await client.get(f"/digests/weekly/{_WEEK_OK_START}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["reason"] is None

    data = body["data"]
    assert data["type"] == "weekly"
    assert data["week_start"] == str(_WEEK_OK_START)
    assert data["week_end"] == str(_WEEK_OK_END)
    assert data["paper_count"] == 50
    assert data["groundbreaking_count"] == 3

    coverage = data["coverage_note"]
    assert coverage["announcement_days"] == ["Sun", "Mon", "Tue", "Wed", "Thu"]
    assert isinstance(coverage["days_with_content"], list)
    assert isinstance(coverage["no_papers_skips"], list)
    assert isinstance(coverage["fetch_failure_skips"], list)
    assert str(datetime.date(2026, 4, 21)) in coverage["fetch_failure_skips"]

    sections = data["sections"]
    assert sections["benchmark_comparisons"] != ""
    assert sections["trend_synthesis"] != ""
    assert sections["cross_paper_analysis"] != ""


@pytest.mark.asyncio
async def test_daily_digest_valid_date_no_date_record_returns_empty(
    client: httpx.AsyncClient,
):
    """A valid date in-window with no DateRecord must return status=empty."""
    # 2026-02-02 (Monday) is after INCEPTION_DATE and before today — no record seeded.
    resp = await client.get("/digests/daily/2026-02-02")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "empty"
    assert body["data"] is None
    assert body["reason"] is not None


@pytest.mark.asyncio
async def test_daily_digest_published_status_no_digest_row_returns_empty(
    client: httpx.AsyncClient, session: AsyncSession
):
    """DateRecord=published with no DailyDigest row must return status=empty."""
    # Seed only the DateRecord (published) — do not create a DailyDigest row.
    await _seed_date_record(session, _DATE_PUBLISHED, "published")
    resp = await client.get(f"/digests/daily/{_DATE_PUBLISHED}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "empty"
    assert body["data"] is None
    assert body["reason"] is not None


@pytest.mark.asyncio
async def test_weekly_digest_future_sunday_returns_not_available(
    client: httpx.AsyncClient,
):
    """A Sunday in the future must return status=not_available."""
    future_sunday = "2027-01-03"  # Sunday, clearly in the future
    resp = await client.get(f"/digests/weekly/{future_sunday}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "not_available"
    assert body["data"] is None
    assert body["reason"] is not None


# ---------------------------------------------------------------------------
# Schema direct-construction coverage
# ---------------------------------------------------------------------------


def test_daily_digest_data_from_dict_passes_through():
    """DailyDigestData validator passes dicts straight through (non-ORM path)."""
    raw = {
        "type": "daily",
        "date": "2026-01-12",
        "generated_at": "2026-01-12T21:05:00+00:00",
        "paper_count": 1,
        "groundbreaking_count": 0,
        "topics": [{"name": "LLMs", "paper_count": 1, "body": "body text"}],
    }
    obj = DailyDigestData(**raw)
    assert obj.paper_count == 1


def test_weekly_digest_data_from_dict_passes_through():
    """WeeklyDigestData validator passes dicts straight through (non-ORM path)."""
    raw = {
        "type": "weekly",
        "week_start": "2026-04-19",
        "week_end": "2026-04-23",
        "generated_at": "2026-04-24T01:05:00+00:00",
        "paper_count": 5,
        "groundbreaking_count": 1,
        "coverage_note": CoverageNote(
            announcement_days=["Sun", "Mon", "Tue", "Wed", "Thu"],
            days_with_content=[datetime.date(2026, 4, 19)],
            no_papers_skips=[],
            fetch_failure_skips=[],
        ),
        "sections": WeeklySections(
            benchmark_comparisons="bc",
            trend_synthesis="ts",
            cross_paper_analysis="cpa",
        ),
    }
    obj = WeeklyDigestData(**raw)
    assert obj.paper_count == 5


# ---------------------------------------------------------------------------
# deps.py coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_session_raises_if_factory_not_configured():
    """get_session must raise RuntimeError when called before configure_session_factory."""
    import src.api.deps as deps_module

    original = deps_module._session_factory
    deps_module._session_factory = None
    try:
        gen = deps_module.get_session()
        try:
            await gen.__anext__()
            pytest.fail("Expected RuntimeError")
        except RuntimeError as exc:
            assert "configure_session_factory" in str(exc)
    finally:
        deps_module._session_factory = original


@pytest.mark.asyncio
async def test_configure_session_factory_and_get_session(engine):
    """configure_session_factory stores the factory; get_session yields a working session."""
    import src.api.deps as deps_module

    original = deps_module._session_factory
    factory = async_sessionmaker(engine, expire_on_commit=False)
    deps_module.configure_session_factory(factory)
    try:
        gen = deps_module.get_session()
        session = await gen.__anext__()
        assert isinstance(session, AsyncSession)
        # Exhaust the generator cleanly.
        try:
            await gen.aclose()
        except StopAsyncIteration:
            pass
    finally:
        deps_module._session_factory = original