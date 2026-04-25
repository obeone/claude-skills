"""Single auth boundary for the MCP server.

This module is the ONLY place in the repository allowed to call
``genai.Client()`` or read ``GEMINI_API_KEY`` / ``GOOGLE_API_KEY``. Tools
acquire the shared client through the lifespan context — instantiated
once per server process and surfaced via
``ctx.request_context.lifespan_context``.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp.server.lowlevel import Server


@dataclass
class AppContext:
    """Shared per-process resources passed to every tool handler."""

    client: Any
    has_api_key: bool


def _detect_api_key() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


def _build_client() -> Any:
    # Imported lazily so test fixtures monkeypatching ``google.genai.Client``
    # before the server starts take effect. Also keeps import errors
    # visible at first use rather than at module import time.
    from google import genai

    return genai.Client()


@asynccontextmanager
async def server_lifespan(_server: Server) -> AsyncIterator[AppContext]:
    """Instantiate the Gemini client once per server process."""

    client = _build_client()
    try:
        yield AppContext(client=client, has_api_key=_detect_api_key())
    finally:
        # google-genai exposes no explicit close in current SDK; let GC
        # reclaim the underlying transport.
        pass
