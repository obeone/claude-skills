#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pyyaml>=6.0",
#     "mcp>=1.14,<2",
# ]
# ///
"""Estimate cost and duration for a TTS script (offline by default).

Default mode is **offline heuristic**. ``--with-api`` opts into an
MCP round-trip for a precise ``tts_count_tokens`` figure; if the MCP
command does not resolve to a reachable binary, the script warns on
stderr and falls back to the heuristic (exit 0).

This script never reads ``GEMINI_API_KEY`` / ``GOOGLE_API_KEY`` and
never imports ``google-genai`` — the MCP is the only Gemini-facing
component.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.config import load_user_config  # noqa: E402
from lib.mcp_client import (  # noqa: E402
    GeminiTTSMCPClient,
    MCPConnectionError,
    MCPToolError,
    resolve_mcp_command,
)
from lib.pricing import (  # noqa: E402
    ESTIMATE_BAND_PCT,
    OUTPUT_TOKENS_PER_SECOND,
    WORDS_PER_MINUTE_HEURISTIC,
    estimate_cost_usd,
    estimate_duration_seconds,
    estimate_output_tokens,
    resolve_model,
)
from lib.script_parser import parse_script, to_model_content  # noqa: E402


def _heuristic_input_tokens(content: str) -> int:
    """Rough 4-chars-per-token heuristic for input size."""
    if not content:
        return 0
    return max(1, len(content) // 4)


def _count_tokens_via_mcp(
    model_id: str, content: str, mcp_command: list[str]
) -> int | None:
    """Invoke ``tts_count_tokens`` via the MCP.

    Returns
    -------
    int or None
        Token count on success. ``None`` if the MCP cannot be reached
        or the tool call fails.
    """
    # Guard on the MCP binary being resolvable before paying the spawn
    # cost. When using the vendored ``uvx`` fallback we still want to
    # warn if ``uvx`` itself is missing.
    first = mcp_command[0]
    if not shutil.which(first):
        print(
            f"WARN: --with-api requested but {first!r} not available on $PATH; "
            "falling back to heuristic",
            file=sys.stderr,
        )
        return None

    stderr_log = Path.home() / ".cache" / "tts-duet" / "mcp-stderr.log"
    try:
        with GeminiTTSMCPClient(command=mcp_command, stderr_log=stderr_log) as client:
            out = client.tts_count_tokens(model=model_id, content=content)
    except (MCPConnectionError, MCPToolError) as exc:
        print(
            f"WARN: count_tokens via MCP failed ({exc}); falling back",
            file=sys.stderr,
        )
        return None

    tokens = out.get("total_tokens") or out.get("tokens")
    try:
        return int(tokens) if tokens is not None else None
    except (TypeError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Estimate cost and duration for a TTS script (offline by default).",
    )
    parser.add_argument("--script", required=True)
    parser.add_argument("--model", default="pro")
    parser.add_argument("--with-api", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    script_path = Path(args.script)
    parsed = parse_script(script_path)
    content = to_model_content(parsed)
    model = resolve_model(args.model)

    transcript_for_duration = "\n".join(turn.text for turn in parsed.turns)
    duration_s = estimate_duration_seconds(transcript_for_duration)
    output_tokens = estimate_output_tokens(duration_s)

    if args.with_api:
        user_config = load_user_config()
        mcp_command = resolve_mcp_command(
            config=user_config.raw, env=dict(os.environ)
        )
        api_tokens = _count_tokens_via_mcp(model.id, content, mcp_command)
        input_tokens = (
            api_tokens if api_tokens is not None else _heuristic_input_tokens(content)
        )
        input_source = "api" if api_tokens is not None else "heuristic"
    else:
        input_tokens = _heuristic_input_tokens(content)
        input_source = "heuristic"

    cost_usd = estimate_cost_usd(model, input_tokens, output_tokens)

    payload: dict[str, Any] = {
        "script": str(script_path),
        "model": {
            "alias": model.name,
            "id": model.id,
            "input_usd_per_1m": model.input_usd_per_1m,
            "output_usd_per_1m": model.output_usd_per_1m,
        },
        "mode": parsed.mode,
        "turn_count": len(parsed.turns),
        "duration_seconds": round(duration_s, 3),
        "input_tokens": input_tokens,
        "input_tokens_source": input_source,
        "output_tokens": output_tokens,
        "cost_usd": round(cost_usd, 6),
        "words_per_minute_heuristic": WORDS_PER_MINUTE_HEURISTIC,
        "output_tokens_per_second": OUTPUT_TOKENS_PER_SECOND,
        "tokens_per_sec_estimate_band_pct": ESTIMATE_BAND_PCT,
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Script       : {payload['script']}")
        print(f"Model        : {model.name} ({model.id})")
        print(f"Mode         : {parsed.mode}  ({len(parsed.turns)} turns)")
        print(f"Duration     : {duration_s:.1f} s (heuristic, {WORDS_PER_MINUTE_HEURISTIC} wpm)")
        print(f"Input tokens : {input_tokens} ({input_source})")
        print(
            f"Output tokens: {output_tokens} "
            f"(~{OUTPUT_TOKENS_PER_SECOND} tok/s, ±{ESTIMATE_BAND_PCT}%)"
        )
        print(f"Cost estimate: ${cost_usd:.4f} USD (±{ESTIMATE_BAND_PCT}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
