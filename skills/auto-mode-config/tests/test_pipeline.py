# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest>=7"]
# ///
"""Pipeline tests for inspect_automode.py and apply_automode.py.

These exercises map onto acceptance criteria #5–#18 from
``team-plan.md``. Each test isolates ``$HOME`` to a tmp directory and
prepends a stub-``claude`` PATH so the live binary is never invoked.

Stub bins live under ``tests/fixtures/stub_claude/``. They are tiny
``/bin/sh`` scripts that emit predetermined critique output and exit
codes. The naming is the actual behaviour: ``claude_ok`` exits 0 with
a contract-conforming critique; ``claude_fail`` exits 2; ``claude_drift``
emits a ``## Severe issues`` header that breaks the section contract;
``claude_no_settings_flag`` advertises no ``--settings`` flag in
``--help`` output.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"
FIXTURES = SKILL_DIR / "tests" / "fixtures"
STUBS = FIXTURES / "stub_claude"

INSPECT = SCRIPTS / "inspect_automode.py"
APPLY = SCRIPTS / "apply_automode.py"

# Add scripts dir to sys.path so we can import _canonical for hash math.
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import _canonical  # noqa: E402


def _make_stub_dir(tmpdir: Path, source_name: str) -> Path:
    """Create a directory with a single ``claude`` symlink to a stub.

    Parameters
    ----------
    tmpdir
        Working tmp directory.
    source_name
        Stub script filename under ``STUBS``.

    Returns
    -------
    Path
        The directory to prepend to PATH.
    """
    bin_dir = tmpdir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    src = STUBS / source_name
    dst = bin_dir / "claude"
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    # Copy (not symlink) so chmod survives across HOME resets.
    shutil.copy2(src, dst)
    os.chmod(dst, 0o755)
    return bin_dir


def _env_with_stub(home: Path, stub: str | None = "claude_ok") -> dict[str, str]:
    """Build an env dict with HOME isolated and PATH prepended by a stub.

    Parameters
    ----------
    home
        Path to use for ``$HOME``.
    stub
        Stub source name. ``None`` means do not prepend anything (PATH
        becomes ``/usr/bin:/bin`` so ``claude`` is unreachable).

    Returns
    -------
    dict
        Process environment.
    """
    env = os.environ.copy()
    env["HOME"] = str(home)
    if stub is None:
        env["PATH"] = "/usr/bin:/bin"
    else:
        bin_dir = _make_stub_dir(home, stub)
        env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    return env


def _run_apply(
    args: list[str],
    home: Path,
    stub: str | None = "claude_ok",
    stdin: str | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    """Invoke ``apply_automode.py`` under an isolated HOME.

    Parameters
    ----------
    args
        CLI arguments.
    home
        ``$HOME`` for the run.
    stub
        Stub claude binary, or ``None`` to omit ``claude`` from PATH.
    stdin
        Optional stdin text.
    timeout
        Seconds before killing the run.

    Returns
    -------
    CompletedProcess
        With ``stdout`` and ``stderr`` decoded as text.
    """
    env = _env_with_stub(home, stub)
    return subprocess.run(
        [sys.executable, str(APPLY), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        input=stdin,
    )


def _run_inspect(
    args: list[str],
    home: Path,
    timeout: int = 10,
) -> subprocess.CompletedProcess:
    """Invoke ``inspect_automode.py`` under an isolated HOME.

    Parameters
    ----------
    args
        CLI arguments.
    home
        ``$HOME`` for the run.
    timeout
        Seconds before killing the run.

    Returns
    -------
    CompletedProcess
        With ``stdout`` and ``stderr`` decoded as text.
    """
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, str(INSPECT), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _seed_settings(home: Path, obj: dict) -> Path:
    """Write ``obj`` to ``$HOME/.claude/settings.json`` mode 0600.

    Parameters
    ----------
    home
        Test ``$HOME``.
    obj
        JSON-serializable dict.

    Returns
    -------
    Path
        Settings path.
    """
    claude = home / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    os.chmod(claude, 0o700)
    path = claude / "settings.json"
    path.write_bytes(_canonical.canonicalize(obj))
    os.chmod(path, 0o600)
    return path


def _proposal_hash(proposal_path: Path, base_obj: dict | None = None) -> str:
    """Compute the canonical sha256 the apply script will produce.

    Parameters
    ----------
    proposal_path
        Source proposal JSON.
    base_obj
        Optional pre-existing settings dict (the apply pipeline merges
        proposal over base before stripping ``__example_only``).

    Returns
    -------
    str
        Hex digest.
    """
    proposal = json.loads(proposal_path.read_bytes())

    def strip(node):
        if isinstance(node, dict):
            if (
                node.get("__example_only") is True
                and set(node.keys()) <= {"__example_only", "value"}
            ):
                return _DROP
            out = {}
            for k, v in node.items():
                nv = strip(v)
                if nv is _DROP:
                    continue
                out[k] = nv
            return out
        if isinstance(node, list):
            return [strip(x) for x in node if strip(x) is not _DROP]
        return node

    base = base_obj or {}
    merged = dict(base)
    for k, v in proposal.items():
        if k == "autoMode" and isinstance(v, dict):
            existing = merged.get("autoMode") if isinstance(merged.get("autoMode"), dict) else {}
            sub = dict(existing) if isinstance(existing, dict) else {}
            for sk, sv in v.items():
                sub[sk] = sv
            merged["autoMode"] = sub
        else:
            merged[k] = v
    stripped = strip(merged)
    if stripped is _DROP:
        stripped = {}
    canonical = _canonical.canonicalize(stripped)
    return hashlib.sha256(canonical).hexdigest()


_DROP = object()


# ---------------------------------------------------------------------------
# Acceptance #5 — concurrent invocation flock contention -> exit 7.
# ---------------------------------------------------------------------------


def test_acc05_concurrent_lock_contention(tmp_path: Path) -> None:
    """A second apply invocation while the lock is held exits 7."""
    lockdir = tmp_path / ".claude"
    lockdir.mkdir(parents=True)
    lockfile = lockdir / "settings.json.lock"
    # Hold the lock with a fresh PID + recent timestamp.
    lockfile.write_text(f"{os.getpid()} 2099-01-01T00:00:00Z\n")
    # Acquire flock from this test process.
    import fcntl

    fd = os.open(lockfile, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        # Make sure mtime is fresh so the apply doesn't reclaim.
        os.utime(lockfile, (time.time(), time.time()))
        proposal = FIXTURES / "proposal_minimal.json"
        out = _run_apply(
            ["--dry-run", "--proposal", str(proposal)],
            tmp_path,
            stub="claude_ok",
        )
        assert out.returncode == 7, (out.returncode, out.stdout, out.stderr)
        assert "another process holds the settings lock" in out.stderr
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# ---------------------------------------------------------------------------
# Acceptance #6 — stale lock reclaim.
# ---------------------------------------------------------------------------


def test_acc06_stale_lock_reclaimed(tmp_path: Path) -> None:
    """A lock with a long-dead PID + ancient mtime is reclaimed."""
    claude = tmp_path / ".claude"
    claude.mkdir(parents=True)
    lockfile = claude / "settings.json.lock"
    lockfile.write_text("99999 2020-01-01T00:00:00Z\n")
    # Force ancient mtime.
    ancient = time.time() - 86400
    os.utime(lockfile, (ancient, ancient))
    proposal = FIXTURES / "proposal_minimal.json"
    out = _run_apply(
        ["--dry-run", "--proposal", str(proposal)],
        tmp_path,
        stub="claude_ok",
    )
    assert out.returncode == 0, (out.returncode, out.stdout, out.stderr)


# ---------------------------------------------------------------------------
# Acceptance #7 — fresh-machine create.
# ---------------------------------------------------------------------------


def test_acc07_fresh_machine_create(tmp_path: Path) -> None:
    """Apply on a fresh ~/.claude creates settings.json mode 0600."""
    proposal = FIXTURES / "proposal_minimal.json"
    expected_hash = _proposal_hash(proposal, base_obj={})
    out = _run_apply(
        [
            "--proposal", str(proposal),
            "--approved-canonical-hash", expected_hash,
        ],
        tmp_path,
        stub="claude_ok",
    )
    assert out.returncode == 0, (out.returncode, out.stdout, out.stderr)
    settings_path = tmp_path / ".claude" / "settings.json"
    assert settings_path.exists()
    mode = settings_path.stat().st_mode & 0o777
    assert mode == 0o600, oct(mode)


# ---------------------------------------------------------------------------
# Acceptance #8 — backup file mode 0600.
# ---------------------------------------------------------------------------


def test_acc08_backup_mode_0600(tmp_path: Path) -> None:
    """The backup file written before atomic replace has mode 0600."""
    _seed_settings(tmp_path, {"existing": True})
    proposal = FIXTURES / "proposal_minimal.json"
    expected_hash = _proposal_hash(proposal, base_obj={"existing": True})
    out = _run_apply(
        [
            "--proposal", str(proposal),
            "--approved-canonical-hash", expected_hash,
        ],
        tmp_path,
        stub="claude_ok",
    )
    assert out.returncode == 0, (out.returncode, out.stdout, out.stderr)
    backups = list((tmp_path / ".claude").glob("settings.json.bak.*"))
    assert backups, "no backup written"
    for bk in backups:
        mode = bk.stat().st_mode & 0o777
        assert mode == 0o600, (str(bk), oct(mode))


# ---------------------------------------------------------------------------
# Acceptance #10 — critique exit non-zero is hard fail.
# ---------------------------------------------------------------------------


def test_acc10_critique_nonzero_hardfail(tmp_path: Path) -> None:
    """Stub claude returning exit 2 -> apply exits 3 (CritiqueFailed)."""
    proposal = FIXTURES / "proposal_minimal.json"
    expected_hash = _proposal_hash(proposal, base_obj={})
    out = _run_apply(
        [
            "--proposal", str(proposal),
            "--approved-canonical-hash", expected_hash,
        ],
        tmp_path,
        stub="claude_fail",
    )
    assert out.returncode == 3, (out.returncode, out.stdout, out.stderr)


# ---------------------------------------------------------------------------
# Acceptance #11 — contract drift.
# ---------------------------------------------------------------------------


def test_acc11_contract_drift_hardfail(tmp_path: Path) -> None:
    """Stub emitting `## Severe issues` (no `## Major issues`) exits 3."""
    proposal = FIXTURES / "proposal_minimal.json"
    out = _run_apply(
        ["--dry-run", "--proposal", str(proposal)],
        tmp_path,
        stub="claude_drift",
    )
    assert out.returncode == 3, (out.returncode, out.stdout, out.stderr)
    assert "missing required" in out.stderr.lower()


# ---------------------------------------------------------------------------
# Acceptance #12 — hash mismatch.
# ---------------------------------------------------------------------------


def test_acc12_hash_mismatch(tmp_path: Path) -> None:
    """Wrong --approved-canonical-hash exits 8 (HashMismatchError)."""
    proposal = FIXTURES / "proposal_minimal.json"
    out = _run_apply(
        [
            "--proposal", str(proposal),
            "--approved-canonical-hash", "0" * 64,
        ],
        tmp_path,
        stub="claude_ok",
    )
    assert out.returncode == 8, (out.returncode, out.stdout, out.stderr)


# ---------------------------------------------------------------------------
# Acceptance #13 — migrate drop-all empties environment to $defaults.
# ---------------------------------------------------------------------------


def test_acc13_migrate_drop_all(tmp_path: Path) -> None:
    """drop-all leaves only the $defaults sentinel in environment."""
    _seed_settings(
        tmp_path,
        {
            "autoMode": {
                "environment": [
                    "$defaults",
                    "claim 1",
                    "claim 2",
                ],
                "allow": ["$defaults"],
                "soft_deny": ["$defaults"],
            }
        },
    )
    proposal = tmp_path / "empty.json"
    proposal.write_text("{}\n")
    # Compute expected hash with drop-all applied.
    base = json.loads((tmp_path / ".claude" / "settings.json").read_bytes())
    base["autoMode"]["environment"] = ["$defaults"]
    canonical = _canonical.canonicalize(base)
    expected = hashlib.sha256(canonical).hexdigest()
    out = _run_apply(
        [
            "--mode", "migrate",
            "--proposal", str(proposal),
            "--migrate-strategy", "drop-all",
            "--approved-canonical-hash", expected,
        ],
        tmp_path,
        stub="claude_ok",
    )
    assert out.returncode == 0, (out.returncode, out.stdout, out.stderr)
    final = json.loads((tmp_path / ".claude" / "settings.json").read_bytes())
    assert final["autoMode"]["environment"] == ["$defaults"]


# ---------------------------------------------------------------------------
# Acceptance #14 — migrate keep-all is byte-equal to base.
# ---------------------------------------------------------------------------


def test_acc14_migrate_keep_all_byte_equal(tmp_path: Path) -> None:
    """keep-all + empty proposal produces canonical bytes equal to base."""
    base = {
        "autoMode": {
            "environment": ["$defaults", "claim A"],
            "allow": ["$defaults"],
            "soft_deny": ["$defaults"],
        }
    }
    settings_path = _seed_settings(tmp_path, base)
    base_bytes = settings_path.read_bytes()
    proposal = tmp_path / "empty.json"
    proposal.write_text("{}\n")
    expected = hashlib.sha256(base_bytes).hexdigest()
    out = _run_apply(
        [
            "--mode", "migrate",
            "--proposal", str(proposal),
            "--migrate-strategy", "keep-all",
            "--approved-canonical-hash", expected,
        ],
        tmp_path,
        stub="claude_ok",
    )
    assert out.returncode == 0, (out.returncode, out.stdout, out.stderr)
    final = settings_path.read_bytes()
    assert final == base_bytes


# ---------------------------------------------------------------------------
# Acceptance #15 — `__example_only` substring in user rule survives.
# ---------------------------------------------------------------------------


def test_acc15_example_only_anti_test(tmp_path: Path) -> None:
    """Wrapper dict is stripped; literal substring inside string survives."""
    proposal_obj = {
        "autoMode": {
            "environment": [
                "$defaults",
                "I sometimes write the literal string __example_only in my notes.",
                {"__example_only": True, "value": "should be stripped"},
            ],
        }
    }
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_bytes(json.dumps(proposal_obj).encode())
    expected = _proposal_hash(proposal_path, base_obj={})
    out = _run_apply(
        [
            "--proposal", str(proposal_path),
            "--approved-canonical-hash", expected,
        ],
        tmp_path,
        stub="claude_ok",
    )
    assert out.returncode == 0, (out.returncode, out.stdout, out.stderr)
    final = json.loads((tmp_path / ".claude" / "settings.json").read_bytes())
    env = final["autoMode"]["environment"]
    assert "$defaults" in env
    assert any("__example_only" in e for e in env if isinstance(e, str))
    assert all(not isinstance(e, dict) for e in env)


# ---------------------------------------------------------------------------
# Acceptance #16 — missing claude CLI loud-fail (exit 5).
# ---------------------------------------------------------------------------


def test_acc16_missing_claude_cli(tmp_path: Path) -> None:
    """No `claude` on PATH -> exit 5 with installation pointer."""
    proposal = FIXTURES / "proposal_minimal.json"
    out = _run_apply(
        ["--dry-run", "--proposal", str(proposal)],
        tmp_path,
        stub=None,
    )
    assert out.returncode == 5, (out.returncode, out.stdout, out.stderr)
    assert "claude.com" in out.stderr or "claude" in out.stderr.lower()


# ---------------------------------------------------------------------------
# Acceptance #17 — stranded-state detection.
# ---------------------------------------------------------------------------


def test_acc17_stranded_state(tmp_path: Path) -> None:
    """An orphan .preview-orig.<pid> aborts startup with exit 9."""
    claude = tmp_path / ".claude"
    claude.mkdir(parents=True)
    orphan = claude / ".auto-mode-config.preview-orig.99999"
    orphan.write_text("{}\n")
    proposal = FIXTURES / "proposal_minimal.json"
    out = _run_apply(
        ["--dry-run", "--proposal", str(proposal)],
        tmp_path,
        stub="claude_ok",
    )
    assert out.returncode == 9, (out.returncode, out.stdout, out.stderr)
    assert "preview-orig" in out.stderr


# ---------------------------------------------------------------------------
# Acceptance #18 — --repair restores from .preview-orig.
# ---------------------------------------------------------------------------


def test_acc18_repair_restores(tmp_path: Path) -> None:
    """--repair restores orphan to settings.json and is idempotent."""
    claude = tmp_path / ".claude"
    claude.mkdir(parents=True)
    orphan = claude / ".auto-mode-config.preview-orig.99999"
    rescued = {"autoMode": {"environment": ["$defaults", "rescued"]}}
    orphan.write_bytes(_canonical.canonicalize(rescued))
    out = _run_apply(["--repair"], tmp_path, stub="claude_ok")
    assert out.returncode == 0, (out.returncode, out.stdout, out.stderr)
    assert not orphan.exists()
    settings = claude / "settings.json"
    assert settings.exists()
    final = json.loads(settings.read_bytes())
    assert final == rescued
    # Idempotent: a second --repair on clean state still exits 0.
    out2 = _run_apply(["--repair"], tmp_path, stub="claude_ok")
    assert out2.returncode == 0


# ---------------------------------------------------------------------------
# Bonus — swap-file fallback refused without opt-in.
# ---------------------------------------------------------------------------


def test_swap_fallback_refused_without_optin(tmp_path: Path) -> None:
    """When --settings unsupported, no opt-in -> exit 1 with pointer."""
    proposal = FIXTURES / "proposal_minimal.json"
    out = _run_apply(
        ["--dry-run", "--proposal", str(proposal)],
        tmp_path,
        stub="claude_no_settings_flag",
    )
    assert out.returncode == 1, (out.returncode, out.stdout, out.stderr)
    assert "--allow-swap-file-fallback" in out.stderr


def test_swap_fallback_runs_with_optin(tmp_path: Path) -> None:
    """With --allow-swap-file-fallback, dry-run completes and restores."""
    proposal = FIXTURES / "proposal_minimal.json"
    out = _run_apply(
        [
            "--dry-run",
            "--proposal", str(proposal),
            "--allow-swap-file-fallback",
        ],
        tmp_path,
        stub="claude_no_settings_flag",
    )
    assert out.returncode == 0, (out.returncode, out.stdout, out.stderr)
    # No orphan left behind.
    leftovers = list((tmp_path / ".claude").glob(".auto-mode-config.preview-orig.*"))
    assert not leftovers


# ---------------------------------------------------------------------------
# inspect_automode coverage.
# ---------------------------------------------------------------------------


def test_inspect_absent_settings(tmp_path: Path) -> None:
    """inspect_automode prints stderr msg + exits 0 when settings absent."""
    out = _run_inspect([], tmp_path)
    assert out.returncode == 0, (out.returncode, out.stdout, out.stderr)
    assert "no autoMode config found" in out.stderr


def test_inspect_canonical_hash(tmp_path: Path) -> None:
    """inspect prints canonical bytes + last-line sha256."""
    obj = {"autoMode": {"environment": ["$defaults"]}}
    settings_path = _seed_settings(tmp_path, obj)
    canonical = settings_path.read_bytes()
    expected = hashlib.sha256(canonical).hexdigest()
    out = _run_inspect([], tmp_path)
    assert out.returncode == 0
    assert out.stdout.strip().splitlines()[-1] == f"canonical_sha256: {expected}"


def test_inspect_show_drift_clean(tmp_path: Path) -> None:
    """No drift when approved cache matches current canonical."""
    obj = {"autoMode": {"environment": ["$defaults"]}}
    settings_path = _seed_settings(tmp_path, obj)
    canonical = settings_path.read_bytes()
    approved = tmp_path / ".claude" / ".auto_mode_approved.json"
    approved.write_bytes(canonical)
    out = _run_inspect(["--show-drift"], tmp_path)
    assert out.returncode == 0, (out.returncode, out.stdout, out.stderr)
    assert "no drift" in out.stdout


def test_inspect_show_drift_changed(tmp_path: Path) -> None:
    """Drift mode exits 6 when approved cache differs from current."""
    obj = {"autoMode": {"environment": ["$defaults"]}}
    _seed_settings(tmp_path, obj)
    approved = tmp_path / ".claude" / ".auto_mode_approved.json"
    different = {"autoMode": {"environment": ["$defaults", "extra"]}}
    approved.write_bytes(_canonical.canonicalize(different))
    out = _run_inspect(["--show-drift"], tmp_path)
    assert out.returncode == 6, (out.returncode, out.stdout, out.stderr)
    assert "drift vs approved" in out.stdout
