"""Anthropic LLM client with structured-output helpers and retry logic.

Exposes two public coroutines:

* ``parse_structured`` — wraps ``messages.parse()`` for Pydantic-typed output.
* ``classify``         — wraps ``messages.create()`` with a pinned tool call.

Both retry up to three times on ``anthropic.APIError`` with exponential
back-off and emit structured JSON log lines at DEBUG/INFO/ERROR.
"""

import time
from enum import StrEnum
from typing import Any

import anthropic
from anthropic import AsyncAnthropic
from pydantic import BaseModel, ConfigDict

from src.config import get_settings
from src.utils.funcs import logger, with_retry

_MAX_RETRIES = 3
_RETRY_BASE_SECONDS = 1.0

# Single shared client instance — created once at import time; no API calls
# are made until a coroutine is awaited.  The API key is read from settings
# (which load from .env via pydantic-settings) rather than relying on the
# Anthropic SDK to find it in os.environ, which pydantic-settings does NOT
# mutate.
_client = AsyncAnthropic(api_key=get_settings().ANTHROPIC_API_KEY)


class Events(StrEnum):
    ENTRY = "entry"
    SUCCESS = "success"
    RETRY = "retry"
    ERROR = "error"


class LogDatum(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event: Events
    model: str | None = None
    elapsed_s: float | None = None
    attempt: int | None = None
    error: str | None = None


@with_retry(
    max_retries=_MAX_RETRIES,
    base_seconds=_RETRY_BASE_SECONDS,
    exceptions=(anthropic.APIError,),
)
async def parse_structured[T: BaseModel](
    model: str, prompt: str, output_schema: type[T]
) -> T:
    """Call Claude with structured output, returning a typed Pydantic object.

    Wraps ``messages.parse(output_format=output_schema)`` and retries up to
    ``_MAX_RETRIES`` times on ``anthropic.APIError`` with exponential back-off
    (delegated to the ``with_retry`` decorator).

    Args:
        model: Claude model string, e.g. ``SONNET`` or ``HAIKU``.
        prompt: User-turn prompt text.
        output_schema: Pydantic model class that defines the expected response shape.

    Returns:
        An instance of ``output_schema`` populated from the model response.

    Raises:
        anthropic.APIError: If all retry attempts fail.
    """
    logger.debug(LogDatum(event=Events.ENTRY.value, model=model)
                 .model_dump(mode="json", exclude_none=True))
    start = time.monotonic()
    response = await _client.messages.parse(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
        output_format=output_schema,
    )
    result = response.parsed_output
    logger.info(
        LogDatum(
            event=Events.SUCCESS.value,
            model=model,
            elapsed_s=round(time.monotonic() - start, 3),
        ).model_dump(mode="json", exclude_none=True)
    )
    return result  # type: ignore[return-value]


@with_retry(
    max_retries=_MAX_RETRIES,
    base_seconds=_RETRY_BASE_SECONDS,
    exceptions=(anthropic.APIError,),
)
async def classify(model: str, prompt: str, tool_def: dict[str, Any]) -> dict[str, Any]:
    """Call Claude with a pinned tool call, returning the tool input dict.

    Wraps ``messages.create(tools=[tool_def], tool_choice={"type":"tool",...})``
    and retries up to ``_MAX_RETRIES`` times on ``anthropic.APIError`` with
    exponential back-off (delegated to the ``with_retry`` decorator).

    Args:
        model: Claude model string, e.g. ``SONNET`` or ``HAIKU``.
        prompt: User-turn prompt text.
        tool_def: Anthropic tool definition dict with ``name``, ``description``,
            and ``input_schema`` keys.

    Returns:
        The ``input`` dict from the first tool_use content block in the response.

    Raises:
        anthropic.APIError: If all retry attempts fail.
    """
    logger.debug(LogDatum(event=Events.ENTRY.value, model=model)
                 .model_dump(mode="json", exclude_none=True))
    start = time.monotonic()
    response = await _client.messages.create(
        model=model,
        max_tokens=256,
        tools=[tool_def],
        tool_choice={"type": "tool", "name": tool_def["name"]},
        messages=[{"role": "user", "content": prompt}],
    )
    result: dict[str, Any] = response.content[0].input
    logger.info(
        LogDatum(
            event=Events.SUCCESS.value,
            model=model,
            elapsed_s=round(time.monotonic() - start, 3),
        ).model_dump(mode="json", exclude_none=True)
    )
    return result
