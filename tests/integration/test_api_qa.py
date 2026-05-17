"""Integration tests for POST /qa endpoint (T042, US3).

Mocks LLM calls (classify, parse_structured) and the retriever; verifies
all three response states:
  - ok: in-scope question returns answer with sources
  - rejected: out-of-scope question returns rejected status
  - empty: in-scope question but no in-window embeddings returns empty status

See contracts/openapi.yaml → POST /qa for schema definitions.
"""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from src.api.deps import get_session
from src.api.routers.qa import router

# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------


def _make_app(session) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    return app


def _mock_session():
    return AsyncMock()


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_embedding_mock(
    arxiv_id: str,
    date: datetime.date,
    chunk_type: str = "abstract",
) -> MagicMock:
    emb = MagicMock()
    emb.arxiv_id = arxiv_id
    emb.title = f"Test Paper {arxiv_id}"
    emb.date = date
    emb.chunk_type = chunk_type
    emb.content = f"Content for {arxiv_id}."
    return emb


_FIVE_EMBEDDINGS = [
    _make_embedding_mock(f"2504.0000{i}", datetime.date(2026, 4, i), "abstract")
    for i in range(1, 6)
]


# ---------------------------------------------------------------------------
# Tests: in-scope question → ok
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_qa_in_scope_question_returns_ok_with_answer_and_sources():
    """In-scope question returns status=ok with non-empty answer and at least one source."""
    session = _mock_session()
    app = _make_app(session)

    mock_answer = MagicMock()
    mock_answer.answer = "Three papers improved MMLU: ..."

    with (
        patch("src.api.routers.qa.classify", new_callable=AsyncMock) as mock_classify,
        patch("src.api.routers.qa.retrieve", new_callable=AsyncMock) as mock_retrieve,
        patch("src.api.routers.qa.parse_structured", new_callable=AsyncMock) as mock_parse,
        patch("src.api.routers.qa.get_settings") as mock_settings,
    ):
        mock_settings.return_value.SMALL_CLAUDE_LLM = "claude-haiku-4-5-20251001"
        mock_settings.return_value.LARGE_CLAUDE_LLM = "claude-sonnet-4-6"
        mock_settings.return_value.RAG_WINDOW_DAYS = 7
        mock_classify.return_value = {"in_scope": True}
        mock_retrieve.return_value = _FIVE_EMBEDDINGS
        mock_parse.return_value = mock_answer

        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/qa",
                json={"question": "Which papers improved MMLU this week?"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["data"]["answer"] == "Three papers improved MMLU: ..."
    assert len(body["data"]["sources"]) == 5
    assert body["reason"] is None


@pytest.mark.asyncio
async def test_qa_sources_contain_required_fields():
    """Each source in the ok response has arxiv_id, title, date, chunk_type."""
    session = _mock_session()
    app = _make_app(session)

    mock_answer = MagicMock()
    mock_answer.answer = "An answer."

    with (
        patch("src.api.routers.qa.classify", new_callable=AsyncMock) as mock_classify,
        patch("src.api.routers.qa.retrieve", new_callable=AsyncMock) as mock_retrieve,
        patch("src.api.routers.qa.parse_structured", new_callable=AsyncMock) as mock_parse,
        patch("src.api.routers.qa.get_settings") as mock_settings,
    ):
        mock_settings.return_value.SMALL_CLAUDE_LLM = "claude-haiku-4-5-20251001"
        mock_settings.return_value.LARGE_CLAUDE_LLM = "claude-sonnet-4-6"
        mock_settings.return_value.RAG_WINDOW_DAYS = 7
        mock_classify.return_value = {"in_scope": True}
        mock_retrieve.return_value = [_FIVE_EMBEDDINGS[0]]
        mock_parse.return_value = mock_answer

        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/qa", json={"question": "Test question?"})

    assert resp.status_code == 200
    source = resp.json()["data"]["sources"][0]
    assert "arxiv_id" in source
    assert "title" in source
    assert "date" in source
    assert "chunk_type" in source


# ---------------------------------------------------------------------------
# Tests: out-of-scope question → rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_qa_out_of_scope_returns_rejected():
    """Out-of-scope question returns status=rejected with reason string."""
    session = _mock_session()
    app = _make_app(session)

    with (
        patch("src.api.routers.qa.classify", new_callable=AsyncMock) as mock_classify,
        patch("src.api.routers.qa.retrieve", new_callable=AsyncMock) as mock_retrieve,
        patch("src.api.routers.qa.get_settings") as mock_settings,
    ):
        mock_settings.return_value.SMALL_CLAUDE_LLM = "claude-haiku-4-5-20251001"
        mock_settings.return_value.LARGE_CLAUDE_LLM = "claude-sonnet-4-6"
        mock_settings.return_value.RAG_WINDOW_DAYS = 7
        mock_classify.return_value = {"in_scope": False}

        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/qa",
                json={"question": "What is the weather in Paris?"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "rejected"
    assert body["data"] is None
    assert "research digests" in body["reason"]
    # Retrieve must NOT be called for rejected questions
    mock_retrieve.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests: empty knowledge base → empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_qa_empty_kb_returns_empty_status():
    """In-scope question with no in-window embeddings returns status=empty."""
    session = _mock_session()
    app = _make_app(session)

    with (
        patch("src.api.routers.qa.classify", new_callable=AsyncMock) as mock_classify,
        patch("src.api.routers.qa.retrieve", new_callable=AsyncMock) as mock_retrieve,
        patch("src.api.routers.qa.get_settings") as mock_settings,
    ):
        mock_settings.return_value.SMALL_CLAUDE_LLM = "claude-haiku-4-5-20251001"
        mock_settings.return_value.LARGE_CLAUDE_LLM = "claude-sonnet-4-6"
        mock_settings.return_value.RAG_WINDOW_DAYS = 7
        mock_classify.return_value = {"in_scope": True}
        mock_retrieve.return_value = []

        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/qa",
                json={"question": "Which LLM papers were published this week?"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "empty"
    assert body["data"] is None
    assert len(body["reason"]) > 0


# ---------------------------------------------------------------------------
# Tests: request validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_qa_empty_question_returns_422():
    """Empty question string fails Pydantic validation with 422."""
    session = _mock_session()
    app = _make_app(session)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/qa", json={"question": ""})

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_qa_missing_question_field_returns_422():
    """Missing question field fails Pydantic validation with 422."""
    session = _mock_session()
    app = _make_app(session)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/qa", json={})

    assert resp.status_code == 422
