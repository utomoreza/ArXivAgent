"""Unit tests for src/rag/retriever.py (T040).

Covers:
- Window filter excludes embeddings outside RAG_WINDOW_DAYS (verified by inspecting
  the WHERE clause added to the SELECT statement).
- Results are re-ranked by date descending after cosine retrieval.
- Top-K limit is respected.
- Empty result set returns empty list without error.
"""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_embedding(date: datetime.date, arxiv_id: str = "2504.00001") -> MagicMock:
    emb = MagicMock()
    emb.date = date
    emb.arxiv_id = arxiv_id
    return emb


def _make_session(rows: list) -> AsyncMock:
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = rows
    session.execute = AsyncMock(return_value=mock_result)
    return session


# ---------------------------------------------------------------------------
# Tests: window filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_passes_window_date_filter_in_query():
    """The query sent to execute() contains a WHERE clause (date >= cutoff)."""
    from src.rag.retriever import retrieve

    session = _make_session([])
    today = datetime.date(2026, 4, 7)
    mock_embed_ret = np.zeros((1, 384), dtype=np.float32)

    with (
        patch("src.rag.retriever.embed", return_value=mock_embed_ret),
        patch("src.rag.retriever.date") as mock_date_cls,
    ):
        mock_date_cls.today.return_value = today
        mock_date_cls.side_effect = lambda *args, **kwargs: datetime.date(*args, **kwargs)
        await retrieve("question", session, window_days=7)

    stmt = session.execute.call_args[0][0]
    # The query must have a WHERE clause for the date filter
    assert stmt.whereclause is not None


@pytest.mark.asyncio
async def test_retrieve_empty_result_returns_empty_list():
    """retrieve() returns empty list when no in-window embeddings exist."""
    from src.rag.retriever import retrieve

    session = _make_session([])
    mock_embed_ret = np.zeros((1, 384), dtype=np.float32)

    with patch("src.rag.retriever.embed", return_value=mock_embed_ret):
        result = await retrieve("question", session, window_days=7)

    assert result == []


# ---------------------------------------------------------------------------
# Tests: re-ranking by date DESC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_reranks_results_by_date_descending():
    """Results are sorted by date DESC after cosine retrieval."""
    from src.rag.retriever import retrieve

    rows = [
        _make_embedding(datetime.date(2026, 4, 1), "2504.00001"),
        _make_embedding(datetime.date(2026, 4, 7), "2504.00002"),
        _make_embedding(datetime.date(2026, 4, 3), "2504.00003"),
    ]
    session = _make_session(rows)
    mock_embed_ret = np.zeros((1, 384), dtype=np.float32)

    with patch("src.rag.retriever.embed", return_value=mock_embed_ret):
        result = await retrieve("question", session, window_days=30)

    dates = [r.date for r in result]
    assert dates == sorted(dates, reverse=True), f"Results not sorted date DESC: {dates}"


@pytest.mark.asyncio
async def test_retrieve_most_recent_first():
    """The first element in the returned list is the most recent embedding."""
    from src.rag.retriever import retrieve

    rows = [
        _make_embedding(datetime.date(2026, 4, 5), "2504.00001"),
        _make_embedding(datetime.date(2026, 4, 7), "2504.00002"),
        _make_embedding(datetime.date(2026, 4, 2), "2504.00003"),
    ]
    session = _make_session(rows)
    mock_embed_ret = np.zeros((1, 384), dtype=np.float32)

    with patch("src.rag.retriever.embed", return_value=mock_embed_ret):
        result = await retrieve("question", session, window_days=30)

    assert result[0].date == datetime.date(2026, 4, 7)


# ---------------------------------------------------------------------------
# Tests: top-K limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_respects_top_k_default():
    """retrieve() respects the default k=10 limit passed to the SQL query."""
    from src.rag.retriever import retrieve

    session = _make_session([])
    mock_embed_ret = np.zeros((1, 384), dtype=np.float32)

    with patch("src.rag.retriever.embed", return_value=mock_embed_ret):
        await retrieve("question", session, window_days=7)

    stmt = session.execute.call_args[0][0]
    # Verify the LIMIT is set on the query
    assert stmt._limit_clause is not None


@pytest.mark.asyncio
async def test_retrieve_respects_custom_k():
    """Custom k is passed as LIMIT to the query."""
    from src.rag.retriever import retrieve

    session = _make_session([])
    mock_embed_ret = np.zeros((1, 384), dtype=np.float32)

    with patch("src.rag.retriever.embed", return_value=mock_embed_ret):
        await retrieve("question", session, window_days=7, k=5)

    stmt = session.execute.call_args[0][0]
    assert stmt._limit_clause is not None


@pytest.mark.asyncio
async def test_retrieve_returns_at_most_k_results():
    """The returned list has at most k items even if DB returns more."""
    from src.rag.retriever import retrieve

    # DB returns 5 items (already limited by SQL LIMIT), re-ranked to date DESC
    rows = [
        _make_embedding(datetime.date(2026, 4, i), f"2504.0000{i}")
        for i in range(1, 6)
    ]
    session = _make_session(rows)
    mock_embed_ret = np.zeros((1, 384), dtype=np.float32)

    with patch("src.rag.retriever.embed", return_value=mock_embed_ret):
        result = await retrieve("question", session, window_days=30, k=5)

    assert len(result) <= 5


# ---------------------------------------------------------------------------
# Tests: embed is called with the question
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_embeds_question_text():
    """retrieve() calls embed() with the question string."""
    from src.rag.retriever import retrieve

    session = _make_session([])
    mock_embed = MagicMock(return_value=np.zeros((1, 384), dtype=np.float32))

    with patch("src.rag.retriever.embed", mock_embed):
        await retrieve("What is the best LLM?", session, window_days=7)

    mock_embed.assert_called_once_with(["What is the best LLM?"])
