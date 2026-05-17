"""Performance tests — SC-006, SC-007, Constitution IV throughput.

All external dependencies (DB, LLM, embedder) are mocked so the tests run
without a live database.  Timing assertions reflect the overhead of the
endpoint logic itself, not network/DB latency.

SLAs:
  SC-006: GET /digests/daily/{date}  p95 ≤ 2 s
  SC-007: POST /qa                   p95 ≤ 10 s
  IV:     Batch paper processing     ≥ 10 papers/s
"""

import asyncio
import datetime
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from src.api.deps import get_session
from src.api.routers.digests import router as digest_router
from src.api.routers.qa import router as qa_router
from src.db.models import DailyDigest, DateRecord, TopicSection, WeeklyDigest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SAMPLE_N = 20   # number of requests per endpoint for p95
_P95_INDEX = int(_SAMPLE_N * 0.95) - 1  # index into sorted latencies
_DATE_OK = "2026-01-12"
_WEEK_OK = "2026-01-11"  # Sunday


# ---------------------------------------------------------------------------
# App factories
# ---------------------------------------------------------------------------


def _make_digest_app(session) -> FastAPI:
    app = FastAPI()
    app.include_router(digest_router)

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    return app


def _make_qa_app(session) -> FastAPI:
    app = FastAPI()
    app.include_router(qa_router)

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    return app


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_date_record_orm(status: str = "published") -> DateRecord:
    dr = DateRecord(date=datetime.date(2026, 1, 12), status=status)
    return dr


def _make_daily_digest_orm() -> DailyDigest:
    digest_id = uuid.uuid4()
    section = TopicSection(
        id=uuid.uuid4(),
        digest_id=digest_id,
        name="Large Language Models",
        paper_count=5,
        body="## LLM section body",
    )
    digest = DailyDigest(
        id=digest_id,
        date=datetime.date(2026, 1, 12),
        generated_at=datetime.datetime(2026, 1, 12, 12, 0, 0, tzinfo=datetime.UTC),
        paper_count=5,
        groundbreaking_count=1,
    )
    digest.topic_sections = [section]
    return digest


def _make_session_for_daily_digest() -> AsyncMock:
    """Session that returns a published DateRecord and a DailyDigest."""
    session = AsyncMock()
    dr = _make_date_record_orm("published")
    digest = _make_daily_digest_orm()

    inner = MagicMock()
    inner.scalars.return_value.first.side_effect = [dr, digest]
    session.execute = AsyncMock(return_value=inner)
    return session


def _make_embedding(i: int) -> MagicMock:
    emb = MagicMock()
    emb.arxiv_id = f"2504.{10000 + i}"
    emb.title = f"Paper {i}"
    emb.date = datetime.date(2026, 4, i % 28 + 1)
    emb.chunk_type = "abstract"
    emb.content = f"Content {i}."
    return emb


_EMBEDDINGS = [_make_embedding(i) for i in range(5)]


# ---------------------------------------------------------------------------
# SC-006: GET /digests/daily/{date} p95 ≤ 2 s
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_digest_p95_within_2s():
    """SC-006: GET /digests/daily/{date} p95 latency must be ≤ 2 s.

    Uses a mocked session so only endpoint logic is timed.
    """
    latencies: list[float] = []

    with patch("src.api.routers.digests.get_settings") as mock_settings:
        mock_settings.return_value.INCEPTION_DATE = datetime.date(2026, 1, 5)

        for _ in range(_SAMPLE_N):
            session = _make_session_for_daily_digest()
            app = _make_digest_app(session)

            t0 = time.perf_counter()
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/digests/daily/{_DATE_OK}")
            latencies.append(time.perf_counter() - t0)

            assert resp.status_code == 200, (
                f"Expected 200, got {resp.status_code}: {resp.text}"
            )

    latencies.sort()
    p95 = latencies[_P95_INDEX]
    assert p95 <= 2.0, (
        f"SC-006 FAIL: p95 latency {p95:.3f}s exceeds 2 s SLA"
        f" (samples: {[f'{x:.3f}' for x in latencies]})"
    )


# ---------------------------------------------------------------------------
# SC-006: GET /digests/weekly/{week_start_date} p95 ≤ 2 s
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weekly_digest_p95_within_2s():
    """SC-006 (weekly variant): GET /digests/weekly/{date} p95 latency ≤ 2 s."""
    weekly = WeeklyDigest(
        id=uuid.uuid4(),
        week_start=datetime.date(2026, 1, 11),
        week_end=datetime.date(2026, 1, 15),
        generated_at=datetime.datetime(2026, 1, 15, 12, 0, 0, tzinfo=datetime.UTC),
        paper_count=30,
        groundbreaking_count=3,
        benchmark_comparisons="## Benchmarks",
        trend_synthesis="## Trends",
        cross_paper_analysis="## Cross",
        days_with_content=[datetime.date(2026, 1, 11)],
        no_papers_skips=[],
        fetch_failure_skips=[],
    )

    latencies: list[float] = []

    with patch("src.api.routers.digests.get_settings") as mock_settings:
        mock_settings.return_value.INCEPTION_DATE = datetime.date(2026, 1, 5)

        for _ in range(_SAMPLE_N):
            session = AsyncMock()
            inner = MagicMock()
            inner.scalars.return_value.first.return_value = weekly
            session.execute = AsyncMock(return_value=inner)

            app = _make_digest_app(session)

            t0 = time.perf_counter()
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/digests/weekly/{_WEEK_OK}")
            latencies.append(time.perf_counter() - t0)

            assert resp.status_code == 200

    latencies.sort()
    p95 = latencies[_P95_INDEX]
    assert p95 <= 2.0, (
        f"SC-006 (weekly) FAIL: p95 latency {p95:.3f}s exceeds 2 s SLA"
    )


# ---------------------------------------------------------------------------
# SC-007: POST /qa p95 ≤ 10 s
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_qa_p95_within_10s():
    """SC-007: POST /qa p95 latency must be ≤ 10 s with seeded mock vector store.

    LLM classify and parse_structured are mocked; retriever returns pre-seeded
    embeddings so only endpoint logic (not model inference) is timed.
    """
    mock_answer = MagicMock()
    mock_answer.answer = "Answer based on context."

    latencies: list[float] = []

    with (
        patch("src.api.routers.qa.classify", new_callable=AsyncMock) as mock_classify,
        patch("src.api.routers.qa.retrieve", new_callable=AsyncMock) as mock_retrieve,
        patch(
            "src.api.routers.qa.parse_structured", new_callable=AsyncMock
        ) as mock_parse,
        patch("src.api.routers.qa.get_settings") as mock_settings,
    ):
        mock_settings.return_value.SMALL_CLAUDE_LLM = "claude-haiku-4-5-20251001"
        mock_settings.return_value.LARGE_CLAUDE_LLM = "claude-sonnet-4-6"
        mock_settings.return_value.RAG_WINDOW_DAYS = 7
        mock_classify.return_value = {"in_scope": True}
        mock_retrieve.return_value = _EMBEDDINGS
        mock_parse.return_value = mock_answer

        for _ in range(_SAMPLE_N):
            session = AsyncMock()
            app = _make_qa_app(session)

            t0 = time.perf_counter()
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/qa",
                    json={"question": "Which papers improved MMLU this week?"},
                )
            latencies.append(time.perf_counter() - t0)

            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

    latencies.sort()
    p95 = latencies[_P95_INDEX]
    assert p95 <= 10.0, (
        f"SC-007 FAIL: p95 latency {p95:.3f}s exceeds 10 s SLA"
        f" (samples: {[f'{x:.3f}' for x in latencies]})"
    )


# ---------------------------------------------------------------------------
# Constitution IV: batch paper processing throughput ≥ 10 papers/s
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_paper_processing_throughput():
    """Constitution IV: batch paper processing must achieve ≥ 10 papers/s.

    All external I/O (HTTP full-text fetch, LLM calls, DB commit) is mocked
    so only the coordination and data-transformation logic is benchmarked.
    This measures the processing framework's intrinsic throughput ceiling.
    """
    from src.pipeline.processor import process_paper

    n_papers = 30

    mock_extraction = MagicMock()
    mock_extraction.contributions = "Key contributions."
    mock_extraction.methodologies = "Method A."
    mock_extraction.benchmarks = "MMLU +5%."
    mock_extraction.institutions = ["MIT"]

    def _make_arxiv_result(i: int) -> MagicMock:
        result = MagicMock()
        result.entry_id = f"https://arxiv.org/abs/2504.{10000 + i}"
        result.title = f"Paper {i}"
        result.summary = "Abstract text."
        result.authors = [MagicMock(name=f"Author {i}")]
        result.published = MagicMock()
        result.published.date.return_value = datetime.date(2026, 4, 21)
        return result

    arxiv_results = [_make_arxiv_result(i) for i in range(n_papers)]

    async def _mock_session() -> AsyncMock:
        s = AsyncMock()
        s.commit = AsyncMock()
        s.add = MagicMock()
        return s

    with (
        patch(
            "src.pipeline.processor._fetch_full_text",
            new=AsyncMock(return_value="full text body"),
        ),
        patch(
            "src.pipeline.processor.parse_structured",
            new=AsyncMock(return_value=mock_extraction),
        ),
        patch(
            "src.pipeline.processor.classify",
            new=AsyncMock(return_value={"primary_topic": "Large Language Models"}),
        ),
        patch("src.pipeline.processor.config") as mock_config,
    ):
        mock_config.LARGE_CLAUDE_LLM = "claude-sonnet-4-6"
        mock_config.SMALL_CLAUDE_LLM = "claude-haiku-4-5-20251001"
        mock_config.TOPIC_LIST = ["Large Language Models", "Computer Vision"]

        t0 = time.perf_counter()
        sessions = [await _mock_session() for _ in arxiv_results]
        tasks = [
            process_paper(result, session)
            for result, session in zip(arxiv_results, sessions)
        ]
        papers = await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - t0

    processed = sum(1 for p in papers if p is not None)
    assert processed == n_papers, (
        f"Expected {n_papers} papers processed, got {processed}"
    )

    throughput = processed / elapsed
    assert throughput >= 10.0, (
        f"Constitution IV FAIL: throughput {throughput:.1f} papers/s < 10 papers/s"
        f" ({processed} papers in {elapsed:.3f}s)"
    )
