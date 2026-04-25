"""``--background --director agent`` is mutually exclusive.

Agent mode requires the calling agent to drive the rewrite — that is
incompatible with detaching into a nohup child. The skill must refuse
the combination up front (before allocating a job dir) and emit a
human-readable error on stderr.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("yaml")
pytest.importorskip("mcp")

import generate_tts  # noqa: E402


SHORT_SCRIPT = "Speaker A: hi.\nSpeaker B: hello.\n"


@pytest.fixture()
def script_path(tmp_path: Path) -> Path:
    path = tmp_path / "script.md"
    path.write_text(SHORT_SCRIPT, encoding="utf-8")
    return path


def test_background_with_agent_director_returns_2(
    script_path: Path,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TTS_DUET_DIRECTOR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    rc = generate_tts.main(
        [
            "--background",
            "--director",
            "agent",
            "--script",
            str(script_path),
            "--yes",
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "--director agent" in err
    assert "--background" in err


def test_background_with_agent_via_env_returns_2(
    script_path: Path,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env-var override must also be guarded."""
    monkeypatch.setenv("TTS_DUET_DIRECTOR", "agent")
    monkeypatch.setenv("HOME", str(tmp_path))

    rc = generate_tts.main(
        [
            "--background",
            "--script",
            str(script_path),
            "--yes",
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "--background" in err
