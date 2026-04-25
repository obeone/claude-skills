"""Agent-mode director handoff tests.

When ``--director agent`` is passed (with ``--job-dir``), the skill
must:

- Compose a director prompt and write it to
  ``<job_dir>/director-prompt.md``.
- Snapshot the input script to ``<job_dir>/director-input.md``.
- Drop a human-readable ``HANDOFF.md``.
- Stamp ``status=awaiting_director`` and ``config.json`` with
  ``director.backend == "agent"`` and ``director.awaiting`` truthy.
- Exit ``0`` and **never spawn an MCP client**.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


pytest.importorskip("yaml", reason="pyyaml required by config loader")
pytest.importorskip("mcp", reason="mcp transport package required by import chain")

import generate_tts  # noqa: E402  — conftest puts scripts/ on sys.path


SHORT_SCRIPT = """## Director's Notes
warm tone, slow pace.

Speaker A: hi there.
Speaker B: hello back.
"""


@pytest.fixture()
def job_dir(tmp_path: Path) -> Path:
    out = tmp_path / "job"
    out.mkdir()
    return out


@pytest.fixture()
def script_path(tmp_path: Path) -> Path:
    path = tmp_path / "script.md"
    path.write_text(SHORT_SCRIPT, encoding="utf-8")
    return path


def _read_status(job_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (job_dir / "status").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def test_agent_handoff_writes_three_artifacts(
    job_dir: Path,
    script_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Sentinel: any attempt to instantiate the MCP client must fail
    # the test. Agent mode must not touch the MCP at all.
    spawned: list[object] = []

    def _exploding_client(*args: object, **kwargs: object) -> object:
        spawned.append((args, kwargs))
        raise AssertionError("agent mode must not spawn GeminiTTSMCPClient")

    monkeypatch.setattr(generate_tts, "GeminiTTSMCPClient", _exploding_client)
    monkeypatch.delenv("TTS_DUET_DIRECTOR", raising=False)
    # Avoid touching ``~/.config/tts-duet/config.yaml``.
    monkeypatch.setenv("HOME", str(job_dir.parent))

    rc = generate_tts.main(
        [
            "--script",
            str(script_path),
            "--director",
            "agent",
            "--job-dir",
            str(job_dir),
            "--yes",
        ]
    )
    assert rc == 0, f"unexpected exit code {rc}"
    assert spawned == [], "agent mode spawned a client"

    prompt = (job_dir / "director-prompt.md").read_text(encoding="utf-8")
    assert "## Director's Notes" in prompt
    assert "## Transcript" in prompt
    # The genre-tag substring should be embedded in the prompt; default
    # preset is podcast-chill when none is supplied.
    assert "Genre:" in prompt

    snapshot = (job_dir / "director-input.md").read_text(encoding="utf-8")
    assert snapshot == SHORT_SCRIPT

    handoff = (job_dir / "HANDOFF.md").read_text(encoding="utf-8")
    assert "director-output.md" in handoff
    assert "--director off" in handoff


def test_agent_handoff_status_and_config_json(
    job_dir: Path,
    script_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        generate_tts,
        "GeminiTTSMCPClient",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("agent mode must not spawn GeminiTTSMCPClient")
        ),
    )
    monkeypatch.delenv("TTS_DUET_DIRECTOR", raising=False)
    monkeypatch.setenv("HOME", str(job_dir.parent))

    rc = generate_tts.main(
        [
            "--script",
            str(script_path),
            "--director",
            "agent",
            "--job-dir",
            str(job_dir),
            "--yes",
        ]
    )
    assert rc == 0

    status = _read_status(job_dir)
    assert status.get("status") == "awaiting_director", status
    assert status.get("handoff") == "director-prompt.md", status

    cfg = json.loads((job_dir / "config.json").read_text(encoding="utf-8"))
    assert cfg.get("director", {}).get("backend") == "agent"
    assert cfg.get("director", {}).get("awaiting") is True
    assert cfg.get("director", {}).get("ran") is False


def test_agent_handoff_requires_job_dir(
    script_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        generate_tts,
        "GeminiTTSMCPClient",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("agent mode must not spawn GeminiTTSMCPClient")
        ),
    )
    monkeypatch.delenv("TTS_DUET_DIRECTOR", raising=False)
    monkeypatch.setenv("HOME", str(script_path.parent))
    rc = generate_tts.main(
        [
            "--script",
            str(script_path),
            "--director",
            "agent",
            "--yes",
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "--job-dir" in err
