"""Groundbreaking Detector — classifies whether a paper is a breakthrough.

A paper is flagged as groundbreaking only when BOTH criteria are satisfied:

1. It claims a measurable improvement on an established benchmark.
2. It introduces a new architecture or paradigm (not incremental tuning).

When both are confirmed the paper receives ``is_groundbreaking=True`` and a
reasoning string of the form
``"Improves {benchmark}; introduces {novel element}."``.

Failing either criterion leaves ``is_groundbreaking=False`` and
``groundbreaking_reasoning=None``. There is no partial flag state.
"""

import time

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.db.models import Paper
from src.llm.client import parse_structured
from src.utils.funcs import logger

config = get_settings()


class _GroundbreakingSchema(BaseModel):
    """LLM output schema for groundbreaking classification.

    Both evidence fields must be non-null for a paper to be flagged.
    """

    is_groundbreaking: bool
    benchmark_improved: str | None
    novel_element: str | None


async def detect_groundbreaking(paper: Paper, session: AsyncSession) -> None:
    """Evaluate a paper against groundbreaking criteria and persist the result.

    Calls Claude Sonnet via ``parse_structured`` to assess two criteria:
    benchmark improvement and architectural novelty. Both must be confirmed
    (non-null evidence fields) for the paper to be flagged. On LLM failure
    the paper is left un-flagged (False / null) and the update is still
    committed so the caller can continue.

    Args:
        paper: The persisted Paper ORM instance to evaluate and update.
        session: Async SQLAlchemy session used to commit the updated paper.
    """
    logger.debug("detect_groundbreaking entry arxiv_id=%s", paper.arxiv_id)
    t0 = time.perf_counter()
    prompt = (
        f"Title: {paper.title}\n"
        f"Abstract: {paper.abstract}\n"
        f"Contributions: {paper.contributions}\n"
        f"Methodologies: {paper.methodologies}\n"
        f"Benchmarks: {paper.benchmarks}\n\n"
        "Assess whether this paper is groundbreaking by checking BOTH criteria:\n"
        "1. Does it claim a measurable improvement on an established benchmark? "
        "If yes, name the benchmark in benchmark_improved.\n"
        "2. Does it introduce a genuinely new architecture or paradigm (not merely "
        "incremental tuning)? If yes, describe it in novel_element.\n\n"
        "Set is_groundbreaking=true only if BOTH criteria are clearly satisfied. "
        "Leave benchmark_improved and/or novel_element as null when the criterion "
        "is not met."
    )

    try:
        result: _GroundbreakingSchema = await parse_structured(
            config.LARGE_CLAUDE_LLM, prompt, _GroundbreakingSchema
        )
    except Exception as exc:
        logger.error(
            "parse_structured failed for %s: %s; leaving paper un-flagged",
            paper.arxiv_id,
            exc,
        )
        paper.is_groundbreaking = False
        paper.groundbreaking_reasoning = None
        await session.commit()
        return

    # Require explicit confirmation from both evidence fields regardless of
    # what the LLM set for is_groundbreaking — prevents partial flag states.
    both_criteria = (
        result.benchmark_improved is not None and result.novel_element is not None
    )

    if result.is_groundbreaking and both_criteria:
        paper.is_groundbreaking = True
        paper.groundbreaking_reasoning = (
            f"Improves {result.benchmark_improved}; introduces {result.novel_element}."
        )
        logger.info(
            "detect_groundbreaking done arxiv_id=%s groundbreaking=True"
            " elapsed_s=%.3f reasoning=%s",
            paper.arxiv_id,
            time.perf_counter() - t0,
            paper.groundbreaking_reasoning,
        )
    else:
        paper.is_groundbreaking = False
        paper.groundbreaking_reasoning = None
        logger.info(
            "detect_groundbreaking done arxiv_id=%s groundbreaking=False"
            " elapsed_s=%.3f",
            paper.arxiv_id,
            time.perf_counter() - t0,
        )

    await session.commit()
