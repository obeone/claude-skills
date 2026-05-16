"""Sync-lane chunk-failure test (plan §9.2 ``test_chunk_failure``).

Force a non-MCP chunk failure (the fake returns
``failure_reason=tts_chunk_failed retryable=false``) and assert:

- ``generate_tts.py`` exits with code ``3`` (chunk failure, distinct
  from MCP protocol error ``5``).
- ``status=failed`` recorded.
- Partial WAVs created before the failure are preserved under
  ``<job_dir>/chunks/`` so the user can inspect them.
"""

from __future__ import annotations

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
LONG_SCRIPT = SCRIPTS_DIR / "tests" / "fixtures" / "scripts" / "long.md"
FAKE_MCP = SCRIPTS_DIR / "tests" / "fixtures" / "fake_mcp_server.py"


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


def test_non_retryable_chunk_failure_exits_three(tmp_path: Path) -> None:
    _require_rewired_skill()
    job_dir = tmp_path / "job-fail"
    job_dir.mkdir()
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", str(job_dir.parent)),
        "TTS_DUET_MCP_COMMAND": f"{sys.executable} {FAKE_MCP}",
        "TTS_DUET_NO_NOTIFY": "1",
        "TTS_DUET_MCP_TRACE": "1",
        # Succeed twice, then fail non-retryably.
        "FAKE_MCP_FAIL_AFTER": "2",
        "FAKE_MCP_FAIL_RETRYABLE": "false",
        "TTS_DUET_MCP_CHUNK_RETRY_MAX": "0",
        "TTS_DUET_MCP_BACKOFF_OVERRIDE": "0.05",
    }
    cmd = [
        sys.executable,
        str(GENERATE_TTS),
        "--script",
        str(LONG_SCRIPT),
        "--job-dir",
        str(job_dir),
        "--yes",
    ]
    proc = subprocess.run(
        cmd, env=env, capture_output=True, text=True, timeout=60.0, check=False
    )
    status = _read_status(job_dir)
    assert proc.returncode == 3, (
        f"expected exit 3 on non-retryable chunk failure, got {proc.returncode}; "
        f"stderr={proc.stderr[-400:]}"
    )
    assert status.get("status") == "failed"


def test_partial_wavs_preserved_on_failure(tmp_path: Path) -> None:
    _require_rewired_skill()
    job_dir = tmp_path / "job-partial"
    job_dir.mkdir()
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", str(job_dir.parent)),
        "TTS_DUET_MCP_COMMAND": f"{sys.executable} {FAKE_MCP}",
        "TTS_DUET_NO_NOTIFY": "1",
        "TTS_DUET_MCP_TRACE": "1",
        "FAKE_MCP_FAIL_AFTER": "2",
        "FAKE_MCP_FAIL_RETRYABLE": "false",
        "TTS_DUET_MCP_CHUNK_RETRY_MAX": "0",
        "TTS_DUET_MCP_BACKOFF_OVERRIDE": "0.05",
    }
    cmd = [
        sys.executable,
        str(GENERATE_TTS),
        "--script",
        str(LONG_SCRIPT),
        "--job-dir",
        str(job_dir),
        "--yes",
    ]
    subprocess.run(
        cmd, env=env, capture_output=True, text=True, timeout=60.0, check=False
    )
    chunks_dir = job_dir / "chunks"
    assert chunks_dir.is_dir(), "<job_dir>/chunks/ should exist even on failure"
    wavs = sorted(chunks_dir.glob("*.wav"))
    assert wavs, (
        "partial WAVs from successful chunks must be preserved for "
        "post-mortem; chunks/ is empty"
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
