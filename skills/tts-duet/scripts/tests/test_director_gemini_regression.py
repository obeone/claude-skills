"""Gemini director-mode regression test.

Pins the wiring between ``generate_tts._run_pipeline`` and
``lib.director.auto_direct``: when ``--director gemini`` runs, the
pipeline must

- spawn an MCP client and call ``text_transform`` exactly once before
  the chunk loop,
- replace the in-memory script with the rewritten output, and
- stamp ``config.json`` with ``director.ran=True`` and
  ``director.backend="gemini"``.

We swap ``GeminiTTSMCPClient`` with a recording stub that doubles as
both the director-pass client AND the chunk-loop client. The chunk
loop calls ``meta_health`` then ``tts_generate_chunk``; we serve canned
PCM for the latter so the pipeline reaches the ``done`` status.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("yaml")
pytest.importorskip("mcp")

import generate_tts  # noqa: E402


# 0.02 s of silence at 24 kHz, 16-bit mono — enough for the WAV
# wrapper to emit a valid file.
_CANNED_PCM = b"\x00" * 960
_PCM_B64 = base64.b64encode(_CANNED_PCM).decode("ascii")


SHORT_SCRIPT = """## Director's Notes
warm.

Speaker A: hi.
Speaker B: hello.
"""

REWRITTEN_SCRIPT = """## Director's Notes
[enriched] warm tone, slow pace.

## Transcript
Speaker A: [enriched] hi.
Speaker B: [enriched] hello.
"""


class _StubClient:
    """Stand-in for :class:`GeminiTTSMCPClient`.

    Records every ``text_transform`` call and serves canned responses
    for ``meta_health`` and ``tts_generate_chunk`` so the chunk loop
    reaches success.
    """

    instances: list["_StubClient"] = []

    def __init__(self, command: list[str], stderr_log: Path | None = None) -> None:
        self.command = command
        self.stderr_log = stderr_log
        self.text_transform_calls: list[dict[str, Any]] = []
        self.generate_chunk_calls: list[dict[str, Any]] = []
        self.health_calls: int = 0
        type(self).instances.append(self)

    def __enter__(self) -> "_StubClient":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def call(self, tool: str, params: dict[str, Any]) -> dict[str, Any]:
        if tool == "meta_health":
            self.health_calls += 1
            return {
                "ok": True,
                "status": "ok",
                "package_version": "stub-2.1.0",
                "protocol_version": "1",
            }
        raise AssertionError(f"unexpected low-level call: {tool}")

    def health(self) -> dict[str, Any]:
        return self.call("meta_health", {})

    def text_transform(self, **kwargs: Any) -> dict[str, Any]:
        self.text_transform_calls.append(dict(kwargs))
        return {
            "text": REWRITTEN_SCRIPT,
            "input_tokens": 11,
            "output_tokens": 22,
            "model_id": kwargs.get("model", "gemini-2.5-flash"),
        }

    def tts_generate_chunk(self, **kwargs: Any) -> dict[str, Any]:
        self.generate_chunk_calls.append(dict(kwargs))
        return {"pcm_base64": _PCM_B64}


@pytest.fixture(autouse=True)
def _clear_instances() -> None:
    _StubClient.instances.clear()
    yield
    _StubClient.instances.clear()


@pytest.fixture()
def script_path(tmp_path: Path) -> Path:
    path = tmp_path / "script.md"
    path.write_text(SHORT_SCRIPT, encoding="utf-8")
    return path


@pytest.fixture()
def job_dir(tmp_path: Path) -> Path:
    out = tmp_path / "job"
    out.mkdir()
    return out


def test_director_gemini_calls_text_transform_once(
    script_path: Path,
    job_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(generate_tts, "GeminiTTSMCPClient", _StubClient)
    monkeypatch.delenv("TTS_DUET_DIRECTOR", raising=False)
    monkeypatch.setenv("HOME", str(job_dir.parent))
    monkeypatch.setenv("TTS_DUET_NO_NOTIFY", "1")

    rc = generate_tts.main(
        [
            "--script",
            str(script_path),
            "--director",
            "gemini",
            "--job-dir",
            str(job_dir),
            "--format",
            "wav",
            "--yes",
        ]
    )
    assert rc == 0, f"unexpected exit code {rc}"

    text_transform_count = sum(
        len(c.text_transform_calls) for c in _StubClient.instances
    )
    assert text_transform_count == 1, (
        f"expected exactly one text_transform call, got {text_transform_count}"
    )

    # The chunk loop must have produced at least one generate_chunk call.
    chunk_count = sum(len(c.generate_chunk_calls) for c in _StubClient.instances)
    assert chunk_count >= 1


def test_director_gemini_rewrites_script_and_stamps_config(
    script_path: Path,
    job_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(generate_tts, "GeminiTTSMCPClient", _StubClient)
    monkeypatch.delenv("TTS_DUET_DIRECTOR", raising=False)
    monkeypatch.setenv("HOME", str(job_dir.parent))
    monkeypatch.setenv("TTS_DUET_NO_NOTIFY", "1")

    rc = generate_tts.main(
        [
            "--script",
            str(script_path),
            "--director",
            "gemini",
            "--job-dir",
            str(job_dir),
            "--format",
            "wav",
            "--yes",
        ]
    )
    assert rc == 0

    rewritten_path = job_dir / "director-output.md"
    assert rewritten_path.is_file()
    assert "[enriched]" in rewritten_path.read_text(encoding="utf-8")

    cfg = json.loads((job_dir / "config.json").read_text(encoding="utf-8"))
    director = cfg.get("director") or {}
    assert director.get("ran") is True, director
    assert director.get("backend") == "gemini", director
    assert director.get("input_tokens") == 11
    assert director.get("output_tokens") == 22


def test_director_off_skips_text_transform(
    script_path: Path,
    job_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(generate_tts, "GeminiTTSMCPClient", _StubClient)
    monkeypatch.delenv("TTS_DUET_DIRECTOR", raising=False)
    monkeypatch.setenv("HOME", str(job_dir.parent))
    monkeypatch.setenv("TTS_DUET_NO_NOTIFY", "1")

    rc = generate_tts.main(
        [
            "--script",
            str(script_path),
            "--director",
            "off",
            "--job-dir",
            str(job_dir),
            "--format",
            "wav",
            "--yes",
        ]
    )
    assert rc == 0
    text_transform_count = sum(
        len(c.text_transform_calls) for c in _StubClient.instances
    )
    assert text_transform_count == 0, (
        "off backend must not invoke text_transform"
    )
    cfg = json.loads((job_dir / "config.json").read_text(encoding="utf-8"))
    assert cfg.get("director") is None
