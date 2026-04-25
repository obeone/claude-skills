"""``text.transform`` — generic Gemini text pipe.

Zero TTS-domain fields. The caller assembles the prompt; this tool only
dispatches it to ``client.models.generate_content`` and returns the
generated text plus token usage.
"""

from __future__ import annotations

from typing import Any

import mcp.types as types

from gemini_tts_mcp import errors
from gemini_tts_mcp.client import AppContext


_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["prompt", "model"],
    "properties": {
        "prompt": {"type": "string"},
        "model": {"type": "string"},
        "temperature": {"type": "number", "default": 0.2},
        "max_output_tokens": {"type": "integer", "default": 8192},
    },
    "additionalProperties": False,
}

_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["text", "input_tokens", "output_tokens"],
    "properties": {
        "text": {"type": "string"},
        "input_tokens": {"type": "integer"},
        "output_tokens": {"type": "integer"},
    },
    "additionalProperties": False,
}


DEFINITIONS: list[types.Tool] = [
    types.Tool(
        name="text.transform",
        description=(
            "Run a generic Gemini text completion. The caller assembles "
            "the entire prompt; this tool returns the generated text and "
            "token usage."
        ),
        inputSchema=_INPUT_SCHEMA,
        outputSchema=_OUTPUT_SCHEMA,
    ),
]

TOOL_NAMES = {tool.name for tool in DEFINITIONS}


def _usage_tokens(response: Any) -> tuple[int, int]:
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return 0, 0
    return (
        int(getattr(usage, "prompt_token_count", 0) or 0),
        int(getattr(usage, "candidates_token_count", 0) or 0),
    )


async def handle(name: str, arguments: dict[str, Any], app: AppContext) -> dict[str, Any]:
    if name != "text.transform":
        raise ValueError(f"text.handle received unknown tool name: {name}")

    try:
        prompt = arguments["prompt"]
        model = arguments["model"]
    except KeyError as exc:
        return errors.bad_input(f"missing required field: {exc.args[0]}")

    temperature = arguments.get("temperature", 0.2)
    max_output_tokens = arguments.get("max_output_tokens", 8192)

    from google.genai import types as gt

    try:
        response = app.client.models.generate_content(
            model=model,
            contents=prompt,
            config=gt.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        if "deprecated" in message.lower() or "not found" in message.lower():
            return errors.upstream_break(message)
        return errors.text_transform_failed(retryable=True, detail=message)

    text_value = getattr(response, "text", None)
    if not isinstance(text_value, str):
        return errors.text_transform_failed(
            retryable=False,
            detail="response did not expose a string ``text`` attribute",
        )

    input_tokens, output_tokens = _usage_tokens(response)
    return {
        "text": text_value,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
