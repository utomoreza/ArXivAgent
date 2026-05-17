# jsonschema.RefResolver is deprecated in v4.18+ but is the reliable approach
# for resolving JSON Pointer $refs in OpenAPI documents until the project
# migrates to the `referencing` library.
"""Contract tests — validate every API response against contracts/openapi.yaml.

Uses jsonschema to validate every response body produced by each endpoint
against the exact schema defined in contracts/openapi.yaml → components/schemas.

Coverage:
  - GET /digests/daily/{date}: all 6 daily states
  - GET /digests/weekly/{week_start_date}: all 3 weekly states + 400 error
  - Q&A schemas: 3 response envelope shapes (endpoint not yet implemented —
    validated by constructing mock payloads directly against the schema)
"""

import datetime
import os
import uuid
import warnings
from pathlib import Path
from unittest.mock import patch

import httpx
import jsonschema
import pytest
import pytest_asyncio
import yaml
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base, DailyDigest, DateRecord, TopicSection, WeeklyDigest

# ---------------------------------------------------------------------------
# Load OpenAPI spec and build a resolver
# ---------------------------------------------------------------------------

_SPEC_PATH = Path(__file__).parent.parent.parent / "specs/001-arxiv-intelligence-agent/contracts/openapi.yaml"


def _load_spec() -> dict:
    with _SPEC_PATH.open() as fh:
        return yaml.safe_load(fh)


_OPENAPI = _load_spec()
_SCHEMAS = _OPENAPI["components"]["schemas"]


def _validate(body: dict, schema_name: str) -> None:
    """Validate *body* against the named schema in the OpenAPI spec.

    Uses jsonschema.RefResolver with the full OpenAPI document as the store
    so that $ref references within components/schemas resolve correctly.

    Args:
        body: Parsed JSON response body to validate.
        schema_name: Key in components/schemas to validate against.

    Raises:
        jsonschema.ValidationError: If *body* does not conform to the schema.
    """
    schema = _SCHEMAS[schema_name]
    # Register the full OpenAPI document so JSON-pointer $refs resolve correctly.
    # Suppress the RefResolver deprecation warning: it remains the most reliable
    # way to resolve JSON Pointer refs until we migrate to `referencing`.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        resolver = jsonschema.RefResolver.from_schema(
            _OPENAPI,
            store={"": _OPENAPI},
        )
        jsonschema.validate(instance=body, schema=schema, resolver=resolver)


# ---------------------------------------------------------------------------
# Date constants
# ---------------------------------------------------------------------------

_INCEPTION = datetime.date(2026, 1, 5)
_DATE_PUBLISHED = datetime.date(2026, 1, 12)      # Monday
_DATE_NO_PAPERS = datetime.date(2026, 1, 13)      # Tuesday
_DATE_FETCH_FAIL = datetime.date(2026, 1, 14)     # Wednesday
_DATE_NO_ANNOUNCE = datetime.date(2026, 1, 10)    # Saturday
_DATE_BEFORE = datetime.date(2026, 1, 4)          # before inception
_DATE_FUTURE = datetime.date(2026, 12, 1)         # future

_WEEK_OK = datetime.date(2026, 4, 19)             # Sunday
_WEEK_OK_END = datetime.date(2026, 4, 23)         # Thursday
_WEEK_PENDING = datetime.date(2026, 4, 26)        # Sunday, no digest
_WEEK_BEFORE = datetime.date(2025, 12, 28)        # Sunday before inception
_WEEK_BAD = datetime.date(2026, 4, 20)            # Monday (400)


# ---------------------------------------------------------------------------
# DB engine / schema fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="module")
async def engine():
    """Create test engine, build schema, yield, then drop."""
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
    """Yield a fresh session; roll back after each test."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()


# ---------------------------------------------------------------------------
# FastAPI test client fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(session: AsyncSession):
    """Minimal FastAPI app with digests router; inception date mocked."""
    from fastapi import FastAPI

    from src.api.deps import get_session
    from src.api.routers.digests import router

    app = FastAPI()
    app.include_router(router)

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override

    with patch("src.api.routers.digests.get_settings") as mock_settings:
        mock_settings.return_value.INCEPTION_DATE = _INCEPTION
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_date(session: AsyncSession, date: datetime.date, status: str) -> DateRecord:
    r = DateRecord(date=date, status=status)
    session.add(r)
    await session.flush()
    return r


async def _seed_published(session: AsyncSession) -> None:
    record = DateRecord(date=_DATE_PUBLISHED, status="published", paper_count=5)
    session.add(record)
    await session.flush()

    digest = DailyDigest(
        id=uuid.uuid4(),
        date=_DATE_PUBLISHED,
        generated_at=datetime.datetime(2026, 1, 12, 21, 0, 0, tzinfo=datetime.UTC),
        paper_count=5,
        groundbreaking_count=1,
    )
    session.add(digest)
    await session.flush()

    section = TopicSection(
        id=uuid.uuid4(),
        digest_id=digest.id,
        name="Large Language Models",
        paper_count=5,
        body="## LLMs\n\nContent.",
    )
    session.add(section)
    await session.flush()


async def _seed_weekly(session: AsyncSession) -> None:
    digest = WeeklyDigest(
        id=uuid.uuid4(),
        week_start=_WEEK_OK,
        week_end=_WEEK_OK_END,
        generated_at=datetime.datetime(2026, 4, 24, 1, 0, 0, tzinfo=datetime.UTC),
        paper_count=20,
        groundbreaking_count=2,
        benchmark_comparisons="## Benchmarks\n\nContent.",
        trend_synthesis="## Trends\n\nContent.",
        cross_paper_analysis="## Cross-paper\n\nContent.",
        days_with_content=[_WEEK_OK, datetime.date(2026, 4, 20)],
        no_papers_skips=[],
        fetch_failure_skips=[datetime.date(2026, 4, 21)],
    )
    session.add(digest)
    await session.flush()


# ---------------------------------------------------------------------------
# GET /digests/daily — 6 states
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contract_daily_ok(client, session):
    """DailyDigestResponse matches openapi.yaml → DailyDigestResponse."""
    await _seed_published(session)
    resp = await client.get(f"/digests/daily/{_DATE_PUBLISHED}")
    assert resp.status_code == 200
    _validate(resp.json(), "DailyDigestResponse")


@pytest.mark.asyncio
async def test_contract_daily_skipped(client, session):
    """SkippedResponse matches openapi.yaml → SkippedResponse."""
    await _seed_date(session, _DATE_NO_PAPERS, "no_papers_skip")
    resp = await client.get(f"/digests/daily/{_DATE_NO_PAPERS}")
    assert resp.status_code == 200
    _validate(resp.json(), "SkippedResponse")


@pytest.mark.asyncio
async def test_contract_daily_fetch_failure(client, session):
    """FetchFailureResponse matches openapi.yaml → FetchFailureResponse."""
    await _seed_date(session, _DATE_FETCH_FAIL, "fetch_failure_skip")
    resp = await client.get(f"/digests/daily/{_DATE_FETCH_FAIL}")
    assert resp.status_code == 200
    _validate(resp.json(), "FetchFailureResponse")


@pytest.mark.asyncio
async def test_contract_daily_no_announcement(client, session):
    """NoAnnouncementResponse matches openapi.yaml → NoAnnouncementResponse."""
    await _seed_date(session, _DATE_NO_ANNOUNCE, "no_announcement")
    resp = await client.get(f"/digests/daily/{_DATE_NO_ANNOUNCE}")
    assert resp.status_code == 200
    _validate(resp.json(), "NoAnnouncementResponse")


@pytest.mark.asyncio
async def test_contract_daily_not_found(client):
    """NotFoundResponse matches openapi.yaml → NotFoundResponse."""
    resp = await client.get(f"/digests/daily/{_DATE_BEFORE}")
    assert resp.status_code == 200
    _validate(resp.json(), "NotFoundResponse")


@pytest.mark.asyncio
async def test_contract_daily_not_available(client):
    """NotAvailableResponse matches openapi.yaml → NotAvailableResponse."""
    resp = await client.get(f"/digests/daily/{_DATE_FUTURE}")
    assert resp.status_code == 200
    _validate(resp.json(), "NotAvailableResponse")


# ---------------------------------------------------------------------------
# GET /digests/weekly — 3 states + 400
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contract_weekly_ok(client, session):
    """WeeklyDigestResponse matches openapi.yaml → WeeklyDigestResponse."""
    await _seed_weekly(session)
    resp = await client.get(f"/digests/weekly/{_WEEK_OK}")
    assert resp.status_code == 200
    _validate(resp.json(), "WeeklyDigestResponse")


@pytest.mark.asyncio
async def test_contract_weekly_pending(client):
    """PendingResponse matches openapi.yaml → PendingResponse."""
    resp = await client.get(f"/digests/weekly/{_WEEK_PENDING}")
    assert resp.status_code == 200
    _validate(resp.json(), "PendingResponse")


@pytest.mark.asyncio
async def test_contract_weekly_not_found(client):
    """Weekly NotFoundResponse matches openapi.yaml → NotFoundResponse."""
    resp = await client.get(f"/digests/weekly/{_WEEK_BEFORE}")
    assert resp.status_code == 200
    _validate(resp.json(), "NotFoundResponse")


@pytest.mark.asyncio
async def test_contract_weekly_validation_error(client):
    """Non-Sunday week_start_date returns ErrorResponse matching openapi.yaml."""
    resp = await client.get(f"/digests/weekly/{_WEEK_BAD}")
    assert resp.status_code == 400
    _validate(resp.json(), "ErrorResponse")


# ---------------------------------------------------------------------------
# Q&A schema shapes (endpoint not yet implemented — T043)
# Validate that mock payloads we would construct match the schemas in the spec.
# ---------------------------------------------------------------------------


def test_contract_qa_response_schema():
    """QAResponse schema accepts a well-formed answer payload."""
    payload = {
        "status": "ok",
        "data": {
            "answer": "The papers show improvements in LLM reasoning.",
            "sources": [
                {
                    "arxiv_id": "2504.00001",
                    "title": "Test Paper",
                    "date": "2026-04-07",
                    "chunk_type": "abstract",
                }
            ],
        },
        "reason": None,
    }
    _validate(payload, "QAResponse")


def test_contract_qa_rejected_schema():
    """RejectedResponse schema accepts a well-formed rejection payload."""
    payload = {
        "status": "rejected",
        "data": None,
        "reason": "This agent only answers questions about the research digests.",
    }
    _validate(payload, "RejectedResponse")


def test_contract_qa_empty_kb_schema():
    """EmptyKBResponse schema accepts a well-formed empty-KB payload."""
    payload = {
        "status": "empty",
        "data": None,
        "reason": "No digests are available yet within the current window.",
    }
    _validate(payload, "EmptyKBResponse")
