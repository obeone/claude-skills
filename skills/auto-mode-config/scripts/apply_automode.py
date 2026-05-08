#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "jsonschema>=4.0",
# ]
# ///
"""Generate, validate, and migrate ``autoMode`` blocks in user settings.

This is the write-side of the ``auto-mode-config`` skill. The full
end-to-end flow lives here:

1. **Stranded-state scan** — refuse to run if ``~/.claude/`` contains an
   orphaned ``.auto-mode-config.preview-orig.<pid>`` from a prior aborted
   run. Operator must run ``--repair`` first.
2. **``claude`` discovery** — refuse loudly when the binary is missing
   (exit 5) or the live ``--version`` triple is outside the band declared
   in ``assets/heuristics.yaml`` (exit 10).
3. **``--settings`` capability probe** — run ``claude auto-mode critique
   --help`` once and cache whether the ``--settings`` flag is supported.
   This is done *before* flock acquisition so we don't hold the lock
   while the binary spins up.
4. **flock** — exclusive non-blocking lock on
   ``~/.claude/settings.json.lock``. Stale locks (dead PID OR > 5 min)
   are reclaimed. Lock contention exits 7 (``LockHeldError``).
5. **Phase 1 (proposal build)** — read current settings, optionally
   prompt for migration of existing ``autoMode.environment`` entries,
   merge proposal additions/edits, structurally strip
   ``__example_only`` wrappers, compute canonical bytes + SHA-256.
6. **Phase 2 (critique gate)** — invoke ``claude auto-mode critique``
   pointing at the proposal. If ``--settings`` is unsupported, fall back
   to a swap-file mechanism guarded by ``--allow-swap-file-fallback``
   and SIGINT/SIGTERM/SIGHUP handlers. Capture stdout verbatim, walk
   ``### N.`` items as informational summary, enforce the section
   contract.
7. **Phase 3 (gate predicate)** — gate passes iff
   ``critique_exit == 0 AND computed_sha256 == --approved-canonical-hash``.
8. **Phase 4 (atomic write)** — backup current settings, write
   canonical to ``settings.json.tmp.<pid>``, fsync, ``os.replace`` to
   the target, prune backups to the most recent five, update
   ``~/.claude/.auto_mode_approved.json``.

Exit codes mirror :mod:`inspect_automode` and the team-plan contract.
``--repair`` is a self-contained subcommand that restores orphaned
``.preview-orig.<pid>`` files and removes dead lockfiles. Idempotent.
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import glob
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import _canonical  # noqa: E402


HEURISTICS_PATH = SCRIPT_DIR.parent / "assets" / "heuristics.yaml"

LOCK_NAME = "settings.json.lock"
SETTINGS_NAME = "settings.json"
PROPOSAL_NAME = ".settings.json.proposal"
APPROVED_NAME = ".auto_mode_approved.json"
PREVIEW_ORIG_PREFIX = ".auto-mode-config.preview-orig."

LOCK_STALE_SECONDS = 300

REQUIRED_CRITIQUE_SECTIONS = frozenset({"## Major issues", "## Smaller issues"})

# Exit codes (mirror team-plan.md).
EXIT_OK = 0
EXIT_USAGE = 1
EXIT_BAD_INPUT = 2
EXIT_CRITIQUE_FAILED = 3
EXIT_MIGRATION_STRATEGY_REQUIRED = 4
EXIT_NO_CLAUDE = 5
EXIT_DRIFT_DETECTED = 6
EXIT_LOCK_HELD = 7
EXIT_HASH_MISMATCH = 8
EXIT_STRANDED = 9
EXIT_OUT_OF_BAND = 10


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _err(msg: str) -> None:
    """Write a single newline-terminated line to stderr.

    Parameters
    ----------
    msg
        Message body, without trailing newline.
    """
    sys.stderr.write(msg + "\n")


def _info(msg: str) -> None:
    """Write a single newline-terminated line to stdout.

    Parameters
    ----------
    msg
        Message body, without trailing newline.
    """
    sys.stdout.write(msg + "\n")


def _claude_dir() -> Path:
    """Return the absolute path to ``~/.claude``.

    Returns
    -------
    Path
        ``~/.claude`` expanded under the current ``$HOME``.
    """
    return Path("~/.claude").expanduser().absolute()


def _ensure_claude_dir() -> Path:
    """Create ``~/.claude`` if missing and enforce mode 0700.

    Returns
    -------
    Path
        ``~/.claude``.
    """
    d = _claude_dir()
    os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


# ---------------------------------------------------------------------------
# version-band check
# ---------------------------------------------------------------------------


_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_BAND_TOKEN_RE = re.compile(r"\s*(>=|<=|>|<|==)\s*(\d+)\.(\d+)(?:\.(\d+))?\s*")


def _parse_version(text: str) -> tuple[int, int, int] | None:
    """Extract the first ``MAJOR.MINOR.PATCH`` triple from ``text``.

    Parameters
    ----------
    text
        Output of ``claude --version`` or any text containing a version.

    Returns
    -------
    tuple of int or None
        Triple, or ``None`` if no triple is present.
    """
    match = _VERSION_RE.search(text)
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _parse_version_band(spec: str) -> list[tuple[str, tuple[int, int, int]]]:
    """Parse a ``>=A.B.C,<X.Y`` band into predicates.

    Parameters
    ----------
    spec
        Raw value of ``claude_code_version_range``.

    Returns
    -------
    list of tuple
        ``(operator, (major, minor, patch))`` pairs.

    Raises
    ------
    ValueError
        If a token is malformed.
    """
    out: list[tuple[str, tuple[int, int, int]]] = []
    for token in spec.split(","):
        match = _BAND_TOKEN_RE.fullmatch(token)
        if match is None:
            raise ValueError(f"unparsable version-band token: {token!r}")
        op = match.group(1)
        major = int(match.group(2))
        minor = int(match.group(3))
        patch = int(match.group(4)) if match.group(4) is not None else 0
        out.append((op, (major, minor, patch)))
    return out


def _band_allows(
    version: tuple[int, int, int],
    predicates: list[tuple[str, tuple[int, int, int]]],
) -> bool:
    """Return True iff ``version`` satisfies every predicate.

    Parameters
    ----------
    version
        Detected ``(major, minor, patch)``.
    predicates
        Output of :func:`_parse_version_band`.

    Returns
    -------
    bool
        Conjunction of all comparisons.
    """
    for op, threshold in predicates:
        if op == ">=" and not (version >= threshold):
            return False
        if op == ">" and not (version > threshold):
            return False
        if op == "<=" and not (version <= threshold):
            return False
        if op == "<" and not (version < threshold):
            return False
        if op == "==" and not (version == threshold):
            return False
    return True


def _load_version_range() -> str:
    """Read ``claude_code_version_range`` from ``heuristics.yaml``.

    Returns
    -------
    str
        Raw band specification.

    Raises
    ------
    SystemExit
        Exits ``EXIT_USAGE`` if the file is missing or malformed.
    """
    if not HEURISTICS_PATH.is_file():
        _err(f"apply_automode.py: heuristics file missing: {HEURISTICS_PATH}")
        raise SystemExit(EXIT_USAGE)
    try:
        flat = _canonical.parse_flat_yaml(
            HEURISTICS_PATH.read_text(encoding="utf-8")
        )
    except ValueError as exc:
        _err(f"apply_automode.py: malformed heuristics file: {exc}")
        raise SystemExit(EXIT_USAGE) from None
    band = flat.get("claude_code_version_range")
    if not band:
        _err(
            "apply_automode.py: heuristics.yaml missing required key "
            "'claude_code_version_range'"
        )
        raise SystemExit(EXIT_USAGE)
    return band


def _probe_claude_version() -> tuple[int, int, int]:
    """Run ``claude --version`` and return the triple.

    Returns
    -------
    tuple of int
        Detected version.

    Raises
    ------
    SystemExit
        Exits ``EXIT_NO_CLAUDE`` on missing binary or unparseable output.
    """
    if shutil.which("claude") is None:
        _err(
            "apply_automode.py: `claude` CLI not found on PATH. Install "
            "Claude Code (https://claude.com/product/claude-code) and "
            "ensure the binary is reachable."
        )
        raise SystemExit(EXIT_NO_CLAUDE)
    try:
        proc = subprocess.run(
            ["claude", "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        _err(f"apply_automode.py: failed to invoke `claude --version`: {exc}")
        raise SystemExit(EXIT_NO_CLAUDE) from None
    combined = (proc.stdout or "") + (proc.stderr or "")
    version = _parse_version(combined)
    if version is None:
        _err(
            "apply_automode.py: could not parse a version triple from "
            f"`claude --version` output: {combined.strip()!r}"
        )
        raise SystemExit(EXIT_NO_CLAUDE)
    return version


# ---------------------------------------------------------------------------
# stranded-state and repair
# ---------------------------------------------------------------------------


def _scan_stranded() -> list[Path]:
    """Find orphaned ``.auto-mode-config.preview-orig.<pid>`` files.

    Returns
    -------
    list of Path
        All matching files in ``~/.claude/``, in glob order.
    """
    pattern = str(_claude_dir() / f"{PREVIEW_ORIG_PREFIX}*")
    return [Path(p) for p in glob.glob(pattern)]


def _pid_from_orphan(path: Path) -> int | None:
    """Extract the trailing PID component from a ``.preview-orig.<pid>`` path.

    Parameters
    ----------
    path
        Stranded orphan path.

    Returns
    -------
    int or None
        Parsed PID, or ``None`` if the suffix is not numeric.
    """
    suffix = path.name[len(PREVIEW_ORIG_PREFIX):]
    if suffix.isdigit():
        return int(suffix)
    return None


def _repair() -> int:
    """Restore orphaned ``.preview-orig.<pid>`` and remove dead locks.

    Returns
    -------
    int
        Process exit code.
    """
    if not _claude_dir().exists():
        _info("apply_automode.py --repair: nothing to repair (no ~/.claude/)")
        return EXIT_OK
    orphans = _scan_stranded()
    settings_path = _claude_dir() / SETTINGS_NAME
    repaired = 0
    skipped: list[str] = []
    for orphan in orphans:
        pid = _pid_from_orphan(orphan)
        if pid is None:
            skipped.append(f"{orphan.name} (non-numeric suffix)")
            continue
        try:
            data = orphan.read_bytes()
            json.loads(data)
        except (OSError, json.JSONDecodeError) as exc:
            skipped.append(f"{orphan.name} (unreadable / not JSON: {exc})")
            continue
        if settings_path.exists():
            ts = time.strftime("%Y-%m-%dT%H-%M-%S")
            backup = settings_path.with_name(
                f"{SETTINGS_NAME}.bak.{ts}.repair"
            )
            try:
                shutil.copy2(settings_path, backup)
                os.chmod(backup, 0o600)
            except OSError as exc:
                _err(f"apply_automode.py --repair: cannot back up {settings_path}: {exc}")
                return EXIT_USAGE
        # Restore the orphan over settings.json atomically via os.replace.
        try:
            os.replace(orphan, settings_path)
            os.chmod(settings_path, 0o600)
        except OSError as exc:
            _err(f"apply_automode.py --repair: cannot restore {orphan}: {exc}")
            return EXIT_USAGE
        repaired += 1
        _info(f"restored {orphan.name} -> {SETTINGS_NAME}")
    # Lock cleanup.
    lock_path = _claude_dir() / LOCK_NAME
    if lock_path.exists():
        if _is_lock_stale(lock_path):
            try:
                lock_path.unlink()
                _info(f"removed stale lock {lock_path}")
            except OSError as exc:
                _err(f"apply_automode.py --repair: cannot remove lock: {exc}")
        else:
            _info(f"lock {lock_path} still held by a live process; left alone")
    if repaired == 0 and not skipped and not lock_path.exists():
        _info("apply_automode.py --repair: nothing to repair (clean state)")
    elif skipped:
        for s in skipped:
            _err(f"skipped: {s}")
    return EXIT_OK


def _is_lock_stale(lock_path: Path) -> bool:
    """Return True iff the lock file is stale (dead PID or > 5 min old).

    Parameters
    ----------
    lock_path
        Path to ``settings.json.lock``.

    Returns
    -------
    bool
        ``True`` if reclaim is allowed.
    """
    try:
        text = lock_path.read_text(encoding="utf-8").strip()
    except OSError:
        return True
    head = text.split()[0] if text else ""
    pid: int | None = None
    if head.isdigit():
        pid = int(head)
    age = 0.0
    try:
        age = time.time() - lock_path.stat().st_mtime
    except OSError:
        age = float("inf")
    if age > LOCK_STALE_SECONDS:
        return True
    if pid is None:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        # Process exists but is owned by another user; treat as alive.
        return False
    except OSError:
        return False
    return False


# ---------------------------------------------------------------------------
# critique probe + invocation
# ---------------------------------------------------------------------------


def _probe_settings_flag() -> bool:
    """Detect whether ``claude auto-mode critique --settings`` is supported.

    Returns
    -------
    bool
        ``True`` when the help output advertises ``--settings``.
    """
    try:
        proc = subprocess.run(
            ["claude", "auto-mode", "critique", "--help"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    combined = (proc.stdout or "") + (proc.stderr or "")
    return "--settings" in combined


def _run_critique(
    settings_path: Path | None,
    model: str | None,
) -> tuple[int, str]:
    """Invoke ``claude auto-mode critique`` and capture stdout + exit.

    Parameters
    ----------
    settings_path
        Optional explicit ``--settings`` path. When ``None``, the binary
        reads its default settings location.
    model
        Optional ``--model`` passthrough.

    Returns
    -------
    tuple of int, str
        ``(exit_code, captured_text)``. Stderr is included after stdout.
    """
    cmd = ["claude", "auto-mode", "critique"]
    if settings_path is not None:
        cmd.extend(["--settings", str(settings_path)])
    if model:
        cmd.extend(["--model", model])
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        captured = (exc.stdout or "") + (exc.stderr or "") + "\n[timed out after 120s]\n"
        return 124, captured
    except OSError as exc:
        return EXIT_NO_CLAUDE, f"failed to invoke `claude`: {exc}\n"
    captured = (proc.stdout or "")
    if proc.stderr:
        captured = captured + "\n[stderr]\n" + proc.stderr
    return proc.returncode, captured


# ---------------------------------------------------------------------------
# critique parsing
# ---------------------------------------------------------------------------


_HEADER_RE = re.compile(r"^(##\s+\S.*?)\s*$")
_ITEM_RE = re.compile(r"^###\s+(\d+)\.")
_ITEM_BOLD_RE = re.compile(r"^\*\*(\d+)\.\*\*")


def _extract_sections(text: str) -> dict[str, list[str]]:
    """Split critique output into ``## ...`` sections.

    Parameters
    ----------
    text
        Captured critique stdout.

    Returns
    -------
    dict
        Mapping of header (``"## Major issues"`` style) to body lines.
        Lines outside any ``## `` header are dropped.
    """
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = _HEADER_RE.match(line)
        if match and line.startswith("## "):
            current = match.group(1).strip()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return sections


def _count_items(body: list[str]) -> tuple[int, bool]:
    """Count ``### N.`` items in a section body.

    Parameters
    ----------
    body
        Section body lines.

    Returns
    -------
    tuple of int, bool
        ``(count, parser_stale)``. The stale flag is ``True`` when both
        the primary ``### N.`` form and the ``**N.**`` fallback yielded
        zero matches and the body is non-empty.
    """
    primary = sum(1 for line in body if _ITEM_RE.match(line))
    if primary > 0:
        return primary, False
    fallback = sum(1 for line in body if _ITEM_BOLD_RE.match(line))
    if fallback > 0:
        return fallback, False
    has_content = any(line.strip() for line in body)
    return 0, has_content


# ---------------------------------------------------------------------------
# proposal handling
# ---------------------------------------------------------------------------


def _strip_example_only(node: Any) -> Any:
    """Recursively strip ``__example_only`` wrappers by structure.

    The structural predicate is::

        isinstance(node, dict) and node.get("__example_only") is True
        and set(node.keys()) <= {"__example_only", "value"}

    A wrapper is removed by returning a sentinel that the caller drops
    from its containing list. Wrappers inside dict values are also
    eligible: when a wrapper is a dict value, the value itself is
    removed (the key remains, mapped to ``None``) — this case is
    expected to be rare; the canonical use is in JSON arrays.

    Parameters
    ----------
    node
        Any decoded JSON value.

    Returns
    -------
    Any
        ``node`` with all wrappers stripped. Returns
        :data:`_DROP_SENTINEL` when ``node`` itself is a wrapper.
    """
    if isinstance(node, dict):
        if (
            node.get("__example_only") is True
            and set(node.keys()) <= {"__example_only", "value"}
        ):
            return _DROP_SENTINEL
        out: dict[str, Any] = {}
        for k, v in node.items():
            new_v = _strip_example_only(v)
            if new_v is _DROP_SENTINEL:
                # Drop the whole key — wrapper inside a dict value is
                # treated as "this slot was a placeholder".
                continue
            out[k] = new_v
        return out
    if isinstance(node, list):
        out_list: list[Any] = []
        for item in node:
            new_item = _strip_example_only(item)
            if new_item is _DROP_SENTINEL:
                continue
            out_list.append(new_item)
        return out_list
    return node


_DROP_SENTINEL = object()


def _merge_proposal(base: Any, proposal: Any) -> Any:
    """Shallow-merge ``proposal`` over ``base`` at ``autoMode``.

    Top-level keys in ``proposal`` overwrite (or create) the same keys
    in ``base``. Inside ``autoMode``, sub-keys merge by replacement: a
    ``proposal["autoMode"]["allow"]`` list replaces the existing one
    rather than appending.

    Parameters
    ----------
    base
        Decoded current settings (any JSON value).
    proposal
        Decoded proposal (must be a dict).

    Returns
    -------
    Any
        Merged decoded settings.

    Raises
    ------
    SystemExit
        Exits ``EXIT_BAD_INPUT`` if either side is not a JSON object.
    """
    if not isinstance(base, dict):
        base = {}
    if not isinstance(proposal, dict):
        _err("apply_automode.py: --proposal payload must be a JSON object")
        raise SystemExit(EXIT_BAD_INPUT)
    out: dict[str, Any] = dict(base)
    for k, v in proposal.items():
        if k == "autoMode" and isinstance(v, dict):
            existing = out.get("autoMode") if isinstance(out.get("autoMode"), dict) else {}
            merged = dict(existing) if isinstance(existing, dict) else {}
            for sk, sv in v.items():
                merged[sk] = sv
            out["autoMode"] = merged
        else:
            out[k] = v
    return out


def _migrate_environment(
    base: Any,
    strategy: str | None,
    interactive: bool,
) -> Any:
    """Apply Option-2b migration to ``autoMode.environment``.

    Parameters
    ----------
    base
        Decoded current settings.
    strategy
        ``"keep-all"``, ``"drop-all"``, ``"fail"``, or ``None`` for
        interactive prompts.
    interactive
        ``True`` if the process is attached to a TTY.

    Returns
    -------
    Any
        Decoded settings with the migration applied.

    Raises
    ------
    SystemExit
        Exits ``EXIT_MIGRATION_STRATEGY_REQUIRED`` when strategy is
        required but missing.
    """
    if not isinstance(base, dict):
        return base
    auto_mode = base.get("autoMode")
    if not isinstance(auto_mode, dict):
        return base
    env = auto_mode.get("environment")
    if not isinstance(env, list) or not env:
        return base
    # Filter out the $defaults sentinel from interactive review; keep it.
    actionable = [(i, e) for i, e in enumerate(env) if e != "$defaults"]
    if not actionable:
        return base
    if strategy == "keep-all":
        return base
    if strategy == "drop-all":
        new_env = [e for e in env if e == "$defaults"]
        if not new_env:
            new_env = ["$defaults"]
        new_auto = dict(auto_mode)
        new_auto["environment"] = new_env
        new_base = dict(base)
        new_base["autoMode"] = new_auto
        return new_base
    if strategy == "fail" or (strategy is None and not interactive):
        _err(
            "apply_automode.py: --mode migrate found existing autoMode.environment "
            "entries but no --migrate-strategy was given on a non-interactive "
            "stream. Re-run with --migrate-strategy {keep-all,drop-all} or with "
            "an attached TTY."
        )
        raise SystemExit(EXIT_MIGRATION_STRATEGY_REQUIRED)
    # Interactive prompt path.
    new_env: list[Any] = []
    keep_defaults = False
    for entry in env:
        if entry == "$defaults":
            keep_defaults = True
            continue
        rendered = json.dumps(entry, ensure_ascii=False)
        while True:
            sys.stderr.write(f"environment entry: {rendered}\n")
            sys.stderr.write("[k]eep / [e]dit / [d]rop / [q]uit > ")
            sys.stderr.flush()
            answer = sys.stdin.readline()
            if answer == "":
                sys.stderr.write("\n")
                _err("apply_automode.py: stdin closed during migration prompt")
                raise SystemExit(EXIT_MIGRATION_STRATEGY_REQUIRED)
            choice = answer.strip().lower()[:1]
            if choice == "k":
                new_env.append(entry)
                break
            if choice == "d":
                break
            if choice == "e":
                sys.stderr.write("new value (single line, JSON-encoded string): ")
                sys.stderr.flush()
                edited = sys.stdin.readline()
                if edited == "":
                    _err("apply_automode.py: stdin closed during edit")
                    raise SystemExit(EXIT_MIGRATION_STRATEGY_REQUIRED)
                edited = edited.rstrip("\n")
                try:
                    new_env.append(json.loads(edited))
                except json.JSONDecodeError:
                    new_env.append(edited)
                break
            if choice == "q":
                _err("apply_automode.py: migration aborted by user")
                raise SystemExit(EXIT_USAGE)
            sys.stderr.write("(answer one of k/e/d/q)\n")
    final_env: list[Any] = []
    if keep_defaults:
        final_env.append("$defaults")
    final_env.extend(new_env)
    new_auto = dict(auto_mode)
    new_auto["environment"] = final_env if final_env else ["$defaults"]
    new_base = dict(base)
    new_base["autoMode"] = new_auto
    return new_base


# ---------------------------------------------------------------------------
# flock helpers
# ---------------------------------------------------------------------------


class _LockHandle:
    """Hold an exclusive flock and clean up on ``release()``.

    Parameters
    ----------
    fd
        Low-level file descriptor with the flock attached.
    path
        Lock filesystem path for cleanup.
    """

    def __init__(self, fd: int, path: Path) -> None:
        self.fd = fd
        self.path = path

    def release(self) -> None:
        """Unlock and close the descriptor; remove the lockfile."""
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        try:
            self.path.unlink()
        except OSError:
            pass


def _acquire_lock() -> _LockHandle:
    """Acquire ``flock`` on ``~/.claude/settings.json.lock``.

    Returns
    -------
    _LockHandle
        Handle with ``release()``.

    Raises
    ------
    SystemExit
        Exits ``EXIT_LOCK_HELD`` on contention against a live process.
    """
    lock_path = _ensure_claude_dir() / LOCK_NAME
    if lock_path.exists() and _is_lock_stale(lock_path):
        try:
            lock_path.unlink()
        except OSError:
            pass
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
            existing = ""
            try:
                existing = lock_path.read_text(encoding="utf-8").strip()
            except OSError:
                pass
            _err(
                "apply_automode.py: another process holds the settings "
                f"lock at {lock_path} ({existing!r}). Wait for it to "
                "finish, or run --repair if you suspect it crashed."
            )
            raise SystemExit(EXIT_LOCK_HELD) from None
        raise
    payload = f"{os.getpid()} {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n".encode("utf-8")
    try:
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, payload)
        os.fsync(fd)
    except OSError:
        pass
    return _LockHandle(fd, lock_path)


# ---------------------------------------------------------------------------
# atomic write + backup retention
# ---------------------------------------------------------------------------


def _backup_settings(settings_path: Path) -> Path | None:
    """Copy current settings to ``settings.json.bak.YYYY-MM-DDTHH-MM-SS``.

    Parameters
    ----------
    settings_path
        Live settings path.

    Returns
    -------
    Path or None
        The backup path, or ``None`` if there was nothing to back up.
    """
    if not settings_path.exists():
        return None
    ts = time.strftime("%Y-%m-%dT%H-%M-%S")
    backup = settings_path.with_name(f"{settings_path.name}.bak.{ts}")
    counter = 0
    while backup.exists():
        counter += 1
        backup = settings_path.with_name(f"{settings_path.name}.bak.{ts}.{counter}")
    shutil.copy2(settings_path, backup)
    try:
        os.chmod(backup, 0o600)
    except OSError:
        pass
    return backup


def _prune_backups(settings_path: Path, keep: int = 5) -> None:
    """Delete oldest ``settings.json.bak.*`` beyond the most recent ``keep``.

    Parameters
    ----------
    settings_path
        Live settings path; backups share its parent.
    keep
        Maximum number of backups to retain.
    """
    parent = settings_path.parent
    prefix = f"{settings_path.name}.bak."
    candidates: list[tuple[float, Path]] = []
    try:
        for entry in parent.iterdir():
            if entry.name.startswith(prefix):
                try:
                    candidates.append((entry.stat().st_mtime, entry))
                except OSError:
                    continue
    except OSError:
        return
    candidates.sort(reverse=True)
    for _, path in candidates[keep:]:
        try:
            path.unlink()
        except OSError:
            pass


def _atomic_write(settings_path: Path, canonical: bytes) -> None:
    """Write ``canonical`` to ``settings_path`` atomically.

    Parameters
    ----------
    settings_path
        Final destination.
    canonical
        Bytes to write (must already be canonical).
    """
    tmp_path = settings_path.with_name(f"{settings_path.name}.tmp.{os.getpid()}")
    fd = os.open(tmp_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.write(fd, canonical)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp_path, settings_path)
    try:
        os.chmod(settings_path, 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# main pipeline
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Return the CLI parser.

    Returns
    -------
    argparse.ArgumentParser
        Parser with all flags wired.
    """
    parser = argparse.ArgumentParser(
        prog="apply_automode.py",
        description=(
            "Generate, validate, and migrate the autoMode block in "
            "~/.claude/settings.json. See team-plan.md for the full "
            "phase-by-phase contract."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("fresh", "migrate"),
        default="fresh",
        help="Intent: fresh-machine init (default) or migrate existing entries.",
    )
    parser.add_argument(
        "--proposal",
        type=Path,
        default=None,
        help="Path to a JSON file describing additions/edits to merge.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the proposal, run critique, print hash. No write.",
    )
    parser.add_argument(
        "--approved-canonical-hash",
        default=None,
        help="Required SHA-256 hex (64 chars) for non-dry-run write.",
    )
    parser.add_argument(
        "--migrate-strategy",
        choices=("keep-all", "drop-all", "fail"),
        default="fail",
        help=(
            "Behaviour for existing autoMode.environment entries when "
            "running non-interactively in --mode migrate (default: fail)."
        ),
    )
    parser.add_argument(
        "--show-drift",
        action="store_true",
        help="Print drift diagnostics (delegates to inspect logic).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Pass through to `claude auto-mode critique --model`.",
    )
    parser.add_argument(
        "--allow-swap-file-fallback",
        action="store_true",
        help=(
            "Permit the swap-file critique fallback when the binary "
            "lacks --settings (off by default; opt-in only)."
        ),
    )
    parser.add_argument(
        "--allow-unknown-critique-sections",
        action="store_true",
        help=(
            "Tolerate extra ## sections in critique output. Missing "
            "required sections are always a hard fail."
        ),
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help=(
            "Subcommand: restore orphaned .preview-orig.<pid> files, "
            "remove dead lockfiles. Idempotent."
        ),
    )
    parser.add_argument(
        "--user-settings",
        default=str(_claude_dir() / SETTINGS_NAME),
        help=argparse.SUPPRESS,
    )
    return parser


def _restore_preview_orig(orig: Path, settings: Path) -> None:
    """Restore ``orig`` over ``settings`` (signal-handler safe).

    Parameters
    ----------
    orig
        ``.preview-orig.<pid>`` path.
    settings
        Live settings path.
    """
    try:
        if orig.exists():
            os.replace(orig, settings)
    except OSError:
        pass


def _critique_with_settings_flag(
    proposal_canonical: bytes,
    model: str | None,
) -> tuple[int, str]:
    """Run critique via ``--settings <proposal>`` (no swap, no signals).

    Parameters
    ----------
    proposal_canonical
        Canonical bytes of the proposal.
    model
        Optional ``--model`` passthrough.

    Returns
    -------
    tuple of int, str
        ``(exit_code, captured_text)``.
    """
    proposal_path = _claude_dir() / PROPOSAL_NAME
    fd = os.open(proposal_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.write(fd, proposal_canonical)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        return _run_critique(proposal_path, model)
    finally:
        try:
            proposal_path.unlink()
        except OSError:
            pass


def _critique_with_swap_file(
    proposal_canonical: bytes,
    model: str | None,
) -> tuple[int, str]:
    """Run critique via the swap-file fallback under signal handlers.

    Parameters
    ----------
    proposal_canonical
        Canonical bytes of the proposal.
    model
        Optional ``--model`` passthrough.

    Returns
    -------
    tuple of int, str
        ``(exit_code, captured_text)``.
    """
    settings_path = _claude_dir() / SETTINGS_NAME
    orig_path = _claude_dir() / f"{PREVIEW_ORIG_PREFIX}{os.getpid()}"
    moved = False
    proposal_written = False
    previous_handlers: dict[int, Any] = {}

    def _restore_and_reraise(signum: int, _frame: Any) -> None:
        """Signal handler: restore swap and re-raise as default."""
        if proposal_written:
            try:
                if settings_path.exists():
                    settings_path.unlink()
            except OSError:
                pass
        if moved:
            _restore_preview_orig(orig_path, settings_path)
        prev = previous_handlers.get(signum, signal.SIG_DFL)
        try:
            signal.signal(signum, prev if prev is not None else signal.SIG_DFL)
        except (OSError, ValueError):
            pass
        os.kill(os.getpid(), signum)

    for sig_name in ("SIGINT", "SIGTERM", "SIGHUP"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            previous_handlers[sig] = signal.signal(sig, _restore_and_reraise)
        except (OSError, ValueError):
            pass

    try:
        if settings_path.exists():
            os.replace(settings_path, orig_path)
            moved = True
        fd = os.open(settings_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        try:
            os.write(fd, proposal_canonical)
            os.fsync(fd)
        finally:
            os.close(fd)
        proposal_written = True
        return _run_critique(None, model)
    finally:
        if proposal_written:
            try:
                if settings_path.exists():
                    settings_path.unlink()
            except OSError:
                pass
        if moved:
            _restore_preview_orig(orig_path, settings_path)
        for sig, prev in previous_handlers.items():
            try:
                signal.signal(sig, prev if prev is not None else signal.SIG_DFL)
            except (OSError, ValueError):
                pass


def _run_critique_gate(
    proposal_canonical: bytes,
    settings_flag_supported: bool,
    allow_swap: bool,
    model: str | None,
    allow_unknown_sections: bool,
) -> int:
    """Run critique and print the gate decision.

    Parameters
    ----------
    proposal_canonical
        Canonical bytes of the proposal.
    settings_flag_supported
        Result of the cached ``--help`` probe.
    allow_swap
        Whether ``--allow-swap-file-fallback`` was passed.
    model
        ``--model`` passthrough.
    allow_unknown_sections
        Whether to tolerate extra ``## `` sections.

    Returns
    -------
    int
        Critique exit code, after contract-drift checks. Returns
        ``EXIT_CRITIQUE_FAILED`` on contract drift.
    """
    if settings_flag_supported:
        exit_code, captured = _critique_with_settings_flag(proposal_canonical, model)
    else:
        if not allow_swap:
            _err(
                "apply_automode.py: this `claude` build does not advertise "
                "`--settings` on `auto-mode critique --help`. The skill "
                "refuses to mutate ~/.claude/settings.json without the "
                "explicit opt-in. Pass --allow-swap-file-fallback (and "
                "read references/critique_workflow.md first) to use the "
                "swap-file mechanism. The known constraint is documented "
                "there."
            )
            raise SystemExit(EXIT_USAGE)
        exit_code, captured = _critique_with_swap_file(proposal_canonical, model)
    sys.stdout.write("=== auto-mode critique ===\n")
    sys.stdout.write(captured)
    if not captured.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.write("=== end auto-mode critique ===\n")
    sections = _extract_sections(captured)
    headers_present = set(sections.keys())
    missing = REQUIRED_CRITIQUE_SECTIONS - headers_present
    extra = headers_present - REQUIRED_CRITIQUE_SECTIONS
    if missing:
        _err(
            "apply_automode.py: critique output is missing required "
            f"section(s): {sorted(missing)}. The upstream `claude "
            "auto-mode critique` contract may have drifted. Refusing "
            "to apply (exit 3)."
        )
        return EXIT_CRITIQUE_FAILED
    if extra and not allow_unknown_sections:
        _err(
            "apply_automode.py: critique output has unknown ## section(s): "
            f"{sorted(extra)}. Re-run with --allow-unknown-critique-sections "
            "if upstream genuinely added new sections, or treat this as "
            "a contract drift (exit 3)."
        )
        return EXIT_CRITIQUE_FAILED
    if extra:
        _info(
            "apply_automode.py: advisory — extra critique sections "
            f"tolerated: {sorted(extra)}"
        )
    parser_stale = False
    for header in REQUIRED_CRITIQUE_SECTIONS:
        body = sections.get(header, [])
        count, stale = _count_items(body)
        if stale:
            parser_stale = True
        _info(f"{header}: {count} item(s)")
    if parser_stale:
        _info(
            "(parser may be stale; raw output above is authoritative)"
        )
    return exit_code


def _drift_report() -> int:
    """Emit the same drift diagnostic as ``inspect_automode --show-drift``.

    Returns
    -------
    int
        ``EXIT_OK`` on equality, ``EXIT_DRIFT_DETECTED`` on drift.
    """
    settings_path = _claude_dir() / SETTINGS_NAME
    approved_path = _claude_dir() / APPROVED_NAME
    if not settings_path.exists():
        _err(f"no autoMode config found at {settings_path}")
        return EXIT_OK
    try:
        obj = _canonical.load_json(settings_path)
    except json.JSONDecodeError as exc:
        _err(f"apply_automode.py: {exc.msg}")
        return EXIT_BAD_INPUT
    canonical = _canonical.canonicalize(obj)
    sha = hashlib.sha256(canonical).hexdigest()
    if not approved_path.exists():
        sys.stdout.buffer.write(canonical)
        sys.stdout.write(f"canonical_sha256: {sha}\n")
        sys.stdout.write(
            f"no approved baseline at {approved_path} "
            "(run apply_automode.py once to seed)\n"
        )
        return EXIT_OK
    approved_bytes = approved_path.read_bytes()
    if approved_bytes == canonical:
        _info(f"canonical_sha256: {sha}")
        _info("no drift against approved baseline")
        return EXIT_OK
    import difflib
    diff = difflib.unified_diff(
        approved_bytes.decode("utf-8", errors="replace").splitlines(keepends=True),
        canonical.decode("utf-8").splitlines(keepends=True),
        fromfile=str(approved_path),
        tofile=str(settings_path),
        n=3,
    )
    sys.stdout.write("=== drift vs approved baseline ===\n")
    for line in diff:
        sys.stdout.write(line)
    sys.stdout.write(f"canonical_sha256: {sha}\n")
    return EXIT_DRIFT_DETECTED


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Parameters
    ----------
    argv
        Optional argument list (defaults to ``sys.argv[1:]``).

    Returns
    -------
    int
        Process exit code.
    """
    args = _build_parser().parse_args(argv)

    if args.repair:
        return _repair()
    if args.show_drift and not args.proposal and not args.dry_run:
        # Standalone drift diagnostic, no critique invocation.
        return _drift_report()

    # Stranded-state scan first.
    stranded = _scan_stranded()
    if stranded:
        names = ", ".join(p.name for p in stranded)
        _err(
            "apply_automode.py: stranded preview-orig file(s) found in "
            f"~/.claude/: {names}. Run `apply_automode.py --repair` to "
            "restore the original settings before continuing."
        )
        return EXIT_STRANDED

    # `claude` discovery + version band check.
    version = _probe_claude_version()
    band = _load_version_range()
    try:
        predicates = _parse_version_band(band)
    except ValueError as exc:
        _err(f"apply_automode.py: invalid claude_code_version_range: {exc}")
        return EXIT_USAGE
    if not _band_allows(version, predicates):
        v_str = ".".join(str(n) for n in version)
        _err(
            f"apply_automode.py: detected Claude Code {v_str} is outside "
            f"the supported band {band!r}. The skill refuses to apply "
            "until heuristics.yaml is updated."
        )
        return EXIT_OUT_OF_BAND

    # Cache the --settings probe BEFORE flock so we don't hold the lock
    # while `claude` spins up.
    settings_flag_supported = _probe_settings_flag()

    settings_path = _claude_dir() / SETTINGS_NAME

    # Build proposal in memory.
    if args.proposal is not None:
        if not args.proposal.is_file():
            _err(f"apply_automode.py: proposal file not found: {args.proposal}")
            return EXIT_USAGE
        try:
            proposal_obj = _canonical.load_json(args.proposal)
        except json.JSONDecodeError as exc:
            _err(f"apply_automode.py: {exc.msg}")
            return EXIT_BAD_INPUT
    else:
        proposal_obj = {}

    # Acquire flock; the lock guards the rest of the pipeline.
    lock = _acquire_lock()
    try:
        if settings_path.exists():
            try:
                base_obj = _canonical.load_json(settings_path)
            except json.JSONDecodeError as exc:
                _err(f"apply_automode.py: {exc.msg}")
                return EXIT_BAD_INPUT
        else:
            # Fresh-machine flow.
            base_obj = {}

        if args.mode == "migrate":
            base_obj = _migrate_environment(
                base_obj,
                args.migrate_strategy if args.migrate_strategy != "fail" or not sys.stdin.isatty() else None,
                interactive=sys.stdin.isatty(),
            )

        merged = _merge_proposal(base_obj, proposal_obj)
        merged = _strip_example_only(merged)
        if merged is _DROP_SENTINEL:
            merged = {}
        canonical = _canonical.canonicalize(merged)
        computed_sha = hashlib.sha256(canonical).hexdigest()

        # Critique gate.
        critique_exit = _run_critique_gate(
            canonical,
            settings_flag_supported,
            args.allow_swap_file_fallback,
            args.model,
            args.allow_unknown_critique_sections,
        )

        if args.dry_run:
            _info(f"canonical_sha256: {computed_sha}")
            _info(
                "dry-run complete; re-run without --dry-run plus "
                f"--approved-canonical-hash {computed_sha} to apply."
            )
            if critique_exit == EXIT_CRITIQUE_FAILED:
                return EXIT_CRITIQUE_FAILED
            return EXIT_OK

        if critique_exit != 0:
            _err(
                "apply_automode.py: critique exited non-zero "
                f"({critique_exit}). Refusing to apply (exit 3)."
            )
            return EXIT_CRITIQUE_FAILED

        if args.approved_canonical_hash is None:
            _info(f"canonical_sha256: {computed_sha}")
            _err(
                "apply_automode.py: non-dry-run runs must pass "
                f"--approved-canonical-hash {computed_sha} to confirm "
                "the operator has reviewed the proposal."
            )
            return EXIT_USAGE

        if args.approved_canonical_hash.strip().lower() != computed_sha:
            _err(
                "apply_automode.py: HashMismatchError: "
                f"--approved-canonical-hash={args.approved_canonical_hash} "
                f"does not match recomputed sha256={computed_sha}. "
                "Refusing to apply (exit 8). The proposal or settings "
                "changed between dry-run and apply."
            )
            return EXIT_HASH_MISMATCH

        # Phase 4: atomic write.
        _ensure_claude_dir()
        if not settings_path.exists():
            # Fresh-machine create with O_EXCL.
            fresh = True
            fd = os.open(
                settings_path,
                os.O_CREAT | os.O_WRONLY | os.O_EXCL,
                0o600,
            )
            try:
                os.write(fd, b"{}\n")
                os.fsync(fd)
            finally:
                os.close(fd)
            backup = None
            _info("no backup needed (fresh install)")
        else:
            fresh = False
            stat = settings_path.stat()
            if (stat.st_mode & 0o777) != 0o600:
                _info(
                    f"warning: {settings_path} mode is "
                    f"{stat.st_mode & 0o777:o} (not 0600); not auto-tightening"
                )
            backup = _backup_settings(settings_path)

        _atomic_write(settings_path, canonical)

        approved_path = _claude_dir() / APPROVED_NAME
        fd = os.open(approved_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        try:
            os.write(fd, canonical)
            os.fsync(fd)
        finally:
            os.close(fd)

        _prune_backups(settings_path, keep=5)

        _info(f"canonical_sha256: {computed_sha}")
        _info(f"wrote {settings_path} (mode 0600)")
        if backup is not None:
            _info(
                f"rollback: cp {backup} {settings_path}"
            )
        elif fresh:
            _info("no rollback (fresh install)")
        return EXIT_OK
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
