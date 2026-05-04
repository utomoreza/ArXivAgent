"""Anthropic LLM client with structured-output helpers and retry logic.

Exposes two public coroutines:

* ``parse_structured`` — wraps ``messages.parse()`` for Pydantic-typed output.
* ``classify``         — wraps ``messages.create()`` with a pinned tool call.

Both retry up to three times on ``anthropic.APIError`` with exponential
back-off and emit structured JSON log lines at DEBUG/INFO/ERROR.
"""

import asyncio
import inspect
import json
import logging
import time
from typing import Any

import anthropic
from anthropic import AsyncAnthropic
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_BASE_SECONDS = 1.0

# Single shared client instance — created once at import time; no API calls
# are made until a coroutine is awaited.
_client = AsyncAnthropic()


async def parse_structured[T: BaseModel](
    model: str, prompt: str, output_schema: type[T]
) -> T:
    """Call Claude with structured output, returning a typed Pydantic object.

    Wraps ``messages.parse(output_format=output_schema)`` and retries up to
    ``_MAX_RETRIES`` times on ``anthropic.APIError`` with exponential back-off.

    Args:
        model: Claude model string, e.g. ``SONNET`` or ``HAIKU``.
        prompt: User-turn prompt text.
        output_schema: Pydantic model class that defines the expected response shape.

    Returns:
        An instance of ``output_schema`` populated from the model response.

    Raises:
        anthropic.APIError: If all retry attempts fail.
    """
    func_name = inspect.currentframe().f_code.co_name

    logger.debug(json.dumps({"event": f"{func_name}.entry", "model": model}))
    start = time.monotonic()
    last_exc: anthropic.APIError | None = None

    for attempt in range(_MAX_RETRIES):
        try:
            response = await _client.messages.parse(
                model=model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
                output_format=output_schema,
            )
            result = response.parsed_output
            elapsed = time.monotonic() - start
            logger.info(
                json.dumps(
                    {
                        "event": f"{func_name}.success",
                        "model": model,
                        "elapsed_s": round(elapsed, 3),
                    }
                )
            )
            return result  # type: ignore[return-value]
        except anthropic.APIError as exc:
            last_exc = exc
            logger.warning(
                json.dumps(
                    {
                        "event": f"{func_name}.retry",
                        "attempt": attempt + 1,
                        "error": str(exc),
                    }
                )
            )
            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(_RETRY_BASE_SECONDS * (2**attempt))

    elapsed = time.monotonic() - start
    logger.error(
        json.dumps(
            {
                "event": f"{func_name}.error",
                "model": model,
                "elapsed_s": round(elapsed, 3),
            }
        )
    )
    raise last_exc  # type: ignore[misc]


async def classify(model: str, prompt: str, tool_def: dict[str, Any]) -> dict[str, Any]:
    """Call Claude with a pinned tool call, returning the tool input dict.

    Wraps ``messages.create(tools=[tool_def], tool_choice={"type":"tool",...})``
    and retries up to ``_MAX_RETRIES`` times on ``anthropic.APIError`` with
    exponential back-off.

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
    func_name = inspect.currentframe().f_code.co_name

    logger.debug(json.dumps({"event": f"{func_name}.entry", "model": model}))
    start = time.monotonic()
    last_exc: anthropic.APIError | None = None

    for attempt in range(_MAX_RETRIES):
        try:
            response = await _client.messages.create(
                model=model,
                max_tokens=256,
                tools=[tool_def],
                tool_choice={"type": "tool", "name": tool_def["name"]},
                messages=[{"role": "user", "content": prompt}],
            )
            result: dict[str, Any] = response.content[0].input
            elapsed = time.monotonic() - start
            logger.info(
                json.dumps(
                    {
                        "event": f"{func_name}.success",
                        "model": model,
                        "elapsed_s": round(elapsed, 3),
                    }
                )
            )
            return result
        except anthropic.APIError as exc:
            last_exc = exc
            logger.warning(
                json.dumps(
                    {
                        "event": f"{func_name}.retry",
                        "attempt": attempt + 1,
                        "error": str(exc),
                    }
                )
            )
            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(_RETRY_BASE_SECONDS * (2**attempt))

    elapsed = time.monotonic() - start
    logger.error(
        json.dumps(
            {
                "event": f"{func_name}.error",
                "model": model,
                "elapsed_s": round(elapsed, 3),
            }
        )
    )
    raise last_exc  # type: ignore[misc]
