#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pyyaml>=6.0",
#     "mcp>=1.14,<2",
# ]
# ///
"""Generate a short audio preview for a single voice via the MCP.

Calls ``tts_preview_voice`` on the ``gemini-tts-mcp`` MCP; this script
never reads ``GEMINI_API_KEY`` / ``GOOGLE_API_KEY`` and never imports
``google-genai``. The MCP subprocess is responsible for the API call.

Output is written to ``$TMPDIR`` (or ``/tmp``) as MP3 when ``ffmpeg``
is available, otherwise WAV. ``--play`` opens the resulting file via
``afplay`` on macOS or ``xdg-open`` on Linux.
"""

from __future__ import annotations

import argparse
import base64
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import audio_io  # noqa: E402
from lib._safe_env import safe_env  # noqa: E402
from lib.config import load_user_config  # noqa: E402
from lib.mcp_client import (  # noqa: E402
    GeminiTTSMCPClient,
    MCPConnectionError,
    MCPToolError,
    resolve_mcp_command,
)
from lib.pricing import resolve_model  # noqa: E402

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEXT_PATH = SKILL_ROOT / "assets" / "preview_text.md"


def _load_default_text() -> str:
    """Return the bundled preview snippet, trimmed."""
    return DEFAULT_TEXT_PATH.read_text(encoding="utf-8").strip()


def _play(path: Path) -> None:
    """Open ``path`` in the platform's default audio player."""
    env = safe_env(for_mcp=False)
    if sys.platform == "darwin" and shutil.which("afplay"):
        subprocess.run(["afplay", str(path)], check=False, env=env)
    elif shutil.which("xdg-open"):
        subprocess.run(["xdg-open", str(path)], check=False, env=env)
    else:
        print(f"(no player found — file written to {path})", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate a short audio preview for a single voice via MCP.",
    )
    parser.add_argument("voice", help="Voice name (case-sensitive).")
    parser.add_argument("--text", help="Override the default preview snippet.")
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--model", default="flash")
    parser.add_argument("--play", action="store_true")
    args = parser.parse_args(argv)

    model = resolve_model(args.model)
    text = (args.text or _load_default_text()).strip()
    if not text:
        print("ERROR: preview text is empty.", file=sys.stderr)
        return 1

    tmp_dir = Path(os.environ.get("TMPDIR", "/tmp"))
    ts = time.strftime("%Y%m%d-%H%M%S")
    wav_path = tmp_dir / f"tts-preview-{args.voice}-{ts}.wav"
    mp3_path = tmp_dir / f"tts-preview-{args.voice}-{ts}.mp3"

    user_config = load_user_config()
    mcp_command = resolve_mcp_command(
        config=user_config.raw, env=dict(os.environ)
    )
    stderr_log = Path.home() / ".cache" / "tts-duet" / "mcp-stderr.log"

    try:
        with GeminiTTSMCPClient(command=mcp_command, stderr_log=stderr_log) as client:
            out = client.tts_preview_voice(
                voice=args.voice,
                text=text,
                model=model.id,
                seconds_hint=float(args.seconds) if args.seconds else None,
            )
    except (MCPConnectionError, MCPToolError) as exc:
        print(f"ERROR: MCP preview failed: {exc}", file=sys.stderr)
        return 5

    pcm_b64 = out.get("pcm_base64") or out.get("pcm_b64")
    if not pcm_b64:
        print("ERROR: MCP returned no audio payload.", file=sys.stderr)
        return 1
    pcm = base64.b64decode(pcm_b64)
    audio_io.pcm_to_wav(pcm, wav_path)

    final_path = wav_path
    if audio_io.has_ffmpeg():
        try:
            audio_io.wav_to_mp3(wav_path, mp3_path, keep_wav=False)
            final_path = mp3_path
        except RuntimeError as exc:
            print(f"WARN: MP3 transcode failed: {exc}", file=sys.stderr)
    else:
        print(audio_io.FFMPEG_MISSING_WARNING, file=sys.stderr)

    print(f"Preview written to {final_path} (~target {args.seconds}s advisory)")

    if args.play:
        _play(final_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
