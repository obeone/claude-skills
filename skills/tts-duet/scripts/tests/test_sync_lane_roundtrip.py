"""Sync-lane round-trip integration test (plan §9.2).

Spawns the fake MCP fixture via ``lib.mcp_client.GeminiTTSMCPClient``
on stdio, runs ``tts.preview_voice`` for one short utterance, decodes
the returned base64 PCM, and writes a WAV via
``lib.audio_io.pcm_to_wav``. We assert the file is non-empty and is a
real RIFF/WAVE container.

The whole test depends on worker-b's ``lib/mcp_client.py``; until that
lands, the import fails and the suite skips.
"""

from __future__ import annotations

import base64
import sys
import wave
from pathlib import Path

import pytest

mcp_client = pytest.importorskip(
    "lib.mcp_client",
    reason="lib.mcp_client not yet landed by worker-b (task #2)",
)
from lib import audio_io  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
FAKE_MCP = FIXTURES_DIR / "fake_mcp_server.py"


def _fake_mcp_command() -> list[str]:
    """Return a command line that runs the fake stdio MCP fixture."""
    return [sys.executable, str(FAKE_MCP)]


@pytest.fixture()
def stderr_log(tmp_path: Path) -> Path:
    return tmp_path / "mcp-stderr.log"


# ---------------------------------------------------------------------------
# Round-trip: spawn -> health -> preview_voice -> decode -> WAV on disk
# ---------------------------------------------------------------------------


def test_sync_lane_health_then_preview_voice_writes_wav(
    tmp_path: Path, stderr_log: Path
) -> None:
    cmd = _fake_mcp_command()
    with mcp_client.GeminiTTSMCPClient(command=cmd, stderr_log=stderr_log) as client:
        health = client.health()
        assert health.get("ok") is True
        out = client.tts_preview_voice(
            voice="Charon", text="Hello world", model="gemini-2.5-flash"
        )
    pcm_b64 = out.get("pcm_base64") or out.get("pcm_b64")
    assert pcm_b64, f"fake MCP returned no PCM payload: {out!r}"
    pcm = base64.b64decode(pcm_b64)
    assert pcm, "decoded PCM is empty"

    wav_path = tmp_path / "preview.wav"
    audio_io.pcm_to_wav(pcm, wav_path)

    assert wav_path.is_file()
    assert wav_path.stat().st_size > 44  # WAV header alone is 44 bytes
    with wave.open(str(wav_path), "rb") as reader:
        assert reader.getnchannels() == 1
        assert reader.getsampwidth() == 2
        assert reader.getframerate() == 24000
        assert reader.getnframes() > 0


def test_sync_lane_generate_chunk_round_trip(
    tmp_path: Path, stderr_log: Path
) -> None:
    cmd = _fake_mcp_command()
    with mcp_client.GeminiTTSMCPClient(command=cmd, stderr_log=stderr_log) as client:
        out = client.tts_generate_chunk(
            model="gemini-2.5-flash",
            content="A: hi\nB: hello",
            voice_a="Charon",
            voice_b="Aoede",
            system_instruction=None,
        )
    pcm_b64 = out.get("pcm_base64") or out.get("pcm_b64")
    assert pcm_b64
    pcm = base64.b64decode(pcm_b64)
    out_path = tmp_path / "chunk.wav"
    audio_io.pcm_to_wav(pcm, out_path)
    assert out_path.is_file()
    assert out_path.stat().st_size > 44


def test_sync_lane_does_not_read_api_keys(
    tmp_path: Path, stderr_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P1 invariant: instantiating the client + calling tools never
    touches GEMINI_API_KEY / GOOGLE_API_KEY in the parent process.

    We monkeypatch ``os.environ.get`` and ``os.environ.__getitem__`` to
    record any access to those keys.
    """
    import os

    hits: list[str] = []
    real_get = os.environ.get
    real_getitem = os.environ.__getitem__

    def _trap_get(key, default=None):  # type: ignore[no-untyped-def]
        if key in {"GEMINI_API_KEY", "GOOGLE_API_KEY"}:
            hits.append(f"get:{key}")
        return real_get(key, default)

    def _trap_getitem(key):  # type: ignore[no-untyped-def]
        if key in {"GEMINI_API_KEY", "GOOGLE_API_KEY"}:
            hits.append(f"getitem:{key}")
        return real_getitem(key)

    monkeypatch.setattr(os.environ, "get", _trap_get)
    monkeypatch.setattr(os.environ, "__getitem__", _trap_getitem)

    cmd = _fake_mcp_command()
    with mcp_client.GeminiTTSMCPClient(command=cmd, stderr_log=stderr_log) as client:
        client.health()

    assert not hits, (
        "skill-side code touched API-key env vars during sync lane: "
        f"{hits}"
    )
