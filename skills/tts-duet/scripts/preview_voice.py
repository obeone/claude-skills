#!/usr/bin/env python3
"""Generate a short preview clip for a single voice.

Used for the pre-tag audition checklist (§3.4). Defaults to the
``flash`` model (cheaper) and the bundled ``assets/preview_text.md``
snippet. Output is written to ``$TMPDIR`` (or ``/tmp``) as MP3 when
``ffmpeg`` is available, otherwise WAV. ``--play`` opens the resulting
file via ``afplay`` on macOS or ``xdg-open`` on Linux so operators can
audition without copy-pasting paths.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import audio_io  # noqa: E402
from lib.pricing import resolve_model  # noqa: E402

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEXT_PATH = SKILL_ROOT / "assets" / "preview_text.md"


def _load_default_text() -> str:
    """Return the bundled preview snippet, trimmed."""
    return DEFAULT_TEXT_PATH.read_text(encoding="utf-8").strip()


def _require_api_key() -> str:
    """Return the Gemini API key or exit 1 with a clear message."""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        print(
            "ERROR: GEMINI_API_KEY / GOOGLE_API_KEY not set; cannot preview.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return key


def _import_genai() -> tuple[object, object]:
    """Import google-genai or exit 1 with an install hint."""
    try:
        from google import genai  # type: ignore[import-not-found]
        from google.genai import types  # type: ignore[import-not-found]
    except ImportError:
        print(
            "ERROR: google-genai is not installed. "
            "Install with: uv pip install -r scripts/requirements.txt",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return genai, types


def _play(path: Path) -> None:
    """Open ``path`` in the platform's default audio player."""
    if sys.platform == "darwin" and shutil.which("afplay"):
        subprocess.run(["afplay", str(path)], check=False)
    elif shutil.which("xdg-open"):
        subprocess.run(["xdg-open", str(path)], check=False)
    else:
        print(f"(no player found — file written to {path})", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. See module docstring."""
    parser = argparse.ArgumentParser(
        description="Generate a short audio preview for a single voice.",
    )
    parser.add_argument("voice", help="Voice name (case-sensitive).")
    parser.add_argument(
        "--text",
        help="Override the default preview snippet with custom text.",
    )
    parser.add_argument(
        "--seconds",
        type=int,
        default=30,
        help="Advisory target length. The SDK is not asked to truncate.",
    )
    parser.add_argument(
        "--model",
        default="flash",
        help="Model alias or full ID. Default: flash (cheaper).",
    )
    parser.add_argument(
        "--play",
        action="store_true",
        help="Open the resulting file after generation.",
    )
    args = parser.parse_args(argv)

    _require_api_key()
    genai, types = _import_genai()

    model = resolve_model(args.model)
    text = (args.text or _load_default_text()).strip()
    if not text:
        print("ERROR: preview text is empty.", file=sys.stderr)
        return 1

    tmp_dir = Path(os.environ.get("TMPDIR", "/tmp"))
    ts = time.strftime("%Y%m%d-%H%M%S")
    wav_path = tmp_dir / f"tts-preview-{args.voice}-{ts}.wav"
    mp3_path = tmp_dir / f"tts-preview-{args.voice}-{ts}.mp3"

    speech_config = types.SpeechConfig(  # type: ignore[attr-defined]
        voice_config=types.VoiceConfig(  # type: ignore[attr-defined]
            prebuilt_voice_config=types.PrebuiltVoiceConfig(  # type: ignore[attr-defined]
                voice_name=args.voice,
            )
        )
    )
    config = types.GenerateContentConfig(  # type: ignore[attr-defined]
        response_modalities=["AUDIO"],
        speech_config=speech_config,
    )

    client = genai.Client()  # type: ignore[attr-defined]
    response = client.models.generate_content(  # type: ignore[attr-defined]
        model=model.id,
        contents=text,
        config=config,
    )

    pcm: bytes = b""
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                pcm += inline.data
    if not pcm:
        print("ERROR: no audio returned by the model.", file=sys.stderr)
        return 1

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

    advisory = args.seconds
    print(f"Preview written to {final_path} (~target {advisory}s advisory)")

    if args.play:
        _play(final_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
