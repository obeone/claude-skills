"""TTS tools: ``tts_generate_chunk``, ``tts_preview_voice``, ``tts_count_tokens``.

All three call into ``google-genai`` through the shared client supplied
by the lifespan context. PCM is always 24 kHz / 16-bit / mono — the skill
side wraps it into WAV via ``finalize_audio.py``.
"""

from __future__ import annotations

import base64
from typing import Any

import mcp.types as types

from gemini_tts_mcp import errors
from gemini_tts_mcp.client import AppContext


SAMPLE_RATE_HZ = 24000
BITS_PER_SAMPLE = 16
CHANNELS = 1

# Base64-encoded 24 kHz mono 16-bit PCM grows ~32 kB / second of audio.
# The Anthropic ceiling is 500 kB; that fits roughly 12-14 minutes of
# audio per chunk before Claude Code persists the result to disk and
# breaks the skill's mcp_client parsing.
MAX_RESULT_SIZE_CHARS = 500_000

_TTS_CHUNK_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["model", "content", "voice_a"],
    "properties": {
        "model": {"type": "string"},
        "content": {"type": "string"},
        "voice_a": {"type": "string"},
        "voice_b": {"type": ["string", "null"]},
        "system_instruction": {"type": ["string", "null"]},
        "request_timeout_s": {"type": "number", "default": 300},
    },
    "additionalProperties": False,
}

_TTS_CHUNK_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "pcm_base64",
        "sample_rate_hz",
        "bits_per_sample",
        "channels",
        "input_tokens",
        "output_tokens",
    ],
    "properties": {
        "pcm_base64": {"type": "string"},
        "sample_rate_hz": {"type": "integer"},
        "bits_per_sample": {"type": "integer"},
        "channels": {"type": "integer"},
        "input_tokens": {"type": "integer"},
        "output_tokens": {"type": "integer"},
    },
    "additionalProperties": False,
}

_PREVIEW_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["voice", "text", "model"],
    "properties": {
        "voice": {"type": "string"},
        "text": {"type": "string"},
        "model": {"type": "string"},
        "seconds_hint": {"type": ["number", "null"]},
    },
    "additionalProperties": False,
}

_COUNT_TOKENS_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["model", "content"],
    "properties": {
        "model": {"type": "string"},
        "content": {"type": "string"},
    },
    "additionalProperties": False,
}

_COUNT_TOKENS_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["total_tokens", "model_id"],
    "properties": {
        "total_tokens": {"type": "integer"},
        "model_id": {"type": "string"},
    },
    "additionalProperties": False,
}


DEFINITIONS: list[types.Tool] = [
    types.Tool(
        name="tts_generate_chunk",
        description=(
            "Generate one PCM audio chunk via Gemini TTS. Returns base64-"
            "encoded raw PCM (24 kHz, 16-bit, mono). Use one or two voice "
            "names; the model expects matching ``Speaker:`` prefixes in "
            "``content`` for multi-speaker output."
        ),
        inputSchema=_TTS_CHUNK_INPUT_SCHEMA,
        outputSchema=_TTS_CHUNK_OUTPUT_SCHEMA,
        _meta={"anthropic/maxResultSizeChars": MAX_RESULT_SIZE_CHARS},
    ),
    types.Tool(
        name="tts_preview_voice",
        description=(
            "Generate a short audio sample of a single voice for "
            "auditioning. Same return shape as ``tts_generate_chunk``."
        ),
        inputSchema=_PREVIEW_INPUT_SCHEMA,
        outputSchema=_TTS_CHUNK_OUTPUT_SCHEMA,
        _meta={"anthropic/maxResultSizeChars": MAX_RESULT_SIZE_CHARS},
    ),
    types.Tool(
        name="tts_count_tokens",
        description=(
            "Deterministic token count for a TTS prompt. No billing, no "
            "audio generation."
        ),
        inputSchema=_COUNT_TOKENS_INPUT_SCHEMA,
        outputSchema=_COUNT_TOKENS_OUTPUT_SCHEMA,
    ),
]

TOOL_NAMES = {tool.name for tool in DEFINITIONS}


def _build_speech_config(voice_a: str, voice_b: str | None) -> Any:
    from google.genai import types as gt

    if voice_b:
        return gt.SpeechConfig(
            multi_speaker_voice_config=gt.MultiSpeakerVoiceConfig(
                speaker_voice_configs=[
                    gt.SpeakerVoiceConfig(
                        speaker="A",
                        voice_config=gt.VoiceConfig(
                            prebuilt_voice_config=gt.PrebuiltVoiceConfig(voice_name=voice_a),
                        ),
                    ),
                    gt.SpeakerVoiceConfig(
                        speaker="B",
                        voice_config=gt.VoiceConfig(
                            prebuilt_voice_config=gt.PrebuiltVoiceConfig(voice_name=voice_b),
                        ),
                    ),
                ],
            ),
        )
    return gt.SpeechConfig(
        voice_config=gt.VoiceConfig(
            prebuilt_voice_config=gt.PrebuiltVoiceConfig(voice_name=voice_a),
        ),
    )


def _extract_pcm(response: Any) -> bytes:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        raise ValueError("response had no candidates")
    parts = getattr(candidates[0].content, "parts", None) or []
    if not parts:
        raise ValueError("response candidate had no parts")
    inline = getattr(parts[0], "inline_data", None)
    data = getattr(inline, "data", None) if inline is not None else None
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError("response part missing inline_data.data bytes")
    return bytes(data)


def _usage_tokens(response: Any) -> tuple[int, int]:
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return 0, 0
    return (
        int(getattr(usage, "prompt_token_count", 0) or 0),
        int(getattr(usage, "candidates_token_count", 0) or 0),
    )


async def _generate(
    *,
    app: AppContext,
    model: str,
    content: str,
    voice_a: str,
    voice_b: str | None,
    system_instruction: str | None,
) -> dict[str, Any]:
    from google.genai import types as gt

    config_kwargs: dict[str, Any] = {
        "response_modalities": ["AUDIO"],
        "speech_config": _build_speech_config(voice_a, voice_b),
    }
    if system_instruction:
        config_kwargs["system_instruction"] = system_instruction

    try:
        response = app.client.models.generate_content(
            model=model,
            contents=content,
            config=gt.GenerateContentConfig(**config_kwargs),
        )
    except Exception as exc:  # noqa: BLE001 — boundary; convert to taxonomy
        message = str(exc)
        if "deprecated" in message.lower() or "not found" in message.lower():
            return errors.upstream_break(message)
        return errors.tts_chunk_failed(retryable=True, detail=message)

    try:
        pcm = _extract_pcm(response)
    except Exception as exc:  # noqa: BLE001
        return errors.tts_chunk_failed(retryable=False, detail=str(exc))

    input_tokens, output_tokens = _usage_tokens(response)
    return {
        "pcm_base64": base64.b64encode(pcm).decode("ascii"),
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "bits_per_sample": BITS_PER_SAMPLE,
        "channels": CHANNELS,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


async def _generate_chunk(arguments: dict[str, Any], app: AppContext) -> dict[str, Any]:
    try:
        model = arguments["model"]
        content = arguments["content"]
        voice_a = arguments["voice_a"]
    except KeyError as exc:
        return errors.bad_input(f"missing required field: {exc.args[0]}")

    return await _generate(
        app=app,
        model=model,
        content=content,
        voice_a=voice_a,
        voice_b=arguments.get("voice_b"),
        system_instruction=arguments.get("system_instruction"),
    )


async def _preview_voice(arguments: dict[str, Any], app: AppContext) -> dict[str, Any]:
    try:
        voice = arguments["voice"]
        text = arguments["text"]
        model = arguments["model"]
    except KeyError as exc:
        return errors.bad_input(f"missing required field: {exc.args[0]}")

    return await _generate(
        app=app,
        model=model,
        content=text,
        voice_a=voice,
        voice_b=None,
        system_instruction=None,
    )


async def _count_tokens(arguments: dict[str, Any], app: AppContext) -> dict[str, Any]:
    try:
        model = arguments["model"]
        content = arguments["content"]
    except KeyError as exc:
        return errors.bad_input(f"missing required field: {exc.args[0]}")

    try:
        response = app.client.models.count_tokens(model=model, contents=content)
    except Exception as exc:  # noqa: BLE001
        return errors.tts_chunk_failed(retryable=True, detail=str(exc))

    total = int(getattr(response, "total_tokens", 0) or 0)
    return {"total_tokens": total, "model_id": model}


async def handle(name: str, arguments: dict[str, Any], app: AppContext) -> dict[str, Any]:
    if name == "tts_generate_chunk":
        return await _generate_chunk(arguments, app)
    if name == "tts_preview_voice":
        return await _preview_voice(arguments, app)
    if name == "tts_count_tokens":
        return await _count_tokens(arguments, app)
    raise ValueError(f"tts.handle received unknown tool name: {name}")
