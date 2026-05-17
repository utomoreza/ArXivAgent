"""Unit tests for src/pipeline/daily_generator.py.

Covers (per T020):
- No digest is produced when DateRecord.status != 'published'.
- All papers are assigned topic_section_id after generation.
- groundbreaking_count exactly matches papers with is_groundbreaking=True.
- Topics are returned ordered by paper_count DESC.
"""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.constants import (
    DATE_STATUS_FETCH_FAILURE_SKIP,
    DATE_STATUS_NO_ANNOUNCEMENT,
    DATE_STATUS_NO_PAPERS_SKIP,
    DATE_STATUS_PUBLISHED,
)
from src.db.models import DateRecord, Paper
from src.pipeline.daily_generator import DailyDigestGenerator

_DATE = datetime.date(2026, 4, 21)  # Monday — valid announcement day


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_date_record(status: str) -> MagicMock:
    dr = MagicMock(spec=DateRecord)
    dr.date = _DATE
    dr.status = status
    dr.paper_count = 3 if status == DATE_STATUS_PUBLISHED else None
    return dr


def _make_paper(
    topic: str,
    is_groundbreaking: bool = False,
    arxiv_id: str | None = None,
) -> MagicMock:
    p = MagicMock(spec=Paper)
    p.arxiv_id = arxiv_id or f"2504.{hash(topic) % 90000 + 10000}"
    p.title = f"Paper on {topic}"
    p.abstract = "An abstract."
    p.contributions = "Contributions."
    p.methodologies = "Methods."
    p.benchmarks = "Benchmarks."
    p.primary_topic = topic
    p.is_groundbreaking = is_groundbreaking
    p.groundbreaking_reasoning = "Reasoning." if is_groundbreaking else None
    p.topic_section_id = None
    return p


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


def _make_execute_result(items: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


def _make_body_result() -> MagicMock:
    m = MagicMock()
    m.body = "## Topic section body\n\nSome content."
    return m


# ---------------------------------------------------------------------------
# Tests: skip non-published dates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [DATE_STATUS_NO_ANNOUNCEMENT, DATE_STATUS_NO_PAPERS_SKIP, DATE_STATUS_FETCH_FAILURE_SKIP],
)
async def test_no_digest_for_non_published_status(status: str) -> None:
    """No digest is produced for any non-published DateRecord status."""
    session = _make_session()
    session.get = AsyncMock(return_value=_make_date_record(status))

    with patch("src.pipeline.daily_generator.parse_structured", new=AsyncMock()):
        result = await DailyDigestGenerator().generate(_DATE, session)

    assert result is None
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_digest_when_date_record_missing() -> None:
    """No digest produced when no DateRecord exists for the date."""
    session = _make_session()
    session.get = AsyncMock(return_value=None)

    with patch("src.pipeline.daily_generator.parse_structured", new=AsyncMock()):
        result = await DailyDigestGenerator().generate(_DATE, session)

    assert result is None
    session.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests: papers assigned topic_section_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_papers_assigned_topic_section_id() -> None:
    """Every paper has topic_section_id set to a non-None UUID after generation."""
    papers = [
        _make_paper("Large Language Models", arxiv_id="2504.00001"),
        _make_paper("Large Language Models", arxiv_id="2504.00002"),
        _make_paper("Computer Vision", arxiv_id="2504.00003"),
    ]
    session = _make_session()
    session.get = AsyncMock(return_value=_make_date_record(DATE_STATUS_PUBLISHED))
    session.execute = AsyncMock(return_value=_make_execute_result(papers))

    with patch(
        "src.pipeline.daily_generator.parse_structured",
        new=AsyncMock(return_value=_make_body_result()),
    ):
        result = await DailyDigestGenerator().generate(_DATE, session)

    assert result is not None
    for paper in papers:
        assert paper.topic_section_id is not None, (
            f"paper {paper.arxiv_id} still has topic_section_id=None"
        )


# ---------------------------------------------------------------------------
# Tests: groundbreaking_count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_groundbreaking_count_matches_flagged_papers() -> None:
    """groundbreaking_count equals the count of is_groundbreaking=True papers."""
    papers = [
        _make_paper("Large Language Models", is_groundbreaking=True, arxiv_id="2504.00001"),
        _make_paper("Large Language Models", is_groundbreaking=True, arxiv_id="2504.00002"),
        _make_paper("Computer Vision", is_groundbreaking=False, arxiv_id="2504.00003"),
        _make_paper("Computer Vision", is_groundbreaking=False, arxiv_id="2504.00004"),
    ]
    session = _make_session()
    session.get = AsyncMock(return_value=_make_date_record(DATE_STATUS_PUBLISHED))
    session.execute = AsyncMock(return_value=_make_execute_result(papers))

    with patch(
        "src.pipeline.daily_generator.parse_structured",
        new=AsyncMock(return_value=_make_body_result()),
    ):
        result = await DailyDigestGenerator().generate(_DATE, session)

    assert result is not None
    assert result.groundbreaking_count == 2


@pytest.mark.asyncio
async def test_groundbreaking_count_zero_when_none_flagged() -> None:
    """groundbreaking_count is 0 when no papers are flagged."""
    papers = [
        _make_paper("Robotics", arxiv_id="2504.00001"),
        _make_paper("Robotics", arxiv_id="2504.00002"),
    ]
    session = _make_session()
    session.get = AsyncMock(return_value=_make_date_record(DATE_STATUS_PUBLISHED))
    session.execute = AsyncMock(return_value=_make_execute_result(papers))

    with patch(
        "src.pipeline.daily_generator.parse_structured",
        new=AsyncMock(return_value=_make_body_result()),
    ):
        result = await DailyDigestGenerator().generate(_DATE, session)

    assert result is not None
    assert result.groundbreaking_count == 0


@pytest.mark.asyncio
async def test_no_digest_when_no_papers_despite_published_record() -> None:
    """Returns None (without committing) when the paper query returns empty."""
    session = _make_session()
    session.get = AsyncMock(return_value=_make_date_record(DATE_STATUS_PUBLISHED))
    session.execute = AsyncMock(return_value=_make_execute_result([]))

    with patch("src.pipeline.daily_generator.parse_structured", new=AsyncMock()):
        result = await DailyDigestGenerator().generate(_DATE, session)

    assert result is None
    session.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests: groundbreaking callout in topic body
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_groundbreaking_callout_appended_to_body() -> None:
    """Body for a topic with a groundbreaking paper contains the reasoning callout."""
    gb_paper = _make_paper("Large Language Models", is_groundbreaking=True, arxiv_id="2504.00001")
    gb_paper.groundbreaking_reasoning = "Improves GLUE; introduces sparse attention."
    non_gb = _make_paper("Large Language Models", is_groundbreaking=False, arxiv_id="2504.00002")
    papers = [gb_paper, non_gb]

    session = _make_session()
    session.get = AsyncMock(return_value=_make_date_record(DATE_STATUS_PUBLISHED))
    session.execute = AsyncMock(return_value=_make_execute_result(papers))

    with patch(
        "src.pipeline.daily_generator.parse_structured",
        new=AsyncMock(return_value=_make_body_result()),
    ):
        result = await DailyDigestGenerator().generate(_DATE, session)

    assert result is not None
    body = result.topic_sections[0].body
    assert "⭐ **Groundbreaking**" in body
    assert gb_paper.groundbreaking_reasoning in body


@pytest.mark.asyncio
async def test_no_callout_when_no_groundbreaking_papers() -> None:
    """Body for a topic with no groundbreaking papers has no callout block."""
    papers = [
        _make_paper("Robotics", is_groundbreaking=False, arxiv_id="2504.00001"),
        _make_paper("Robotics", is_groundbreaking=False, arxiv_id="2504.00002"),
    ]
    session = _make_session()
    session.get = AsyncMock(return_value=_make_date_record(DATE_STATUS_PUBLISHED))
    session.execute = AsyncMock(return_value=_make_execute_result(papers))

    with patch(
        "src.pipeline.daily_generator.parse_structured",
        new=AsyncMock(return_value=_make_body_result()),
    ):
        result = await DailyDigestGenerator().generate(_DATE, session)

    assert result is not None
    body = result.topic_sections[0].body
    assert "⭐ **Groundbreaking**" not in body


# ---------------------------------------------------------------------------
# Tests: topic ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topics_ordered_by_paper_count_desc() -> None:
    """topic_sections on the returned digest are ordered by paper_count DESC.

    6 papers across 3 topics (CV=3, RL=2, LLM=1). Asserts the sections come
    back in descending order and the total paper_count on the digest is correct.
    """
    # CV: 3 papers, RL: 2 papers, LLM: 1 paper → expected order CV, RL, LLM
    papers = [
        _make_paper("Computer Vision", arxiv_id="2504.00001"),
        _make_paper("Computer Vision", arxiv_id="2504.00002"),
        _make_paper("Computer Vision", arxiv_id="2504.00003"),
        _make_paper("Reinforcement Learning", arxiv_id="2504.00004"),
        _make_paper("Reinforcement Learning", arxiv_id="2504.00005"),
        _make_paper("Large Language Models", arxiv_id="2504.00006"),
    ]
    session = _make_session()
    session.get = AsyncMock(return_value=_make_date_record(DATE_STATUS_PUBLISHED))
    session.execute = AsyncMock(return_value=_make_execute_result(papers))

    with patch(
        "src.pipeline.daily_generator.parse_structured",
        new=AsyncMock(return_value=_make_body_result()),
    ):
        result = await DailyDigestGenerator().generate(_DATE, session)

    assert result is not None
    assert result.paper_count == 6

    sections = result.topic_sections
    assert len(sections) == 3

    counts = [s.paper_count for s in sections]
    assert counts == sorted(counts, reverse=True), (
        f"Sections not sorted DESC by paper_count: {counts}"
    )
    assert sections[0].name == "Computer Vision"
    assert sections[1].name == "Reinforcement Learning"
    assert sections[2].name == "Large Language Models"
