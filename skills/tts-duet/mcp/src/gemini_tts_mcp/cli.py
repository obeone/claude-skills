"""Command-line entrypoint for the vendored MCP server.

The default mode (no flags) runs the stdio server; auxiliary flags are
provided for operator diagnostics and contract-test fixture generation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from gemini_tts_mcp._version import __version__
from gemini_tts_mcp.server import PROTOCOL_VERSION, SERVER_NAME, run
from gemini_tts_mcp.tools import all_definitions


SCHEMA_FIXTURES_DIR = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "schemas"
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=SERVER_NAME,
        description="Gemini TTS MCP server (vendored for the tts-duet skill).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=__version__,
    )
    parser.add_argument(
        "--protocol-version",
        action="store_true",
        help="Print the MCP protocol version this server implements and exit.",
    )
    parser.add_argument(
        "--dump-schemas",
        action="store_true",
        help=(
            "Write one JSON Schema document per registered tool to "
            f"{SCHEMA_FIXTURES_DIR} and print the file list to stdout."
        ),
    )
    parser.add_argument(
        "--schemas-dir",
        type=Path,
        default=None,
        help="Override the fixture directory used by --dump-schemas.",
    )
    return parser


def _slug(tool_name: str) -> str:
    return tool_name.replace(".", "_")


def _tool_payload(tool: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": tool.inputSchema,
    }
    output_schema = getattr(tool, "outputSchema", None)
    if output_schema is not None:
        payload["outputSchema"] = output_schema
    meta = getattr(tool, "_meta", None) or getattr(tool, "meta", None)
    if meta:
        payload["_meta"] = meta
    return payload


def dump_schemas(target_dir: Path) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for tool in all_definitions():
        path = target_dir / f"{_slug(tool.name)}.json"
        path.write_text(
            json.dumps(_tool_payload(tool), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.protocol_version:
        print(PROTOCOL_VERSION)
        return 0

    if args.dump_schemas:
        target = args.schemas_dir or SCHEMA_FIXTURES_DIR
        written = dump_schemas(target)
        for path in written:
            print(path)
        return 0

    run()
    return 0
