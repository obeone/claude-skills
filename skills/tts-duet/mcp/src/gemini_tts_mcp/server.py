"""Stdio MCP server for gemini-tts-mcp.

Wires the lifespan-managed Gemini client to the tool registry under
``gemini_tts_mcp.tools``. The handler dispatches by name into the
per-module ``handle()`` coroutine; structured outputs are validated by
the low-level server against each tool's ``outputSchema``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from gemini_tts_mcp._version import __version__
from gemini_tts_mcp.client import AppContext, server_lifespan
from gemini_tts_mcp.tools import HANDLERS, all_definitions

SERVER_NAME = "gemini-tts-mcp"
PROTOCOL_VERSION = "1"


def build_server() -> Server:
    """Create and configure the low-level MCP server instance."""

    server: Server = Server(SERVER_NAME, lifespan=server_lifespan)

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return all_definitions()

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = HANDLERS.get(name)
        if handler is None:
            raise ValueError(f"Unknown tool: {name}")
        ctx = server.request_context
        app: AppContext = ctx.lifespan_context  # type: ignore[assignment]
        return await handler(name, arguments or {}, app)

    return server


async def _run_async() -> None:
    server = build_server()
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name=SERVER_NAME,
                server_version=__version__,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def run() -> None:
    """Entrypoint: run the stdio server until the client disconnects."""

    asyncio.run(_run_async())
