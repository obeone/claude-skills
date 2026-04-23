"""End-to-end ``meta.health`` round-trip against the real stdio server.

Spawns ``python -m gemini_tts_mcp`` as a subprocess and drives it with
the official MCP Python client over stdio — matching how Claude Code
registers the server in production. This is the smallest honest
integration test we can ship for the skeleton.
"""

from __future__ import annotations

import json
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from gemini_tts_mcp._version import __version__


pytestmark = pytest.mark.asyncio


async def test_meta_health_roundtrip() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "gemini_tts_mcp"],
        env=None,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            assert "meta.health" in tool_names

            result = await session.call_tool("meta.health", {})

    # Low-level server serialises structured output both as
    # ``structuredContent`` (post-2025-06-18 clients) and as a
    # JSON-encoded text content block (older clients). Accept either.
    payload: dict[str, object] | None = None
    if getattr(result, "structuredContent", None):
        payload = result.structuredContent  # type: ignore[assignment]
    else:
        assert result.content, "expected at least one content block"
        first = result.content[0]
        text = getattr(first, "text", None)
        assert text, "expected text content for legacy-client fallback"
        payload = json.loads(text)

    assert isinstance(payload, dict)
    assert payload["status"] == "ok"
    assert payload["package_version"] == __version__
    assert payload["protocol_version"] == "1"
    assert payload["sdk_version"] == "stub"
    assert "mcp_version" in payload
    assert payload["model_availability"] is None
