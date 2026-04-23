"""Command-line entrypoint for the vendored MCP server.

This module hosts the argparse surface shared by ``python -m
gemini_tts_mcp`` and the ``gemini-tts-mcp`` console script. The default
mode (no flags) runs the stdio server; auxiliary flags are provided for
operator diagnostics.

``--dump-schemas`` is a stub in the skeleton — it emits an empty JSON
document so the future contract-test tooling can wire against the CLI
immediately. Worker-3 fills in real schema output in task #2.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from gemini_tts_mcp._version import __version__
from gemini_tts_mcp.server import PROTOCOL_VERSION, SERVER_NAME, run


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
            "Emit JSON Schema documents for every registered tool to stdout "
            "and exit. Skeleton: emits an empty object."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.protocol_version:
        print(PROTOCOL_VERSION)
        return 0

    if args.dump_schemas:
        # Task #2 will replace this with real per-tool schemas.
        json.dump({}, sys.stdout)
        sys.stdout.write("\n")
        return 0

    run()
    return 0
