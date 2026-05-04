"""SQLAlchemy 2.0 ORM models for ArXivAgent.

Creation order: DateRecord → DailyDigest → TopicSection → WeeklyDigest → Paper → PaperEmbedding.

ORM navigation graph (relationship attribute names, all bidirectional via back_populates)::

    DateRecord
        ├── .papers          ──► [Paper]
        └── .daily_digest    ──► DailyDigest | None
                                      │
                                      └── .topic_sections ──► [TopicSection]
                                                                     │
                                                                     └── .papers ──► [Paper]
                                                                                        │
                                                                                        └── .embeddings ──► [PaperEmbedding]

    Reverse traversal (every arrow above has a named inverse):
        Paper.date_record      ──► DateRecord
        Paper.topic_section    ──► TopicSection | None
        TopicSection.daily_digest ──► DailyDigest
        DailyDigest.date_record   ──► DateRecord
        PaperEmbedding.paper      ──► Paper

    WeeklyDigest has no relationships — it links to DailyDigest via date-range
    query (WHERE date BETWEEN week_start AND week_end), not a FK.
"""

import datetime
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects import postgresql  # side-effect: registers to_tsvector types
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from src.db import constants

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

DateStatus = Enum(*constants.DATE_STATUS_VALUES, name=constants.ENUM_DATE_STATUS)
ChunkType = Enum(*constants.CHUNK_TYPE_VALUES, name=constants.ENUM_CHUNK_TYPE)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# DateRecord
# ---------------------------------------------------------------------------


class DateRecord(Base):
    """One record per calendar date - single source of truth for date status."""

    __tablename__ = constants.TBL_DATE_RECORDS
    __table_args__ = (
        CheckConstraint(
            constants.CK_DATE_RECORD_PAPER_COUNT_EXPR,
            name=constants.CK_DATE_RECORD_PAPER_COUNT_NAME,
        ),
    )

    date: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    status: Mapped[str] = mapped_column(DateStatus, nullable=False)
    paper_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recorded_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    papers: Mapped[list["Paper"]] = relationship("Paper", back_populates="date_record")
    daily_digest: Mapped["DailyDigest | None"] = relationship(
        "DailyDigest", back_populates="date_record", uselist=False
    )


# ---------------------------------------------------------------------------
# DailyDigest
# ---------------------------------------------------------------------------


class DailyDigest(Base):
    """Stored digest document for one arXiv announcement day.

    paper_count > 0 is enforced - a digest row only exists when papers were published.
    """

    __tablename__ = constants.TBL_DAILY_DIGESTS
    __table_args__ = (
        UniqueConstraint(constants.COL_DATE, name=constants.UQ_DAILY_DIGEST_DATE_NAME),
        CheckConstraint(
            constants.CK_DIGEST_PAPER_COUNT_POSITIVE_EXPR,
            name=constants.CK_DAILY_DIGEST_PAPER_COUNT_NAME,
        ),
        Index(constants.IDX_DAILY_DIGEST_DATE, constants.COL_DATE),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    date: Mapped[datetime.date] = mapped_column(
        Date,
        ForeignKey(
            f"{constants.TBL_DATE_RECORDS}.{constants.COL_DATE}", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    generated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    paper_count: Mapped[int] = mapped_column(Integer, nullable=False)
    groundbreaking_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    date_record: Mapped[DateRecord] = relationship(
        "DateRecord", back_populates="daily_digest"
    )
    topic_sections: Mapped[list["TopicSection"]] = relationship(
        "TopicSection", back_populates="daily_digest", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# TopicSection
# ---------------------------------------------------------------------------


class TopicSection(Base):
    """One topic section within a DailyDigest. Ordered at query time by paper_count DESC."""

    __tablename__ = constants.TBL_TOPIC_SECTIONS
    __table_args__ = (
        Index(constants.IDX_TOPIC_SECTION_DIGEST_ID, constants.COL_DIGEST_ID),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    digest_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{constants.TBL_DAILY_DIGESTS}.{constants.COL_ID}", ondelete="CASCADE"
        ),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    paper_count: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    daily_digest: Mapped[DailyDigest] = relationship(
        "DailyDigest", back_populates="topic_sections"
    )
    papers: Mapped[list["Paper"]] = relationship(
        "Paper", back_populates="topic_section"
    )


# ---------------------------------------------------------------------------
# WeeklyDigest
# ---------------------------------------------------------------------------


class WeeklyDigest(Base):
    """Stored digest for one Sun-Thu arXiv announcement week.

    No FK to DailyDigest - linked by date range at query time.
    Coverage arrays stored inline; paper_count > 0 enforced at DB level.
    week_start must be Sunday (DOW=0); week_end must be Thursday (DOW=4).
    """

    __tablename__ = constants.TBL_WEEKLY_DIGESTS
    __table_args__ = (
        UniqueConstraint(
            constants.COL_WEEK_START, name=constants.UQ_WEEKLY_DIGEST_WEEK_START_NAME
        ),
        CheckConstraint(
            constants.CK_DIGEST_PAPER_COUNT_POSITIVE_EXPR,
            name=constants.CK_WEEKLY_DIGEST_PAPER_COUNT_NAME,
        ),
        CheckConstraint(
            constants.CK_WEEKLY_WEEK_START_IS_SUNDAY_EXPR,
            name=constants.CK_WEEKLY_WEEK_START_NAME,
        ),
        CheckConstraint(
            constants.CK_WEEKLY_WEEK_END_IS_THURSDAY_EXPR,
            name=constants.CK_WEEKLY_WEEK_END_NAME,
        ),
        Index(constants.IDX_WEEKLY_DIGEST_WEEK_START, constants.COL_WEEK_START),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    week_start: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    week_end: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    generated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    paper_count: Mapped[int] = mapped_column(Integer, nullable=False)
    groundbreaking_count: Mapped[int] = mapped_column(Integer, nullable=False)
    benchmark_comparisons: Mapped[str] = mapped_column(Text, nullable=False)
    trend_synthesis: Mapped[str] = mapped_column(Text, nullable=False)
    cross_paper_analysis: Mapped[str] = mapped_column(Text, nullable=False)
    days_with_content: Mapped[list[datetime.date]] = mapped_column(
        ARRAY(Date), nullable=False, server_default=text("'{}'::date[]")
    )
    no_papers_skips: Mapped[list[datetime.date]] = mapped_column(
        ARRAY(Date), nullable=False, server_default=text("'{}'::date[]")
    )
    fetch_failure_skips: Mapped[list[datetime.date]] = mapped_column(
        ARRAY(Date), nullable=False, server_default=text("'{}'::date[]")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ---------------------------------------------------------------------------
# Paper
# ---------------------------------------------------------------------------


class Paper(Base):
    """A single arXiv publication after full processing.

    groundbreaking_reasoning must be non-null iff is_groundbreaking is True -
    the biconditional CHECK enforces both directions.
    """

    __tablename__ = constants.TBL_PAPERS
    __table_args__ = (
        CheckConstraint(
            constants.CK_PAPER_GROUNDBREAKING_EXPR,
            name=constants.CK_PAPER_GROUNDBREAKING_NAME,
        ),
        Index(constants.IDX_PAPERS_SUBMITTED_DATE, constants.COL_SUBMITTED_DATE),
        Index(constants.IDX_PAPERS_PRIMARY_TOPIC, constants.COL_PRIMARY_TOPIC),
        Index(constants.IDX_PAPERS_IS_GROUNDBREAKING, constants.COL_IS_GROUNDBREAKING),
        Index(
            constants.IDX_PAPERS_FTS,
            text("to_tsvector('english', title || ' ' || abstract)"),
            postgresql_using="gin",
        ),
        Index(constants.IDX_PAPERS_AUTHORS, constants.COL_AUTHORS, postgresql_using="gin"),
        Index(
            constants.IDX_PAPERS_INSTITUTIONS,
            constants.COL_INSTITUTIONS,
            postgresql_using="gin",
        ),
    )

    arxiv_id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    institutions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    abstract: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_date: Mapped[datetime.date] = mapped_column(
        Date,
        ForeignKey(
            f"{constants.TBL_DATE_RECORDS}.{constants.COL_DATE}", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    topic_section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{constants.TBL_TOPIC_SECTIONS}.{constants.COL_ID}", ondelete="SET NULL"
        ),
        nullable=True,
    )
    primary_topic: Mapped[str] = mapped_column(Text, nullable=False)
    secondary_topics: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    contributions: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    methodologies: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    benchmarks: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    is_groundbreaking: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    groundbreaking_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    date_record: Mapped[DateRecord] = relationship(
        "DateRecord", back_populates="papers"
    )
    topic_section: Mapped[TopicSection | None] = relationship(
        "TopicSection", back_populates="papers"
    )
    embeddings: Mapped[list["PaperEmbedding"]] = relationship(
        "PaperEmbedding", back_populates="paper", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# PaperEmbedding
# ---------------------------------------------------------------------------


class PaperEmbedding(Base):
    """Vector embedding for RAG retrieval - exactly two rows per paper (abstract + content).

    UNIQUE(arxiv_id, chunk_type) enforces the 1:2 fixed cardinality at the DB level.
    """

    __tablename__ = constants.TBL_PAPER_EMBEDDINGS
    __table_args__ = (
        UniqueConstraint(
            constants.COL_ARXIV_ID,
            constants.COL_CHUNK_TYPE,
            name=constants.UQ_PAPER_EMBEDDING_ARXIV_CHUNK_NAME,
        ),
        Index(constants.IDX_PAPER_EMBEDDING_DATE, constants.COL_DATE),
        Index(constants.IDX_PAPER_EMBEDDING_ARXIV_ID, constants.COL_ARXIV_ID),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    arxiv_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey(
            f"{constants.TBL_PAPERS}.{constants.COL_ARXIV_ID}", ondelete="CASCADE"
        ),
        nullable=False,
    )
    chunk_type: Mapped[str] = mapped_column(ChunkType, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)
    date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    primary_topic: Mapped[str] = mapped_column(Text, nullable=False)
    secondary_topics: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    is_groundbreaking: Mapped[bool] = mapped_column(Boolean, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    institutions: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)

    paper: Mapped[Paper] = relationship("Paper", back_populates="embeddings")


# suppress unused import warning — postgresql import is a required side-effect
_ = postgresql
