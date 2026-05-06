"""Unit tests for src/pipeline/processor.py.

Covers:
- primary_topic is always a member of TOPIC_LIST
- groundbreaking_reasoning is null and is_groundbreaking is False (default)
- HTML fetch is attempted before PDF fallback; PDF called only on non-200
- parse_structured is called for extraction
- paper is persisted to DB via session.add + session.commit
"""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.pipeline.processor as processor_module
from src.config import _DEFAULT_TOPIC_LIST
from src.pipeline.processor import process_paper

# ---------------------------------------------------------------------------
# Constants derived from real config defaults — no mocking needed
# ---------------------------------------------------------------------------

_TOPIC_LIST: list[str] = [t.strip() for t in _DEFAULT_TOPIC_LIST.split(",")]
_ARXIV_ID = "2504.12345"
_SUBMITTED_DATE = datetime.date(2025, 4, 15)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_arxiv_result() -> MagicMock:
    result = MagicMock()
    result.entry_id = f"http://arxiv.org/abs/{_ARXIV_ID}v1"
    result.title = "A Great Paper"
    result.authors = [MagicMock(), MagicMock()]
    result.authors[0].name = "Alice"
    result.authors[1].name = "Bob"
    result.summary = "An abstract about ML."
    result.published = datetime.datetime(
        _SUBMITTED_DATE.year, _SUBMITTED_DATE.month, _SUBMITTED_DATE.day,
        tzinfo=datetime.UTC,
    )
    return result


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session


def _make_extraction() -> MagicMock:
    ext = MagicMock()
    ext.contributions = "Novel attention mechanism."
    ext.methodologies = "Transformer-based approach."
    ext.benchmarks = "BLEU +2 on WMT."
    ext.institutions = ["MIT", "Stanford"]
    return ext


def _make_http_client(status_code: int = 200, text: str = "html body") -> MagicMock:
    """Return a mock httpx.AsyncClient whose GET always returns *status_code*."""
    http = MagicMock()
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=False)
    http.get = AsyncMock(
        return_value=MagicMock(status_code=status_code, text=text, content=b"")
    )
    return http


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_classify(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock(return_value={"primary_topic": _TOPIC_LIST[0]})
    monkeypatch.setattr(processor_module, "classify", mock)
    return mock


@pytest.fixture(autouse=True)
def mock_parse_structured(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock(return_value=_make_extraction())
    monkeypatch.setattr(processor_module, "parse_structured", mock)
    return mock


# ---------------------------------------------------------------------------
# primary_topic
# ---------------------------------------------------------------------------


async def test_primary_topic_comes_from_classify_and_is_in_topic_list(
    mock_classify: AsyncMock,
) -> None:
    """primary_topic is taken from classify output and must be a member of TOPIC_LIST."""
    expected_topic = _TOPIC_LIST[2]
    mock_classify.return_value = {"primary_topic": expected_topic}

    with patch("httpx.AsyncClient", return_value=_make_http_client()):
        paper = await process_paper(_make_arxiv_result(), _make_session())

    assert paper.primary_topic == expected_topic
    assert paper.primary_topic in _TOPIC_LIST


# ---------------------------------------------------------------------------
# groundbreaking defaults
# ---------------------------------------------------------------------------


async def test_groundbreaking_defaults_are_false_and_null() -> None:
    """process_paper does not set groundbreaking flags — detector handles that later."""
    with patch("httpx.AsyncClient", return_value=_make_http_client()):
        paper = await process_paper(_make_arxiv_result(), _make_session())

    assert paper.is_groundbreaking is False
    assert paper.groundbreaking_reasoning is None


# ---------------------------------------------------------------------------
# HTML first, PDF fallback
# ---------------------------------------------------------------------------


async def test_html_url_is_fetched_first() -> None:
    """The first GET targets arxiv.org/html/{arxiv_id}, not the PDF endpoint."""
    http = _make_http_client(status_code=200)

    with patch("httpx.AsyncClient", return_value=http):
        await process_paper(_make_arxiv_result(), _make_session())

    first_url: str = http.get.call_args_list[0].args[0]
    assert "html" in first_url
    assert _ARXIV_ID in first_url


async def test_pdf_not_called_when_html_succeeds() -> None:
    """pdfplumber is never opened when the HTML response is 200."""
    with patch("httpx.AsyncClient", return_value=_make_http_client(status_code=200)):
        with patch("pdfplumber.open") as mock_pdf:
            await process_paper(_make_arxiv_result(), _make_session())

    mock_pdf.assert_not_called()


async def test_pdf_fallback_when_html_returns_non_200() -> None:
    """pdfplumber.open is called when the HTML fetch returns non-200."""
    html_resp = MagicMock(status_code=404, text="", content=b"")
    pdf_resp = MagicMock(status_code=200, text="", content=b"%PDF fake")

    http = MagicMock()
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=False)
    http.get = AsyncMock(side_effect=[html_resp, pdf_resp])

    fake_pdf = MagicMock()
    fake_pdf.__enter__ = MagicMock(return_value=fake_pdf)
    fake_pdf.__exit__ = MagicMock(return_value=False)
    fake_page = MagicMock()
    fake_page.extract_text.return_value = "extracted text"
    fake_pdf.pages = [fake_page]

    with patch("httpx.AsyncClient", return_value=http):
        with patch("pdfplumber.open", return_value=fake_pdf) as mock_pdf:
            await process_paper(_make_arxiv_result(), _make_session())

    mock_pdf.assert_called_once()


# ---------------------------------------------------------------------------
# HTML exception → PDF fallback
# ---------------------------------------------------------------------------


async def test_html_exception_falls_back_to_pdf() -> None:
    """An exception from the HTML GET triggers PDF fallback instead of returning empty."""
    pdf_resp = MagicMock(status_code=200, text="", content=b"%PDF fake")

    http = MagicMock()
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=False)
    http.get = AsyncMock(side_effect=[OSError("connection refused"), pdf_resp])

    fake_pdf = MagicMock()
    fake_pdf.__enter__ = MagicMock(return_value=fake_pdf)
    fake_pdf.__exit__ = MagicMock(return_value=False)
    fake_page = MagicMock()
    fake_page.extract_text.return_value = "pdf text"
    fake_pdf.pages = [fake_page]

    with patch("httpx.AsyncClient", return_value=http):
        with patch("pdfplumber.open", return_value=fake_pdf):
            paper = await process_paper(_make_arxiv_result(), _make_session())

    assert paper is not None
    assert http.get.call_count == 2  # HTML attempted, then PDF


async def test_pdf_fetch_exception_returns_empty_text_not_none() -> None:
    """PDF GET exception yields empty full text; paper is still persisted."""
    html_resp = MagicMock(status_code=404, text="", content=b"")

    http = MagicMock()
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=False)
    http.get = AsyncMock(side_effect=[html_resp, OSError("timeout")])

    with patch("httpx.AsyncClient", return_value=http):
        paper = await process_paper(_make_arxiv_result(), _make_session())

    assert paper is not None


async def test_pdf_non_200_returns_empty_text_not_none() -> None:
    """PDF GET non-200 yields empty full text; paper is still persisted."""
    html_resp = MagicMock(status_code=404, text="", content=b"")
    pdf_resp = MagicMock(status_code=503, text="", content=b"")

    http = MagicMock()
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=False)
    http.get = AsyncMock(side_effect=[html_resp, pdf_resp])

    with patch("httpx.AsyncClient", return_value=http):
        paper = await process_paper(_make_arxiv_result(), _make_session())

    assert paper is not None


async def test_pdf_parse_exception_returns_empty_text_not_none() -> None:
    """pdfplumber raising on corrupt bytes yields empty full text; paper is still persisted."""
    html_resp = MagicMock(status_code=404, text="", content=b"")
    pdf_resp = MagicMock(status_code=200, text="", content=b"not a pdf")

    http = MagicMock()
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=False)
    http.get = AsyncMock(side_effect=[html_resp, pdf_resp])

    with patch("httpx.AsyncClient", return_value=http):
        with patch("pdfplumber.open", side_effect=ValueError("bad pdf")):
            paper = await process_paper(_make_arxiv_result(), _make_session())

    assert paper is not None


# ---------------------------------------------------------------------------
# parse_structured is called; returns None on failure
# ---------------------------------------------------------------------------


async def test_parse_structured_called_for_extraction(
    mock_parse_structured: AsyncMock,
) -> None:
    """process_paper calls parse_structured exactly once to extract paper content."""
    with patch("httpx.AsyncClient", return_value=_make_http_client()):
        await process_paper(_make_arxiv_result(), _make_session())

    mock_parse_structured.assert_awaited_once()


async def test_returns_none_when_parse_structured_fails(
    mock_parse_structured: AsyncMock,
) -> None:
    """process_paper returns None when parse_structured raises after all retries."""
    mock_parse_structured.side_effect = Exception("LLM unavailable")

    with patch("httpx.AsyncClient", return_value=_make_http_client()):
        paper = await process_paper(_make_arxiv_result(), _make_session())

    assert paper is None


async def test_returns_none_when_classify_fails(
    mock_classify: AsyncMock,
) -> None:
    """process_paper returns None when classify raises after all retries."""
    mock_classify.side_effect = Exception("LLM unavailable")

    with patch("httpx.AsyncClient", return_value=_make_http_client()):
        paper = await process_paper(_make_arxiv_result(), _make_session())

    assert paper is None


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------


async def test_paper_is_persisted_to_db() -> None:
    """process_paper calls session.add(paper) then session.commit()."""
    session = _make_session()

    with patch("httpx.AsyncClient", return_value=_make_http_client()):
        paper = await process_paper(_make_arxiv_result(), session)

    session.add.assert_called_once_with(paper)
    session.commit.assert_awaited_once()


async def test_arxiv_id_parsed_from_non_standard_entry_id() -> None:
    """_parse_arxiv_id falls back to path splitting when the URL has no /abs/ segment."""
    result = _make_arxiv_result()
    result.entry_id = "2504.99999v2"  # no /abs/ segment — triggers fallback branch

    with patch("httpx.AsyncClient", return_value=_make_http_client()):
        paper = await process_paper(result, _make_session())

    assert paper.arxiv_id == "2504.99999"


async def test_returned_paper_has_core_fields_from_arxiv_result() -> None:
    """process_paper maps arxiv.Result fields onto Paper columns correctly."""
    session = _make_session()
    result = _make_arxiv_result()

    with patch("httpx.AsyncClient", return_value=_make_http_client()):
        paper = await process_paper(result, session)

    assert paper.arxiv_id == _ARXIV_ID
    assert paper.title == result.title
    assert paper.abstract == result.summary
    assert paper.submitted_date == _SUBMITTED_DATE
    assert paper.authors == ["Alice", "Bob"]
