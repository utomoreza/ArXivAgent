"""Initial schema: enums, vector extension, all tables, B-tree indexes.

Revision ID: 0001
Revises:
Create Date: 2026-04-29

Creation order: enums → vector extension → date_records → daily_digests →
topic_sections → weekly_digests → papers → paper_embeddings.

The HNSW vector index on paper_embeddings.embedding is intentionally omitted
here — it must be created AFTER initial backfill data is loaded (see migration
0002_hnsw_index.py).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from src.db import constants

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Custom ENUM types (must precede tables that reference them)
    # ------------------------------------------------------------------
    postgresql.ENUM(
        *constants.DATE_STATUS_VALUES, name=constants.ENUM_DATE_STATUS
    ).create(op.get_bind(), checkfirst=True)
    postgresql.ENUM(
        *constants.CHUNK_TYPE_VALUES, name=constants.ENUM_CHUNK_TYPE
    ).create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # 2. pgvector extension (must precede paper_embeddings table)
    # ------------------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ------------------------------------------------------------------
    # 3. date_records
    # ------------------------------------------------------------------
    op.create_table(
        constants.TBL_DATE_RECORDS,
        sa.Column(constants.COL_DATE, sa.Date(), nullable=False),
        sa.Column(
            constants.COL_STATUS,
            postgresql.ENUM(
                *constants.DATE_STATUS_VALUES,
                name=constants.ENUM_DATE_STATUS,
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(constants.COL_PAPER_COUNT, sa.Integer(), nullable=True),
        sa.Column(
            constants.COL_RECORDED_AT,
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            constants.CK_DATE_RECORD_PAPER_COUNT_EXPR,
            name=constants.CK_DATE_RECORD_PAPER_COUNT_NAME,
        ),
        sa.PrimaryKeyConstraint(constants.COL_DATE),
    )

    # ------------------------------------------------------------------
    # 4. daily_digests
    # ------------------------------------------------------------------
    op.create_table(
        constants.TBL_DAILY_DIGESTS,
        sa.Column(constants.COL_ID, postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(constants.COL_DATE, sa.Date(), nullable=False),
        sa.Column(constants.COL_GENERATED_AT, sa.DateTime(timezone=True), nullable=False),
        sa.Column(constants.COL_PAPER_COUNT, sa.Integer(), nullable=False),
        sa.Column(constants.COL_GROUNDBREAKING_COUNT, sa.Integer(), nullable=False),
        sa.Column(
            constants.COL_CREATED_AT,
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            constants.CK_DIGEST_PAPER_COUNT_POSITIVE_EXPR,
            name=constants.CK_DAILY_DIGEST_PAPER_COUNT_NAME,
        ),
        sa.ForeignKeyConstraint(
            [constants.COL_DATE],
            [f"{constants.TBL_DATE_RECORDS}.{constants.COL_DATE}"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(constants.COL_ID),
        sa.UniqueConstraint(constants.COL_DATE, name=constants.UQ_DAILY_DIGEST_DATE_NAME),
    )
    op.create_index(
        constants.IDX_DAILY_DIGEST_DATE,
        constants.TBL_DAILY_DIGESTS,
        [constants.COL_DATE],
    )

    # ------------------------------------------------------------------
    # 5. topic_sections
    # ------------------------------------------------------------------
    op.create_table(
        constants.TBL_TOPIC_SECTIONS,
        sa.Column(constants.COL_ID, postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            constants.COL_DIGEST_ID, postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(constants.COL_NAME, sa.Text(), nullable=False),
        sa.Column(constants.COL_PAPER_COUNT, sa.Integer(), nullable=False),
        sa.Column(constants.COL_BODY, sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            [constants.COL_DIGEST_ID],
            [f"{constants.TBL_DAILY_DIGESTS}.{constants.COL_ID}"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(constants.COL_ID),
    )
    op.create_index(
        constants.IDX_TOPIC_SECTION_DIGEST_ID,
        constants.TBL_TOPIC_SECTIONS,
        [constants.COL_DIGEST_ID],
    )

    # ------------------------------------------------------------------
    # 6. weekly_digests
    # ------------------------------------------------------------------
    op.create_table(
        constants.TBL_WEEKLY_DIGESTS,
        sa.Column(constants.COL_ID, postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(constants.COL_WEEK_START, sa.Date(), nullable=False),
        sa.Column(constants.COL_WEEK_END, sa.Date(), nullable=False),
        sa.Column(constants.COL_GENERATED_AT, sa.DateTime(timezone=True), nullable=False),
        sa.Column(constants.COL_PAPER_COUNT, sa.Integer(), nullable=False),
        sa.Column(constants.COL_GROUNDBREAKING_COUNT, sa.Integer(), nullable=False),
        sa.Column(constants.COL_BENCHMARK_COMPARISONS, sa.Text(), nullable=False),
        sa.Column(constants.COL_TREND_SYNTHESIS, sa.Text(), nullable=False),
        sa.Column(constants.COL_CROSS_PAPER_ANALYSIS, sa.Text(), nullable=False),
        sa.Column(
            constants.COL_DAYS_WITH_CONTENT,
            postgresql.ARRAY(sa.Date()),
            server_default=sa.text("'{}'::date[]"),
            nullable=False,
        ),
        sa.Column(
            constants.COL_NO_PAPERS_SKIPS,
            postgresql.ARRAY(sa.Date()),
            server_default=sa.text("'{}'::date[]"),
            nullable=False,
        ),
        sa.Column(
            constants.COL_FETCH_FAILURE_SKIPS,
            postgresql.ARRAY(sa.Date()),
            server_default=sa.text("'{}'::date[]"),
            nullable=False,
        ),
        sa.Column(
            constants.COL_CREATED_AT,
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            constants.CK_DIGEST_PAPER_COUNT_POSITIVE_EXPR,
            name=constants.CK_WEEKLY_DIGEST_PAPER_COUNT_NAME,
        ),
        sa.CheckConstraint(
            constants.CK_WEEKLY_WEEK_START_IS_SUNDAY_EXPR,
            name=constants.CK_WEEKLY_WEEK_START_NAME,
        ),
        sa.CheckConstraint(
            constants.CK_WEEKLY_WEEK_END_IS_THURSDAY_EXPR,
            name=constants.CK_WEEKLY_WEEK_END_NAME,
        ),
        sa.PrimaryKeyConstraint(constants.COL_ID),
        sa.UniqueConstraint(
            constants.COL_WEEK_START, name=constants.UQ_WEEKLY_DIGEST_WEEK_START_NAME
        ),
    )
    op.create_index(
        constants.IDX_WEEKLY_DIGEST_WEEK_START,
        constants.TBL_WEEKLY_DIGESTS,
        [constants.COL_WEEK_START],
    )

    # ------------------------------------------------------------------
    # 7. papers
    # ------------------------------------------------------------------
    op.create_table(
        constants.TBL_PAPERS,
        sa.Column(constants.COL_ARXIV_ID, sa.Text(), nullable=False),
        sa.Column(constants.COL_TITLE, sa.Text(), nullable=False),
        sa.Column(constants.COL_AUTHORS, postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            constants.COL_INSTITUTIONS,
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(constants.COL_ABSTRACT, sa.Text(), nullable=False),
        sa.Column(constants.COL_SUBMITTED_DATE, sa.Date(), nullable=False),
        sa.Column(
            constants.COL_TOPIC_SECTION_ID,
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(constants.COL_PRIMARY_TOPIC, sa.Text(), nullable=False),
        sa.Column(
            constants.COL_SECONDARY_TOPICS,
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            constants.COL_CONTRIBUTIONS,
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            constants.COL_METHODOLOGIES,
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            constants.COL_BENCHMARKS,
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            constants.COL_IS_GROUNDBREAKING,
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(constants.COL_GROUNDBREAKING_REASONING, sa.Text(), nullable=True),
        sa.Column(
            constants.COL_CREATED_AT,
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            constants.CK_PAPER_GROUNDBREAKING_EXPR,
            name=constants.CK_PAPER_GROUNDBREAKING_NAME,
        ),
        sa.ForeignKeyConstraint(
            [constants.COL_SUBMITTED_DATE],
            [f"{constants.TBL_DATE_RECORDS}.{constants.COL_DATE}"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [constants.COL_TOPIC_SECTION_ID],
            [f"{constants.TBL_TOPIC_SECTIONS}.{constants.COL_ID}"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(constants.COL_ARXIV_ID),
    )
    op.create_index(
        constants.IDX_PAPERS_SUBMITTED_DATE,
        constants.TBL_PAPERS,
        [constants.COL_SUBMITTED_DATE],
    )
    op.create_index(
        constants.IDX_PAPERS_PRIMARY_TOPIC,
        constants.TBL_PAPERS,
        [constants.COL_PRIMARY_TOPIC],
    )
    op.create_index(
        constants.IDX_PAPERS_IS_GROUNDBREAKING,
        constants.TBL_PAPERS,
        [constants.COL_IS_GROUNDBREAKING],
    )
    op.create_index(
        constants.IDX_PAPERS_FTS,
        constants.TBL_PAPERS,
        [sa.text(
            f"to_tsvector('english', {constants.COL_TITLE} || ' ' || {constants.COL_ABSTRACT})"
        )],
        postgresql_using="gin",
    )
    op.create_index(
        constants.IDX_PAPERS_AUTHORS,
        constants.TBL_PAPERS,
        [constants.COL_AUTHORS],
        postgresql_using="gin",
    )
    op.create_index(
        constants.IDX_PAPERS_INSTITUTIONS,
        constants.TBL_PAPERS,
        [constants.COL_INSTITUTIONS],
        postgresql_using="gin",
    )

    # ------------------------------------------------------------------
    # 8. paper_embeddings
    # Use raw SQL because Alembic's op.create_table doesn't natively understand
    # the pgvector vector(384) type. The HNSW index is intentionally omitted
    # here — it must be created after initial backfill (see migration 0002).
    # ------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE {constants.TBL_PAPER_EMBEDDINGS} (
            {constants.COL_ID}          UUID PRIMARY KEY,
            {constants.COL_ARXIV_ID}    TEXT NOT NULL
                REFERENCES {constants.TBL_PAPERS}({constants.COL_ARXIV_ID})
                ON DELETE CASCADE,
            {constants.COL_CHUNK_TYPE}  {constants.ENUM_CHUNK_TYPE} NOT NULL,
            {constants.COL_CONTENT}     TEXT NOT NULL,
            {constants.COL_EMBEDDING}   vector(384) NOT NULL,
            {constants.COL_DATE}        DATE NOT NULL,
            {constants.COL_PRIMARY_TOPIC}   TEXT NOT NULL,
            {constants.COL_SECONDARY_TOPICS} TEXT[] NOT NULL,
            {constants.COL_IS_GROUNDBREAKING} BOOLEAN NOT NULL,
            {constants.COL_TITLE}       TEXT NOT NULL,
            {constants.COL_AUTHORS}     TEXT[] NOT NULL,
            {constants.COL_INSTITUTIONS} TEXT[] NOT NULL,
            CONSTRAINT {constants.UQ_PAPER_EMBEDDING_ARXIV_CHUNK_NAME}
                UNIQUE ({constants.COL_ARXIV_ID}, {constants.COL_CHUNK_TYPE})
        )
        """
    )
    op.create_index(
        constants.IDX_PAPER_EMBEDDING_DATE,
        constants.TBL_PAPER_EMBEDDINGS,
        [constants.COL_DATE],
    )
    op.create_index(
        constants.IDX_PAPER_EMBEDDING_ARXIV_ID,
        constants.TBL_PAPER_EMBEDDINGS,
        [constants.COL_ARXIV_ID],
    )


def downgrade() -> None:
    op.drop_table(constants.TBL_PAPER_EMBEDDINGS)
    op.drop_table(constants.TBL_PAPERS)
    op.drop_table(constants.TBL_WEEKLY_DIGESTS)
    op.drop_table(constants.TBL_TOPIC_SECTIONS)
    op.drop_table(constants.TBL_DAILY_DIGESTS)
    op.drop_table(constants.TBL_DATE_RECORDS)
    op.execute("DROP EXTENSION IF EXISTS vector")
    op.execute(f"DROP TYPE IF EXISTS {constants.ENUM_CHUNK_TYPE}")
    op.execute(f"DROP TYPE IF EXISTS {constants.ENUM_DATE_STATUS}")
