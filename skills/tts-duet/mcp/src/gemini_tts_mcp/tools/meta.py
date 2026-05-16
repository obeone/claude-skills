"""``meta_health`` — readiness probe with cached model availability."""

from __future__ import annotations

import json
import os
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import mcp.types as types

from gemini_tts_mcp._version import __version__
from gemini_tts_mcp.client import AppContext


PROTOCOL_VERSION = "1"

PROBE_MODELS = (
    "gemini-2.5-flash-preview-tts",
    "gemini-2.5-pro-preview-tts",
)

CACHE_TTL_SECONDS = 3600

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

_OUTPUT_SCHEMA: dict[str, Any] = {
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
        "has_api_key": {"type": "boolean"},
        "model_availability": {"type": ["object", "null"]},
    },
    "additionalProperties": True,
}


DEFINITIONS: list[types.Tool] = [
    types.Tool(
        name="meta_health",
        description=(
            "Probe MCP readiness. Returns package / protocol / SDK "
            "versions and a cached per-model availability map."
        ),
        inputSchema=_INPUT_SCHEMA,
        outputSchema=_OUTPUT_SCHEMA,
    ),
]

TOOL_NAMES = {tool.name for tool in DEFINITIONS}


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unknown"


def _cache_path() -> Path:
    override = os.environ.get("GEMINI_TTS_MCP_CACHE_DIR")
    base = Path(override) if override else Path.home() / ".cache" / "gemini-tts-mcp"
    return base / "models.json"


def _read_cache(path: Path) -> dict[str, bool] | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    fetched_at = payload.get("fetched_at")
    models = payload.get("models")
    if not isinstance(fetched_at, (int, float)) or not isinstance(models, dict):
        return None
    if time.time() - float(fetched_at) > CACHE_TTL_SECONDS:
        return None
    return {str(k): bool(v) for k, v in models.items()}


def _write_cache(path: Path, models: dict[str, bool]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"fetched_at": time.time(), "models": models}),
            encoding="utf-8",
        )
    except OSError:
        # Cache is best-effort; never fail the probe on a write error.
        pass


def _probe_model_availability(app: AppContext) -> dict[str, bool] | None:
    listed: set[str] = set()
    try:
        for entry in app.client.models.list():
            name = getattr(entry, "name", None)
            if isinstance(name, str):
                listed.add(name.split("/")[-1])
    except Exception:  # noqa: BLE001
        return None
    return {model: model in listed for model in PROBE_MODELS}


async def handle(name: str, arguments: dict[str, Any], app: AppContext) -> dict[str, Any]:
    if name != "meta_health":
        raise ValueError(f"meta.handle received unknown tool name: {name}")

    cache_path = _cache_path()
    availability = _read_cache(cache_path)
    if availability is None:
        availability = _probe_model_availability(app)
        if availability is not None:
            _write_cache(cache_path, availability)

    return {
        "status": "ok",
        "mcp_version": _package_version("mcp"),
        "package_version": __version__,
        "protocol_version": PROTOCOL_VERSION,
        "sdk_version": _package_version("google-genai"),
        "has_api_key": app.has_api_key,
        "model_availability": availability,
    }
