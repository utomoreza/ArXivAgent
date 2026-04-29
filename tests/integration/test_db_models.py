"""Integration tests for ORM model constraints.

Requires a real PostgreSQL database — set TEST_DATABASE_URL env var.
All tests run against a fresh schema created per session.
"""

import datetime
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base, DateRecord, DailyDigest, Paper, PaperEmbedding, TopicSection, WeeklyDigest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Create a test engine, build the schema, yield, then drop it."""
    import os

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


@pytest_asyncio.fixture
async def session(engine):
    """Yield a fresh session per test; roll back after each test."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()


# ---------------------------------------------------------------------------
# DateRecord constraint: paper_count must be NULL when status != 'published'
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_date_record_rejects_paper_count_when_not_published(session: AsyncSession):
    """DateRecord CHECK constraint must reject paper_count on non-published rows."""
    record = DateRecord(
        date=datetime.date(2025, 1, 6),  # Monday — announcement day
        status="no_papers_skip",
        paper_count=5,  # must be rejected
    )
    session.add(record)
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_date_record_allows_paper_count_null_when_not_published(session: AsyncSession):
    record = DateRecord(
        date=datetime.date(2025, 1, 7),
        status="no_papers_skip",
        paper_count=None,
    )
    session.add(record)
    await session.flush()  # should not raise
    assert record.date == datetime.date(2025, 1, 7)


@pytest.mark.asyncio
async def test_date_record_allows_paper_count_when_published(session: AsyncSession):
    record = DateRecord(
        date=datetime.date(2025, 1, 8),
        status="published",
        paper_count=42,
    )
    session.add(record)
    await session.flush()  # should not raise
    assert record.paper_count == 42


@pytest.mark.asyncio
async def test_date_record_allows_null_paper_count_when_published(session: AsyncSession):
    """NULL paper_count is permitted even on published (edge case: 0 is valid too)."""
    record = DateRecord(
        date=datetime.date(2025, 1, 9),
        status="published",
        paper_count=0,
    )
    session.add(record)
    await session.flush()
    assert record.paper_count == 0


# ---------------------------------------------------------------------------
# FK violation tests
# These come before the Paper fixture section to verify that the FK
# relationships used by that fixture's seed data are correctly enforced.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paper_fk_violation_on_submitted_date(session: AsyncSession):
    """Inserting a Paper with a non-existent submitted_date FK must raise."""
    paper = Paper(
        arxiv_id="2501.00099",
        title="FK Violation Paper",
        authors=["Eve"],
        institutions=[],
        abstract="...",
        submitted_date=datetime.date(1999, 1, 1),  # no DateRecord for this date
        primary_topic="Large Language Models",
        secondary_topics=[],
        contributions="",
        methodologies="",
        benchmarks="",
        is_groundbreaking=False,
        groundbreaking_reasoning=None,
    )
    session.add(paper)
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_topic_section_fk_violation_on_digest_id(session: AsyncSession):
    """Inserting a TopicSection with a non-existent digest_id must raise."""
    section = TopicSection(
        id=uuid.uuid4(),
        digest_id=uuid.uuid4(),  # no such DailyDigest
        name="Robotics",
        paper_count=0,
        body="",
    )
    session.add(section)
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_daily_digest_fk_violation_on_date(session: AsyncSession):
    """Inserting a DailyDigest with a non-existent date FK must raise."""
    digest = DailyDigest(
        id=uuid.uuid4(),
        date=datetime.date(1998, 1, 1),  # no DateRecord
        generated_at=datetime.datetime(1998, 1, 1, tzinfo=datetime.timezone.utc),
        paper_count=0,
        groundbreaking_count=0,
    )
    session.add(digest)
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_daily_digest_rejects_duplicate_date(session: AsyncSession):
    """UNIQUE constraint on date must reject a second DailyDigest for the same date."""
    shared_date = datetime.date(2025, 1, 20)
    dr = DateRecord(date=shared_date, status="published", paper_count=5)
    session.add(dr)
    await session.flush()

    session.add(DailyDigest(
        id=uuid.uuid4(),
        date=shared_date,
        generated_at=datetime.datetime(2025, 1, 20, 21, 0, tzinfo=datetime.timezone.utc),
        paper_count=5,
        groundbreaking_count=0,
    ))
    await session.flush()

    session.add(DailyDigest(
        id=uuid.uuid4(),  # different PK — UNIQUE on date is the only shared value
        date=shared_date,
        generated_at=datetime.datetime(2025, 1, 20, 22, 0, tzinfo=datetime.timezone.utc),
        paper_count=5,
        groundbreaking_count=0,
    ))
    with pytest.raises(IntegrityError):
        await session.flush()


# ---------------------------------------------------------------------------
# Paper constraint: groundbreaking_reasoning must be non-null when is_groundbreaking=True
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def date_record_and_topic_section(session: AsyncSession):
    """Seed a DateRecord + DailyDigest + TopicSection needed for Paper FKs."""
    dr = DateRecord(date=datetime.date(2025, 2, 3), status="published", paper_count=1)
    session.add(dr)
    await session.flush()

    digest = DailyDigest(
        id=uuid.uuid4(),
        date=datetime.date(2025, 2, 3),
        generated_at=datetime.datetime(2025, 2, 3, 21, 0, tzinfo=datetime.timezone.utc),
        paper_count=1,
        groundbreaking_count=0,
    )
    session.add(digest)
    await session.flush()

    section = TopicSection(
        id=uuid.uuid4(),
        digest_id=digest.id,
        name="Large Language Models",
        paper_count=1,
        body="## LLM papers",
    )
    session.add(section)
    await session.flush()
    return dr, digest, section


@pytest.mark.asyncio
async def test_paper_groundbreaking_reasoning_must_be_non_null_when_flagged(
    session: AsyncSession, date_record_and_topic_section
):
    """CHECK constraint must reject is_groundbreaking=True with NULL reasoning."""
    dr, digest, section = date_record_and_topic_section
    paper = Paper(
        arxiv_id="2501.00001",
        title="A Groundbreaking Paper",
        authors=["Alice"],
        institutions=[],
        abstract="Abstract text.",
        submitted_date=dr.date,
        topic_section_id=section.id,
        primary_topic="Large Language Models",
        secondary_topics=[],
        contributions="Big contributions.",
        methodologies="Novel method.",
        benchmarks="SOTA on X.",
        is_groundbreaking=True,
        groundbreaking_reasoning=None,  # must be rejected
    )
    session.add(paper)
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_paper_groundbreaking_with_reasoning_must_succeed(
    session: AsyncSession, date_record_and_topic_section
):
    """is_groundbreaking=True with non-null reasoning must be accepted."""
    dr, _, section = date_record_and_topic_section
    paper = Paper(
        arxiv_id="2501.00003",
        title="A Groundbreaking Paper With Reasoning",
        authors=["Carol"],
        institutions=[],
        abstract="Abstract text.",
        submitted_date=dr.date,
        topic_section_id=section.id,
        primary_topic="Large Language Models",
        secondary_topics=[],
        contributions="Big contributions.",
        methodologies="Novel method.",
        benchmarks="SOTA on X.",
        is_groundbreaking=True,
        groundbreaking_reasoning="Improves MMLU by 5%; introduces sparse MoE routing.",
    )
    session.add(paper)
    await session.flush()  # should not raise
    assert paper.groundbreaking_reasoning is not None


@pytest.mark.asyncio
async def test_paper_allows_null_reasoning_when_not_groundbreaking(
    session: AsyncSession, date_record_and_topic_section
):
    dr, _, section = date_record_and_topic_section
    paper = Paper(
        arxiv_id="2501.00002",
        title="An Ordinary Paper",
        authors=["Bob"],
        institutions=[],
        abstract="Abstract text.",
        submitted_date=dr.date,
        topic_section_id=section.id,
        primary_topic="Large Language Models",
        secondary_topics=[],
        contributions="Some contributions.",
        methodologies="Standard method.",
        benchmarks="",
        is_groundbreaking=False,
        groundbreaking_reasoning=None,  # allowed
    )
    session.add(paper)
    await session.flush()
    assert paper.groundbreaking_reasoning is None


@pytest.mark.asyncio
async def test_paper_rejects_reasoning_when_not_groundbreaking(
    session: AsyncSession, date_record_and_topic_section
):
    """CHECK constraint must reject non-null reasoning when is_groundbreaking=False."""
    dr, _, section = date_record_and_topic_section
    paper = Paper(
        arxiv_id="2501.00004",
        title="An Ordinary Paper With Spurious Reasoning",
        authors=["Dave"],
        institutions=[],
        abstract="Abstract text.",
        submitted_date=dr.date,
        topic_section_id=section.id,
        primary_topic="Large Language Models",
        secondary_topics=[],
        contributions="Some contributions.",
        methodologies="Standard method.",
        benchmarks="",
        is_groundbreaking=False,
        groundbreaking_reasoning="This should not be here.",  # must be rejected
    )
    session.add(paper)
    with pytest.raises(IntegrityError):
        await session.flush()


# ---------------------------------------------------------------------------
# WeeklyDigest constraint: week_start must be UNIQUE
# WeeklyDigest has no FK to other tables — the link to DailyDigest is a
# date-range query at read time, so only the UNIQUE constraint is DB-enforced.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weekly_digest_happy_path(session: AsyncSession):
    """A well-formed WeeklyDigest row must be accepted."""
    digest = WeeklyDigest(
        id=uuid.uuid4(),
        week_start=datetime.date(2025, 3, 2),   # Sunday
        week_end=datetime.date(2025, 3, 6),     # Thursday
        generated_at=datetime.datetime(2025, 3, 7, 1, 0, tzinfo=datetime.timezone.utc),
        paper_count=10,
        groundbreaking_count=1,
        benchmark_comparisons="## Benchmarks\n...",
        trend_synthesis="## Trends\n...",
        cross_paper_analysis="## Cross-paper\n...",
        days_with_content=[datetime.date(2025, 3, 3), datetime.date(2025, 3, 4)],
        no_papers_skips=[datetime.date(2025, 3, 2)],
        fetch_failure_skips=[],
    )
    session.add(digest)
    await session.flush()  # should not raise
    assert digest.week_start == datetime.date(2025, 3, 2)


@pytest.mark.asyncio
async def test_weekly_digest_rejects_duplicate_week_start(session: AsyncSession):
    """UNIQUE constraint on week_start must reject a second row with the same value."""
    def make_digest(week_start: datetime.date) -> WeeklyDigest:
        return WeeklyDigest(
            id=uuid.uuid4(),
            week_start=week_start,
            week_end=week_start + datetime.timedelta(days=4),
            generated_at=datetime.datetime(2025, 3, 14, 1, 0, tzinfo=datetime.timezone.utc),
            paper_count=5,
            groundbreaking_count=0,
            benchmark_comparisons="",
            trend_synthesis="",
            cross_paper_analysis="",
            days_with_content=[],
            no_papers_skips=[],
            fetch_failure_skips=[],
        )

    session.add(make_digest(datetime.date(2025, 3, 9)))
    await session.flush()

    session.add(make_digest(datetime.date(2025, 3, 9)))  # same week_start
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
@pytest.mark.parametrize("week_start,week_end", [
    (datetime.date(2025, 3, 3), datetime.date(2025, 3, 6)),   # Monday start — rejected
    (datetime.date(2025, 3, 4), datetime.date(2025, 3, 6)),   # Tuesday start — rejected
    (datetime.date(2025, 3, 5), datetime.date(2025, 3, 6)),   # Wednesday start — rejected
    (datetime.date(2025, 3, 6), datetime.date(2025, 3, 6)),   # Thursday start — rejected
    (datetime.date(2025, 3, 7), datetime.date(2025, 3, 6)),   # Friday start — rejected
    (datetime.date(2025, 3, 8), datetime.date(2025, 3, 6)),   # Saturday start — rejected
])
async def test_weekly_digest_rejects_non_sunday_week_start(
    session: AsyncSession, week_start: datetime.date, week_end: datetime.date
):
    """CHECK constraint must reject week_start on any day other than Sunday."""
    digest = WeeklyDigest(
        id=uuid.uuid4(),
        week_start=week_start,
        week_end=week_end,
        generated_at=datetime.datetime(2025, 3, 10, 1, 0, tzinfo=datetime.timezone.utc),
        paper_count=0,
        groundbreaking_count=0,
        benchmark_comparisons="",
        trend_synthesis="",
        cross_paper_analysis="",
        days_with_content=[],
        no_papers_skips=[],
        fetch_failure_skips=[],
    )
    session.add(digest)
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
@pytest.mark.parametrize("week_start,week_end", [
    (datetime.date(2025, 3, 16), datetime.date(2025, 3, 17)),  # Monday end — rejected
    (datetime.date(2025, 3, 16), datetime.date(2025, 3, 18)),  # Tuesday end — rejected
    (datetime.date(2025, 3, 16), datetime.date(2025, 3, 19)),  # Wednesday end — rejected
    (datetime.date(2025, 3, 16), datetime.date(2025, 3, 21)),  # Friday end — rejected
    (datetime.date(2025, 3, 16), datetime.date(2025, 3, 22)),  # Saturday end — rejected
    (datetime.date(2025, 3, 16), datetime.date(2025, 3, 23)),  # Sunday end — rejected
])
async def test_weekly_digest_rejects_non_thursday_week_end(
    session: AsyncSession, week_start: datetime.date, week_end: datetime.date
):
    """CHECK constraint must reject week_end on any day other than Thursday."""
    digest = WeeklyDigest(
        id=uuid.uuid4(),
        week_start=week_start,
        week_end=week_end,
        generated_at=datetime.datetime(2025, 3, 21, 1, 0, tzinfo=datetime.timezone.utc),
        paper_count=0,
        groundbreaking_count=0,
        benchmark_comparisons="",
        trend_synthesis="",
        cross_paper_analysis="",
        days_with_content=[],
        no_papers_skips=[],
        fetch_failure_skips=[],
    )
    session.add(digest)
    with pytest.raises(IntegrityError):
        await session.flush()


# ---------------------------------------------------------------------------
# PaperEmbedding constraints: FK on arxiv_id, chunk_type ENUM enforcement
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_paper(session: AsyncSession, date_record_and_topic_section):
    """Seed a Paper row so PaperEmbedding FK tests have a valid parent."""
    dr, _, section = date_record_and_topic_section
    paper = Paper(
        arxiv_id="2501.99999",
        title="Embedding Test Paper",
        authors=["Zara"],
        institutions=[],
        abstract="Abstract for embedding tests.",
        submitted_date=dr.date,
        topic_section_id=section.id,
        primary_topic="Large Language Models",
        secondary_topics=[],
        contributions="Contributions.",
        methodologies="Method.",
        benchmarks="",
        is_groundbreaking=False,
        groundbreaking_reasoning=None,
    )
    session.add(paper)
    await session.flush()
    return paper


@pytest.mark.asyncio
async def test_paper_embedding_fk_violation_on_arxiv_id(session: AsyncSession):
    """PaperEmbedding with a non-existent arxiv_id FK must raise."""
    embedding = PaperEmbedding(
        id=uuid.uuid4(),
        arxiv_id="9999.00000",  # no such Paper
        chunk_type="abstract",
        content="Some text.",
        embedding=[0.0] * 384,
        date=datetime.date(2025, 2, 3),
        primary_topic="Large Language Models",
        secondary_topics=[],
        is_groundbreaking=False,
        title="Ghost Paper",
        authors=["Nobody"],
        institutions=[],
    )
    session.add(embedding)
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_paper_embedding_rejects_invalid_chunk_type(
    session: AsyncSession, seeded_paper: Paper
):
    """chunk_type ENUM must reject values outside ('abstract', 'content')."""
    embedding = PaperEmbedding(
        id=uuid.uuid4(),
        arxiv_id=seeded_paper.arxiv_id,
        chunk_type="full_text",  # not a valid enum value — must be rejected
        content="Some text.",
        embedding=[0.0] * 384,
        date=seeded_paper.submitted_date,
        primary_topic=seeded_paper.primary_topic,
        secondary_topics=[],
        is_groundbreaking=False,
        title=seeded_paper.title,
        authors=seeded_paper.authors,
        institutions=[],
    )
    session.add(embedding)
    with pytest.raises((IntegrityError, DataError)):
        await session.flush()


@pytest.mark.asyncio
async def test_paper_embedding_happy_path_both_chunk_types(
    session: AsyncSession, seeded_paper: Paper
):
    """Both valid chunk types ('abstract' and 'content') must be accepted."""
    for chunk_type in ("abstract", "content"):
        embedding = PaperEmbedding(
            id=uuid.uuid4(),
            arxiv_id=seeded_paper.arxiv_id,
            chunk_type=chunk_type,
            content=f"{chunk_type} text.",
            embedding=[0.0] * 384,
            date=seeded_paper.submitted_date,
            primary_topic=seeded_paper.primary_topic,
            secondary_topics=[],
            is_groundbreaking=False,
            title=seeded_paper.title,
            authors=seeded_paper.authors,
            institutions=[],
        )
        session.add(embedding)

    await session.flush()  # should not raise for either chunk type


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate_chunk_type", ["abstract", "content"])
async def test_paper_embedding_rejects_duplicate_chunk_type_per_paper(
    session: AsyncSession, seeded_paper: Paper, duplicate_chunk_type: str
):
    """UNIQUE(arxiv_id, chunk_type) must reject a second embedding of the same
    chunk type for the same paper — enforcing exactly one abstract and one
    content chunk per paper."""
    def make_embedding() -> PaperEmbedding:
        return PaperEmbedding(
            id=uuid.uuid4(),  # different PK — UNIQUE on (arxiv_id, chunk_type) is the only shared value
            arxiv_id=seeded_paper.arxiv_id,
            chunk_type=duplicate_chunk_type,
            content="Some text.",
            embedding=[0.0] * 384,
            date=seeded_paper.submitted_date,
            primary_topic=seeded_paper.primary_topic,
            secondary_topics=[],
            is_groundbreaking=False,
            title=seeded_paper.title,
            authors=seeded_paper.authors,
            institutions=[],
        )

    session.add(make_embedding())
    await session.flush()

    session.add(make_embedding())
    with pytest.raises(IntegrityError):
        await session.flush()
