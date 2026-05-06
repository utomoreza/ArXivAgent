"""Unit tests for src/pipeline/detector.py.

Covers (per T018 / spec.md FR-011):
- Paper with both criteria (benchmark improvement + novel architecture) is
  flagged with non-empty reasoning in the format
  "Improves {benchmark}; introduces {novel element}."
- Paper failing EITHER criterion alone is NOT flagged (no partial flag).
- No partial flag state exists: is_groundbreaking=True always has non-null
  reasoning, is_groundbreaking=False always has null reasoning.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.models import Paper
from src.pipeline.detector import detect_groundbreaking


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_paper(**kwargs) -> MagicMock:
    """Build a minimal Paper-like mock with sensible defaults."""
    paper = MagicMock(spec=Paper)
    paper.arxiv_id = "2504.99999"
    paper.title = "Test Paper"
    paper.abstract = "An abstract."
    paper.contributions = "Novel contributions."
    paper.methodologies = "New method."
    paper.benchmarks = "BLEU +5."
    paper.is_groundbreaking = False
    paper.groundbreaking_reasoning = None
    for k, v in kwargs.items():
        setattr(paper, k, v)
    return paper


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.commit = AsyncMock()
    return session


def _parse_structured_result(
    is_groundbreaking: bool,
    benchmark_improved: str | None,
    novel_element: str | None,
) -> MagicMock:
    """Build a mock Pydantic-style result from parse_structured."""
    result = MagicMock()
    result.is_groundbreaking = is_groundbreaking
    result.benchmark_improved = benchmark_improved
    result.novel_element = novel_element
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_both_criteria_met_flags_paper_with_reasoning():
    """Paper with benchmark_improved + novel_element gets flagged with reasoning."""
    paper = _make_paper()
    session = _make_session()
    llm_result = _parse_structured_result(
        is_groundbreaking=True,
        benchmark_improved="ImageNet top-1",
        novel_element="sparse Mixture-of-Experts layer",
    )

    with patch(
        "src.pipeline.detector.parse_structured", new=AsyncMock(return_value=llm_result)
    ):
        await detect_groundbreaking(paper, session)

    assert paper.is_groundbreaking is True
    assert paper.groundbreaking_reasoning is not None
    assert "ImageNet top-1" in paper.groundbreaking_reasoning
    assert "sparse Mixture-of-Experts layer" in paper.groundbreaking_reasoning
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_benchmark_only_does_not_flag():
    """Paper improving a benchmark but lacking novelty is NOT flagged."""
    paper = _make_paper()
    session = _make_session()
    llm_result = _parse_structured_result(
        is_groundbreaking=False,
        benchmark_improved="MMLU",
        novel_element=None,
    )

    with patch(
        "src.pipeline.detector.parse_structured", new=AsyncMock(return_value=llm_result)
    ):
        await detect_groundbreaking(paper, session)

    assert paper.is_groundbreaking is False
    assert paper.groundbreaking_reasoning is None
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_novelty_only_does_not_flag():
    """Paper introducing novel architecture but no benchmark improvement is NOT flagged."""
    paper = _make_paper()
    session = _make_session()
    llm_result = _parse_structured_result(
        is_groundbreaking=False,
        benchmark_improved=None,
        novel_element="new attention mechanism",
    )

    with patch(
        "src.pipeline.detector.parse_structured", new=AsyncMock(return_value=llm_result)
    ):
        await detect_groundbreaking(paper, session)

    assert paper.is_groundbreaking is False
    assert paper.groundbreaking_reasoning is None
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_neither_criterion_does_not_flag():
    """Paper meeting neither criterion is NOT flagged."""
    paper = _make_paper()
    session = _make_session()
    llm_result = _parse_structured_result(
        is_groundbreaking=False,
        benchmark_improved=None,
        novel_element=None,
    )

    with patch(
        "src.pipeline.detector.parse_structured", new=AsyncMock(return_value=llm_result)
    ):
        await detect_groundbreaking(paper, session)

    assert paper.is_groundbreaking is False
    assert paper.groundbreaking_reasoning is None
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_llm_true_but_benchmark_missing_does_not_flag():
    """LLM says groundbreaking but benchmark_improved is None — we do NOT flag."""
    paper = _make_paper()
    session = _make_session()
    llm_result = _parse_structured_result(
        is_groundbreaking=True,
        benchmark_improved=None,
        novel_element="some architecture",
    )

    with patch(
        "src.pipeline.detector.parse_structured", new=AsyncMock(return_value=llm_result)
    ):
        await detect_groundbreaking(paper, session)

    assert paper.is_groundbreaking is False
    assert paper.groundbreaking_reasoning is None
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_llm_true_but_novel_element_missing_does_not_flag():
    """LLM says groundbreaking but novel_element is None — we do NOT flag."""
    paper = _make_paper()
    session = _make_session()
    llm_result = _parse_structured_result(
        is_groundbreaking=True,
        benchmark_improved="SuperGLUE",
        novel_element=None,
    )

    with patch(
        "src.pipeline.detector.parse_structured", new=AsyncMock(return_value=llm_result)
    ):
        await detect_groundbreaking(paper, session)

    assert paper.is_groundbreaking is False
    assert paper.groundbreaking_reasoning is None
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_llm_false_but_both_fields_present_does_not_flag():
    """LLM says not groundbreaking even with both fields present — we respect that."""
    paper = _make_paper()
    session = _make_session()
    llm_result = _parse_structured_result(
        is_groundbreaking=False,
        benchmark_improved="BLEU",
        novel_element="novel distillation scheme",
    )

    with patch(
        "src.pipeline.detector.parse_structured", new=AsyncMock(return_value=llm_result)
    ):
        await detect_groundbreaking(paper, session)

    assert paper.is_groundbreaking is False
    assert paper.groundbreaking_reasoning is None
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_llm_failure_leaves_paper_unflagged():
    """parse_structured raising an exception leaves the paper un-flagged and still commits."""
    paper = _make_paper()
    session = _make_session()

    with patch(
        "src.pipeline.detector.parse_structured",
        new=AsyncMock(side_effect=Exception("API timeout")),
    ):
        await detect_groundbreaking(paper, session)

    assert paper.is_groundbreaking is False
    assert paper.groundbreaking_reasoning is None
    session.commit.assert_awaited_once()
