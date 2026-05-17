"""Unit tests for src/pipeline/rag_indexer.py (T038).

Covers:
- Exactly 2 PaperEmbedding rows created per paper (abstract + content).
- Abstract chunk never truncates.
- Content chunk truncation: benchmarks removed first, then methodologies, then contributions.
- All denormalized metadata fields are populated on both rows.
"""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from src.db.models import Paper

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DATE = datetime.date(2026, 4, 7)


def _make_paper(
    arxiv_id: str = "2504.00001",
    contributions: str = "Short contributions.",
    methodologies: str = "Short methodologies.",
    benchmarks: str = "Short benchmarks.",
    is_groundbreaking: bool = False,
    groundbreaking_reasoning: str | None = None,
) -> MagicMock:
    p = MagicMock(spec=Paper)
    p.arxiv_id = arxiv_id
    p.title = "Test Paper Title"
    p.authors = ["Alice Smith", "Bob Jones"]
    p.institutions = ["MIT", "Stanford"]
    p.abstract = "This is the abstract."
    p.submitted_date = _DATE
    p.primary_topic = "Large Language Models"
    p.secondary_topics = ["Computer Vision"]
    p.is_groundbreaking = is_groundbreaking
    p.groundbreaking_reasoning = groundbreaking_reasoning
    p.contributions = contributions
    p.methodologies = methodologies
    p.benchmarks = benchmarks
    return p


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session


def _words(n: int, prefix: str = "word") -> str:
    """Return a string of n distinct-looking words to inflate token count."""
    return " ".join(f"{prefix}{i}" for i in range(n))


# ---------------------------------------------------------------------------
# Tests: two rows created per paper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_index_paper_creates_exactly_two_embeddings():
    """index_paper persists exactly 2 PaperEmbedding rows: one abstract, one content."""
    from src.pipeline.rag_indexer import index_paper

    paper = _make_paper()
    session = _make_session()
    mock_embed = MagicMock(return_value=np.zeros((2, 384), dtype=np.float32))

    with patch("src.pipeline.rag_indexer.embed", mock_embed):
        await index_paper(paper, session)

    assert session.add.call_count == 2
    added_objects = [call_args[0][0] for call_args in session.add.call_args_list]
    chunk_types = {obj.chunk_type for obj in added_objects}
    assert chunk_types == {"abstract", "content"}


@pytest.mark.asyncio
async def test_index_paper_commits_session():
    """index_paper commits the session after adding both embeddings."""
    from src.pipeline.rag_indexer import index_paper

    paper = _make_paper()
    session = _make_session()
    mock_embed = MagicMock(return_value=np.zeros((2, 384), dtype=np.float32))

    with patch("src.pipeline.rag_indexer.embed", mock_embed):
        await index_paper(paper, session)

    session.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# Tests: abstract chunk
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_abstract_chunk_omits_institutions_line_when_empty():
    """Abstract chunk skips the Institutions line when paper.institutions is empty."""
    from src.pipeline.rag_indexer import index_paper

    paper = _make_paper()
    paper.institutions = []
    session = _make_session()
    mock_embed = MagicMock(return_value=np.zeros((2, 384), dtype=np.float32))

    with patch("src.pipeline.rag_indexer.embed", mock_embed):
        await index_paper(paper, session)

    added_objects = [call_args[0][0] for call_args in session.add.call_args_list]
    abstract_row = next(o for o in added_objects if o.chunk_type == "abstract")
    assert "Institutions:" not in abstract_row.content


@pytest.mark.asyncio
async def test_abstract_chunk_contains_title_authors_institutions_abstract():
    """Abstract chunk includes all expected text components."""
    from src.pipeline.rag_indexer import index_paper

    paper = _make_paper()
    session = _make_session()
    mock_embed = MagicMock(return_value=np.zeros((2, 384), dtype=np.float32))

    with patch("src.pipeline.rag_indexer.embed", mock_embed):
        await index_paper(paper, session)

    added_objects = [call_args[0][0] for call_args in session.add.call_args_list]
    abstract_row = next(o for o in added_objects if o.chunk_type == "abstract")
    content = abstract_row.content
    assert paper.title in content
    assert "Alice Smith" in content
    assert "Bob Jones" in content
    assert "MIT" in content
    assert "Stanford" in content
    assert paper.abstract in content


@pytest.mark.asyncio
async def test_abstract_chunk_never_truncates_for_normal_paper():
    """Abstract chunk stays well within token limits for a typical arXiv paper."""
    from src.pipeline.rag_indexer import index_paper

    # 150-word abstract — well within any practical limit
    long_abstract = _words(150)
    paper = _make_paper()
    paper.abstract = long_abstract

    session = _make_session()
    mock_embed = MagicMock(return_value=np.zeros((2, 384), dtype=np.float32))

    with patch("src.pipeline.rag_indexer.embed", mock_embed):
        await index_paper(paper, session)

    added_objects = [call_args[0][0] for call_args in session.add.call_args_list]
    abstract_row = next(o for o in added_objects if o.chunk_type == "abstract")
    assert long_abstract in abstract_row.content


# ---------------------------------------------------------------------------
# Tests: content chunk truncation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_content_chunk_not_truncated_when_under_limit():
    """Content chunk is returned intact when token count is under 512."""
    from src.pipeline.rag_indexer import index_paper

    paper = _make_paper(
        contributions="Contributions here.",
        methodologies="Methodologies here.",
        benchmarks="Benchmarks here.",
    )
    session = _make_session()
    mock_embed = MagicMock(return_value=np.zeros((2, 384), dtype=np.float32))

    with patch("src.pipeline.rag_indexer.embed", mock_embed):
        await index_paper(paper, session)

    added_objects = [call_args[0][0] for call_args in session.add.call_args_list]
    content_row = next(o for o in added_objects if o.chunk_type == "content")
    assert "Contributions here." in content_row.content
    assert "Methodologies here." in content_row.content
    assert "Benchmarks here." in content_row.content


@pytest.mark.asyncio
async def test_content_chunk_truncates_benchmarks_first():
    """When content > 512 tokens, benchmarks are removed first."""
    from src.pipeline.rag_indexer import index_paper

    # contributions(200) + methodologies(200) + benchmarks(200) > 512
    # contributions(200) + methodologies(200) < 512
    contributions = _words(200, "contrib")
    methodologies = _words(200, "method")
    benchmarks = _words(200, "bench")
    paper = _make_paper(
        contributions=contributions,
        methodologies=methodologies,
        benchmarks=benchmarks,
    )
    session = _make_session()
    mock_embed = MagicMock(return_value=np.zeros((2, 384), dtype=np.float32))

    with patch("src.pipeline.rag_indexer.embed", mock_embed):
        await index_paper(paper, session)

    added_objects = [call_args[0][0] for call_args in session.add.call_args_list]
    content_row = next(o for o in added_objects if o.chunk_type == "content")
    chunk = content_row.content
    # Benchmarks removed
    assert benchmarks not in chunk
    # Contributions and methodologies preserved
    assert contributions in chunk
    assert methodologies in chunk


@pytest.mark.asyncio
async def test_content_chunk_truncates_methodologies_when_still_over_limit():
    """When contributions alone > 512 tokens, methodologies are also removed."""
    from src.pipeline.rag_indexer import index_paper

    # contributions(400) > 512 by itself? No — 400 + title ~< 512.
    # contributions(350) + methodologies(350) = 700+ > 512 even without benchmarks
    contributions = _words(350, "contrib")
    methodologies = _words(350, "method")
    benchmarks = _words(100, "bench")
    paper = _make_paper(
        contributions=contributions,
        methodologies=methodologies,
        benchmarks=benchmarks,
    )
    session = _make_session()
    mock_embed = MagicMock(return_value=np.zeros((2, 384), dtype=np.float32))

    with patch("src.pipeline.rag_indexer.embed", mock_embed):
        await index_paper(paper, session)

    added_objects = [call_args[0][0] for call_args in session.add.call_args_list]
    content_row = next(o for o in added_objects if o.chunk_type == "content")
    chunk = content_row.content
    # Both benchmarks and methodologies removed
    assert benchmarks not in chunk
    assert methodologies not in chunk
    # Contributions preserved
    assert contributions in chunk


@pytest.mark.asyncio
async def test_content_chunk_truncates_contributions_as_last_resort():
    """When even contributions exceeds cap, contributions are removed too."""
    from src.pipeline.rag_indexer import index_paper

    contributions = _words(600, "contrib")
    methodologies = _words(600, "method")
    benchmarks = _words(600, "bench")
    paper = _make_paper(
        contributions=contributions,
        methodologies=methodologies,
        benchmarks=benchmarks,
    )
    session = _make_session()
    mock_embed = MagicMock(return_value=np.zeros((2, 384), dtype=np.float32))

    with patch("src.pipeline.rag_indexer.embed", mock_embed):
        await index_paper(paper, session)

    added_objects = [call_args[0][0] for call_args in session.add.call_args_list]
    content_row = next(o for o in added_objects if o.chunk_type == "content")
    chunk = content_row.content
    # All three removed (only title remains)
    assert contributions not in chunk
    assert methodologies not in chunk
    assert benchmarks not in chunk
    assert paper.title in chunk


# ---------------------------------------------------------------------------
# Tests: content chunk includes groundbreaking reasoning when flagged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_content_chunk_includes_groundbreaking_reasoning():
    """Content chunk appends groundbreaking_reasoning when paper is flagged."""
    from src.pipeline.rag_indexer import index_paper

    reasoning = "Improves GLUE; introduces sparse Mamba attention."
    paper = _make_paper(is_groundbreaking=True, groundbreaking_reasoning=reasoning)
    session = _make_session()
    mock_embed = MagicMock(return_value=np.zeros((2, 384), dtype=np.float32))

    with patch("src.pipeline.rag_indexer.embed", mock_embed):
        await index_paper(paper, session)

    added_objects = [call_args[0][0] for call_args in session.add.call_args_list]
    content_row = next(o for o in added_objects if o.chunk_type == "content")
    assert reasoning in content_row.content


@pytest.mark.asyncio
async def test_content_chunk_omits_groundbreaking_reasoning_when_not_flagged():
    """Content chunk has no groundbreaking reasoning when paper is not flagged."""
    from src.pipeline.rag_indexer import index_paper

    paper = _make_paper(is_groundbreaking=False, groundbreaking_reasoning=None)
    session = _make_session()
    mock_embed = MagicMock(return_value=np.zeros((2, 384), dtype=np.float32))

    with patch("src.pipeline.rag_indexer.embed", mock_embed):
        await index_paper(paper, session)

    added_objects = [call_args[0][0] for call_args in session.add.call_args_list]
    content_row = next(o for o in added_objects if o.chunk_type == "content")
    assert "Groundbreaking" not in content_row.content


# ---------------------------------------------------------------------------
# Tests: denormalized metadata fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_denormalized_fields_populated_on_both_rows():
    """All denormalized metadata fields are set correctly on both embedding rows."""
    from src.pipeline.rag_indexer import index_paper

    paper = _make_paper(is_groundbreaking=True, groundbreaking_reasoning="reason.")
    session = _make_session()
    mock_embed = MagicMock(return_value=np.zeros((2, 384), dtype=np.float32))

    with patch("src.pipeline.rag_indexer.embed", mock_embed):
        await index_paper(paper, session)

    added_objects = [call_args[0][0] for call_args in session.add.call_args_list]
    for row in added_objects:
        assert row.arxiv_id == paper.arxiv_id
        assert row.date == paper.submitted_date
        assert row.primary_topic == paper.primary_topic
        assert row.secondary_topics == paper.secondary_topics
        assert row.is_groundbreaking == paper.is_groundbreaking
        assert row.title == paper.title
        assert row.authors == paper.authors
        assert row.institutions == paper.institutions
        assert row.embedding is not None
        assert row.content is not None
        assert row.id is not None
