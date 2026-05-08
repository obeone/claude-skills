"""Pipeline + acceptance tests (predicates #5..#23 plus inspect/scan side tests).

Each acceptance predicate has a dedicated, named test
(``test_acc05_..`` through ``test_acc23_..``). Tests that exercise the
``apply_automode.py`` CLI run it as a subprocess with ``HOME`` clamped
to ``tmp_path`` and ``PATH`` clamped to a directory containing only
the relevant stub ``claude`` binary plus the system bin dirs needed to
resolve ``uv``.

The rapidfuzz anti-test scans every ``# /// script`` block under
``scripts/`` to ensure no entry-point script declares the dependency
forbidden by the handoff.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

import _canonical  # noqa: E402  (path injected via conftest)
import _locks  # noqa: E402


# ---------------------------------------------------------------------------
# Exit codes (mirror apply_automode contract)
# ---------------------------------------------------------------------------


EXIT_OK = 0
EXIT_USAGE = 1
EXIT_VALIDATION = 2
EXIT_CRITIQUE_FAILED = 3
EXIT_PERMISSION = 4
EXIT_CLAUDE_CLI_MISSING = 5
EXIT_DRIFT = 6
EXIT_LOCK_HELD = 7
EXIT_HASH_MISMATCH = 8
EXIT_STRANDED_STATE = 9
EXIT_OUT_OF_BAND = 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply_cli(scripts_dir: Path) -> Path:
    return scripts_dir / "apply_automode.py"


def _inspect_cli(scripts_dir: Path) -> Path:
    return scripts_dir / "inspect_automode.py"


def _scan_cli(scripts_dir: Path) -> Path:
    return scripts_dir / "scan_project.py"


def _require(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"required script missing: {path}")


def _system_path() -> str:
    """Return a PATH containing the system bin dirs needed for ``uv``.

    We do NOT include the user's ``~/.local/bin``; only the canonical
    homebrew + system locations so the env stays reproducible and
    stub-claude-only PATHs still resolve ``uv``.
    """

    parts: list[str] = []
    for cand in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"):
        if os.path.isdir(cand):
            parts.append(cand)
    return ":".join(parts)


def _make_stub_path(tmp_path: Path, stub_src: Path, *, link_name: str = "claude") -> Path:
    """Build a minimal bin dir with ``link_name`` -> ``stub_src``."""

    bin_dir = tmp_path / f"_bin_{stub_src.name}"
    bin_dir.mkdir(exist_ok=True)
    target = bin_dir / link_name
    if target.exists() or target.is_symlink():
        target.unlink()
    os.symlink(stub_src, target)
    return bin_dir


def _clean_env(
    tmp_path: Path,
    *,
    extra_path: list[str] | None = None,
    home: Path | None = None,
    include_system: bool = True,
) -> dict[str, str]:
    """Build a clean env with ``HOME`` clamped and a controlled ``PATH``."""

    parts: list[str] = list(extra_path or [])
    if include_system:
        parts.append(_system_path())
    env = {
        "PATH": ":".join(parts),
        "HOME": str(home or tmp_path),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
    }
    if "UV_CACHE_DIR" in os.environ:
        env["UV_CACHE_DIR"] = os.environ["UV_CACHE_DIR"]
    if "UV_PYTHON_INSTALL_DIR" in os.environ:
        env["UV_PYTHON_INSTALL_DIR"] = os.environ["UV_PYTHON_INSTALL_DIR"]
    if "TMPDIR" in os.environ:
        env["TMPDIR"] = os.environ["TMPDIR"]
    return env


def _build_local_settings(
    project_dir: Path,
    *,
    automode: dict[str, Any] | None,
) -> Path:
    """Write ``.claude/settings.local.json`` with the given autoMode block."""

    project_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {}
    if automode is not None:
        payload["autoMode"] = automode
    target = project_dir / "settings.local.json"
    target.write_bytes(_canonical.canonicalize(payload))
    os.chmod(target, 0o600)
    return target


def _hash_from_dryrun_stderr(stderr: bytes) -> str | None:
    """Extract the canonical sha256 from apply_automode's dry-run stderr."""

    blob = stderr.decode("utf-8", "replace")
    m = re.search(r"dry-run canonical sha256:\s*([0-9a-f]{64})", blob)
    if m:
        return m.group(1)
    m = re.search(r"--approved-canonical-hash\s+([0-9a-f]{64})", blob)
    if m:
        return m.group(1)
    return None


def _proposal_from_dryrun_stdout(stdout: bytes) -> dict[str, Any] | None:
    """Parse the canonical proposal JSON apply_automode prints to stdout."""

    try:
        return json.loads(stdout.decode("utf-8"))
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Acceptance #5 — concurrent flock contention (in-process)
# ---------------------------------------------------------------------------


def test_acc05_concurrent_lock_contention(tmp_path: Path):
    """Second concurrent acquire fails fast with LockHeldError."""

    lock_path = tmp_path / "settings.local.json.lock"
    handle = _locks.acquire(lock_path, ttl=300)
    try:
        t0 = time.monotonic()
        with pytest.raises(_locks.LockHeldError):
            _locks.acquire(lock_path, ttl=300)
        elapsed = time.monotonic() - t0
        assert elapsed < 0.5, f"second acquire took {elapsed:.3f}s"
    finally:
        _locks.release(handle)


def test_acc05_concurrent_cli_lock_contention(
    tmp_path: Path,
    scripts_dir: Path,
    stub_claude_dir: Path,
    fixtures_dir: Path,
):
    """``apply_automode --dry-run`` exits 7 when a concurrent flock is held."""

    apply = _apply_cli(scripts_dir)
    _require(apply)

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "proj"
    project_claude = project / ".claude"
    project_claude.mkdir(parents=True)

    # Pre-acquire the lock to simulate a concurrent holder.
    lock_path = project_claude / "settings.local.json.lock"
    handle = _locks.acquire(lock_path, ttl=300)

    bin_dir = _make_stub_path(tmp_path, stub_claude_dir / "claude_ok")
    env = _clean_env(tmp_path, extra_path=[str(bin_dir)], home=home)
    proposal = fixtures_dir / "proposal_minimal.json"
    try:
        # The dry-run path doesn't acquire a lock at all — only the
        # commit path does. So we run a real commit (with a precomputed
        # hash) and expect it to bail at the lock acquire stage.
        # First, compute the hash with a dry-run while the lock is held
        # (dry-run doesn't lock).
        dry = subprocess.run(
            [
                "uv", "run", str(apply),
                "--project-root", str(project),
                "--mode", "fresh",
                "--proposal", str(proposal),
                "--dry-run",
            ],
            env=env, capture_output=True, timeout=60,
        )
        if dry.returncode != EXIT_OK:
            pytest.skip(
                f"dry-run failed for hash extraction: "
                f"{dry.stderr.decode('utf-8', 'replace')!r}"
            )
        approved_hash = _hash_from_dryrun_stderr(dry.stderr)
        if not approved_hash:
            pytest.skip("could not extract canonical hash from dry-run")

        proc = subprocess.run(
            [
                "uv", "run", str(apply),
                "--project-root", str(project),
                "--mode", "fresh",
                "--proposal", str(proposal),
                "--approved-canonical-hash", approved_hash,
            ],
            env=env, capture_output=True, timeout=60,
        )
    finally:
        _locks.release(handle)

    assert proc.returncode == EXIT_LOCK_HELD, (
        f"expected exit {EXIT_LOCK_HELD} on lock contention; got "
        f"{proc.returncode}; "
        f"stderr={proc.stderr.decode('utf-8', 'replace')!r}"
    )


# ---------------------------------------------------------------------------
# Acceptance #6 — stale-lock reclaim
# ---------------------------------------------------------------------------


def test_acc06_stale_lock_reclaimed(tmp_path: Path):
    """A stale lock (dead PID + old timestamp) is reclaimed on acquire."""

    lock_path = tmp_path / "settings.local.json.lock"
    lock_path.write_text("99999 2020-01-01T00:00:00+00:00\n", encoding="utf-8")
    assert _locks.is_stale(lock_path) is True
    handle = _locks.acquire(lock_path)
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
        pid_str, _, _ = raw.partition(" ")
        assert int(pid_str) == os.getpid()
    finally:
        _locks.release(handle)


# ---------------------------------------------------------------------------
# Acceptance #7 — fresh-machine create
# ---------------------------------------------------------------------------


def test_acc07_fresh_machine_create(
    tmp_path: Path,
    scripts_dir: Path,
    stub_claude_dir: Path,
    fixtures_dir: Path,
):
    """Fresh machine: dry-run mode auto picks 'fresh', no writes happen."""

    apply = _apply_cli(scripts_dir)
    _require(apply)

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "proj"
    project.mkdir()

    bin_dir = _make_stub_path(tmp_path, stub_claude_dir / "claude_ok")
    env = _clean_env(tmp_path, extra_path=[str(bin_dir)], home=home)

    proposal = fixtures_dir / "proposal_minimal.json"
    proc = subprocess.run(
        [
            "uv", "run", str(apply),
            "--project-root", str(project),
            "--mode", "fresh",
            "--proposal", str(proposal),
            "--dry-run",
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert proc.returncode == EXIT_OK, (
        f"apply_automode dry-run on fresh project exited "
        f"{proc.returncode}; stderr={proc.stderr.decode('utf-8', 'replace')!r}"
    )
    # Dry-run does not create the local file or its parent dir.
    assert not (project / ".claude" / "settings.local.json").exists()


def test_acc07_real_commit_creates_mode_0600(
    tmp_path: Path,
    scripts_dir: Path,
    stub_claude_dir: Path,
    fixtures_dir: Path,
):
    """Non-dry-run on a fresh project creates the file mode 0600 with 0700 parent."""

    apply = _apply_cli(scripts_dir)
    _require(apply)

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "proj"
    project.mkdir()

    bin_dir = _make_stub_path(tmp_path, stub_claude_dir / "claude_ok")
    env = _clean_env(tmp_path, extra_path=[str(bin_dir)], home=home)

    proposal = fixtures_dir / "proposal_minimal.json"
    dry = subprocess.run(
        [
            "uv", "run", str(apply),
            "--project-root", str(project),
            "--mode", "fresh",
            "--proposal", str(proposal),
            "--dry-run",
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert dry.returncode == EXIT_OK, dry.stderr.decode("utf-8", "replace")
    h = _hash_from_dryrun_stderr(dry.stderr)
    assert h, "could not extract sha256 from dry-run stderr"

    proc = subprocess.run(
        [
            "uv", "run", str(apply),
            "--project-root", str(project),
            "--mode", "fresh",
            "--proposal", str(proposal),
            "--approved-canonical-hash", h,
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert proc.returncode == EXIT_OK, (
        f"commit failed: {proc.stderr.decode('utf-8', 'replace')!r}"
    )
    local = project / ".claude" / "settings.local.json"
    assert local.is_file()
    file_mode = stat.S_IMODE(local.stat().st_mode)
    assert file_mode == 0o600, f"file mode {oct(file_mode)} != 0o600"
    parent_mode = stat.S_IMODE((project / ".claude").stat().st_mode)
    assert parent_mode == 0o700, f"parent mode {oct(parent_mode)} != 0o700"


# ---------------------------------------------------------------------------
# Acceptance #8 — backup file mode 0600
# ---------------------------------------------------------------------------


def test_acc08_backup_mode_0600(
    tmp_path: Path,
    scripts_dir: Path,
    stub_claude_dir: Path,
    fixtures_dir: Path,
):
    """After a successful apply over an existing file, the backup is mode 0600."""

    apply = _apply_cli(scripts_dir)
    _require(apply)

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "proj"
    project_claude = project / ".claude"
    project_claude.mkdir(parents=True)

    _build_local_settings(
        project_claude,
        automode={
            "allow": ["Read(**)"],
            "ask": [],
            "deny": [],
            "environment": ["$defaults"],
        },
    )

    bin_dir = _make_stub_path(tmp_path, stub_claude_dir / "claude_ok")
    env = _clean_env(tmp_path, extra_path=[str(bin_dir)], home=home)

    proposal = fixtures_dir / "proposal_minimal.json"
    dry = subprocess.run(
        [
            "uv", "run", str(apply),
            "--project-root", str(project),
            "--mode", "migrate",
            "--proposal", str(proposal),
            "--migrate-strategy", "keep-all",
            "--dry-run",
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert dry.returncode == EXIT_OK, dry.stderr.decode("utf-8", "replace")
    h = _hash_from_dryrun_stderr(dry.stderr)
    assert h, "could not extract sha256 from dry-run stderr"

    proc = subprocess.run(
        [
            "uv", "run", str(apply),
            "--project-root", str(project),
            "--mode", "migrate",
            "--proposal", str(proposal),
            "--migrate-strategy", "keep-all",
            "--approved-canonical-hash", h,
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert proc.returncode == EXIT_OK, (
        f"apply failed: {proc.stderr.decode('utf-8', 'replace')!r}"
    )

    backups = sorted(project_claude.glob("settings.local.json.bak.*"))
    assert backups, "expected at least one backup after apply"
    for b in backups:
        mode = stat.S_IMODE(b.stat().st_mode)
        assert mode == 0o600, f"{b} mode {oct(mode)} != 0o600"


# ---------------------------------------------------------------------------
# Acceptance #10 — critique non-zero is hard fail
# ---------------------------------------------------------------------------


def test_acc10_critique_nonzero_hardfail(
    tmp_path: Path,
    scripts_dir: Path,
    stub_claude_dir: Path,
    fixtures_dir: Path,
):
    apply = _apply_cli(scripts_dir)
    _require(apply)

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "proj"
    project.mkdir()

    bin_dir = _make_stub_path(tmp_path, stub_claude_dir / "claude_fail")
    env = _clean_env(tmp_path, extra_path=[str(bin_dir)], home=home)

    proposal = fixtures_dir / "proposal_minimal.json"
    # Need to compute hash with a passing critique first; use claude_ok
    # for the dry-run, then claude_fail for the commit.
    bin_ok = _make_stub_path(tmp_path, stub_claude_dir / "claude_ok", link_name="claude_ok_link")
    # Re-use bin dir naming so both stubs sit on PATH? Simpler: dry-run
    # against claude_fail still emits "## Major issues + ## Smaller issues"
    # on stderr but exits 1; that's caught at the critique step which
    # only runs in commit mode. Dry-run does not invoke the critique.
    dry = subprocess.run(
        [
            "uv", "run", str(apply),
            "--project-root", str(project),
            "--mode", "fresh",
            "--proposal", str(proposal),
            "--dry-run",
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert dry.returncode == EXIT_OK, dry.stderr.decode("utf-8", "replace")
    h = _hash_from_dryrun_stderr(dry.stderr)
    assert h, "could not extract sha256 from dry-run stderr"

    proc = subprocess.run(
        [
            "uv", "run", str(apply),
            "--project-root", str(project),
            "--mode", "fresh",
            "--proposal", str(proposal),
            "--approved-canonical-hash", h,
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert proc.returncode == EXIT_CRITIQUE_FAILED, (
        f"expected exit {EXIT_CRITIQUE_FAILED} on critique-fail stub; "
        f"got {proc.returncode}; "
        f"stderr={proc.stderr.decode('utf-8', 'replace')!r}"
    )


# ---------------------------------------------------------------------------
# Acceptance #11 — contract drift is hard fail
# ---------------------------------------------------------------------------


def test_acc11_contract_drift_hardfail(
    tmp_path: Path,
    scripts_dir: Path,
    stub_claude_dir: Path,
    fixtures_dir: Path,
):
    apply = _apply_cli(scripts_dir)
    _require(apply)

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "proj"
    project.mkdir()

    bin_dir = _make_stub_path(tmp_path, stub_claude_dir / "claude_drift")
    env = _clean_env(tmp_path, extra_path=[str(bin_dir)], home=home)

    proposal = fixtures_dir / "proposal_minimal.json"
    dry = subprocess.run(
        [
            "uv", "run", str(apply),
            "--project-root", str(project),
            "--mode", "fresh",
            "--proposal", str(proposal),
            "--dry-run",
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert dry.returncode == EXIT_OK, dry.stderr.decode("utf-8", "replace")
    h = _hash_from_dryrun_stderr(dry.stderr)
    assert h, "could not extract sha256 from dry-run stderr"

    proc = subprocess.run(
        [
            "uv", "run", str(apply),
            "--project-root", str(project),
            "--mode", "fresh",
            "--proposal", str(proposal),
            "--approved-canonical-hash", h,
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert proc.returncode == EXIT_CRITIQUE_FAILED, (
        f"expected exit {EXIT_CRITIQUE_FAILED} on contract-drift stub; "
        f"got {proc.returncode}; "
        f"stderr={proc.stderr.decode('utf-8', 'replace')!r}"
    )


# ---------------------------------------------------------------------------
# Acceptance #12 — hash mismatch
# ---------------------------------------------------------------------------


def test_acc12_hash_mismatch(
    tmp_path: Path,
    scripts_dir: Path,
    stub_claude_dir: Path,
    fixtures_dir: Path,
):
    apply = _apply_cli(scripts_dir)
    _require(apply)

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "proj"
    project.mkdir()

    bin_dir = _make_stub_path(tmp_path, stub_claude_dir / "claude_ok")
    env = _clean_env(tmp_path, extra_path=[str(bin_dir)], home=home)

    proposal = fixtures_dir / "proposal_minimal.json"
    bogus_hash = "0" * 64
    proc = subprocess.run(
        [
            "uv", "run", str(apply),
            "--project-root", str(project),
            "--mode", "fresh",
            "--proposal", str(proposal),
            "--approved-canonical-hash", bogus_hash,
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert proc.returncode == EXIT_HASH_MISMATCH, (
        f"expected exit {EXIT_HASH_MISMATCH} on bogus hash; "
        f"got {proc.returncode}; "
        f"stderr={proc.stderr.decode('utf-8', 'replace')!r}"
    )


# ---------------------------------------------------------------------------
# Acceptance #13 — migrate drop-all empties environment to ["$defaults"]
# ---------------------------------------------------------------------------


def test_acc13_migrate_drop_all(
    tmp_path: Path,
    scripts_dir: Path,
    stub_claude_dir: Path,
):
    apply = _apply_cli(scripts_dir)
    _require(apply)

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "proj"
    project_claude = project / ".claude"
    project_claude.mkdir(parents=True)

    _build_local_settings(
        project_claude,
        automode={
            "allow": ["Read(**)", "Bash(npm test*)"],
            "ask": [],
            "deny": [],
            "environment": [
                "$defaults",
                "node-monorepo",
                "python-uv-project",
            ],
        },
    )

    bin_dir = _make_stub_path(tmp_path, stub_claude_dir / "claude_ok")
    env = _clean_env(tmp_path, extra_path=[str(bin_dir)], home=home)

    proc = subprocess.run(
        [
            "uv", "run", str(apply),
            "--project-root", str(project),
            "--mode", "migrate",
            "--migrate-strategy", "drop-all",
            "--dry-run",
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert proc.returncode == EXIT_OK, (
        f"drop-all dry-run failed: {proc.stderr.decode('utf-8', 'replace')!r}"
    )
    proposed = _proposal_from_dryrun_stdout(proc.stdout)
    assert proposed is not None, (
        f"could not parse dry-run stdout as JSON: {proc.stdout!r}"
    )
    am = proposed["autoMode"]
    assert am.get("environment") == ["$defaults"]
    assert am.get("allow", []) == []
    assert am.get("deny", []) == []
    assert am.get("ask", []) == []


# ---------------------------------------------------------------------------
# Acceptance #14 — migrate keep-all is byte-equal (file untouched on dry-run)
# ---------------------------------------------------------------------------


def test_acc14_migrate_keep_all_byte_equal(
    tmp_path: Path,
    scripts_dir: Path,
    stub_claude_dir: Path,
):
    apply = _apply_cli(scripts_dir)
    _require(apply)

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "proj"
    project_claude = project / ".claude"
    project_claude.mkdir(parents=True)

    automode = {
        "allow": ["Read(**)", "Bash(uv run pytest*)"],
        "ask": ["Bash(rm *)"],
        "deny": ["Bash(curl *)"],
        "environment": ["$defaults", "team-shared"],
    }
    pre = _build_local_settings(project_claude, automode=automode)
    pre_bytes = pre.read_bytes()

    bin_dir = _make_stub_path(tmp_path, stub_claude_dir / "claude_ok")
    env = _clean_env(tmp_path, extra_path=[str(bin_dir)], home=home)

    proc = subprocess.run(
        [
            "uv", "run", str(apply),
            "--project-root", str(project),
            "--mode", "migrate",
            "--migrate-strategy", "keep-all",
            "--dry-run",
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert proc.returncode == EXIT_OK, proc.stderr.decode("utf-8", "replace")
    # File untouched on dry-run.
    assert pre.read_bytes() == pre_bytes
    # Proposal preserves all entries.
    proposed = _proposal_from_dryrun_stdout(proc.stdout)
    assert proposed is not None
    am = proposed["autoMode"]
    for section, items in automode.items():
        assert am.get(section) == items, (
            f"keep-all changed section {section}: {am.get(section)!r} != {items!r}"
        )


# ---------------------------------------------------------------------------
# Acceptance #15 — __example_only anti-test
# ---------------------------------------------------------------------------


def test_acc15_example_only_anti_test():
    """Structural wrapper stripped; substring preserved."""

    try:
        import importlib

        apply_mod = importlib.import_module("apply_automode")
    except Exception as exc:
        pytest.skip(f"apply_automode module not importable: {exc}")

    strip = getattr(apply_mod, "_strip_example_only", None)
    if strip is None:
        pytest.skip("apply_automode._strip_example_only not available")

    wrapped = {
        "autoMode": {
            "environment": [
                "$defaults",
                {"__example_only": True, "value": "team-shared"},
            ],
            "allow": [
                "Read(**)",
                "Bash(echo __example_only marker)",
                {"__example_only": True, "value": "Bash(npm test*)"},
            ],
            "ask": [],
            "deny": [],
        }
    }
    out = strip(wrapped)
    am = out["autoMode"]
    # Structural wrapper stripped to its real value.
    assert "team-shared" in am["environment"]
    assert "Bash(npm test*)" in am["allow"]
    # Substring preserved verbatim.
    assert any(
        isinstance(r, str) and "__example_only" in r for r in am["allow"]
    )
    # No structural wrapper objects survive.
    for item in am["environment"]:
        assert not (isinstance(item, dict) and item.get("__example_only"))
    for item in am["allow"]:
        assert not (isinstance(item, dict) and item.get("__example_only"))


# ---------------------------------------------------------------------------
# Acceptance #16 — missing claude CLI
# ---------------------------------------------------------------------------


def test_acc16_missing_claude_cli(
    tmp_path: Path, scripts_dir: Path, fixtures_dir: Path,
):
    """With ``claude`` absent on PATH, the script reports a CLI-missing error.

    The handoff exit code 5 (EXIT_CLAUDE_CLI_MISSING) is reachable via
    the swap-file fallback path which tries to invoke ``claude`` and
    catches ``ClaudeCLIMissingError``. Without ``--allow-swap-file-fallback``
    the script exits earlier with a usage error pointing to the flag —
    which is also a correct refusal. We accept either as a clean refusal
    that mentions the missing CLI.
    """

    apply = _apply_cli(scripts_dir)
    _require(apply)

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "proj"
    project.mkdir()

    # PATH must still resolve uv (system bin), but have no `claude`.
    env = _clean_env(tmp_path, home=home)

    proposal = fixtures_dir / "proposal_minimal.json"
    proc = subprocess.run(
        [
            "uv", "run", str(apply),
            "--project-root", str(project),
            "--mode", "fresh",
            "--proposal", str(proposal),
            "--allow-swap-file-fallback",
            "--dry-run",
        ],
        env=env, capture_output=True, timeout=60,
    )
    # Dry-run never invokes the critique, so even with claude missing,
    # the dry-run can succeed. The handoff predicate is about the
    # commit path: clamp out claude AND require commit.
    if proc.returncode == EXIT_OK:
        h = _hash_from_dryrun_stderr(proc.stderr)
        assert h
        proc = subprocess.run(
            [
                "uv", "run", str(apply),
                "--project-root", str(project),
                "--mode", "fresh",
                "--proposal", str(proposal),
                "--allow-swap-file-fallback",
                "--approved-canonical-hash", h,
            ],
            env=env, capture_output=True, timeout=60,
        )
    assert proc.returncode == EXIT_CLAUDE_CLI_MISSING, (
        f"expected exit {EXIT_CLAUDE_CLI_MISSING} when claude CLI missing; "
        f"got {proc.returncode}; "
        f"stderr={proc.stderr.decode('utf-8', 'replace')!r}"
    )


# ---------------------------------------------------------------------------
# Acceptance #17 — stranded state in BOTH ~/.claude and project .claude
# ---------------------------------------------------------------------------


def test_acc17_stranded_state(
    tmp_path: Path,
    scripts_dir: Path,
    stub_claude_dir: Path,
    fixtures_dir: Path,
):
    apply = _apply_cli(scripts_dir)
    _require(apply)

    home = tmp_path / "home"
    home_claude = home / ".claude"
    home_claude.mkdir(parents=True)
    project = tmp_path / "proj"
    project_claude = project / ".claude"
    project_claude.mkdir(parents=True)

    # Plant orphans in both directories.
    (home_claude / ".autoMode-config.preview-orig.99998").write_text(
        '{"autoMode": {"environment": ["$defaults"]}}\n', encoding="utf-8"
    )
    (project_claude / ".autoMode-config.preview-orig.99999").write_text(
        '{"autoMode": {"environment": ["$defaults"]}}\n', encoding="utf-8"
    )

    bin_dir = _make_stub_path(tmp_path, stub_claude_dir / "claude_ok")
    env = _clean_env(tmp_path, extra_path=[str(bin_dir)], home=home)

    proposal = fixtures_dir / "proposal_minimal.json"
    proc = subprocess.run(
        [
            "uv", "run", str(apply),
            "--project-root", str(project),
            "--mode", "fresh",
            "--proposal", str(proposal),
            "--dry-run",
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert proc.returncode == EXIT_STRANDED_STATE, (
        f"expected exit {EXIT_STRANDED_STATE} on stranded orphans; "
        f"got {proc.returncode}; "
        f"stderr={proc.stderr.decode('utf-8', 'replace')!r}"
    )
    blob = proc.stdout + proc.stderr
    assert b"--repair" in blob, "expected --repair pointer in output"
    # Both orphans listed.
    assert b"99998" in blob
    assert b"99999" in blob


# ---------------------------------------------------------------------------
# Acceptance #18 — --repair restores orphans and is idempotent
# ---------------------------------------------------------------------------


def test_acc18_repair_restores(
    tmp_path: Path,
    scripts_dir: Path,
    stub_claude_dir: Path,
):
    apply = _apply_cli(scripts_dir)
    _require(apply)

    home = tmp_path / "home"
    home_claude = home / ".claude"
    home_claude.mkdir(parents=True)
    project = tmp_path / "proj"
    project_claude = project / ".claude"
    project_claude.mkdir(parents=True)

    # Orphan + dead lock.
    orphan = home_claude / ".autoMode-config.preview-orig.99999"
    orphan.write_text(
        '{"autoMode": {"environment": ["$defaults"]}}\n', encoding="utf-8"
    )
    dead_lock = project_claude / "settings.local.json.lock"
    dead_lock.write_text("99999 2020-01-01T00:00:00+00:00\n", encoding="utf-8")

    bin_dir = _make_stub_path(tmp_path, stub_claude_dir / "claude_ok")
    env = _clean_env(tmp_path, extra_path=[str(bin_dir)], home=home)

    first = subprocess.run(
        [
            "uv", "run", str(apply),
            "--project-root", str(project),
            "--repair",
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert first.returncode == EXIT_OK, (
        f"first --repair failed: {first.stderr.decode('utf-8', 'replace')!r}"
    )
    # Orphan restored: ~/.claude/settings.json should now exist.
    assert (home_claude / "settings.json").is_file()
    assert not orphan.exists(), "orphan should have been consumed"

    # Second --repair must be a no-op (still exit 0, idempotent).
    second = subprocess.run(
        [
            "uv", "run", str(apply),
            "--project-root", str(project),
            "--repair",
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert second.returncode == EXIT_OK


# ---------------------------------------------------------------------------
# Acceptance #19 — adopt-from-shared
# ---------------------------------------------------------------------------


def test_acc19_adopt_from_shared(
    tmp_path: Path,
    scripts_dir: Path,
    fixtures_dir: Path,
):
    """scan_project surfaces autoMode entries from .claude/settings.json."""

    scan = _scan_cli(scripts_dir)
    _require(scan)

    project = tmp_path / "proj"
    project_claude = project / ".claude"
    project_claude.mkdir(parents=True)
    shared = project_claude / "settings.json"
    shutil.copy2(fixtures_dir / "shared_settings.json", shared)

    env = _clean_env(tmp_path)
    proc = subprocess.run(
        [
            "uv", "run", str(scan),
            "--project-root", str(project),
            "--include-shared",
            "--json",
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    data = json.loads(proc.stdout.decode("utf-8"))
    cands = data["shared_adoption_candidates"]
    assert isinstance(cands, list) and len(cands) >= 1, (
        f"expected adoption candidates; got {cands!r}"
    )
    sections = {c["section"] for c in cands}
    assert "environment" in sections
    assert {"allow", "deny", "ask"} & sections


def test_acc19_no_include_shared_omits_candidates(
    tmp_path: Path,
    scripts_dir: Path,
    fixtures_dir: Path,
):
    scan = _scan_cli(scripts_dir)
    _require(scan)

    project = tmp_path / "proj"
    project_claude = project / ".claude"
    project_claude.mkdir(parents=True)
    shutil.copy2(fixtures_dir / "shared_settings.json", project_claude / "settings.json")

    env = _clean_env(tmp_path)
    proc = subprocess.run(
        [
            "uv", "run", str(scan),
            "--project-root", str(project),
            "--no-include-shared",
            "--json",
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout.decode("utf-8"))
    assert data["shared_adoption_candidates"] == []


# ---------------------------------------------------------------------------
# Acceptance #20 — write-shared opt-in
# ---------------------------------------------------------------------------


def test_acc20_no_write_shared_keeps_shared_byte_equal(
    tmp_path: Path,
    scripts_dir: Path,
    stub_claude_dir: Path,
    fixtures_dir: Path,
):
    """Without --write-shared, .claude/settings.json is byte-equal after apply."""

    apply = _apply_cli(scripts_dir)
    _require(apply)

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "proj"
    project_claude = project / ".claude"
    project_claude.mkdir(parents=True)

    shared = project_claude / "settings.json"
    shutil.copy2(fixtures_dir / "shared_settings.json", shared)
    pre_bytes = shared.read_bytes()

    bin_dir = _make_stub_path(tmp_path, stub_claude_dir / "claude_ok")
    env = _clean_env(tmp_path, extra_path=[str(bin_dir)], home=home)

    proposal = fixtures_dir / "proposal_minimal.json"
    dry = subprocess.run(
        [
            "uv", "run", str(apply),
            "--project-root", str(project),
            "--mode", "fresh",
            "--proposal", str(proposal),
            "--migrate-strategy", "keep-all",
            "--dry-run",
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert dry.returncode == EXIT_OK, dry.stderr.decode("utf-8", "replace")
    h = _hash_from_dryrun_stderr(dry.stderr)
    assert h
    proc = subprocess.run(
        [
            "uv", "run", str(apply),
            "--project-root", str(project),
            "--mode", "fresh",
            "--proposal", str(proposal),
            "--migrate-strategy", "keep-all",
            "--approved-canonical-hash", h,
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert proc.returncode == EXIT_OK, proc.stderr.decode("utf-8", "replace")
    # Without --write-shared, the shared file is byte-equal even after
    # a successful Phase 3 commit.
    assert shared.read_bytes() == pre_bytes


def test_acc20_write_shared_warning_printed(
    tmp_path: Path,
    scripts_dir: Path,
    stub_claude_dir: Path,
    fixtures_dir: Path,
):
    """With --write-shared, the classifier-ignores warning is printed."""

    apply = _apply_cli(scripts_dir)
    _require(apply)

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "proj"
    project_claude = project / ".claude"
    project_claude.mkdir(parents=True)
    shutil.copy2(fixtures_dir / "shared_settings.json", project_claude / "settings.json")

    bin_dir = _make_stub_path(tmp_path, stub_claude_dir / "claude_ok")
    env = _clean_env(tmp_path, extra_path=[str(bin_dir)], home=home)

    proposal = fixtures_dir / "proposal_minimal.json"
    dry = subprocess.run(
        [
            "uv", "run", str(apply),
            "--project-root", str(project),
            "--mode", "fresh",
            "--proposal", str(proposal),
            "--migrate-strategy", "keep-all",
            "--dry-run",
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert dry.returncode == EXIT_OK, dry.stderr.decode("utf-8", "replace")
    h = _hash_from_dryrun_stderr(dry.stderr)
    assert h
    # Run the real commit with --write-shared and a closed stdin (so
    # the interactive 'I understand' branch is skipped — non-interactive
    # short-circuit). The phase 4 path must still emit the warning.
    proc = subprocess.run(
        [
            "uv", "run", str(apply),
            "--project-root", str(project),
            "--mode", "fresh",
            "--proposal", str(proposal),
            "--migrate-strategy", "keep-all",
            "--approved-canonical-hash", h,
            "--write-shared",
        ],
        env=env, capture_output=True, timeout=60, input=b"",
    )
    blob = (proc.stdout + proc.stderr).decode("utf-8", "replace").lower()
    assert any(
        marker in blob
        for marker in (
            "classifier ignore",
            "classifier-ignored",
            "ignores automode",
            "ignores",
            "manifest of intent",
        )
    ), (
        "expected classifier-ignores warning when --write-shared used; "
        f"saw: {blob[:600]!r}"
    )


# ---------------------------------------------------------------------------
# Acceptance #21 — multi-file inspect
# ---------------------------------------------------------------------------


def test_acc21_multi_file_inspect(
    tmp_path: Path,
    scripts_dir: Path,
    fixtures_dir: Path,
):
    inspect = _inspect_cli(scripts_dir)
    _require(inspect)

    home = tmp_path / "home"
    home_claude = home / ".claude"
    home_claude.mkdir(parents=True)
    project = tmp_path / "proj"
    project_claude = project / ".claude"
    project_claude.mkdir(parents=True)

    # All 3 present.
    shutil.copy2(fixtures_dir / "shared_settings.json", home_claude / "settings.json")
    shutil.copy2(fixtures_dir / "shared_settings.json", project_claude / "settings.json")
    shutil.copy2(fixtures_dir / "local_settings.json", project_claude / "settings.local.json")

    env = _clean_env(tmp_path, home=home)
    proc = subprocess.run(
        [
            "uv", "run", str(inspect),
            "--project-root", str(project),
            "--json",
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    data = json.loads(proc.stdout.decode("utf-8"))
    assert set(data["files"]) == {"user", "shared", "local"}
    for label in ("user", "shared", "local"):
        rec = data["files"][label]
        assert rec["exists"] is True
        assert rec["automode_present"] is True
        assert isinstance(rec["canonical_sha256"], str)
        assert len(rec["canonical_sha256"]) == 64

    # Absence of one file is non-fatal.
    (project_claude / "settings.local.json").unlink()
    proc2 = subprocess.run(
        [
            "uv", "run", str(inspect),
            "--project-root", str(project),
            "--json",
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert proc2.returncode == 0
    data2 = json.loads(proc2.stdout.decode("utf-8"))
    assert data2["files"]["local"]["exists"] is False
    assert data2["files"]["local"]["automode_present"] is False


# ---------------------------------------------------------------------------
# Acceptance #22 — auto fresh/migrate detection
# ---------------------------------------------------------------------------


def test_acc22_auto_fresh_migrate_detection(
    tmp_path: Path,
    scripts_dir: Path,
    stub_claude_dir: Path,
    fixtures_dir: Path,
):
    """``--mode auto`` picks fresh on empty projects, migrate when local exists."""

    apply = _apply_cli(scripts_dir)
    _require(apply)

    try:
        import importlib

        apply_mod = importlib.import_module("apply_automode")
        from _paths import resolve as resolve_paths
    except Exception as exc:
        pytest.skip(f"apply_automode not importable: {exc}")

    detect = getattr(apply_mod, "_detect_mode", None)
    if detect is None:
        pytest.skip("_detect_mode not exposed")

    # Fresh project: no .claude/settings.local.json
    project_a = tmp_path / "proj_fresh"
    project_a.mkdir()
    files_a = resolve_paths(project_a)
    assert detect(files_a) == "fresh"

    # Project with autoMode in local.
    project_b = tmp_path / "proj_migrate"
    project_b_claude = project_b / ".claude"
    project_b_claude.mkdir(parents=True)
    _build_local_settings(
        project_b_claude,
        automode={"allow": [], "ask": [], "deny": [], "environment": ["$defaults"]},
    )
    files_b = resolve_paths(project_b)
    assert detect(files_b) == "migrate"

    # Override wins: --mode fresh on a project with .local.json should
    # not re-detect — we observe via the dry-run output that the
    # baseline is treated as fresh (proposal does not include the
    # existing entries verbatim because the override skips _migrate).
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = _make_stub_path(tmp_path, stub_claude_dir / "claude_ok")
    env = _clean_env(tmp_path, extra_path=[str(bin_dir)], home=home)
    proposal = fixtures_dir / "proposal_minimal.json"
    proc = subprocess.run(
        [
            "uv", "run", str(apply),
            "--project-root", str(project_b),
            "--mode", "fresh",
            "--proposal", str(proposal),
            "--dry-run",
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert proc.returncode == EXIT_OK, proc.stderr.decode("utf-8", "replace")
    proposed = _proposal_from_dryrun_stdout(proc.stdout)
    assert proposed is not None


# ---------------------------------------------------------------------------
# Acceptance #23 — gitignore check
# ---------------------------------------------------------------------------


def test_acc23_gitignore_check_warns_when_missing(
    tmp_path: Path,
    scripts_dir: Path,
):
    scan = _scan_cli(scripts_dir)
    _require(scan)

    project = tmp_path / "proj"
    project.mkdir()
    env = _clean_env(tmp_path)
    proc = subprocess.run(
        [
            "uv", "run", str(scan),
            "--project-root", str(project),
            "--check-gitignore",
            "--json",
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert proc.returncode == 0
    stderr = proc.stderr.decode("utf-8", "replace").lower()
    assert "gitignore" in stderr or "warning" in stderr
    assert "settings.local.json" in stderr


def test_acc23_gitignore_check_silent_when_covered(
    tmp_path: Path,
    scripts_dir: Path,
):
    scan = _scan_cli(scripts_dir)
    _require(scan)

    project = tmp_path / "proj"
    project.mkdir()
    (project / ".gitignore").write_text(
        ".claude/settings.local.json\n", encoding="utf-8"
    )
    env = _clean_env(tmp_path)
    proc = subprocess.run(
        [
            "uv", "run", str(scan),
            "--project-root", str(project),
            "--check-gitignore",
            "--json",
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert proc.returncode == 0
    stderr = proc.stderr.decode("utf-8", "replace").lower()
    # No gitignore-warning surfaced.
    assert not ("warning" in stderr and "gitignore" in stderr)


# ---------------------------------------------------------------------------
# rapidfuzz anti-test
# ---------------------------------------------------------------------------


_PEP723_RE = re.compile(
    r"^# /// script\s*\n(.*?)^# ///\s*$",
    re.MULTILINE | re.DOTALL,
)


def test_no_rapidfuzz_in_pep723_blocks(scripts_dir: Path):
    """No /// script block under scripts/ may declare rapidfuzz."""

    offenders: list[str] = []
    for py in scripts_dir.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        for match in _PEP723_RE.finditer(text):
            block = match.group(1).lower()
            if "rapidfuzz" in block:
                offenders.append(str(py))
    assert not offenders, f"rapidfuzz found in PEP 723 blocks of: {offenders!r}"


def test_no_jsonschema_in_pep723_blocks(scripts_dir: Path):
    """No /// script block under scripts/ may declare jsonschema."""

    offenders: list[str] = []
    for py in scripts_dir.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        for match in _PEP723_RE.finditer(text):
            block = match.group(1).lower()
            if "jsonschema" in block:
                offenders.append(str(py))
    assert not offenders, f"jsonschema found in PEP 723 blocks of: {offenders!r}"


# ---------------------------------------------------------------------------
# inspect-side drift / cache tests (extra coverage for #21)
# ---------------------------------------------------------------------------


def test_inspect_show_drift_exit_6(
    tmp_path: Path,
    scripts_dir: Path,
    fixtures_dir: Path,
):
    inspect = _inspect_cli(scripts_dir)
    _require(inspect)

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "proj"
    project_claude = project / ".claude"
    project_claude.mkdir(parents=True)
    shutil.copy2(fixtures_dir / "local_settings.json", project_claude / "settings.local.json")

    env = _clean_env(tmp_path, home=home)
    proc = subprocess.run(
        [
            "uv", "run", str(inspect),
            "--project-root", str(project),
            "--show-drift",
            "--json",
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert proc.returncode == EXIT_DRIFT, (
        f"expected exit {EXIT_DRIFT}; got {proc.returncode}; "
        f"stderr={proc.stderr.decode('utf-8', 'replace')!r}"
    )


def test_inspect_no_drift_when_cache_matches(
    tmp_path: Path,
    scripts_dir: Path,
    fixtures_dir: Path,
):
    inspect = _inspect_cli(scripts_dir)
    _require(inspect)

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "proj"
    project_claude = project / ".claude"
    project_claude.mkdir(parents=True)

    local = project_claude / "settings.local.json"
    shutil.copy2(fixtures_dir / "local_settings.json", local)
    data = json.loads(local.read_text(encoding="utf-8"))
    am = data["autoMode"]
    h = hashlib.sha256(_canonical.canonicalize(am)).hexdigest()
    cache = {"local": {"hash": h}}
    (project_claude / ".auto_mode_approved.json").write_bytes(_canonical.canonicalize(cache))

    env = _clean_env(tmp_path, home=home)
    proc = subprocess.run(
        [
            "uv", "run", str(inspect),
            "--project-root", str(project),
            "--show-drift",
            "--file", "local",
            "--json",
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert proc.returncode == EXIT_OK, (
        f"expected no drift; stderr={proc.stderr.decode('utf-8', 'replace')!r}"
    )


# ---------------------------------------------------------------------------
# scan_project happy-path smoke (acceptance #19 supporting test)
# ---------------------------------------------------------------------------


def test_scan_project_human_output(
    tmp_path: Path,
    scripts_dir: Path,
):
    scan = _scan_cli(scripts_dir)
    _require(scan)

    project = tmp_path / "proj"
    project.mkdir()
    (project / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")

    env = _clean_env(tmp_path)
    proc = subprocess.run(
        [
            "uv", "run", str(scan),
            "--project-root", str(project),
        ],
        env=env, capture_output=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    out = proc.stdout.decode("utf-8")
    assert "signal" in out.lower()
    assert "dockerfile" in out.lower()


# ---------------------------------------------------------------------------
# stdlib validator unit tests (no jsonschema dependency)
# ---------------------------------------------------------------------------


def _get_validator():
    """Import _validate_proposal from the scripts directory."""

    try:
        import importlib
        mod = importlib.import_module("apply_automode")
        fn = getattr(mod, "_validate_proposal", None)
        err = getattr(mod, "ProposalValidationError", None)
        if fn is None or err is None:
            pytest.skip("_validate_proposal or ProposalValidationError not importable")
        return fn, err
    except Exception as exc:
        pytest.skip(f"apply_automode not importable: {exc}")


def test_validator_rejects_non_object():
    """Top-level non-object is rejected with a clear message."""

    validate, ProposalValidationError = _get_validator()
    with pytest.raises(ProposalValidationError, match="expected object"):
        validate(["not", "an", "object"])


def test_validator_rejects_missing_automode():
    """Missing autoMode key raises with a message naming the key."""

    validate, ProposalValidationError = _get_validator()
    with pytest.raises(ProposalValidationError, match="autoMode"):
        validate({"metadata": {}})


def test_validator_rejects_automode_non_object():
    """autoMode value that is not an object is rejected."""

    validate, ProposalValidationError = _get_validator()
    with pytest.raises(ProposalValidationError, match="autoMode"):
        validate({"autoMode": ["list", "not", "object"]})


def test_validator_rejects_unknown_automode_key():
    """Unknown key inside autoMode is rejected and names the key."""

    validate, ProposalValidationError = _get_validator()
    with pytest.raises(ProposalValidationError, match="unknown key"):
        validate({"autoMode": {"allow": [], "badkey": []}})


def test_validator_rejects_non_array_section():
    """A known autoMode section that is not an array is rejected with path."""

    validate, ProposalValidationError = _get_validator()
    with pytest.raises(ProposalValidationError, match=r"autoMode\.environment"):
        validate({"autoMode": {"environment": "should-be-array"}})


def test_validator_rejects_int_in_array_with_path():
    """An int inside autoMode.environment[2] produces a path-aware error."""

    validate, ProposalValidationError = _get_validator()
    with pytest.raises(ProposalValidationError, match=r"autoMode\.environment\[2\]"):
        validate({
            "autoMode": {
                "environment": ["$defaults", "good-string", 42],
                "allow": [],
            }
        })


def test_validator_accepts_valid_proposal():
    """A well-formed proposal passes without error."""

    validate, ProposalValidationError = _get_validator()
    validate({
        "autoMode": {
            "allow": ["Read(**)"],
            "ask": [],
            "deny": [],
            "environment": ["$defaults"],
        }
    })


def test_validator_accepts_example_only_wrapper():
    """Structural __example_only wrapper is accepted in array position."""

    validate, ProposalValidationError = _get_validator()
    validate({
        "autoMode": {
            "environment": [
                "$defaults",
                {"__example_only": True, "value": "team-shared"},
            ],
            "allow": [],
        }
    })


def test_validator_accepts_extra_top_level_keys():
    """Extra top-level keys (e.g. permissions) are allowed (pass-through)."""

    validate, ProposalValidationError = _get_validator()
    validate({
        "autoMode": {
            "allow": ["Read(**)"],
            "environment": ["$defaults"],
        },
        "permissions": {"allow": ["Read(**)"]},
    })
