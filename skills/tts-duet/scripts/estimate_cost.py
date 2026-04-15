#!/usr/bin/env python3
"""Estimate the cost and duration of a TTS generation offline.

Default mode is **offline heuristic**: uses words-per-minute to derive
duration, and the SSOT values in :mod:`lib.pricing` to derive cost.
``--with-api`` opts into calling ``client.models.count_tokens`` for a
precise input-token figure; this is the only branch that requires
``GEMINI_API_KEY``. ``--json`` emits a machine-readable document that
always includes the key ``tokens_per_sec_estimate_band_pct`` so the
caller knows how wide the uncertainty band is (see §3.3).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Allow running as a stand-alone script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.pricing import (  # noqa: E402  (path injection above)
    ESTIMATE_BAND_PCT,
    OUTPUT_TOKENS_PER_SECOND,
    WORDS_PER_MINUTE_HEURISTIC,
    estimate_cost_usd,
    estimate_duration_seconds,
    estimate_output_tokens,
    resolve_model,
)
from lib.script_parser import parse_script, to_model_content  # noqa: E402


def _count_tokens_via_api(model_id: str, content: str) -> int | None:
    """Call ``client.models.count_tokens`` if the SDK and key are available.

    Parameters
    ----------
    model_id : str
        Full Gemini model identifier.
    content : str
        Rendered model content string.

    Returns
    -------
    int or None
        Token count, or ``None`` if the SDK import / auth fails. In
        that case callers should fall back to the heuristic.
    """
    try:
        from google import genai  # type: ignore[import-not-found]
    except ImportError:
        print(
            "WARN: google-genai not installed; --with-api ignored",
            file=sys.stderr,
        )
        return None
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        print(
            "WARN: GEMINI_API_KEY / GOOGLE_API_KEY unset; --with-api ignored",
            file=sys.stderr,
        )
        return None
    try:
        client = genai.Client()
        response = client.models.count_tokens(model=model_id, contents=content)
        return int(getattr(response, "total_tokens", 0) or 0)
    except Exception as exc:  # noqa: BLE001 — pragmatic: API churn
        print(f"WARN: count_tokens failed ({exc}); falling back", file=sys.stderr)
        return None


def _heuristic_input_tokens(content: str) -> int:
    """Rough 4-chars-per-token heuristic for input size.

    Only used when ``--with-api`` is not set.
    """
    if not content:
        return 0
    return max(1, len(content) // 4)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. See module docstring."""
    parser = argparse.ArgumentParser(
        description="Estimate cost and duration for a TTS script (offline by default).",
    )
    parser.add_argument("--script", required=True, help="Path to the script file.")
    parser.add_argument(
        "--model",
        default="pro",
        help="Model alias or full Gemini model ID. Default: pro.",
    )
    parser.add_argument(
        "--with-api",
        action="store_true",
        help="Opt into count_tokens API call for exact input-token count.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON (machine-readable).",
    )
    args = parser.parse_args(argv)

    script_path = Path(args.script)
    parsed = parse_script(script_path)
    content = to_model_content(parsed)
    model = resolve_model(args.model)

    transcript_for_duration = "\n".join(turn.text for turn in parsed.turns)
    duration_s = estimate_duration_seconds(transcript_for_duration)
    output_tokens = estimate_output_tokens(duration_s)

    if args.with_api:
        api_tokens = _count_tokens_via_api(model.id, content)
        input_tokens = (
            api_tokens if api_tokens is not None
            else _heuristic_input_tokens(content)
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
        print(
            f"Input tokens : {input_tokens} "
            f"({input_source})"
        )
        print(f"Output tokens: {output_tokens} "
              f"(~{OUTPUT_TOKENS_PER_SECOND} tok/s, ±{ESTIMATE_BAND_PCT}%)")
        print(f"Cost estimate: ${cost_usd:.4f} USD (±{ESTIMATE_BAND_PCT}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
