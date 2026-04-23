"""Stdio MCP server skeleton for gemini-tts-mcp.

Only ``meta.health`` is wired in this skeleton; the ``tts.*`` and
``text.transform`` tools land in the next commit (task #2). The
``sdk_version`` field is stubbed here — worker-3 will replace it with
``importlib.metadata.version("google-genai")`` once the real Gemini
client is introduced.
"""

from __future__ import annotations

import asyncio
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from gemini_tts_mcp._version import __version__

SERVER_NAME = "gemini-tts-mcp"
PROTOCOL_VERSION = "1"

META_HEALTH_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

META_HEALTH_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "status",
        "mcp_version",
        "package_version",
        "protocol_version",
        "sdk_version",
        "model_availability",
    ],
    "properties": {
        "status": {"type": "string", "enum": ["ok", "error"]},
        "mcp_version": {"type": "string"},
        "package_version": {"type": "string"},
        "protocol_version": {"type": "string"},
        "sdk_version": {"type": "string"},
        "model_availability": {"type": ["object", "null"]},
    },
}


def _mcp_sdk_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("mcp")
    except PackageNotFoundError:
        return "unknown"


def build_server() -> Server:
    """Create and configure the low-level MCP server instance."""

    server: Server = Server(SERVER_NAME)

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="meta.health",
                description=(
                    "Probe MCP readiness. Returns package / protocol / SDK "
                    "versions and (once implemented) per-model availability."
                ),
                inputSchema=META_HEALTH_INPUT_SCHEMA,
                outputSchema=META_HEALTH_OUTPUT_SCHEMA,
            ),
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "meta.health":
            return {
                "status": "ok",
                "mcp_version": _mcp_sdk_version(),
                "package_version": __version__,
                "protocol_version": PROTOCOL_VERSION,
                "sdk_version": "stub",
                "model_availability": None,
            }
        raise ValueError(f"Unknown tool: {name}")

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
