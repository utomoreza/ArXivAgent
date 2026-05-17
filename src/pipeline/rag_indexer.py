"""RAG Indexer — build and persist PaperEmbedding rows for each processed paper.

Creates exactly two rows per paper:
- **abstract chunk**: title + authors + institutions + abstract
- **content chunk**: title + contributions + methodologies + benchmarks
  (+ groundbreaking reasoning when flagged)

Content chunk is capped at 512 whitespace-split tokens. Fields are dropped in
priority order when the cap is exceeded: benchmarks first (most replaceable),
then methodologies, then contributions (as last resort).

All denormalized metadata fields on PaperEmbedding are populated from the Paper
row so the retriever never needs to join back to the papers table.
"""

import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Paper, PaperEmbedding
from src.rag.embedder import embed
from src.utils.funcs import logger

_CONTENT_TOKEN_CAP = 512


def _count_tokens(text: str) -> int:
    """Approximate token count via whitespace splitting.

    Args:
        text: Text to measure.

    Returns:
        Number of whitespace-separated tokens.
    """
    return len(text.split())


def _build_abstract_chunk(paper: Paper) -> str:
    """Build the abstract chunk text for embedding.

    Combines title, author list, institution list, and abstract into a single
    string. Designed to answer "who wrote this" and "what is this paper about"
    queries. Does not truncate — abstract text always fits within 256 tokens.

    Args:
        paper: The Paper ORM instance to build the chunk from.

    Returns:
        Multi-line string ready to embed.
    """
    authors_str = ", ".join(paper.authors)
    parts = [
        paper.title,
        f"Authors: {authors_str}",
    ]
    if paper.institutions:
        institutions_str = ", ".join(paper.institutions)
        parts.append(f"Institutions: {institutions_str}")
    parts.append(f"Abstract: {paper.abstract}")
    return "\n".join(parts)


def _build_content_chunk(paper: Paper) -> str:
    """Build the content chunk text, truncating to 512 tokens if necessary.

    Truncation priority (what is dropped first when over the cap):
    benchmarks → methodologies → contributions. Groundbreaking reasoning is
    always appended last and is not subject to truncation.

    Args:
        paper: The Paper ORM instance to build the chunk from.

    Returns:
        Multi-line string within the 512-token cap.
    """
    gb_reasoning = paper.groundbreaking_reasoning if paper.is_groundbreaking else None

    def _assemble(contributions: str, methodologies: str, benchmarks: str) -> str:
        parts = [paper.title]
        if contributions:
            parts.append(f"Contributions: {contributions}")
        if methodologies:
            parts.append(f"Methodologies: {methodologies}")
        if benchmarks:
            parts.append(f"Benchmarks: {benchmarks}")
        if gb_reasoning:
            parts.append(f"Groundbreaking: {gb_reasoning}")
        return "\n".join(parts)

    text = _assemble(paper.contributions, paper.methodologies, paper.benchmarks)
    if _count_tokens(text) <= _CONTENT_TOKEN_CAP:
        return text

    # Drop benchmarks first
    text = _assemble(paper.contributions, paper.methodologies, "")
    if _count_tokens(text) <= _CONTENT_TOKEN_CAP:
        return text

    # Drop methodologies next
    text = _assemble(paper.contributions, "", "")
    if _count_tokens(text) <= _CONTENT_TOKEN_CAP:
        return text

    # Drop contributions as last resort — only title (+ groundbreaking) remains
    return _assemble("", "", "")


async def index_paper(paper: Paper, session: AsyncSession) -> None:
    """Create and persist two PaperEmbedding rows for the given paper.

    Embeds both chunks in a single batched ``embed()`` call, then adds both
    rows to the session and commits. Idempotency is enforced at the DB level
    via UNIQUE(arxiv_id, chunk_type).

    Args:
        paper: The fully processed Paper ORM instance (must have topic_section_id set).
        session: Async SQLAlchemy session used to commit the embeddings.
    """
    logger.debug("index_paper entry arxiv_id=%s", paper.arxiv_id)
    t0 = time.perf_counter()

    abstract_text = _build_abstract_chunk(paper)
    content_text = _build_content_chunk(paper)

    vectors = embed([abstract_text, content_text])
    logger.debug("embed call completed arxiv_id=%s", paper.arxiv_id)

    _common = {
        "arxiv_id": paper.arxiv_id,
        "date": paper.submitted_date,
        "primary_topic": paper.primary_topic,
        "secondary_topics": paper.secondary_topics,
        "is_groundbreaking": paper.is_groundbreaking,
        "title": paper.title,
        "authors": paper.authors,
        "institutions": paper.institutions,
    }

    abstract_row = PaperEmbedding(
        id=uuid.uuid4(),
        chunk_type="abstract",
        content=abstract_text,
        embedding=vectors[0].tolist(),
        **_common,
    )
    content_row = PaperEmbedding(
        id=uuid.uuid4(),
        chunk_type="content",
        content=content_text,
        embedding=vectors[1].tolist(),
        **_common,
    )

    session.add(abstract_row)
    session.add(content_row)
    await session.commit()

    elapsed = time.perf_counter() - t0
    logger.info(
        "indexed paper %s: abstract=%d tokens, content=%d tokens, elapsed_s=%.3f",
        paper.arxiv_id,
        _count_tokens(abstract_text),
        _count_tokens(content_text),
        elapsed,
    )
