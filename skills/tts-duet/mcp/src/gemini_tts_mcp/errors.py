"""Structured error helpers for tool returns.

Every MCP tool returns ``{failure_reason, retryable, detail}`` dicts on
failure rather than raising — the skill-side ``mcp_client.py`` branches
on ``failure_reason`` to drive retry / backoff logic. Returning a
structured error preserves the ``retryable`` bit through the JSON-RPC
boundary; raising would surface as a generic ``McpError`` and lose it.
"""

from __future__ import annotations

from typing import Any


def _error(failure_reason: str, *, retryable: bool, detail: str) -> dict[str, Any]:
    return {
        "failure_reason": failure_reason,
        "retryable": retryable,
        "detail": detail,
    }


def tts_chunk_failed(*, retryable: bool, detail: str) -> dict[str, Any]:
    return _error("tts_chunk_failed", retryable=retryable, detail=detail)


def text_transform_failed(*, retryable: bool, detail: str) -> dict[str, Any]:
    return _error("text_transform_failed", retryable=retryable, detail=detail)


def upstream_break(detail: str) -> dict[str, Any]:
    return _error("upstream_break", retryable=False, detail=detail)


def bad_input(detail: str) -> dict[str, Any]:
    return _error("bad_input", retryable=False, detail=detail)
