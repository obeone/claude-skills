#!/usr/bin/env python3
"""
Fake stdio MCP server for skill-side tests.

This server speaks the real MCP JSON-RPC protocol via
``mcp.server.lowlevel.Server`` (same code path as the production
``gemini-tts-mcp``) but returns canned responses — no ``google-genai``
imports, no network calls.

Failure injection
-----------------
Environment variables let tests drive specific fault paths:

``FAKE_MCP_FAIL_AFTER``
    Non-negative integer ``n``. The first ``n`` ``tts.generate_chunk``
    calls succeed; every call after returns a structured error with
    ``failure_reason="tts_chunk_failed"``. Combine with
    ``FAKE_MCP_FAIL_RETRYABLE`` to toggle the ``retryable`` bit.
``FAKE_MCP_FAIL_RETRYABLE``
    ``"1"`` / ``"true"`` (default: true) — the ``retryable`` bit sent
    on injected failures.
``FAKE_MCP_CRASH_AFTER``
    Non-negative integer ``n``. The server exits with code 1 *after*
    serving its ``n``-th ``tts.generate_chunk`` response, simulating a
    mid-session crash for ``test_mcp_crash_recovery``.
``FAKE_MCP_HEALTH_PROTOCOL``
    Override the ``protocol_version`` returned by ``meta.health``. Used
    to exercise the version-skew guard.
``FAKE_MCP_HEALTH_KEY_STATUS``
    Override the ``api_key_status`` field in ``meta.health`` (e.g.
    ``"missing"``). Defaults to ``"ok"``.
``FAKE_MCP_SCHEMAS_DIR``
    Path to a directory holding ``<tool>.json`` schema files. When set,
    the server advertises those schemas verbatim on ``tools/list`` —
    this is what keeps the fake honest against the real MCP.

The constants are also exposed as module-level callables so tests can
import and unit-test the handler logic directly.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

SERVER_NAME = "gemini-tts-mcp"
SERVER_VERSION = "fake-0.0.0"
DEFAULT_PROTOCOL_VERSION = "1"

TOOL_NAMES: tuple[str, ...] = (
    "tts.generate_chunk",
    "tts.preview_voice",
    "tts.count_tokens",
    "text.transform",
    "meta.health",
)

# 0.02 s of silence at 24 kHz 16-bit mono = 960 bytes. Large enough for
# the skill's WAV wrapper to emit a valid file; small enough to keep
# JSON-RPC payloads tiny.
_CANNED_PCM = b"\x00" * 960


def _env_int(name: str, default: int | None = None) -> int | None:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class _CallState:
    """Per-process counters for failure injection."""

    def __init__(self) -> None:
        self.generate_chunk_calls: int = 0
        self.preview_voice_calls: int = 0
        self.count_tokens_calls: int = 0
        self.text_transform_calls: int = 0
        self.health_calls: int = 0
        # Set when ``FAKE_MCP_CRASH_AFTER`` trips. The next tool call
        # received on stdio triggers ``os._exit(1)`` before it runs,
        # giving the client a guaranteed BrokenPipe on the *next*
        # ``generate_chunk`` (rather than relying on a timer race).
        self.crash_pending: bool = False

    def snapshot(self) -> dict[str, int]:
        return {
            "generate_chunk": self.generate_chunk_calls,
            "preview_voice": self.preview_voice_calls,
            "count_tokens": self.count_tokens_calls,
            "text_transform": self.text_transform_calls,
            "health": self.health_calls,
        }


STATE = _CallState()


def _load_recorded_schemas() -> dict[str, dict[str, Any]]:
    """Load schemas from ``FAKE_MCP_SCHEMAS_DIR`` if it is set."""
    dir_path = os.environ.get("FAKE_MCP_SCHEMAS_DIR")
    if not dir_path:
        return {}
    root = Path(dir_path)
    if not root.is_dir():
        return {}
    loaded: dict[str, dict[str, Any]] = {}
    for name in TOOL_NAMES:
        file_name = name.replace(".", "_") + ".json"
        candidate = root / file_name
        if candidate.is_file():
            try:
                loaded[name] = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
    return loaded


def _default_input_schemas() -> dict[str, dict[str, Any]]:
    """Conservative stand-ins used when no recorded schemas are provided."""
    return {
        "tts.generate_chunk": {
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "content": {"type": "string"},
                "voice_a": {"type": "string"},
                "voice_b": {"type": ["string", "null"]},
                "system_instruction": {"type": ["string", "null"]},
            },
            "required": ["model", "content", "voice_a"],
        },
        "tts.preview_voice": {
            "type": "object",
            "properties": {
                "voice": {"type": "string"},
                "text": {"type": "string"},
                "model": {"type": "string"},
            },
            "required": ["voice", "text", "model"],
        },
        "tts.count_tokens": {
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["model", "content"],
        },
        "text.transform": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "model": {"type": "string"},
                "temperature": {"type": "number", "default": 0.2},
                "max_output_tokens": {"type": "integer", "default": 8192},
            },
            "required": ["prompt", "model"],
            "additionalProperties": False,
        },
        "meta.health": {"type": "object", "properties": {}, "additionalProperties": False},
    }


def build_server() -> Server:
    """Assemble a low-level MCP server wired to the canned handlers."""
    recorded = _load_recorded_schemas()
    defaults = _default_input_schemas()

    def schema_for(tool: str) -> dict[str, Any]:
        return recorded.get(tool, defaults[tool])

    server: Server = Server(SERVER_NAME)

    @server.list_tools()  # type: ignore[misc]
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=name,
                description=f"Canned fake of {name}",
                inputSchema=schema_for(name),
            )
            for name in TOOL_NAMES
        ]

    @server.call_tool()  # type: ignore[misc]
    async def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "tts.generate_chunk":
            return handle_generate_chunk(arguments)
        if name == "tts.preview_voice":
            return handle_preview_voice(arguments)
        if name == "tts.count_tokens":
            return handle_count_tokens(arguments)
        if name == "text.transform":
            return handle_text_transform(arguments)
        if name == "meta.health":
            return handle_health(arguments)
        raise ValueError(f"Unknown tool: {name}")

    return server


# ---------------------------------------------------------------------------
# Handlers — exposed at module scope so tests can unit-test them without
# wiring up a full stdio server.
# ---------------------------------------------------------------------------


def handle_generate_chunk(arguments: dict[str, Any]) -> dict[str, Any]:
    # Honour a pending crash BEFORE incrementing the counter so the
    # client sees a BrokenPipe on the very next call after crash_after.
    if STATE.crash_pending:
        os._exit(1)
    STATE.generate_chunk_calls += 1
    fail_after = _env_int("FAKE_MCP_FAIL_AFTER")
    if fail_after is not None and STATE.generate_chunk_calls > fail_after:
        return {
            "failure_reason": "tts_chunk_failed",
            "retryable": _env_bool("FAKE_MCP_FAIL_RETRYABLE", True),
            "detail": "fake chunk failure injected via FAKE_MCP_FAIL_AFTER",
        }
    crash_after = _env_int("FAKE_MCP_CRASH_AFTER")
    response = {
        "pcm_base64": base64.b64encode(_CANNED_PCM).decode("ascii"),
        "sample_rate_hz": 24000,
        "bits_per_sample": 16,
        "channels": 1,
        "input_tokens": 10,
        "output_tokens": len(_CANNED_PCM) // 2,
    }
    if crash_after is not None and STATE.generate_chunk_calls >= crash_after:
        # Arm the crash for the NEXT call (after this response flushes).
        STATE.crash_pending = True
    return response


def handle_preview_voice(arguments: dict[str, Any]) -> dict[str, Any]:
    STATE.preview_voice_calls += 1
    return {
        "pcm_base64": base64.b64encode(_CANNED_PCM).decode("ascii"),
        "sample_rate_hz": 24000,
        "bits_per_sample": 16,
        "channels": 1,
    }


def handle_count_tokens(arguments: dict[str, Any]) -> dict[str, Any]:
    STATE.count_tokens_calls += 1
    content = arguments.get("content", "")
    # Deterministic approximation: 1 token per 4 characters, minimum 1.
    approx = max(1, len(content) // 4)
    return {"tokens": approx}


def handle_text_transform(arguments: dict[str, Any]) -> dict[str, Any]:
    STATE.text_transform_calls += 1
    prompt = arguments.get("prompt", "")
    # Return the prompt verbatim as "text" so director tests can assert
    # that prompt composition happens skill-side, not MCP-side.
    return {
        "text": f"[director-pass] {prompt}",
        "input_tokens": max(1, len(prompt) // 4),
        "output_tokens": max(1, len(prompt) // 4),
    }


def handle_health(arguments: dict[str, Any]) -> dict[str, Any]:
    STATE.health_calls += 1
    return {
        "ok": True,
        "package_version": SERVER_VERSION,
        "protocol_version": os.environ.get(
            "FAKE_MCP_HEALTH_PROTOCOL", DEFAULT_PROTOCOL_VERSION
        ),
        "api_key_status": os.environ.get("FAKE_MCP_HEALTH_KEY_STATUS", "ok"),
        "model_availability": {
            "gemini-2.5-flash-preview-tts": True,
            "gemini-2.5-pro-preview-tts": True,
        },
    }


async def _run() -> None:
    server = build_server()
    async with mcp.server.stdio.stdio_server() as (read, write):
        await server.run(
            read,
            write,
            InitializationOptions(
                server_name=SERVER_NAME,
                server_version=SERVER_VERSION,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
