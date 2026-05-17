"""Paper Processor — fetch full text and extract structured content from arXiv results.


For each arxiv.Result:
1. Fetch HTML from ``arxiv.org/html/{arxiv_id}`` via httpx.
2. Fall back to pdfplumber PDF parse if HTML returns non-200.
3. Call Claude Sonnet via ``parse_structured`` for structured extraction
   (contributions, methodologies, benchmarks, institutions).
4. Call Claude Haiku via ``classify`` to assign a primary topic.
5. Persist a ``Paper`` row and return it.
"""

import io
import re
import time

import arxiv
import httpx
import pdfplumber
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.db.constants import COL_PRIMARY_TOPIC
from src.db.models import Paper
from src.llm.client import classify, parse_structured
from src.utils.funcs import logger

_ARXIV_HTML_BASE = "https://arxiv.org/html"
_ARXIV_PDF_BASE = "https://arxiv.org/pdf"
_FULL_TEXT_CHAR_LIMIT = 8000
_REGEX_PARSE_ARXIV_ID = r"abs/([^v/]+)"

config = get_settings()


# ---------------------------------------------------------------------------
# Extraction schema
# ---------------------------------------------------------------------------


class ExtractionSchema(BaseModel):
    """Structured fields extracted from a paper's full text by Claude Sonnet."""

    contributions: str
    methodologies: str
    benchmarks: str
    institutions: list[str]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_arxiv_id(entry_id: str) -> str:
    """Extract bare arXiv ID (e.g. '2504.12345') from an entry_id URL."""
    match = re.search(_REGEX_PARSE_ARXIV_ID, entry_id)
    if match:
        return match.group(1)
    return entry_id.rstrip("/").split("/")[-1].split("v")[0]


async def _fetch_full_text(arxiv_id: str) -> str:
    """Fetch full paper text, trying HTML first then PDF.

    Args:
        arxiv_id: Bare arXiv ID, e.g. ``'2504.12345'``.

    Returns:
        Extracted text string (may be empty if both sources yield nothing).
    """
    html_url = f"{_ARXIV_HTML_BASE}/{arxiv_id}"
    pdf_url = f"{_ARXIV_PDF_BASE}/{arxiv_id}"

    async with httpx.AsyncClient() as client:
        try:
            html_response = await client.get(html_url)
            html_ok = html_response.status_code == 200
        except Exception as exc:
            logger.warning(
                "HTML fetch failed for %s: %s; falling back to PDF", arxiv_id, exc
            )
            html_ok = False

        if html_ok:
            logger.debug("HTML fetch succeeded for %s", arxiv_id)
            return html_response.text  # type: ignore[possibly-undefined]

        logger.debug("Falling back to PDF for %s", arxiv_id)
        try:
            pdf_response = await client.get(pdf_url)
        except Exception as exc:
            logger.error(
                "PDF fetch failed for %s: %s; returning empty text", arxiv_id, exc
            )
            return ""

    if pdf_response.status_code != 200:
        logger.error(
            "PDF fetch returned %d for %s; returning empty text",
            pdf_response.status_code,
            arxiv_id,
        )
        return ""

    try:
        with pdfplumber.open(io.BytesIO(pdf_response.content)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
    except Exception as exc:
        logger.error("PDF parse failed for %s: %s; returning empty text", arxiv_id, exc)
        return ""

    return "\n".join(pages)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def process_paper(result: arxiv.Result, session: AsyncSession) -> Paper | None:
    """Fetch, extract, classify, and persist a single arXiv paper.

    Fetches full text (HTML preferred, PDF fallback), runs structured
    extraction via Claude Sonnet, assigns a primary topic via Claude Haiku,
    and persists the resulting ``Paper`` row.

    Returns ``None`` if LLM extraction or classification fails after all
    retries — the caller should skip this paper rather than abort the run.

    Args:
        result: An ``arxiv.Result`` object from the arXiv API.
        session: Async SQLAlchemy session used to persist the Paper row.

    Returns:
        The persisted ``Paper`` ORM instance, or ``None`` on LLM failure.
    """
    arxiv_id = _parse_arxiv_id(result.entry_id)
    submitted_date = result.published.date()
    authors = [a.name for a in result.authors]

    logger.debug("process_paper entry arxiv_id=%s", arxiv_id)
    t0 = time.perf_counter()

    full_text = await _fetch_full_text(arxiv_id)

    # in case no full_text extracted from the paper, just use empty string
    if not full_text:
        logger.warning(
            "Extracting full text for %s is failed; using empty string",
            arxiv_id,
        )

    extraction_prompt = (
        f"Title: {result.title}\n"
        f"Abstract: {result.summary}\n\n"
        f"Full text:\n{full_text[:_FULL_TEXT_CHAR_LIMIT]}\n\n"
        "Extract: key contributions, methodologies, benchmark results, and "
        "author institutions."
    )
    try:
        extraction: ExtractionSchema = await parse_structured(
            config.LARGE_CLAUDE_LLM, extraction_prompt, ExtractionSchema
        )
    except Exception as exc:
        logger.error(
            "parse_structured failed for %s: %s; skipping paper", arxiv_id, exc
        )
        return None

    topic_tool = {
        "name": "assign_primary_topic",
        "description": "Assign the single most relevant research topic for this paper.",
        "input_schema": {
            "type": "object",
            "properties": {
                COL_PRIMARY_TOPIC: {
                    "type": "string",
                    "enum": config.TOPIC_LIST,
                    "description": "The primary topic this paper belongs to.",
                }
            },
            "required": [COL_PRIMARY_TOPIC],
        },
    }
    classify_prompt = (
        f"Title: {result.title}\nAbstract: {result.summary}\n\n"
        f"Assign the single most relevant topic from: {', '.join(config.TOPIC_LIST)}."
    )
    try:
        topic_result = await classify(
            config.SMALL_CLAUDE_LLM, classify_prompt, topic_tool
        )
    except Exception as exc:
        logger.error("classify failed for %s: %s; skipping paper", arxiv_id, exc)
        return None
    primary_topic: str = topic_result[COL_PRIMARY_TOPIC]

    paper = Paper(
        arxiv_id=arxiv_id,
        title=result.title,
        authors=authors,
        institutions=extraction.institutions,
        abstract=result.summary,
        submitted_date=submitted_date,
        primary_topic=primary_topic,
        secondary_topics=[],
        contributions=extraction.contributions,
        methodologies=extraction.methodologies,
        benchmarks=extraction.benchmarks,
        is_groundbreaking=False,
        groundbreaking_reasoning=None,
    )
    session.add(paper)
    await session.commit()

    logger.info(
        "process_paper done arxiv_id=%s topic=%s elapsed_s=%.3f",
        arxiv_id,
        primary_topic,
        time.perf_counter() - t0,
    )
    return paper
