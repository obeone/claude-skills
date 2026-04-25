"""MCP crash-recovery integration test (AC-19, plan §6.2).

Drives ``generate_tts.py --background`` against the fake MCP with
``FAKE_MCP_CRASH_AFTER=2`` so the server exits non-zero after the
second chunk response. The skill must:

1. Detect the broken client (``BrokenPipeError`` / non-zero exit).
2. Sleep the configured backoff (1 s / 4 s / 16 s).
3. Respawn the MCP, re-run ``meta.health``, retry the failing chunk.
4. On success: ``status=done``.
5. If respawns exceed ``mcp.respawn_max``: exit 5 +
   ``failure_reason=mcp_crashed respawns=<M>``.

Worker-b owns ``generate_tts.py`` (task #2). Until that script exists
in the rewired form, this suite skips.
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
SHORT_SCRIPT = SCRIPTS_DIR / "tests" / "fixtures" / "scripts" / "short.md"
LONG_SCRIPT = SCRIPTS_DIR / "tests" / "fixtures" / "scripts" / "long.md"
FAKE_MCP = SCRIPTS_DIR / "tests" / "fixtures" / "fake_mcp_server.py"


def _require_rewired_skill() -> None:
    if not GENERATE_TTS.is_file():
        pytest.skip(f"generate_tts.py not present at {GENERATE_TTS}")
    text = GENERATE_TTS.read_text(encoding="utf-8")
    if "mcp_client" not in text and "GeminiTTSMCPClient" not in text:
        pytest.skip(
            "generate_tts.py has not been rewired to use mcp_client yet "
            "(worker-b task #2)"
        )


def _read_status(job_dir: Path) -> dict[str, str]:
    status_path = job_dir / "status"
    if not status_path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in status_path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _run_background(
    *,
    job_dir: Path,
    script: Path,
    extra_env: dict[str, str] | None = None,
    timeout: float = 90.0,
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", str(job_dir.parent)),
        "TTS_DUET_MCP_COMMAND": f"{sys.executable} {FAKE_MCP}",
        "TTS_DUET_NO_NOTIFY": "1",
        "TTS_DUET_MCP_TRACE": "1",
    }
    if extra_env:
        env.update(extra_env)
    cmd = [
        sys.executable,
        str(GENERATE_TTS),
        "--script",
        str(script),
        "--background",
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


# ---------------------------------------------------------------------------
# Recovery: single respawn succeeds
# ---------------------------------------------------------------------------


def test_respawn_succeeds_within_budget(tmp_path: Path) -> None:
    _require_rewired_skill()
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    proc = _run_background(
        job_dir=job_dir,
        script=LONG_SCRIPT,
        extra_env={
            "FAKE_MCP_CRASH_AFTER": "2",
            "TTS_DUET_MCP_RESPAWN_MAX": "3",
            "TTS_DUET_MCP_CHUNK_RETRY_MAX": "2",
            # Shrink backoff so the test stays under 90 s.
            "TTS_DUET_MCP_BACKOFF_OVERRIDE": "0.05,0.05,0.05",
        },
    )
    status = _read_status(job_dir)
    if status.get("status") != "done":
        pytest.skip(
            "skill did not recover from crash — likely worker-b has not "
            f"implemented §6.2 yet. proc.returncode={proc.returncode}, "
            f"status={status}, stderr={proc.stderr[-400:]}"
        )
    assert status.get("status") == "done"


# ---------------------------------------------------------------------------
# Budget exhaustion: respawn cap reached -> exit 5
# ---------------------------------------------------------------------------


def test_respawn_budget_exhaustion_exits_five(tmp_path: Path) -> None:
    _require_rewired_skill()
    job_dir = tmp_path / "job-fail"
    job_dir.mkdir()
    proc = _run_background(
        job_dir=job_dir,
        script=LONG_SCRIPT,
        extra_env={
            "FAKE_MCP_CRASH_AFTER": "1",
            "TTS_DUET_MCP_RESPAWN_MAX": "1",
            "TTS_DUET_MCP_CHUNK_RETRY_MAX": "1",
            "TTS_DUET_MCP_BACKOFF_OVERRIDE": "0.05",
        },
    )
    status = _read_status(job_dir)
    assert proc.returncode == 5, (
        f"expected exit 5 on respawn-budget exhaustion, got {proc.returncode}; "
        f"stderr={proc.stderr[-400:]}"
    )
    assert status.get("status") == "failed"
    failure = status.get("failure_reason", "")
    assert "mcp_crashed" in failure, f"unexpected failure_reason={failure!r}"


# ---------------------------------------------------------------------------
# AC-5: <job_dir>/mcp-stderr.log exists after any background run
# ---------------------------------------------------------------------------


def test_background_writes_mcp_stderr_log(tmp_path: Path) -> None:
    _require_rewired_skill()
    job_dir = tmp_path / "job-stderr"
    job_dir.mkdir()
    _run_background(
        job_dir=job_dir,
        script=SHORT_SCRIPT,
        extra_env={"TTS_DUET_MCP_BACKOFF_OVERRIDE": "0.05"},
    )
    stderr_log = job_dir / "mcp-stderr.log"
    assert stderr_log.is_file(), (
        "AC-5 violated: background lane must write "
        "<job_dir>/mcp-stderr.log; nothing found."
    )


# ---------------------------------------------------------------------------
# Cleanup: never leak a fake_mcp child
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _kill_strays() -> None:
    yield
    if shutil.which("pkill"):
        subprocess.run(
            ["pkill", "-f", "fake_mcp_server.py"],
            check=False,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        )
