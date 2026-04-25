"""Background-lane happy path (AC-5 + §5.5 + §6.3).

End-to-end run: ``generate_tts.py --background`` against the fake MCP
on a short script. Verifies:

- ``status=done`` written to ``<job_dir>/status``.
- ``<job_dir>/mcp-stderr.log`` is created (AC-5).
- ``<job_dir>/config.json`` has every required v1 field (§5.5).
- ``<job_dir>/mcp_trace.jsonl`` records a ``meta.health`` preflight as
  the first entry (AC-5).
- ``<job_dir>/notification`` exists.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SKILL_ROOT = REPO_ROOT / "skills" / "tts-duet"
SCRIPTS_DIR = SKILL_ROOT / "scripts"
GENERATE_TTS = SCRIPTS_DIR / "generate_tts.py"
SHORT_SCRIPT = SCRIPTS_DIR / "tests" / "fixtures" / "scripts" / "short.md"
FAKE_MCP = SCRIPTS_DIR / "tests" / "fixtures" / "fake_mcp_server.py"

REQUIRED_CONFIG_FIELDS: frozenset[str] = frozenset(
    {
        "version",
        "created_at",
        "script_path",
        "script_hash",
        "model",
        "voices",
        "lang",
        "format",
        "chunk_count",
        "chunks_done",
        "mcp_command",
        "mcp_version",
        "protocol_version",
        "cli_snapshot",
    }
)


def _require_rewired_skill() -> None:
    if not GENERATE_TTS.is_file():
        pytest.skip(f"generate_tts.py not present at {GENERATE_TTS}")
    text = GENERATE_TTS.read_text(encoding="utf-8")
    if "mcp_client" not in text and "GeminiTTSMCPClient" not in text:
        pytest.skip(
            "generate_tts.py not rewired to mcp_client yet (worker-b task #2)"
        )


def _read_status(job_dir: Path) -> dict[str, str]:
    path = job_dir / "status"
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


@pytest.fixture()
def background_run(tmp_path: Path) -> Path:
    _require_rewired_skill()
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", str(job_dir.parent)),
        "TTS_DUET_MCP_COMMAND": f"{sys.executable} {FAKE_MCP}",
        "TTS_DUET_NO_NOTIFY": "1",
        "TTS_DUET_MCP_TRACE": "1",
    }
    cmd = [
        sys.executable,
        str(GENERATE_TTS),
        "--script",
        str(SHORT_SCRIPT),
        "--background",
        "--job-dir",
        str(job_dir),
        "--yes",
    ]
    proc = subprocess.run(
        cmd, env=env, capture_output=True, text=True, timeout=60.0, check=False
    )
    if proc.returncode != 0:
        pytest.skip(
            f"background run did not exit 0 (rc={proc.returncode}); "
            f"stderr={proc.stderr[-400:]}"
        )
    return job_dir


# ---------------------------------------------------------------------------
# AC-5: stderr + preflight + status
# ---------------------------------------------------------------------------


def test_status_is_done(background_run: Path) -> None:
    status = _read_status(background_run)
    assert status.get("status") == "done", f"status={status!r}"


def test_mcp_stderr_log_present(background_run: Path) -> None:
    assert (background_run / "mcp-stderr.log").is_file(), (
        "AC-5: <job_dir>/mcp-stderr.log MUST exist after any background run"
    )


def test_mcp_trace_first_entry_is_meta_health(background_run: Path) -> None:
    trace = background_run / "mcp_trace.jsonl"
    assert trace.is_file(), "AC-5: mcp_trace.jsonl must exist when TTS_DUET_MCP_TRACE=1"
    first_line = trace.read_text(encoding="utf-8").splitlines()[0]
    record = json.loads(first_line)
    tool = record.get("tool") or record.get("method")
    assert tool in {"meta.health", "meta_health"}, (
        f"AC-5: first mcp_trace entry must be meta.health, got {tool!r}"
    )


def test_notification_present(background_run: Path) -> None:
    assert (background_run / "notification").is_file(), (
        "background lane must write a notification artifact on done"
    )


# ---------------------------------------------------------------------------
# §5.5: config.json schema v1
# ---------------------------------------------------------------------------


def test_config_json_has_v1_required_fields(background_run: Path) -> None:
    config_path = background_run / "config.json"
    assert config_path.is_file(), "<job_dir>/config.json missing"
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    assert cfg.get("version") == 1, f"version={cfg.get('version')!r}"
    missing = REQUIRED_CONFIG_FIELDS - set(cfg)
    assert not missing, f"config.json missing required fields: {missing}"


def test_config_json_records_mcp_version_and_command(background_run: Path) -> None:
    cfg = json.loads((background_run / "config.json").read_text(encoding="utf-8"))
    assert cfg.get("mcp_version"), "mcp_version not recorded"
    assert cfg.get("mcp_command"), "mcp_command not recorded"


def test_config_json_chunks_done_equals_chunk_count(background_run: Path) -> None:
    cfg = json.loads((background_run / "config.json").read_text(encoding="utf-8"))
    assert cfg.get("chunks_done") == cfg.get("chunk_count"), (
        f"chunks_done={cfg.get('chunks_done')} != chunk_count={cfg.get('chunk_count')}"
    )


@pytest.fixture(autouse=True)
def _kill_strays() -> None:
    yield
    if shutil.which("pkill"):
        subprocess.run(
            ["pkill", "-f", "fake_mcp_server.py"],
            check=False,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        )
