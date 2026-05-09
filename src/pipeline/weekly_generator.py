"""Weekly Digest Generator — synthesise a Sun-Thu week of daily digests.

Aggregates all DailyDigest rows within the week window and calls Claude Sonnet
three times to produce benchmark_comparisons, trend_synthesis, and
cross_paper_analysis sections.  Coverage arrays are built from DateRecord
statuses for the same window and stored inline on WeeklyDigest.
"""

import datetime
import uuid
from datetime import timedelta
from enum import StrEnum

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import get_settings
from src.db import constants
from src.db.models import DailyDigest, DateRecord, WeeklyDigest
from src.llm.client import parse_structured
from src.utils.funcs import logger

_config = get_settings()


class _SectionNames(StrEnum):
    BC = "benchmark_comparisons"
    TS = "trend_synthesis"
    CPA = "cross_paper_analysis"


_PROMPTS = {
    _SectionNames.BC.value: (
        "Based on the following week of ML research digests, write a "
        "Markdown section comparing the most significant benchmark results "
        "and performance improvements reported across all papers.\n\n"
    ),
    _SectionNames.TS.value: (
        "Based on the following week of ML research digests, write a "
        "Markdown section synthesising the dominant research trends, "
        "emerging themes, and notable shifts in the field this week.\n\n"
    ),
    _SectionNames.CPA.value: (
        "Based on the following week of ML research digests, write a "
        "Markdown section analysing connections, contradictions, and "
        "complementary findings across papers from different topics.\n\n"
    ),
}


class _SynthesisSection(BaseModel):
    """LLM output schema for one weekly synthesis section."""

    content: str


class WeeklyDigestGenerator:
    """Orchestrates weekly digest creation for a Sun-Thu announcement window.

    Call ``generate(week_start, session)`` as the main entry point.
    """

    def _validate_week_start(self, week_start: datetime.date) -> None:
        """Raise ValueError if week_start is not a Sunday.

        Args:
            week_start: The proposed start date.

        Raises:
            ValueError: If week_start.weekday() != 6 (Sunday).
        """
        if week_start.weekday() != 6:
            raise ValueError(
                f"week_start must be a Sunday, got {week_start.strftime('%A')} "
                f"({week_start})"
            )

    async def _fetch_digests(
        self,
        week_start: datetime.date,
        week_end: datetime.date,
        session: AsyncSession,
    ) -> list[DailyDigest]:
        """Query DailyDigest rows in the week window with their topic sections.

        Args:
            week_start: Sunday of the announcement week (inclusive).
            week_end: Thursday of the same week (inclusive).
            session: Async SQLAlchemy session.

        Returns:
            List of DailyDigest instances with topic_sections eager-loaded.
        """
        stmt = (
            select(DailyDigest)
            .where(DailyDigest.date.between(week_start, week_end))
            .options(selectinload(DailyDigest.topic_sections))
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def _fetch_date_records(
        self,
        week_start: datetime.date,
        week_end: datetime.date,
        session: AsyncSession,
    ) -> list[DateRecord]:
        """Query DateRecord rows in the week window for coverage arrays.

        Args:
            week_start: Sunday of the week (inclusive).
            week_end: Thursday of the week (inclusive).
            session: Async SQLAlchemy session.

        Returns:
            List of DateRecord instances for the window.
        """
        stmt = select(DateRecord).where(
            DateRecord.date.between(week_start, week_end)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    def _build_coverage_arrays(
        self,
        digests: list[DailyDigest],
        date_records: list[DateRecord],
    ) -> tuple[list[datetime.date], list[datetime.date], list[datetime.date]]:
        """Derive the three coverage arrays from digest dates and record statuses.

        days_with_content comes from the actual DailyDigest rows (not just
        published DateRecord rows) so it reflects what was actually generated.

        Args:
            digests: DailyDigest rows found for the week.
            date_records: DateRecord rows for the same window.

        Returns:
            Tuple of (days_with_content, no_papers_skips, fetch_failure_skips).
        """
        days_with_content = [d.date for d in digests]
        no_papers_skips = [
            dr.date
            for dr in date_records
            if dr.status == constants.DATE_STATUS_NO_PAPERS_SKIP
        ]
        fetch_failure_skips = [
            dr.date
            for dr in date_records
            if dr.status == constants.DATE_STATUS_FETCH_FAILURE_SKIP
        ]
        return days_with_content, no_papers_skips, fetch_failure_skips

    def _build_context(self, digests: list[DailyDigest]) -> str:
        """Flatten all TopicSection bodies from the week into one context string.

        Args:
            digests: Daily digests for the week, with topic_sections loaded.

        Returns:
            Multi-section Markdown context string for the LLM prompts.
        """
        parts: list[str] = []
        for digest in digests:
            parts.append(f"### {digest.date}")
            for section in digest.topic_sections:
                parts.append(f"#### {section.name}\n{section.body}")
        return "\n\n".join(parts)

    async def _generate_section(self, section_name: _SectionNames, context: str) -> str:
        """Call Claude Sonnet to render one weekly synthesis section.

        Args:
            section_name: One of 'benchmark_comparisons', 'trend_synthesis',
                or 'cross_paper_analysis'.
            context: Flattened week content to provide as LLM context.

        Returns:
            Rendered Markdown string for the section.
        """
        prompt = _PROMPTS[section_name] + context
        result: _SynthesisSection = await parse_structured(
            _config.LARGE_CLAUDE_LLM, prompt, _SynthesisSection
        )
        return result.content

    async def generate(
        self, week_start: datetime.date, session: AsyncSession
    ) -> WeeklyDigest | None:
        """Generate and persist a WeeklyDigest for the Sun-Thu window.

        Validates that week_start is a Sunday, then queries all DailyDigest rows
        in the window.  Returns None if none exist.  Calls Sonnet three times for
        the synthesis sections, builds coverage arrays from DateRecord statuses,
        and persists the WeeklyDigest.

        Args:
            week_start: The Sunday opening the announcement week.
            session: Async SQLAlchemy session used for all DB reads and writes.

        Returns:
            The persisted WeeklyDigest, or None when no daily digests exist.

        Raises:
            ValueError: If week_start is not a Sunday.
        """
        self._validate_week_start(week_start)
        week_end = week_start + timedelta(days=4)

        digests = await self._fetch_digests(week_start, week_end, session)
        if not digests:
            logger.info("no daily digests found for week starting %s", week_start)
            return None

        date_records = await self._fetch_date_records(week_start, week_end, session)
        days_with_content, no_papers_skips, fetch_failure_skips = (
            self._build_coverage_arrays(digests, date_records)
        )

        context = self._build_context(digests)
        generated_sections = {}
        for section in _SectionNames:
            generated_sections[section.value] = await self._generate_section(
                section.value, context
            )

        paper_count = sum(d.paper_count for d in digests)
        groundbreaking_count = sum(d.groundbreaking_count for d in digests)
        now = datetime.datetime.now(datetime.UTC)

        weekly = WeeklyDigest(
            id=uuid.uuid4(),
            week_start=week_start,
            week_end=week_end,
            generated_at=now,
            paper_count=paper_count,
            groundbreaking_count=groundbreaking_count,
            benchmark_comparisons=generated_sections[_SectionNames.BC.value],
            trend_synthesis=generated_sections[_SectionNames.TS.value],
            cross_paper_analysis=generated_sections[_SectionNames.CPA.value],
            days_with_content=days_with_content,
            no_papers_skips=no_papers_skips,
            fetch_failure_skips=fetch_failure_skips,
        )
        session.add(weekly)
        await session.commit()

        logger.info(
            "generated weekly digest for week %s-%s: %d papers, %d topics",
            week_start,
            week_end,
            paper_count,
            len(digests),
        )
        return weekly
