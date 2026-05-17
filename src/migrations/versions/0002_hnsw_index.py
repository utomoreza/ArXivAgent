"""Post-backfill HNSW index on paper_embeddings.embedding.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-17

Creates a pgvector HNSW index for cosine similarity search only after
confirming that paper_embeddings has at least one row.  This index must be
built after inception backfill completes — building it on an empty table
wastes time and prevents the query planner from using it during backfill.

HNSW is preferred over IVFFlat for ~180k vectors at 384 dims: better recall,
no `lists` tuning required.  Parameters: m=16 (graph connectivity),
ef_construction=64 (build-time accuracy/speed tradeoff).
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_paper_embeddings_embedding_hnsw"
_TABLE = "paper_embeddings"
_COLUMN = "embedding"


def upgrade() -> None:
    bind = op.get_bind()
    row_count = bind.execute(
        sa.text(f"SELECT COUNT(*) FROM {_TABLE}")
    ).scalar()

    if row_count and row_count > 0:
        op.execute(
            sa.text(
                f"CREATE INDEX IF NOT EXISTS {_INDEX_NAME} "
                f"ON {_TABLE} "
                f"USING hnsw ({_COLUMN} vector_cosine_ops) "
                f"WITH (m = 16, ef_construction = 64)"
            )
        )
    else:
        # Table is empty — index will be created by the post-backfill hook in
        # src/scheduler/jobs.py after run_inception_backfill() completes.
        pass


def downgrade() -> None:
    op.execute(sa.text(f"DROP INDEX IF EXISTS {_INDEX_NAME}"))
