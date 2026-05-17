"""End-to-end integration test for the daily research digest pipeline (T031).

Mocks arXiv HTTP and LLM calls; uses the real test PostgreSQL database.
Exercises the full pipeline:
  fetch_papers → process_paper → detect_groundbreaking → generate_daily_digest
Then queries GET /digests/daily/{date} via the FastAPI test client and asserts
all response fields are correct.

Each LLM call is patched at the module where it is imported (not at definition
site) so that the processor, detector, and generator each see an isolated mock.
"""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import arxiv
import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base
from src.pipeline.daily_generator import DailyDigestGenerator
from src.pipeline.detector import detect_groundbreaking
from src.pipeline.fetcher import Fetcher
from src.pipeline.processor import ExtractionSchema, process_paper

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_INCEPTION_DATE = datetime.date(2026, 4, 1)   # matches .env
_DATE_TWO_PAPERS = datetime.date(2026, 4, 7)  # Monday — 2 papers, 1 groundbreaking
_DATE_ONE_PAPER = datetime.date(2026, 4, 8)   # Tuesday — 1 paper, 0 groundbreaking


# ---------------------------------------------------------------------------
# Engine / schema fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="module")
async def engine():
    """Create test engine, build schema, yield, then drop."""
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


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(engine):
    """Truncate all domain tables before each test so pipeline commits don't bleed."""
    async with engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE topic_sections, daily_digests, papers, date_records CASCADE")
        )


@pytest_asyncio.fixture
async def session(engine):
    """Yield a fresh session per test (pipeline commits; no rollback wrapper needed)."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_arxiv_result(arxiv_id: str, date: datetime.date) -> MagicMock:
    """Build a MagicMock that quacks like arxiv.Result."""
    result = MagicMock(spec=arxiv.Result)
    result.entry_id = f"http://arxiv.org/abs/{arxiv_id}v1"
    result.published = datetime.datetime(
        date.year, date.month, date.day, 20, 0, 0,
        tzinfo=datetime.UTC,
    )
    result.title = f"Test Paper {arxiv_id}"
    result.summary = f"Abstract for paper {arxiv_id}."
    author = MagicMock()
    author.name = "Test Author"
    result.authors = [author]
    return result


def _mock_http():
    """Return a mock httpx.AsyncClient context manager that returns HTML 200."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html><body>Full paper text.</body></html>"
    instance = AsyncMock()
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=None)
    instance.get = AsyncMock(return_value=mock_response)
    return instance


def _extraction() -> ExtractionSchema:
    return ExtractionSchema(
        contributions="Novel contributions.",
        methodologies="Methodology description.",
        benchmarks="GLUE +5 points.",
        institutions=["MIT"],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_pipeline_produces_correct_digest(session: AsyncSession):
    """The full pipeline produces a DailyDigest with the correct groundbreaking_count."""
    # Import private schemas for mock return values via their module
    from src.pipeline.daily_generator import _TopicBodySchema
    from src.pipeline.detector import _GroundbreakingSchema

    arxiv_results = [
        _make_arxiv_result("2504.00001", _DATE_TWO_PAPERS),
        _make_arxiv_result("2504.00002", _DATE_TWO_PAPERS),
    ]
    mock_client = MagicMock(spec=arxiv.Client)
    mock_client.results.return_value = iter(arxiv_results)

    gb_responses = [
        _GroundbreakingSchema(
            is_groundbreaking=True,
            benchmark_improved="GLUE",
            novel_element="Transformer-free attention",
        ),
        _GroundbreakingSchema(
            is_groundbreaking=False,
            benchmark_improved=None,
            novel_element=None,
        ),
    ]

    with (
        patch("src.pipeline.processor.parse_structured", new_callable=AsyncMock) as mock_proc_parse,
        patch("src.pipeline.processor.classify", new_callable=AsyncMock) as mock_classify,
        patch("src.pipeline.detector.parse_structured", new_callable=AsyncMock) as mock_det_parse,
        patch("src.pipeline.daily_generator.parse_structured", new_callable=AsyncMock) as mock_gen_parse,
        patch("httpx.AsyncClient", return_value=_mock_http()),
    ):
        mock_proc_parse.return_value = _extraction()
        mock_classify.return_value = {"primary_topic": "Large Language Models"}
        mock_det_parse.side_effect = gb_responses
        mock_gen_parse.return_value = _TopicBodySchema(body="## LLMs\n\nContent.")

        # Step 1: fetch
        fetcher = Fetcher(client=mock_client, search=MagicMock())
        fetch_result = await fetcher.fetch_papers(_DATE_TWO_PAPERS, session)
        assert fetch_result.status == "published"
        assert len(fetch_result.papers) == 2

        # Step 2: process each paper
        papers = []
        for result in fetch_result.papers:
            paper = await process_paper(result, session)
            assert paper is not None
            papers.append(paper)

        # Step 3: groundbreaking detection
        for paper in papers:
            await detect_groundbreaking(paper, session)

        # Step 4: generate digest
        generator = DailyDigestGenerator()
        digest = await generator.generate(_DATE_TWO_PAPERS, session)

    assert digest is not None
    assert digest.paper_count == 2
    assert digest.groundbreaking_count == 1

    gb = [p for p in papers if p.is_groundbreaking]
    non_gb = [p for p in papers if not p.is_groundbreaking]
    assert len(gb) == 1
    assert len(non_gb) == 1
    assert gb[0].groundbreaking_reasoning is not None
    assert non_gb[0].groundbreaking_reasoning is None

    assert len(digest.topic_sections) >= 1
    assert all(p.topic_section_id is not None for p in papers)


@pytest.mark.asyncio
async def test_digest_retrievable_via_api(session: AsyncSession):
    """Digest produced by the pipeline must be retrievable with status=ok via the API."""
    from src.pipeline.daily_generator import _TopicBodySchema
    from src.pipeline.detector import _GroundbreakingSchema

    arxiv_results = [_make_arxiv_result("2504.00003", _DATE_ONE_PAPER)]
    mock_client = MagicMock(spec=arxiv.Client)
    mock_client.results.return_value = iter(arxiv_results)

    with (
        patch("src.pipeline.processor.parse_structured", new_callable=AsyncMock) as mock_proc_parse,
        patch("src.pipeline.processor.classify", new_callable=AsyncMock) as mock_classify,
        patch("src.pipeline.detector.parse_structured", new_callable=AsyncMock) as mock_det_parse,
        patch("src.pipeline.daily_generator.parse_structured", new_callable=AsyncMock) as mock_gen_parse,
        patch("httpx.AsyncClient", return_value=_mock_http()),
    ):
        mock_proc_parse.return_value = _extraction()
        mock_classify.return_value = {"primary_topic": "Computer Vision"}
        mock_det_parse.return_value = _GroundbreakingSchema(
            is_groundbreaking=False,
            benchmark_improved=None,
            novel_element=None,
        )
        mock_gen_parse.return_value = _TopicBodySchema(body="## CV\n\nContent.")

        fetcher = Fetcher(client=mock_client, search=MagicMock())
        fetch_result = await fetcher.fetch_papers(_DATE_ONE_PAPER, session)
        assert fetch_result.status == "published"

        for result in fetch_result.papers:
            paper = await process_paper(result, session)
            if paper:
                await detect_groundbreaking(paper, session)

        generator = DailyDigestGenerator()
        await generator.generate(_DATE_ONE_PAPER, session)

    # Query via FastAPI test client
    from fastapi import FastAPI

    from src.api.deps import get_session
    from src.api.routers.digests import router

    app = FastAPI()
    app.include_router(router)

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override

    with patch("src.api.routers.digests.get_settings") as mock_settings:
        mock_settings.return_value.INCEPTION_DATE = _INCEPTION_DATE
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/digests/daily/{_DATE_ONE_PAPER}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    data = body["data"]
    assert data["paper_count"] == 1
    assert data["groundbreaking_count"] == 0
    assert len(data["topics"]) == 1
    assert data["topics"][0]["name"] == "Computer Vision"
