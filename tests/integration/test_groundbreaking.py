"""Acceptance test for groundbreaking paper detection (T033, US2).

Tests the full pipeline with six controlled papers:
  - 2 papers meeting BOTH criteria (benchmark + novel architecture) → flagged
  - 2 papers meeting ONE criterion only → NOT flagged
  - 2 papers meeting NEITHER criterion → NOT flagged

Validates SC-003: false-positive rate across the sample is below 10%.
"""

import datetime
import os
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
from src.pipeline.detector import _GroundbreakingSchema, detect_groundbreaking
from src.pipeline.fetcher import Fetcher
from src.pipeline.processor import ExtractionSchema, process_paper

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_INCEPTION_DATE = datetime.date(2026, 4, 1)
# Thursday — avoids date conflict with test_pipeline.py (_DATE_TWO_PAPERS=Apr-07, _DATE_ONE_PAPER=Apr-08)
_TEST_DATE = datetime.date(2026, 4, 9)

# 2 groundbreaking, 2 one-criterion-only, 2 neither
_ARXIV_IDS = [
    "2504.10001",  # both criteria → groundbreaking
    "2504.10002",  # both criteria → groundbreaking
    "2504.10003",  # benchmark only → NOT groundbreaking
    "2504.10004",  # novel arch only → NOT groundbreaking
    "2504.10005",  # neither → NOT groundbreaking
    "2504.10006",  # neither → NOT groundbreaking
]

# Ground truth: only the first two IDs are truly groundbreaking
_TRULY_GROUNDBREAKING = frozenset({"2504.10001", "2504.10002"})

_GROUNDBREAKING_RESPONSES = [
    # Paper 2504.10001: both criteria
    _GroundbreakingSchema(
        is_groundbreaking=True,
        benchmark_improved="GLUE",
        novel_element="sparse Mamba attention",
    ),
    # Paper 2504.10002: both criteria
    _GroundbreakingSchema(
        is_groundbreaking=True,
        benchmark_improved="ImageNet Top-1",
        novel_element="mixture-of-depths routing",
    ),
    # Paper 2504.10003: benchmark only — novel_element is None → NOT flagged
    _GroundbreakingSchema(
        is_groundbreaking=False,
        benchmark_improved="SQuAD F1",
        novel_element=None,
    ),
    # Paper 2504.10004: novel arch only — benchmark_improved is None → NOT flagged
    _GroundbreakingSchema(
        is_groundbreaking=False,
        benchmark_improved=None,
        novel_element="hyperbolic graph convolution",
    ),
    # Paper 2504.10005: neither
    _GroundbreakingSchema(
        is_groundbreaking=False,
        benchmark_improved=None,
        novel_element=None,
    ),
    # Paper 2504.10006: neither
    _GroundbreakingSchema(
        is_groundbreaking=False,
        benchmark_improved=None,
        novel_element=None,
    ),
]


# ---------------------------------------------------------------------------
# Engine / schema fixtures
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
# Shared pipeline runner
# ---------------------------------------------------------------------------


async def _run_pipeline(session: AsyncSession) -> tuple[list, object]:
    """Run fetch → process → detect for all 6 test papers; return (papers, digest)."""
    from src.pipeline.daily_generator import _TopicBodySchema

    arxiv_results = [_make_arxiv_result(aid) for aid in _ARXIV_IDS]
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
        mock_classify.return_value = {"primary_topic": "Large Language Models"}
        mock_det_parse.side_effect = list(_GROUNDBREAKING_RESPONSES)  # copy to avoid exhaustion
        mock_gen_parse.return_value = _TopicBodySchema(body="## LLMs\n\nContent.")

        fetcher = Fetcher(client=mock_client, search=MagicMock())
        fetch_result = await fetcher.fetch_papers(_TEST_DATE, session)
        assert fetch_result.status == "published"
        assert len(fetch_result.papers) == 6

        papers = []
        for result in fetch_result.papers:
            paper = await process_paper(result, session)
            assert paper is not None
            papers.append(paper)

        for paper in papers:
            await detect_groundbreaking(paper, session)

        generator = DailyDigestGenerator()
        digest = await generator.generate(_TEST_DATE, session)

    return papers, digest


def _make_arxiv_result(arxiv_id: str) -> MagicMock:
    """Build a MagicMock that quacks like arxiv.Result."""
    result = MagicMock(spec=arxiv.Result)
    result.entry_id = f"http://arxiv.org/abs/{arxiv_id}v1"
    result.published = datetime.datetime(
        _TEST_DATE.year, _TEST_DATE.month, _TEST_DATE.day, 20, 0, 0,
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
async def test_groundbreaking_correct_flags(session: AsyncSession):
    """Exactly 2 of 6 papers are flagged; others have is_groundbreaking=False and null reasoning."""
    papers, _digest = await _run_pipeline(session)

    groundbreaking = [p for p in papers if p.is_groundbreaking]
    not_groundbreaking = [p for p in papers if not p.is_groundbreaking]

    assert len(groundbreaking) == 2
    assert len(not_groundbreaking) == 4

    for paper in groundbreaking:
        assert paper.arxiv_id in _TRULY_GROUNDBREAKING
        assert paper.groundbreaking_reasoning is not None
        assert len(paper.groundbreaking_reasoning) > 0

    for paper in not_groundbreaking:
        assert paper.arxiv_id not in _TRULY_GROUNDBREAKING
        assert paper.groundbreaking_reasoning is None


@pytest.mark.asyncio
async def test_groundbreaking_reasoning_format(session: AsyncSession):
    """Reasoning string follows 'Improves {benchmark}; introduces {novel element}.' format."""
    papers, _ = await _run_pipeline(session)

    gb = [p for p in papers if p.is_groundbreaking]
    assert len(gb) == 2

    for paper in gb:
        r = paper.groundbreaking_reasoning
        assert r.startswith("Improves "), f"Unexpected format: {r!r}"
        assert "; introduces " in r, f"Missing '; introduces': {r!r}"
        assert r.endswith("."), f"Missing trailing period: {r!r}"

    # Verify specific reasoning strings match the mock responses
    reasoning_by_id = {p.arxiv_id: p.groundbreaking_reasoning for p in gb}
    assert reasoning_by_id["2504.10001"] == "Improves GLUE; introduces sparse Mamba attention."
    assert reasoning_by_id["2504.10002"] == "Improves ImageNet Top-1; introduces mixture-of-depths routing."


@pytest.mark.asyncio
async def test_groundbreaking_count_in_digest(session: AsyncSession):
    """groundbreaking_count propagates correctly through the digest and API response."""
    _, digest = await _run_pipeline(session)

    assert digest is not None
    assert digest.paper_count == 6
    assert digest.groundbreaking_count == 2

    # Retrieve via API and verify groundbreaking_count in envelope
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
            resp = await client.get(f"/digests/daily/{_TEST_DATE}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["data"]["groundbreaking_count"] == 2
    assert body["data"]["paper_count"] == 6


@pytest.mark.asyncio
async def test_false_positive_rate_below_10_percent(session: AsyncSession):
    """SC-003: false-positive rate (flagged but should not be) < 10% across the sample."""
    papers, _ = await _run_pipeline(session)

    false_positives = [
        p for p in papers
        if p.is_groundbreaking and p.arxiv_id not in _TRULY_GROUNDBREAKING
    ]
    total_negatives = len([aid for aid in _ARXIV_IDS if aid not in _TRULY_GROUNDBREAKING])

    false_positive_rate = len(false_positives) / total_negatives if total_negatives > 0 else 0.0

    assert false_positive_rate < 0.10, (
        f"False-positive rate {false_positive_rate:.2%} exceeds 10% SC-003 threshold; "
        f"false positives: {[p.arxiv_id for p in false_positives]}"
    )
