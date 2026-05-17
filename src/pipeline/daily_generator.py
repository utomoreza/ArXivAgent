"""Daily Digest Generator — group papers by topic and produce a DailyDigest.

Runs after all papers for a given announcement day have been processed.
Skips immediately if the DateRecord for the date is not ``published``.

For each topic group the LLM renders a Markdown ``body``; sections are
persisted as ``TopicSection`` rows and returned sorted by ``paper_count DESC``.
"""

import datetime
import uuid
from collections import defaultdict

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.db import constants
from src.db.models import DailyDigest, DateRecord, Paper, TopicSection
from src.llm.client import parse_structured
from src.utils.funcs import logger

_config = get_settings()


class _TopicBodySchema(BaseModel):
    """LLM output schema for a single topic section body."""

    body: str


class DailyDigestGenerator:
    """Orchestrates digest creation for a single announcement day.

    Call ``generate(date, session)`` as the main entry point; the private
    helpers each own one clearly-scoped responsibility.
    """

    async def _check_date_record(
        self, date: datetime.date, session: AsyncSession
    ) -> DateRecord | None:
        """Return the DateRecord for *date* only when its status is 'published'.

        Args:
            date: The announcement date to check.
            session: Async SQLAlchemy session.

        Returns:
            The DateRecord when published, else None.
        """
        record: DateRecord | None = await session.get(DateRecord, date)
        if record is None or record.status != constants.DATE_STATUS_PUBLISHED:
            logger.info(
                "skipping daily digest for %s: status=%s",
                date,
                record.status if record else None,
            )
            return None
        return record

    async def _fetch_papers(
        self, date: datetime.date, session: AsyncSession
    ) -> list[Paper]:
        """Query all Paper rows submitted on *date*.

        Args:
            date: The announcement date to query.
            session: Async SQLAlchemy session.

        Returns:
            List of Paper ORM instances (may be empty).
        """
        stmt = select(Paper).where(Paper.submitted_date == date)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    def _group_and_sort(
        self, papers: list[Paper]
    ) -> list[tuple[str, list[Paper]]]:
        """Group papers by primary_topic, largest group first.

        Args:
            papers: All papers for the announcement day.

        Returns:
            (topic_name, papers) tuples sorted by group size DESC.
        """
        groups: dict[str, list[Paper]] = defaultdict(list)
        for paper in papers:
            groups[paper.primary_topic].append(paper)
        return sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)

    async def _generate_topic_body(
        self, topic_name: str, papers: list[Paper]
    ) -> str:
        """Call Claude Sonnet to render a Markdown section for one topic.

        Args:
            topic_name: Human-readable label, e.g. 'Large Language Models'.
            papers: Papers belonging to this topic.

        Returns:
            Rendered Markdown string for the TopicSection body.
        """
        paper_summaries = "\n\n".join(
            f"**{p.title}** ({p.arxiv_id})\n"
            f"Abstract: {p.abstract}\n"
            f"Contributions: {p.contributions}\n"
            f"Methodologies: {p.methodologies}\n"
            f"Benchmarks: {p.benchmarks}"
            + (
                f"\n⭐ Groundbreaking: {p.groundbreaking_reasoning}"
                if p.is_groundbreaking
                else ""
            )
            for p in papers
        )
        prompt = (
            f"Generate a concise Markdown digest section for the topic '{topic_name}'. "
            f"Summarise the following {len(papers)} paper(s):\n\n{paper_summaries}"
        )
        result: _TopicBodySchema = await parse_structured(
            _config.LARGE_CLAUDE_LLM, prompt, _TopicBodySchema
        )
        return result.body

    async def _build_sections(
        self,
        digest: DailyDigest,
        sorted_groups: list[tuple[str, list[Paper]]],
        session: AsyncSession,
    ) -> list[TopicSection]:
        """Create TopicSection rows and wire paper.topic_section_id for each group.

        Args:
            digest: The DailyDigest row (already added to session; id is set).
            sorted_groups: Topic groups sorted by paper count DESC.
            session: Async SQLAlchemy session.

        Returns:
            Ordered list of TopicSection instances matching sorted_groups order.
        """
        sections: list[TopicSection] = []
        for topic_name, topic_papers in sorted_groups:
            body = await self._generate_topic_body(topic_name, topic_papers)
            section = TopicSection(
                id=uuid.uuid4(),
                digest_id=digest.id,
                name=topic_name,
                paper_count=len(topic_papers),
                body=body,
            )
            session.add(section)
            for paper in topic_papers:
                paper.topic_section_id = section.id
            sections.append(section)
        return sections

    async def generate(
        self, date: datetime.date, session: AsyncSession
    ) -> DailyDigest | None:
        """Generate and persist a DailyDigest for the given announcement date.

        Returns None immediately if the date has no published DateRecord.
        Groups papers by primary_topic, renders Markdown per topic via the LLM,
        persists DailyDigest + TopicSection rows, updates every paper's
        topic_section_id, and returns the digest with sections attached in
        paper_count DESC order.

        Args:
            date: The arXiv announcement date to generate a digest for.
            session: Async SQLAlchemy session used for all DB reads and writes.

        Returns:
            The persisted DailyDigest with topic_sections sorted by
            paper_count DESC, or None if the date is not published.
        """
        if not await self._check_date_record(date, session):
            return None

        papers = await self._fetch_papers(date, session)
        if not papers:
            logger.info("no papers found for published date %s; skipping digest", date)
            return None

        sorted_groups = self._group_and_sort(papers)
        groundbreaking_count = sum(1 for p in papers if p.is_groundbreaking)
        now = datetime.datetime.now(datetime.UTC)

        digest = DailyDigest(
            id=uuid.uuid4(),
            date=date,
            generated_at=now,
            paper_count=len(papers),
            groundbreaking_count=groundbreaking_count,
        )
        session.add(digest)

        sections = await self._build_sections(digest, sorted_groups, session)
        # Attach sorted sections before commit so the relationship is populated
        # in-memory; avoids triggering lazy loading after the session flushes.
        digest.topic_sections = sections
        await session.commit()

        logger.info(
            "generated daily digest for %s: %d papers, %d groundbreaking, %d topics",
            date,
            len(papers),
            groundbreaking_count,
            len(sections),
        )
        return digest
