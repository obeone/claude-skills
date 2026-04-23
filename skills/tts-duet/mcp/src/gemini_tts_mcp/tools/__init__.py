"""Tool registry for gemini-tts-mcp.

Each tool module exposes ``DEFINITIONS`` (a list of ``mcp.types.Tool``)
and a ``handle(name, arguments, app)`` coroutine. ``server.py`` aggregates
them into the low-level server's ``list_tools`` / ``call_tool`` registry.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

import mcp.types as types

from gemini_tts_mcp.client import AppContext
from gemini_tts_mcp.tools import meta, text, tts


Handler = Callable[[str, dict[str, Any], AppContext], Awaitable[dict[str, Any]]]


def all_definitions() -> list[types.Tool]:
    return [*tts.DEFINITIONS, *text.DEFINITIONS, *meta.DEFINITIONS]


HANDLERS: dict[str, Handler] = {
    **{name: tts.handle for name in tts.TOOL_NAMES},
    **{name: text.handle for name in text.TOOL_NAMES},
    **{name: meta.handle for name in meta.TOOL_NAMES},
}


__all__ = ["all_definitions", "HANDLERS", "Handler"]
