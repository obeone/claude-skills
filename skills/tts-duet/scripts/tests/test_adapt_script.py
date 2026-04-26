"""Adaptation pre-pass tests.

Cover three contracts:

* Agent backend writes the three handoff artifacts and exits ``0``
  (mirrors :mod:`tests.test_director_agent_handoff`).
* :func:`lib.adaptation.compose_prompt` embeds the shape, target
  duration, language directive and optional style hint.
* Gemini backend (with a mocked MCP client) writes the adapted script
  to ``--output`` and a correct ``.meta.json`` sidecar.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


pytest.importorskip("yaml", reason="pyyaml required by config loader")
pytest.importorskip("mcp", reason="mcp transport package required by import chain")

import adapt_script  # noqa: E402  — conftest puts scripts/ on sys.path
from lib.adaptation import compose_prompt  # noqa: E402


RAW_INPUT = (
    "Quantum computing leverages superposition and entanglement to perform "
    "many calculations in parallel. Today's prototypes use only a handful of "
    "qubits, but the field is racing toward useful error-corrected machines.\n"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def input_path(tmp_path: Path) -> Path:
    path = tmp_path / "raw.md"
    path.write_text(RAW_INPUT, encoding="utf-8")
    return path


@pytest.fixture()
def job_dir(tmp_path: Path) -> Path:
    out = tmp_path / "job"
    out.mkdir()
    return out


def _read_status(job_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (job_dir / "status").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


# ---------------------------------------------------------------------------
# Agent backend handoff
# ---------------------------------------------------------------------------


def test_agent_handoff_writes_three_artifacts(
    job_dir: Path,
    input_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--backend agent`` must never spawn the MCP and must drop the
    three handoff files plus a ``status=awaiting_adaptation`` file."""
    spawned: list[object] = []

    def _exploding_client(*args: object, **kwargs: object) -> object:
        spawned.append((args, kwargs))
        raise AssertionError("agent mode must not spawn GeminiTTSMCPClient")

    monkeypatch.setattr(adapt_script, "GeminiTTSMCPClient", _exploding_client)
    monkeypatch.setenv("HOME", str(job_dir.parent))

    rc = adapt_script.main(
        [
            "--input",
            str(input_path),
            "--backend",
            "agent",
            "--shape",
            "dialogue",
            "--language",
            "auto",
            "--target-duration",
            "60",
            "--job-dir",
            str(job_dir),
            "--yes",
        ]
    )
    assert rc == 0, f"unexpected exit code {rc}"
    assert spawned == [], "agent mode spawned a client"

    prompt = (job_dir / "adaptation-prompt.md").read_text(encoding="utf-8")
    assert "Shape: dialogue" in prompt
    assert "Speaker A:" in prompt
    assert "Target duration" in prompt

    snapshot = (job_dir / "adaptation-input.md").read_text(encoding="utf-8")
    assert snapshot == RAW_INPUT

    handoff = (job_dir / "HANDOFF.md").read_text(encoding="utf-8")
    assert "adapted-script.md" in handoff

    status = _read_status(job_dir)
    assert status.get("status") == "awaiting_adaptation", status
    assert status.get("handoff") == "adaptation-prompt.md", status


def test_agent_backend_requires_job_dir(
    input_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        adapt_script,
        "GeminiTTSMCPClient",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("agent mode must not spawn GeminiTTSMCPClient")
        ),
    )
    monkeypatch.setenv("HOME", str(input_path.parent))

    rc = adapt_script.main(
        [
            "--input",
            str(input_path),
            "--backend",
            "agent",
            "--target-duration",
            "30",
            "--yes",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "--job-dir" in err


# ---------------------------------------------------------------------------
# Prompt composition
# ---------------------------------------------------------------------------


def test_compose_prompt_includes_shape_duration_language_and_style() -> None:
    prompt = compose_prompt(
        raw_input="Hello world.\n",
        shape="interview",
        language="fr",
        target_duration_s=120.0,
        style="energetic and curious",
    )
    assert "Shape: interview" in prompt
    # Interview rule mentions interviewer/interviewee.
    assert "interview" in prompt.lower()
    # 120 s @ 150 wpm -> 300 words; the prompt should mention the duration.
    assert "120" in prompt
    assert "300" in prompt
    # Explicit language directive when not 'auto'.
    assert "fr" in prompt
    assert "translate" in prompt.lower()
    # Style hint is forwarded verbatim.
    assert "energetic and curious" in prompt
    # Raw input must be embedded.
    assert "Hello world." in prompt


def test_compose_prompt_auto_language_says_match_input() -> None:
    prompt = compose_prompt(
        raw_input="x",
        shape="mono",
        language="auto",
        target_duration_s=30.0,
    )
    assert "match the language of the input" in prompt.lower()
    # Mono shape should mention the Mono: speaker label.
    assert "Mono:" in prompt


# ---------------------------------------------------------------------------
# Gemini backend (mocked MCP)
# ---------------------------------------------------------------------------


class _RecordingClient:
    """Stub for ``GeminiTTSMCPClient`` used by the gemini-backend test."""

    def __init__(self, response_text: str) -> None:
        self.calls: list[dict[str, Any]] = []
        self._response_text = response_text

    # The script uses the client as a context manager.
    def __enter__(self) -> "_RecordingClient":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def text_transform(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(dict(kwargs))
        return {
            "text": self._response_text,
            "input_tokens": 42,
            "output_tokens": 87,
            "model_id": kwargs.get("model", "gemini-2.5-flash"),
        }


def test_gemini_backend_writes_script_and_meta(
    tmp_path: Path,
    input_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "adapted.md"
    response_text = (
        "Speaker A: Quantum computing is the new frontier.\n"
        "Speaker B: Tell me more — what makes a qubit different?\n"
    )

    instances: list[_RecordingClient] = []

    def _client_factory(
        *args: object, **kwargs: object
    ) -> _RecordingClient:
        client = _RecordingClient(response_text=response_text)
        instances.append(client)
        return client

    monkeypatch.setattr(adapt_script, "GeminiTTSMCPClient", _client_factory)
    monkeypatch.setattr(
        adapt_script,
        "resolve_mcp_command",
        lambda *args, **kwargs: ["fake-mcp-cmd"],
    )
    monkeypatch.setenv("HOME", str(tmp_path))

    rc = adapt_script.main(
        [
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--backend",
            "gemini",
            "--shape",
            "dialogue",
            "--language",
            "en",
            "--target-duration",
            "90",
            "--style",
            "warm and curious",
            "--model",
            "gemini-2.5-flash",
            "--temperature",
            "0.4",
            "--yes",
        ]
    )
    assert rc == 0, f"unexpected exit code {rc}"
    assert len(instances) == 1, "gemini backend must spawn exactly one client"

    written = output_path.read_text(encoding="utf-8")
    assert "Speaker A:" in written
    assert "Speaker B:" in written

    meta_path = output_path.with_suffix(output_path.suffix + ".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta == {
        "model": "gemini-2.5-flash",
        "target_duration_s": 90.0,
        "shape": "dialogue",
        "language": "en",
        "input_tokens_est": 42,
        "output_tokens_est": 87,
    }

    # The MCP must only see the standard four-key payload — no
    # shape / language / target_duration_s sidecar fields.
    last = instances[0].calls[-1]
    assert set(last) == {"prompt", "model", "temperature", "max_output_tokens"}
    assert last["temperature"] == pytest.approx(0.4)
    assert "Shape: dialogue" in last["prompt"]


def test_gemini_backend_requires_output(
    input_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        adapt_script,
        "GeminiTTSMCPClient",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("must not spawn before output validation")
        ),
    )
    monkeypatch.setattr(
        adapt_script,
        "resolve_mcp_command",
        lambda *args, **kwargs: ["fake-mcp-cmd"],
    )
    monkeypatch.setenv("HOME", str(input_path.parent))

    rc = adapt_script.main(
        [
            "--input",
            str(input_path),
            "--backend",
            "gemini",
            "--target-duration",
            "60",
            "--yes",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "--output" in err
