"""RAG Retriever — fetch relevant PaperEmbedding rows for a query.

Embeds the question, runs cosine similarity retrieval within a rolling date window,
then re-ranks results by date descending so the most recent papers surface first.
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import PaperEmbedding
from src.rag.embedder import embed
from src.utils.funcs import logger


async def retrieve(
    question: str,
    session: AsyncSession,
    window_days: int,
    k: int = 10,
) -> list[PaperEmbedding]:
    """Retrieve top-K relevant embeddings within the rolling date window.

    Embeds the question, queries pgvector for nearest neighbours limited to
    embeddings within ``window_days`` of today, then re-ranks the results by
    date descending (most recent first) before returning.

    Args:
        question: Natural-language question to retrieve context for.
        session: Async SQLAlchemy session for the DB query.
        window_days: Only consider embeddings with ``date >= today - window_days``.
        k: Maximum number of embeddings to return (applied as SQL LIMIT).

    Returns:
        List of PaperEmbedding rows, sorted by date DESC, at most k items.
        Returns an empty list when no in-window embeddings exist.
    """
    query_vec = embed([question])[0]
    cutoff = date.today() - timedelta(days=window_days)

    stmt = (
        select(PaperEmbedding)
        .where(PaperEmbedding.date >= cutoff)
        .order_by(PaperEmbedding.embedding.cosine_distance(query_vec))
        .limit(k)
    )

    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    if not rows:
        logger.debug(
            "retrieve: no in-window embeddings for window_days=%d", window_days
        )
        return []

    # Re-rank by date DESC: most recent papers surface first within the top-K
    rows.sort(key=lambda r: r.date, reverse=True)

    logger.debug(
        "retrieve: returning %d embeddings (window=%d days, k=%d)",
        len(rows),
        window_days,
        k,
    )
    return rows
