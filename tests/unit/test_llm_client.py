"""Unit tests for src/llm/client.py.

Covers:
- parse_structured: success, retry-then-succeed, all-retries-fail, model forwarding
- classify: success, retry-then-succeed, all-retries-fail, model + tool forwarding
- Logging calls (entry / success / error) at the appropriate levels
"""

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call

import anthropic
import httpx
import pytest
from pydantic import BaseModel

import src.llm.client as llm_client
from src.config import _DEFAULT_LARGE_CLAUDE_LLM, _DEFAULT_SMALL_CLAUDE_LLM
from src.llm.client import classify, parse_structured

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _api_error(msg: str = "simulated API error") -> anthropic.APIError:
    """Return an APIError instance with a dummy request."""
    return anthropic.APIError(msg, _FAKE_REQUEST, body=None)


class _Output(BaseModel):
    """Minimal Pydantic model used as the parse_structured output schema."""

    value: str


_TOOL_DEF: dict[str, Any] = {
    "name": "classify_topic",
    "description": "Assign the paper's primary research topic",
    "input_schema": {
        "type": "object",
        "properties": {"topic": {"type": "string"}},
        "required": ["topic"],
    },
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace the module-level _client with a MagicMock whose async methods
    are AsyncMocks so they can be awaited in tests."""
    client_mock = MagicMock()
    client_mock.messages.parse = AsyncMock()
    client_mock.messages.create = AsyncMock()
    monkeypatch.setattr(llm_client, "_client", client_mock)
    return client_mock


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace asyncio.sleep with a no-op so retry tests finish instantly."""
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())


# ---------------------------------------------------------------------------
# parse_structured — success path
# ---------------------------------------------------------------------------


async def test_parse_structured_returns_typed_output(mock_client: MagicMock) -> None:
    """parse_structured returns the parsed_output from the SDK response."""
    expected = _Output(value="hello")
    mock_client.messages.parse.return_value = MagicMock(parsed_output=expected)

    result = await parse_structured(_DEFAULT_LARGE_CLAUDE_LLM, "test prompt", _Output)

    assert result is expected
    assert isinstance(result, _Output)


async def test_parse_structured_forwards_model_and_schema(mock_client: MagicMock) -> None:
    """parse_structured passes the model and output_format to messages.parse."""
    mock_client.messages.parse.return_value = MagicMock(parsed_output=_Output(value="x"))

    await parse_structured(_DEFAULT_LARGE_CLAUDE_LLM, "prompt", _Output)

    kwargs = mock_client.messages.parse.call_args.kwargs
    assert kwargs["model"] == _DEFAULT_LARGE_CLAUDE_LLM
    assert kwargs["output_format"] is _Output


async def test_parse_structured_forwards_prompt(mock_client: MagicMock) -> None:
    """parse_structured passes the prompt as the user message content."""
    mock_client.messages.parse.return_value = MagicMock(parsed_output=_Output(value="x"))
    prompt = "Summarise this paper."

    await parse_structured(_DEFAULT_LARGE_CLAUDE_LLM, prompt, _Output)

    kwargs = mock_client.messages.parse.call_args.kwargs
    assert kwargs["messages"] == [{"role": "user", "content": prompt}]


# ---------------------------------------------------------------------------
# parse_structured — retry logic
# ---------------------------------------------------------------------------


async def test_parse_structured_retries_on_api_error(mock_client: MagicMock) -> None:
    """parse_structured retries exactly 3 times on APIError then re-raises."""
    mock_client.messages.parse.side_effect = _api_error()

    with pytest.raises(anthropic.APIError):
        await parse_structured(_DEFAULT_LARGE_CLAUDE_LLM, "prompt", _Output)

    assert mock_client.messages.parse.call_count == 3


async def test_parse_structured_sleeps_between_retries(mock_client: MagicMock) -> None:
    """parse_structured applies exponential backoff between the first two retries."""
    mock_client.messages.parse.side_effect = _api_error()

    with pytest.raises(anthropic.APIError):
        await parse_structured(_DEFAULT_LARGE_CLAUDE_LLM, "prompt", _Output)

    sleep_calls = asyncio.sleep.call_args_list  # type: ignore[attr-defined]
    # Two sleeps between 3 attempts; base=1.0 → 1.0s then 2.0s
    assert sleep_calls == [call(1.0), call(2.0)]


async def test_parse_structured_succeeds_after_retry(mock_client: MagicMock) -> None:
    """parse_structured returns the result when the second attempt succeeds."""
    expected = _Output(value="recovered")
    mock_client.messages.parse.side_effect = [
        _api_error(),
        MagicMock(parsed_output=expected),
    ]

    result = await parse_structured(_DEFAULT_LARGE_CLAUDE_LLM, "prompt", _Output)

    assert result is expected
    assert mock_client.messages.parse.call_count == 2


async def test_parse_structured_reraises_last_exception(mock_client: MagicMock) -> None:
    """parse_structured re-raises the exception from the final (3rd) attempt."""
    sentinel_error = _api_error("final failure")
    mock_client.messages.parse.side_effect = [
        _api_error("first"),
        _api_error("second"),
        sentinel_error,
    ]

    with pytest.raises(anthropic.APIError) as exc_info:
        await parse_structured(_DEFAULT_LARGE_CLAUDE_LLM, "prompt", _Output)

    assert exc_info.value is sentinel_error


# ---------------------------------------------------------------------------
# parse_structured — logging
# ---------------------------------------------------------------------------


async def test_parse_structured_logs_entry_at_debug(
    mock_client: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """parse_structured emits a DEBUG log entry on every call."""
    mock_client.messages.parse.return_value = MagicMock(parsed_output=_Output(value="x"))

    with caplog.at_level(logging.DEBUG, logger="src.llm.client"):
        await parse_structured(_DEFAULT_LARGE_CLAUDE_LLM, "prompt", _Output)

    debug_msgs = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("parse_structured.entry" in r.message for r in debug_msgs)


async def test_parse_structured_logs_success_at_info(
    mock_client: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """parse_structured emits an INFO log on success."""
    mock_client.messages.parse.return_value = MagicMock(parsed_output=_Output(value="x"))

    with caplog.at_level(logging.DEBUG, logger="src.llm.client"):
        await parse_structured(_DEFAULT_LARGE_CLAUDE_LLM, "prompt", _Output)

    info_msgs = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any("parse_structured.success" in r.message for r in info_msgs)


async def test_parse_structured_logs_error_on_failure(
    mock_client: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """parse_structured emits an ERROR log when all retries are exhausted."""
    mock_client.messages.parse.side_effect = _api_error()

    with caplog.at_level(logging.DEBUG, logger="src.llm.client"):
        with pytest.raises(anthropic.APIError):
            await parse_structured(_DEFAULT_LARGE_CLAUDE_LLM, "prompt", _Output)

    error_msgs = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("parse_structured.error" in r.message for r in error_msgs)


# ---------------------------------------------------------------------------
# classify — success path
# ---------------------------------------------------------------------------


async def test_classify_returns_tool_input(mock_client: MagicMock) -> None:
    """classify returns the input dict from the first tool_use content block."""
    tool_input = {"topic": "Large Language Models"}
    mock_response = MagicMock()
    mock_response.content = [MagicMock(input=tool_input)]
    mock_client.messages.create.return_value = mock_response

    result = await classify(_DEFAULT_SMALL_CLAUDE_LLM, "prompt", _TOOL_DEF)

    assert result == tool_input


async def test_classify_forwards_model(mock_client: MagicMock) -> None:
    """classify passes the model string to messages.create."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(input={"topic": "CV"})]
    mock_client.messages.create.return_value = mock_response

    await classify(_DEFAULT_SMALL_CLAUDE_LLM, "prompt", _TOOL_DEF)

    kwargs = mock_client.messages.create.call_args.kwargs
    assert kwargs["model"] == _DEFAULT_SMALL_CLAUDE_LLM


async def test_classify_forwards_tool_def_and_choice(mock_client: MagicMock) -> None:
    """classify passes tools list and tool_choice that pins to the tool name."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(input={"topic": "CV"})]
    mock_client.messages.create.return_value = mock_response

    await classify(_DEFAULT_SMALL_CLAUDE_LLM, "prompt", _TOOL_DEF)

    kwargs = mock_client.messages.create.call_args.kwargs
    assert kwargs["tools"] == [_TOOL_DEF]
    assert kwargs["tool_choice"] == {"type": "tool", "name": _TOOL_DEF["name"]}


async def test_classify_forwards_prompt(mock_client: MagicMock) -> None:
    """classify passes the prompt as the user message content."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(input={"topic": "CV"})]
    mock_client.messages.create.return_value = mock_response
    prompt = "Classify this paper."

    await classify(_DEFAULT_SMALL_CLAUDE_LLM, prompt, _TOOL_DEF)

    kwargs = mock_client.messages.create.call_args.kwargs
    assert kwargs["messages"] == [{"role": "user", "content": prompt}]


# ---------------------------------------------------------------------------
# classify — retry logic
# ---------------------------------------------------------------------------


async def test_classify_retries_on_api_error(mock_client: MagicMock) -> None:
    """classify retries exactly 3 times on APIError then re-raises."""
    mock_client.messages.create.side_effect = _api_error()

    with pytest.raises(anthropic.APIError):
        await classify(_DEFAULT_SMALL_CLAUDE_LLM, "prompt", _TOOL_DEF)

    assert mock_client.messages.create.call_count == 3


async def test_classify_sleeps_between_retries(mock_client: MagicMock) -> None:
    """classify applies exponential backoff between the first two retries."""
    mock_client.messages.create.side_effect = _api_error()

    with pytest.raises(anthropic.APIError):
        await classify(_DEFAULT_SMALL_CLAUDE_LLM, "prompt", _TOOL_DEF)

    sleep_calls = asyncio.sleep.call_args_list  # type: ignore[attr-defined]
    assert sleep_calls == [call(1.0), call(2.0)]


async def test_classify_succeeds_after_retry(mock_client: MagicMock) -> None:
    """classify returns the result when the second attempt succeeds."""
    tool_input = {"topic": "Robotics"}
    good_response = MagicMock()
    good_response.content = [MagicMock(input=tool_input)]
    mock_client.messages.create.side_effect = [_api_error(), good_response]

    result = await classify(_DEFAULT_SMALL_CLAUDE_LLM, "prompt", _TOOL_DEF)

    assert result == tool_input
    assert mock_client.messages.create.call_count == 2


async def test_classify_reraises_last_exception(mock_client: MagicMock) -> None:
    """classify re-raises the exception from the final (3rd) attempt."""
    sentinel_error = _api_error("final classify failure")
    mock_client.messages.create.side_effect = [
        _api_error("first"),
        _api_error("second"),
        sentinel_error,
    ]

    with pytest.raises(anthropic.APIError) as exc_info:
        await classify(_DEFAULT_SMALL_CLAUDE_LLM, "prompt", _TOOL_DEF)

    assert exc_info.value is sentinel_error


# ---------------------------------------------------------------------------
# classify — logging
# ---------------------------------------------------------------------------


async def test_classify_logs_entry_at_debug(
    mock_client: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """classify emits a DEBUG log entry on every call."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(input={"topic": "CV"})]
    mock_client.messages.create.return_value = mock_response

    with caplog.at_level(logging.DEBUG, logger="src.llm.client"):
        await classify(_DEFAULT_SMALL_CLAUDE_LLM, "prompt", _TOOL_DEF)

    debug_msgs = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("classify.entry" in r.message for r in debug_msgs)


async def test_classify_logs_success_at_info(
    mock_client: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """classify emits an INFO log on success."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(input={"topic": "CV"})]
    mock_client.messages.create.return_value = mock_response

    with caplog.at_level(logging.DEBUG, logger="src.llm.client"):
        await classify(_DEFAULT_SMALL_CLAUDE_LLM, "prompt", _TOOL_DEF)

    info_msgs = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any("classify.success" in r.message for r in info_msgs)


async def test_classify_logs_error_on_failure(
    mock_client: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """classify emits an ERROR log when all retries are exhausted."""
    mock_client.messages.create.side_effect = _api_error()

    with caplog.at_level(logging.DEBUG, logger="src.llm.client"):
        with pytest.raises(anthropic.APIError):
            await classify(_DEFAULT_SMALL_CLAUDE_LLM, "prompt", _TOOL_DEF)

    error_msgs = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("classify.error" in r.message for r in error_msgs)
