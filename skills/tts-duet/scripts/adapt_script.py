#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pyyaml>=6.0",
#     "mcp>=1.14,<2",
#     "coloredlogs>=15.0",
# ]
# ///
"""Adaptation pre-pass CLI for the ``tts-duet`` skill.

Turns raw input text (article, transcript, paper, notes, ...) into a
runnable Speaker A / B (or mono / interview) script that downstream
``generate_tts.py`` can consume. Two backends mirror ``--director``:

- ``agent`` — the calling agent does it locally; this script writes a
  handoff prompt + input snapshot + ``HANDOFF.md`` and exits ``0`` with
  ``status=awaiting_adaptation``.
- ``gemini`` — the script calls the MCP ``text.transform`` tool and
  writes the adapted script to ``--output``.

Exit codes
----------
- ``0`` success.
- ``1`` bad input (missing file, missing flag, ...).
- ``2`` reserved (no cost gate — text.transform is cheap).
- ``3`` MCP call failed.
- ``4`` reserved.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.adaptation import auto_adapt, compose_prompt  # noqa: E402
from lib.config import (  # noqa: E402
    VALID_ADAPTATION_BACKENDS,
    VALID_SHAPES,
    UserConfig,
    load_user_config,
)
from lib.mcp_client import (  # noqa: E402
    GeminiTTSMCPClient,
    MCPConnectionError,
    MCPToolError,
    resolve_mcp_command,
)

LOG = logging.getLogger("adapt_script")


def _setup_logging(level: int = logging.INFO) -> None:
    """Install coloredlogs if available, fall back to stdlib otherwise."""
    try:
        import coloredlogs  # type: ignore[import-not-found]

        coloredlogs.install(level=level, logger=LOG)
    except ImportError:
        logging.basicConfig(level=level)


def _build_parser(user_config: UserConfig) -> argparse.ArgumentParser:
    """Build the argparse parser, seeded with user-config defaults."""
    parser = argparse.ArgumentParser(
        description=(
            "Adapt raw text into a runnable Speaker-A/B / mono / "
            "interview script for tts-duet."
        )
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to the raw input text file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Destination path for the adapted script. Required when "
            "--backend gemini."
        ),
    )
    parser.add_argument(
        "--backend",
        choices=sorted(VALID_ADAPTATION_BACKENDS),
        default=user_config.adaptation.backend,
        help=(
            "Which backend produces the adapted script. Default from "
            "~/.config/tts-duet/config.yaml (adaptation.backend)."
        ),
    )
    parser.add_argument(
        "--shape",
        choices=sorted(VALID_SHAPES),
        default=user_config.shape,
        help="Target script shape. Default from user config.",
    )
    parser.add_argument(
        "--language",
        default=user_config.language,
        help=(
            "Output language: 'auto' (match input) or any BCP-47 tag. "
            "Default from user config."
        ),
    )
    parser.add_argument(
        "--target-duration",
        dest="target_duration_s",
        required=True,
        type=float,
        help="Target spoken duration in seconds.",
    )
    parser.add_argument(
        "--style",
        default=None,
        help="Optional free-form style hint, passed verbatim to the prompt.",
    )
    parser.add_argument(
        "--job-dir",
        type=Path,
        help="Job directory; required when --backend agent.",
    )
    parser.add_argument(
        "--model",
        default=user_config.adaptation.model or user_config.director.model,
        help=(
            "Gemini model ID for text.transform. Default from "
            "adaptation.model in user config."
        ),
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=user_config.adaptation.temperature,
        help="Sampling temperature for text.transform. Default: 0.3.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompts.",
    )
    return parser


def _write_status(
    job_dir: Path,
    status: str,
    **fields: str,
) -> None:
    """Write a ``status`` file shaped like ``generate_tts.py``."""
    lines = [f"status={status}"]
    lines.extend(f"{k}={v}" for k, v in fields.items())
    (job_dir / "status").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_agent_handoff(
    *,
    args: argparse.Namespace,
    raw_input: str,
) -> int:
    """Compose an adaptation prompt to the job dir and stop.

    Writes ``adaptation-prompt.md``, ``adaptation-input.md`` and
    ``HANDOFF.md`` to ``args.job_dir`` so the calling agent can take
    over the rewrite. The downstream pipeline expects the calling agent
    to write ``adapted-script.md`` to the job dir.
    """
    if args.job_dir is None:
        print(
            "ERROR: --backend agent requires --job-dir",
            file=sys.stderr,
        )
        return 1

    job_dir: Path = args.job_dir
    try:
        job_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"ERROR: could not create --job-dir: {exc}", file=sys.stderr)
        return 1

    prompt = compose_prompt(
        raw_input=raw_input,
        shape=args.shape,
        language=args.language,
        target_duration_s=args.target_duration_s,
        style=args.style,
    )

    handoff_text = (
        "# Adaptation handoff (agent mode)\n"
        "\n"
        "The skill stopped after composing an adaptation-pass prompt. "
        "To continue:\n"
        "\n"
        "1. Read `adaptation-prompt.md` and produce an adapted script "
        "that follows the strict output format described in that "
        "prompt (one turn per line, prefixed with `Speaker A:`, "
        "`Speaker B:` or `Mono:`; no preamble, no fences).\n"
        "\n"
        "2. Save the adapted script to `adapted-script.md` in this "
        "directory.\n"
        "\n"
        "3. Continue with the standard tts-duet pipeline against "
        "`adapted-script.md` (e.g. run the director pass, then "
        "generate audio).\n"
    )

    try:
        (job_dir / "adaptation-prompt.md").write_text(prompt, encoding="utf-8")
        (job_dir / "adaptation-input.md").write_text(raw_input, encoding="utf-8")
        (job_dir / "HANDOFF.md").write_text(handoff_text, encoding="utf-8")
    except OSError as exc:
        print(f"ERROR: could not write adaptation handoff: {exc}", file=sys.stderr)
        return 1

    _write_status(
        job_dir,
        "awaiting_adaptation",
        handoff="adaptation-prompt.md",
    )
    print(
        f"Adaptation handoff ready: {job_dir / 'HANDOFF.md'}",
        file=sys.stdout,
    )
    return 0


def _run_gemini_backend(
    *,
    args: argparse.Namespace,
    user_config: UserConfig,
    raw_input: str,
) -> int:
    """Call the MCP ``text.transform`` tool and write the adapted script."""
    if args.output is None:
        print(
            "ERROR: --backend gemini requires --output",
            file=sys.stderr,
        )
        return 1

    output_path: Path = args.output
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"ERROR: could not create output parent: {exc}", file=sys.stderr)
        return 1

    mcp_command = resolve_mcp_command(config=user_config.raw)
    stderr_log: Path | None = None
    if args.job_dir is not None:
        try:
            args.job_dir.mkdir(parents=True, exist_ok=True)
            stderr_log = args.job_dir / "mcp-stderr.log"
            stderr_log.touch(exist_ok=True)
        except OSError as exc:
            LOG.debug("could not prepare MCP stderr log: %s", exc)
            stderr_log = None

    try:
        with GeminiTTSMCPClient(
            command=mcp_command, stderr_log=stderr_log
        ) as client:
            result = auto_adapt(
                raw_input=raw_input,
                client=client,
                model=args.model,
                shape=args.shape,
                language=args.language,
                target_duration_s=args.target_duration_s,
                style=args.style,
                temperature=args.temperature,
                max_output_tokens=user_config.adaptation.max_output_tokens,
            )
    except (MCPConnectionError, MCPToolError) as exc:
        print(f"ERROR: MCP adaptation call failed: {exc}", file=sys.stderr)
        return 3

    try:
        output_path.write_text(result.text, encoding="utf-8")
    except OSError as exc:
        print(f"ERROR: could not write adapted script: {exc}", file=sys.stderr)
        return 1

    meta_path = output_path.with_suffix(output_path.suffix + ".meta.json")
    meta: dict[str, Any] = {
        "model": result.model_id or args.model,
        "target_duration_s": args.target_duration_s,
        "shape": args.shape,
        "language": args.language,
        "input_tokens_est": result.input_tokens,
        "output_tokens_est": result.output_tokens,
    }
    try:
        meta_path.write_text(
            json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8"
        )
    except OSError as exc:
        LOG.debug("could not write meta sidecar: %s", exc)

    print(f"Adapted script written: {output_path}", file=sys.stdout)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    _setup_logging()
    user_config = load_user_config()
    parser = _build_parser(user_config)
    args = parser.parse_args(argv)

    input_path: Path = args.input
    if not input_path.is_file():
        print(f"ERROR: --input not found: {input_path}", file=sys.stderr)
        return 1
    try:
        raw_input = input_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"ERROR: could not read --input: {exc}", file=sys.stderr)
        return 1

    if args.backend == "agent":
        rc = _run_agent_handoff(args=args, raw_input=raw_input)
    elif args.backend == "gemini":
        rc = _run_gemini_backend(
            args=args, user_config=user_config, raw_input=raw_input
        )
    else:  # pragma: no cover — argparse keeps choices in sync
        print(f"ERROR: unsupported --backend: {args.backend}", file=sys.stderr)
        rc = 1

    return rc


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
