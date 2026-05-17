"""Q&A router — POST /qa endpoint for RAG-based digest question answering.

Flow:
1. Scope check: classify question as in-scope or out-of-scope using Claude Haiku.
2. Retrieve: query pgvector for relevant PaperEmbedding rows within the window.
3. Generate: call Claude Sonnet to produce an answer grounded in retrieved context.

Returns one of three envelopes:
- QAResponse (status=ok): in-scope question with answer and source citations
- RejectedResponse (status=rejected): out-of-scope question
- EmptyKBResponse (status=empty): no in-window embeddings available
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.schemas import (
    EmptyKBResponse,
    QAAnswer,
    QARequest,
    QAResponse,
    QASource,
    RejectedResponse,
    Status,
)
from src.config import get_settings
from src.llm.client import classify, parse_structured
from src.rag.retriever import retrieve
from src.utils.funcs import logger

router = APIRouter()

_REASON_REJECTED = "This agent only answers questions about the research digests."
_REASON_EMPTY = (
    "No digests are available yet within the current window"
    " — please check back after the first digest is generated."
)

_SCOPE_TOOL = {
    "name": "check_scope",
    "description": (
        "Determine whether a question is about AI/ML research papers or digests."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "in_scope": {
                "type": "boolean",
                "description": (
                    "True if the question is about research papers, their findings, "
                    "benchmarks, methodologies, or related research digests."
                ),
            }
        },
        "required": ["in_scope"],
    },
}


class _AnswerSchema(BaseModel):
    """LLM output schema for the Q&A answer."""

    answer: str


def _format_context(chunks: list) -> str:
    """Format retrieved PaperEmbedding chunks into a context string for the LLM.

    Args:
        chunks: PaperEmbedding rows from the retriever, sorted date DESC.

    Returns:
        Multi-section string with each chunk labelled by type, title, and date.
    """
    parts = [
        f"[{c.chunk_type.upper()}] {c.title} ({c.arxiv_id}, {c.date})\n{c.content}"
        for c in chunks
    ]
    return "\n\n---\n\n".join(parts)


@router.post("/qa")
async def query_digests(
    request: QARequest,
    session: AsyncSession = Depends(get_session),
):
    """Answer a natural language question using retrieved digest context.

    Args:
        request: Request body containing the question string.
        session: Async database session injected by FastAPI.

    Returns:
        One of QAResponse, RejectedResponse, or EmptyKBResponse.
    """
    settings = get_settings()

    # Step 1: scope check
    scope_prompt = (
        f"Question: {request.question}\n\n"
        "Is this question about AI/ML research papers, their findings, "
        "benchmarks, methodologies, or related research digests?"
    )
    scope_result = await classify(
        settings.SMALL_CLAUDE_LLM, scope_prompt, _SCOPE_TOOL
    )
    if not scope_result.get("in_scope"):
        logger.info("QA rejected (out of scope): %s", request.question[:80])
        return RejectedResponse(status=Status.REJECTED, reason=_REASON_REJECTED)

    # Step 2: retrieve relevant chunks
    chunks = await retrieve(request.question, session, settings.RAG_WINDOW_DAYS)
    if not chunks:
        logger.info("QA empty KB for question: %s", request.question[:80])
        return EmptyKBResponse(status=Status.EMPTY, reason=_REASON_EMPTY)

    # Step 3: generate answer
    context = _format_context(chunks)
    answer_schema: _AnswerSchema = await parse_structured(
        settings.LARGE_CLAUDE_LLM,
        (
            "Use the following research digest context to answer the question.\n\n"
            f"Context:\n{context}\n\nQuestion: {request.question}"
        ),
        _AnswerSchema,
    )

    sources = [
        QASource(
            arxiv_id=c.arxiv_id,
            title=c.title,
            date=c.date,
            chunk_type=c.chunk_type,
        )
        for c in chunks
    ]

    logger.info(
        "QA answered: %d chunks, %d sources", len(chunks), len(sources)
    )
    return QAResponse(
        status=Status.OK,
        data=QAAnswer(answer=answer_schema.answer, sources=sources),
        reason=None,
    )
