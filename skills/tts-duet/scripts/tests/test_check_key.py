"""``generate_tts.py --check-key`` preflight test.

``--check-key`` probes the gemini-tts MCP via ``meta_health`` and exits:

- ``0`` when the server is healthy AND reports a key present
  (``has_api_key`` truthy). It must NOT require ``--script``.
- ``1`` with a remediation message on stderr when no key is present.

The fake MCP fixture (``fixtures/fake_mcp_server.py``) returns
``has_api_key`` derived from ``FAKE_MCP_HEALTH_KEY_STATUS``: the default
``"ok"`` means a key is present; overriding it to ``"missing"`` flips
``has_api_key`` to ``False``.
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
FAKE_MCP = SCRIPTS_DIR / "tests" / "fixtures" / "fake_mcp_server.py"


def _require_rewired_skill() -> None:
    if not GENERATE_TTS.is_file():
        pytest.skip(f"generate_tts.py not present at {GENERATE_TTS}")
    text = GENERATE_TTS.read_text(encoding="utf-8")
    if "--check-key" not in text:
        pytest.skip("generate_tts.py has no --check-key flag yet")


def _run_check_key(
    tmp_path: Path, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "TTS_DUET_MCP_COMMAND": f"{sys.executable} {FAKE_MCP}",
        "TTS_DUET_NO_NOTIFY": "1",
    }
    if extra_env:
        env.update(extra_env)
    cmd = [sys.executable, str(GENERATE_TTS), "--check-key"]
    return subprocess.run(
        cmd, env=env, capture_output=True, text=True, timeout=60.0, check=False
    )


def test_check_key_exits_zero_when_key_present(tmp_path: Path) -> None:
    """Fake reports a key present → exit 0, no --script needed."""
    _require_rewired_skill()
    proc = _run_check_key(tmp_path)
    assert proc.returncode == 0, (
        f"expected exit 0 when key present, got {proc.returncode}; "
        f"stderr={proc.stderr[-400:]}"
    )
    assert "present" in proc.stdout.lower()


def test_check_key_exits_one_when_key_missing(tmp_path: Path) -> None:
    """Fake reports no key → exit 1 with remediation on stderr."""
    _require_rewired_skill()
    proc = _run_check_key(
        tmp_path, extra_env={"FAKE_MCP_HEALTH_KEY_STATUS": "missing"}
    )
    assert proc.returncode == 1, (
        f"expected exit 1 when key missing, got {proc.returncode}; "
        f"stdout={proc.stdout[-400:]}"
    )
    err = proc.stderr
    # Remediation must point at the canonical user-level settings file
    # and tell the user to restart Claude Code.
    assert "~/.claude/settings.json" in err
    assert "GEMINI_API_KEY" in err
    assert "restart" in err.lower()
    # It must NOT echo a key value.
    assert "your-key-here" not in proc.stdout


@pytest.fixture(autouse=True)
def _kill_strays() -> None:
    yield
    if shutil.which("pkill"):
        subprocess.run(
            ["pkill", "-f", "fake_mcp_server.py"],
            check=False,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        )
