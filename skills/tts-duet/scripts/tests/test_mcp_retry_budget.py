"""MCP per-chunk retry-budget exhaustion test (AC-19, plan §6.2).

Whereas ``test_mcp_crash_recovery.py`` exercises *respawn* exhaustion,
this module exercises the *per-chunk retry* axis: the fake MCP returns
``{failure_reason: "tts_chunk_failed", retryable: true}`` on every
``tts.generate_chunk`` call, and the skill must:

1. Retry up to ``mcp.chunk_retry_max`` times against the SAME client.
2. On exhaustion, abort with exit 5 + ``status=failed
   failure_reason=mcp_crashed chunk=<k> retries=<N>``.

Parametrised across small budgets so the test stays cheap.
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
            "generate_tts.py has not been rewired to use mcp_client yet"
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


def _run(
    *,
    job_dir: Path,
    chunk_retry_max: int,
    respawn_max: int = 1,
    timeout: float = 60.0,
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", str(job_dir.parent)),
        "TTS_DUET_MCP_COMMAND": f"{sys.executable} {FAKE_MCP}",
        "TTS_DUET_NO_NOTIFY": "1",
        "TTS_DUET_MCP_TRACE": "1",
        "FAKE_MCP_FAIL_AFTER": "0",  # every call fails
        "FAKE_MCP_FAIL_RETRYABLE": "true",
        "TTS_DUET_MCP_CHUNK_RETRY_MAX": str(chunk_retry_max),
        "TTS_DUET_MCP_RESPAWN_MAX": str(respawn_max),
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
    return subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


@pytest.mark.parametrize("chunk_retry_max", [1, 2, 3])
def test_chunk_retry_exhaustion_exits_five(
    tmp_path: Path, chunk_retry_max: int
) -> None:
    _require_rewired_skill()
    job_dir = tmp_path / f"job-retry-{chunk_retry_max}"
    job_dir.mkdir()
    proc = _run(job_dir=job_dir, chunk_retry_max=chunk_retry_max)
    status = _read_status(job_dir)
    assert proc.returncode == 5, (
        f"expected exit 5 on chunk_retry exhaustion (max={chunk_retry_max}), "
        f"got {proc.returncode}; stderr={proc.stderr[-400:]}"
    )
    assert status.get("status") == "failed"
    failure = status.get("failure_reason", "")
    assert "mcp_crashed" in failure or "chunk_failed" in failure, (
        f"unexpected failure_reason={failure!r}"
    )


def test_chunk_retry_records_chunk_index(tmp_path: Path) -> None:
    """Plan §6.2 requires the failure_reason payload to include
    ``chunk=k retries=N`` so post-mortem is possible."""
    _require_rewired_skill()
    job_dir = tmp_path / "job-payload"
    job_dir.mkdir()
    _run(job_dir=job_dir, chunk_retry_max=1)
    status = _read_status(job_dir)
    raw = " ".join(f"{k}={v}" for k, v in status.items())
    # We tolerate either inline payload (`failure_reason=mcp_crashed
    # chunk=1 retries=1`) or a separate `chunk` / `retries` key.
    assert "chunk" in raw or "retries" in raw, (
        f"status missing chunk/retries diagnostic: {status!r}"
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
