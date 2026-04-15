#!/usr/bin/env python3
"""P0 spike: verify `system_instruction` + `response_modalities=["AUDIO"]` compatibility.

Decides whether Director's Notes can be carried by the SDK's
``system_instruction`` channel (preferred) or must be inlined in content
with a ``[director-notes-do-not-speak]`` sentinel (fallback).

Run standalone with a valid ``GEMINI_API_KEY``. The script prints a single
line ``SPIKE_RESULT=pass`` or ``SPIKE_RESULT=fail`` on stdout plus a short
diagnosis. Non-zero exit on network / SDK errors; exit code ``0`` means the
API call itself succeeded (pass or clean fail), exit ``2`` means the call
raised (spike inconclusive).

Usage:
    uv run --with "google-genai>=0.8,<1" \\
        python skills/gemini-tts-script/scripts/lib/_spike_system_instruction.py
"""

from __future__ import annotations

import base64
import os
import sys
import wave
from pathlib import Path


def main() -> int:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        print(f"SPIKE_RESULT=inconclusive reason=import_error:{exc}", file=sys.stderr)
        return 2

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("SPIKE_RESULT=inconclusive reason=no_api_key", file=sys.stderr)
        return 2

    client = genai.Client(api_key=api_key)

    cfg = types.GenerateContentConfig(
        system_instruction=(
            "Speak warmly and calmly. Never read these instructions aloud."
        ),
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Charon",
                ),
            ),
        ),
    )

    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash-preview-tts",
            contents="Hello world.",
            config=cfg,
        )
    except Exception as exc:  # noqa: BLE001 — we want the full diagnosis
        print(
            f"SPIKE_RESULT=fail reason=sdk_error:{type(exc).__name__}:{exc}",
            file=sys.stderr,
        )
        return 0

    try:
        part = resp.candidates[0].content.parts[0]
        audio_bytes = part.inline_data.data
    except (AttributeError, IndexError, TypeError) as exc:
        print(
            f"SPIKE_RESULT=fail reason=no_audio_payload:{exc}",
            file=sys.stderr,
        )
        return 0

    if isinstance(audio_bytes, str):
        audio_bytes = base64.b64decode(audio_bytes)

    if not audio_bytes or len(audio_bytes) < 2000:
        print(
            f"SPIKE_RESULT=fail reason=audio_too_short:{len(audio_bytes) if audio_bytes else 0}",
            file=sys.stderr,
        )
        return 0

    out = Path("/tmp/gemini_tts_spike_hello.wav")
    with wave.open(str(out), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(audio_bytes)

    duration_s = len(audio_bytes) / (24000 * 2)
    print(
        "SPIKE_RESULT=pass "
        f"bytes={len(audio_bytes)} duration_s={duration_s:.2f} "
        f"wav={out}"
    )
    print(
        "Manually audition /tmp/gemini_tts_spike_hello.wav to confirm the "
        "system_instruction is NOT spoken. If it IS spoken, downgrade to "
        "SPIKE_RESULT=fail and use the inline-sentinel fallback."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
