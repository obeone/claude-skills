#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Apply or migrate autoMode for a Claude Code project.

Implements the 4-phase pipeline from the team-plan handoff:

- Phase 0: auto-detect fresh vs migrate (presence of autoMode in
  ``.claude/settings.local.json``).
- Phase 1: adopt-from-shared (read ``.claude/settings.json`` autoMode,
  per-entry interactive [k]eep / [e]dit / [d]rop / [q]uit).
- Phase 2: scan signals (Dockerfile, package.json, .gitignore, etc.).
- Phase 3: commit local — ``claude auto-mode critique`` (Path b gate)
  + hash gate + atomic write to ``.claude/settings.local.json`` with
  per-file flock and 5-backup retention.
- Phase 4: propose-to-shared (opt-in via ``--write-shared``).

The full CLI surface is documented in ``--help``. Exit codes are stable
and mirror the handoff contract.
"""

from __future__ import annotations

import argparse
import copy
import datetime as _dt
import fnmatch
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
HEURISTICS_PATH = SKILL_DIR / "assets" / "heuristics.yaml"
DROPPED_RULES_PATH = SKILL_DIR / "assets" / "dropped_rules.yaml"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _canonical import canonicalize, load_json, parse_flat_yaml  # noqa: E402
from _lint_rules import (  # noqa: E402
    SEVERITY_ERROR,
    format_findings,
    lint_proposal,
)
from _locks import (  # noqa: E402
    LockHeldError,
    acquire as lock_acquire,
    install_signal_release,
    release as lock_release,
    reclaim_if_stale,
)
from _paths import (  # noqa: E402
    EXPECTED_PARENT_MODE,
    EXPECTED_SECRET_MODE,
    PROJECT_DIR,
    ProjectFiles,
    ensure_project_dir,
    ensure_user_dir,
    resolve,
)


# ---------------------------------------------------------------------------
# Exit codes (stable across builds — see handoff section "Exit codes").
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
# Static configuration
# ---------------------------------------------------------------------------

# Permission patterns the classifier drops from `permissions.allow`
# when the user enters auto mode (source: code.claude.com docs,
# /en/permission-modes "How the classifier evaluates actions"). These
# are NOT autoMode rules — autoMode rules are prose. If any of these
# literals appear inside an autoMode section, the user has likely
# pasted a permissions pattern by mistake; the skill warns and drops.
# The exact literals the classifier itself drops. Complementary to the
# semantic lint's AM004, which flags the broader `Tool(specifier)` shape.
DROPPED_PATTERN_LITERALS = (
    "Bash(*)",
    "PowerShell(*)",
    "Bash(python*)",
    "Agent(*)",
)

REQUIRED_CRITIQUE_SECTIONS = frozenset({"## Major issues", "## Smaller issues"})

# Section-header validation is opt-in because the binary's headers drift
# across versions. Substantiveness validation is NOT opt-in: the binary
# can exit 0 while producing nothing at all (observed:
# "Analyzing your auto mode rules…\n\nNo critique was generated. Please
# try again."). Exit code alone would open the gate on an unreviewed
# proposal, which is exactly what the gate exists to prevent.
#
# Phrases that mean "the binary declined to produce a critique". Matched
# case-insensitively against the whole output.
DEGENERATE_CRITIQUE_PATTERNS = (
    re.compile(r"\bno\s+critique\s+(?:was\s+)?(?:generated|produced)\b", re.I),
    re.compile(r"\bunable\s+to\s+(?:generate|produce)\s+a?\s*critique\b", re.I),
)
# Below this many non-whitespace characters the output cannot carry a
# review of anything. The stub fixtures and every real critique observed
# clear it by a wide margin.
MIN_CRITIQUE_CHARS = 24

BACKUP_RETENTION = 5

# The four (and only four) official autoMode array fields. The
# classifier reads exactly these keys; anything else is rejected by the
# validator and migrated by Phase 1a adoption (legacy `deny` becomes
# `soft_deny` candidates; legacy `ask` is surfaced with a warning and
# dropped because autoMode has no `ask` bucket).
AUTOMODE_ARRAY_KEYS = frozenset(
    {"environment", "allow", "soft_deny", "hard_deny"}
)
# Sections holding rule strings (everything except `environment`).
# `environment` holds trust signals, not rules.
RULE_SECTIONS = ("allow", "soft_deny", "hard_deny")
# Legacy section names the skill knows about and migrates on adoption.
LEGACY_RENAME = {"deny": "soft_deny"}
LEGACY_DROP = ("ask",)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class HashMismatchError(Exception):
    """Approved hash does not match canonical bytes of the proposal."""


class CritiqueContractError(Exception):
    """``claude auto-mode critique`` output violated the section contract."""


class ClaudeCLIMissingError(Exception):
    """The ``claude`` CLI was not found on PATH."""


class OutOfBandVersionError(Exception):
    """Detected ``claude`` version sits outside the heuristics range."""


class ProposalValidationError(Exception):
    """Proposal did not satisfy the JSON Schema."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def _now_stamp() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _archive_critique(
    project_dir: Path,
    *,
    proposal_hash: str,
    exit_code: int,
    output: str,
) -> Path:
    """Write the raw critique output to .claude/.automode-history/.

    Returns the archive path. Best-effort: failures are logged to stderr
    and otherwise swallowed (we never let a logging hiccup break the
    pipeline).

    Parameters
    ----------
    project_dir:
        The project's ``.claude/`` directory (not the project root).
    proposal_hash:
        SHA-256 of the canonical proposal bytes, for audit correlation.
    exit_code:
        Exit code returned by the critique subprocess.
    output:
        Combined stdout+stderr from the critique invocation.
    """

    history_dir = project_dir / ".automode-history"
    stamp = _now_stamp()
    archive_path = history_dir / f"critique-{stamp}.md"
    try:
        history_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            cli = _claude_cli()
            version_proc = subprocess.run(
                [cli, "--version"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            version_line = (version_proc.stdout or version_proc.stderr or "").strip().splitlines()[0] if (version_proc.stdout or version_proc.stderr) else "unknown"
        except Exception:  # noqa: BLE001
            version_line = "unknown"
        header = (
            f"# Critique of {project_dir.parent}\n\n"
            f"timestamp: {stamp}\n"
            f"claude_version: {version_line}\n"
            f"proposal_hash: {proposal_hash}\n"
            f"exit_code: {exit_code}\n\n"
            f"---\n\n"
        )
        payload = (header + output).encode("utf-8")
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(archive_path, flags, 0o600)
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            os.chmod(archive_path, 0o600)
        except PermissionError:
            pass
        _eprint(f"archived critique to {archive_path}")
    except Exception as exc:  # noqa: BLE001
        _eprint(f"warning: could not archive critique output: {exc}")
    return archive_path


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _automode_only_hash(doc: dict[str, Any]) -> str:
    """Return sha256 of canonical bytes of ``doc['autoMode']`` only.

    The drift cache stores this value (matching the scope used by
    ``inspect_automode.py``); the full-document hash drives the
    ``--approved-canonical-hash`` gate predicate and the critique
    archive label.
    """

    auto = doc.get("autoMode") if isinstance(doc, dict) else None
    return _sha256_bytes(canonicalize(auto if auto is not None else {}))


def _atomic_write(target: Path, payload: bytes, *, mode: int = EXPECTED_SECRET_MODE) -> None:
    """Atomically write ``payload`` to ``target`` with ``mode`` permissions.

    ``open(tmp, ...)`` -> ``os.write`` -> ``os.fsync`` -> ``os.replace``.

    The temp is unlinked on every failure path. It can hold the user's
    real settings (the critique swap writes their whole file through
    here), so a leftover would be both a disclosure and a piece of
    stranded state; ``_stranded_files`` only sees the ones a SIGKILL
    leaves behind, which is exactly what ``--repair`` is for.
    """

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + f".tmp.{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp, flags, mode)
    try:
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, target)
    except BaseException:
        # ENOSPC, EIO, a KeyboardInterrupt mid-write: never leave the
        # payload lying around under a name nothing reclaims.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        os.chmod(target, mode)
    except PermissionError:
        pass


def _merge_for_critique(proposal: dict[str, Any], base: Any) -> dict[str, Any]:
    """Overlay ``proposal`` onto a copy of the user's real settings.

    The swap-file critique path replaces ``~/.claude/settings.json`` for
    the duration of the subprocess. Handing the CLI the proposal *alone*
    strips the user's ``env``, ``hooks``, ``statusLine``,
    ``enabledPlugins``, ``permissions`` and everything else, which makes
    the binary run amputated and return "No critique was generated". The
    document handed to the critique must therefore be the real settings
    with the proposal's ``autoMode`` block layered on top.

    ``autoMode`` is the ONLY key overlaid, and it is replaced wholesale
    rather than deep-merged. Overlaying only that key means the swap can
    never substitute the user's ``hooks``, ``env`` or ``permissions``
    with anything a proposal carries; replacing it wholesale means no
    residue of the previous block corrupts the review of the block that
    actually *is* under review. ``_validate_proposal`` already rejects a
    proposal carrying any other top-level key, so this is the second line
    of defence on the one path that writes into the user's own file.

    Parameters
    ----------
    proposal
        The validated proposal document. Only its ``autoMode`` key is
        read; anything else is ignored by construction.
    base
        Whatever ``~/.claude/settings.json`` decoded to. Anything that is
        not a JSON object (missing file, unreadable, or a scalar/array at
        the top level) means there is nothing to merge onto.

    Returns
    -------
    dict
        A fresh document. Neither argument is mutated.
    """

    automode = copy.deepcopy(proposal.get("autoMode", {}))

    # Degraded fallback: no usable base, so the critique sees the
    # proposal alone (the pre-fix behaviour, kept for this one case).
    if not isinstance(base, dict):
        return {"autoMode": automode}

    merged = copy.deepcopy(base)
    merged["autoMode"] = automode
    return merged


def _local_commit_document(
    local_settings: Path, proposal: dict[str, Any]
) -> dict[str, Any]:
    """Return the document to commit to ``.claude/settings.local.json``.

    A proposal is autoMode-only, but the file it lands in is a real
    settings file that may hold ``permissions``, ``enabledMcpjsonServers``
    and so on. Writing the proposal verbatim would delete those, so the
    existing document is read back and only its ``autoMode`` block is
    replaced. Nothing outside ``autoMode`` is ever introduced by this
    function: every other key comes from what the user already had.

    Parameters
    ----------
    local_settings
        Path to ``.claude/settings.local.json``.
    proposal
        The approved, validated proposal.

    Returns
    -------
    dict
        A fresh document ready for ``canonicalize``.
    """

    existing: Any = None
    if local_settings.is_file():
        try:
            existing = load_json(local_settings)
        except Exception:  # noqa: BLE001
            # Unparseable: the caller already reported it upstream, and
            # there is nothing safe to preserve out of it.
            existing = None

    automode = copy.deepcopy(proposal.get("autoMode", {}))
    if not isinstance(existing, dict):
        return {"autoMode": automode}
    out = copy.deepcopy(existing)
    out["autoMode"] = automode
    return out


def _warn_history_not_ignored(files: ProjectFiles) -> None:
    """Warn when ``.claude/.automode-history/`` is not gitignored.

    The archive holds the critique's combined stdout+stderr, and the
    critique runs against a document built from the user's real settings,
    so the output can quote values from their ``env``. The files are 0600
    but that does not stop ``git add``.

    Parameters
    ----------
    files
        Resolved project paths.
    """

    history_dir = files.project_dir / ".automode-history"
    try:
        rel = history_dir.relative_to(files.project_root).as_posix()
    except ValueError:
        return
    if _path_is_gitignored(files.project_root, rel):
        return
    _eprint(
        f"warning: {rel}/ is not covered by any .gitignore rule. "
        f"Critique archives can quote values from your settings; add "
        f"this line to .gitignore:\n"
        f"  {rel}/"
    )


def _path_is_gitignored(root: Path, rel: str) -> bool:
    """Return whether ``rel`` is covered by a ``.gitignore`` rule.

    Deliberately reads only ``<root>/.gitignore`` and
    ``<root>/.claude/.gitignore``: those are the only two files that can
    plausibly cover ``.claude/.automode-history/``, and walking the tree
    for every ``.gitignore`` (which is what ``scan_project`` does) would
    descend into ``node_modules``, ``.venv`` and vendored trees on every
    commit run, unbounded on a monorepo. A rule buried in some deeper
    ``.gitignore`` is a known miss; it costs one spurious warning, never
    a wrong write.

    A rule covers the path when it names the path itself or any ancestor
    of it, with or without git's trailing slash, or when it fnmatches the
    path. ``scan_project._is_gitignored`` handles neither the trailing
    slash nor the ancestor case, which is why this is not delegated.

    Parameters
    ----------
    root
        Project root.
    rel
        Path relative to ``root``, POSIX-style.

    Returns
    -------
    bool
        ``True`` when some rule covers the path. Best effort: any failure
        reads as "covered" so a hygiene warning never becomes noise.
    """

    for gitignore, base in (
        (root / ".gitignore", ""),
        (root / PROJECT_DIR / ".gitignore", f"{PROJECT_DIR}/"),
    ):
        try:
            if not gitignore.is_file():
                continue
            lines = gitignore.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return True
        # Rules are relative to the directory holding the .gitignore, so
        # `.automode-history/` inside .claude/.gitignore names the same
        # directory as `.claude/.automode-history/` at the root.
        if base and not rel.startswith(base):
            continue
        local_rel = rel[len(base):]
        # Every ancestor down to the path itself, so a `.claude/` rule
        # (or a `.automode-history` one) covers what sits under it.
        parts = local_rel.split("/")
        prefixes = {"/".join(parts[:i]) for i in range(1, len(parts) + 1)}
        for line in lines:
            entry = line.strip()
            if not entry or entry.startswith("#"):
                continue
            normalized = entry.strip("/")
            if any(
                prefix == normalized or fnmatch.fnmatch(prefix, normalized)
                for prefix in prefixes
            ):
                return True
    return False


def _read_json_or_empty(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return load_json(path)
    except json.JSONDecodeError as exc:
        raise ProposalValidationError(str(exc)) from exc


def _backup_file(target: Path, *, suffix: str | None = None) -> Path | None:
    """Copy ``target`` to a timestamped backup; prune to 5 most recent."""

    if not target.is_file():
        return None
    stamp = _now_stamp()
    tail = f".{suffix}" if suffix else ""
    backup = target.with_name(f"{target.name}.bak.{stamp}{tail}")
    shutil.copy2(target, backup)
    try:
        os.chmod(backup, EXPECTED_SECRET_MODE)
    except PermissionError:
        pass
    _prune_backups(target)
    return backup


def _prune_backups(target: Path) -> None:
    pattern = re.compile(re.escape(target.name) + r"\.bak\.\d{8}T\d{6}Z(\..+)?$")
    backups = sorted(
        (p for p in target.parent.glob(target.name + ".bak.*") if pattern.match(p.name)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in backups[BACKUP_RETENTION:]:
        try:
            old.unlink()
        except OSError:
            pass


def _strip_example_only(obj: Any) -> Any:
    """Recursively strip ``{"__example_only": true, "value": X}`` wrappers.

    Plain string occurrences of ``"__example_only"`` are preserved
    verbatim; only the structural wrapper form is unwrapped.
    """

    if isinstance(obj, dict):
        if (
            obj.get("__example_only") is True
            and "value" in obj
            and len(obj) == 2
        ):
            return _strip_example_only(obj["value"])
        return {k: _strip_example_only(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_example_only(v) for v in obj]
    return obj


def _filter_dropped(
    items: list[Any],
) -> tuple[list[Any], list[tuple[Any, str]]]:
    """Return ``(kept, dropped)`` after filtering classifier-dropped patterns.

    A pattern is dropped when its string equals one of
    ``Bash(*)``, ``PowerShell(*)``, ``Bash(python*)``, ``Agent(*)``.
    Other ``__example_only`` substrings are not affected.
    """

    kept: list[Any] = []
    dropped: list[tuple[Any, str]] = []
    for entry in items:
        if isinstance(entry, str) and entry in DROPPED_PATTERN_LITERALS:
            dropped.append((entry, "silently dropped by classifier"))
            continue
        kept.append(entry)
    return kept, dropped


# ---------------------------------------------------------------------------
# Schema validation (stdlib — no third-party dependencies)
# ---------------------------------------------------------------------------


def _is_example_only_wrapper(obj: Any) -> bool:
    """Return True for the structural ``{"__example_only": true, "value": X}`` form."""

    return (
        isinstance(obj, dict)
        and obj.get("__example_only") is True
        and "value" in obj
        and len(obj) == 2
    )


def _validate_proposal(proposal: Any) -> None:
    """Validate ``proposal`` against the autoMode proposal schema.

    Uses only the Python standard library. Raises ``ProposalValidationError``
    with a JSON-path-aware message on the first violation found.

    Schema enforced:

    - Top-level must be an object.
    - ``autoMode`` is required and must be an object.
    - Unknown keys inside ``autoMode`` (keys not in ``AUTOMODE_ARRAY_KEYS``)
      are rejected with a message naming the offending key.
    - Any key in ``AUTOMODE_ARRAY_KEYS`` that is present must be an array.
    - Every element of such an array must be a string or a structural
      ``__example_only`` wrapper ``{"__example_only": true, "value": X}``.
    - ``autoMode`` is the ONLY permitted top-level key. Any other one is
      rejected with a message naming it.

    That last clause is a security boundary, not tidiness. The committed
    document is written straight into ``.claude/settings.local.json`` and
    the swap path writes it into ``~/.claude/settings.json`` while the
    ``claude`` binary is invoked against it. Proposals are authored by an
    agent reading ``CLAUDE.md`` / ``AGENTS.md``, so their author is not
    necessarily the user: a pass-through ``hooks`` key would let a
    proposal install a command that runs on the user's next tool call,
    and it would survive the commit permanently.
    """

    if not isinstance(proposal, dict):
        raise ProposalValidationError(
            f"proposal: expected object, got {type(proposal).__name__}"
        )

    if "autoMode" not in proposal:
        raise ProposalValidationError("proposal: required key 'autoMode' is missing")

    unknown_top = set(proposal.keys()) - {"autoMode"}
    if unknown_top:
        key = sorted(unknown_top)[0]
        raise ProposalValidationError(
            f"proposal: unknown top-level key {key!r}; 'autoMode' is the "
            f"only permitted key. A proposal must never carry 'hooks', "
            f"'env', 'permissions' or anything else: those are written "
            f"straight into your settings files"
        )

    auto = proposal["autoMode"]
    if not isinstance(auto, dict):
        raise ProposalValidationError(
            f"autoMode: expected object, got {type(auto).__name__}"
        )

    unknown_auto = set(auto.keys()) - AUTOMODE_ARRAY_KEYS
    if unknown_auto:
        key = sorted(unknown_auto)[0]
        raise ProposalValidationError(
            f"autoMode: unknown key {key!r}"
        )

    for section in AUTOMODE_ARRAY_KEYS:
        if section not in auto:
            continue
        items = auto[section]
        if not isinstance(items, list):
            raise ProposalValidationError(
                f"autoMode.{section}: expected array, got {type(items).__name__}"
            )
        for idx, elem in enumerate(items):
            if isinstance(elem, str):
                continue
            if _is_example_only_wrapper(elem):
                continue
            raise ProposalValidationError(
                f"autoMode.{section}[{idx}]: expected string, "
                f"got {type(elem).__name__}"
            )


# ---------------------------------------------------------------------------
# Critique runner
# ---------------------------------------------------------------------------


def _claude_cli() -> str:
    """Return the ``claude`` executable path, raising on missing."""

    found = shutil.which("claude") or shutil.which(
        os.environ.get("CLAUDE_CLI_BIN", "claude")
    )
    if not found:
        raise ClaudeCLIMissingError(
            "the 'claude' CLI is not on PATH. Install Claude Code or "
            "export CLAUDE_CLI_BIN=/path/to/claude."
        )
    return found


def _critique_supports_settings_flag() -> bool:
    """Return True when ``claude auto-mode critique`` accepts ``--settings``."""

    try:
        cli = _claude_cli()
    except ClaudeCLIMissingError:
        return False
    try:
        proc = subprocess.run(
            [cli, "auto-mode", "critique", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    blob = (proc.stdout or "") + (proc.stderr or "")
    return "--settings" in blob


def _check_critique_substantive(text: str) -> None:
    """Raise ``CritiqueContractError`` when the critique says nothing.

    The binary exits 0 even when it produces no critique, so the exit
    code is not a sufficient gate. This check is version-agnostic: it
    never asserts a section layout, only that *some* review text came
    back. Bypass with ``--allow-empty-critique`` when a legitimately
    terse critique trips it.

    Parameters
    ----------
    text
        Combined stdout+stderr of the critique invocation.

    Raises
    ------
    CritiqueContractError
        The output is empty, too short to be a review, or explicitly
        announces that no critique was generated.
    """

    body = text.strip()
    if not body:
        raise CritiqueContractError(
            "critique output is empty; the binary exited 0 without "
            "reviewing the proposal (rerun, or pass "
            "--allow-empty-critique to accept it)"
        )
    for pattern in DEGENERATE_CRITIQUE_PATTERNS:
        if pattern.search(body):
            raise CritiqueContractError(
                "critique output reports that no critique was generated; "
                "the proposal was not reviewed (rerun, or pass "
                "--allow-empty-critique to accept it)"
            )
    if len("".join(body.split())) < MIN_CRITIQUE_CHARS:
        raise CritiqueContractError(
            f"critique output is too short to be a review "
            f"({len(body)} chars); the proposal was likely not reviewed "
            f"(rerun, or pass --allow-empty-critique to accept it)"
        )


def _check_critique_sections(text: str, *, allow_unknown: bool) -> None:
    """Raise ``CritiqueContractError`` when section set drifts.

    Only called when ``--strict-critique-sections`` is active.
    """

    headers = set(re.findall(r"^##\s+.+$", text, flags=re.MULTILINE))
    missing = REQUIRED_CRITIQUE_SECTIONS - headers
    extras = headers - REQUIRED_CRITIQUE_SECTIONS
    if missing:
        raise CritiqueContractError(
            f"critique output missing required sections: "
            f"{sorted(missing)}"
        )
    if extras and not allow_unknown:
        raise CritiqueContractError(
            f"critique output has unexpected section headers: "
            f"{sorted(extras)}"
        )


def _parse_version(text: str) -> tuple[int, int, int] | None:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _check_version_band(meta: dict[str, str]) -> None:
    band = meta.get("claude_code_version_range")
    if not band:
        return
    try:
        cli = _claude_cli()
    except ClaudeCLIMissingError:
        return
    try:
        proc = subprocess.run(
            [cli, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return
    blob = (proc.stdout or "") + (proc.stderr or "")
    have = _parse_version(blob)
    if not have:
        return
    m = re.match(r"\s*(>=?)\s*([\d.]+)\s*,\s*(<=?)\s*([\d.]+)\s*$", band)
    if not m:
        return
    lo_op, lo_s, hi_op, hi_s = m.group(1), m.group(2), m.group(3), m.group(4)
    lo = _parse_version(lo_s)
    hi = _parse_version(hi_s)
    if lo is None or hi is None:
        return
    if (lo_op == ">=" and have < lo) or (lo_op == ">" and have <= lo):
        raise OutOfBandVersionError(
            f"claude {have} is below the supported range ({band})"
        )
    if (hi_op == "<=" and have > hi) or (hi_op == "<" and have >= hi):
        raise OutOfBandVersionError(
            f"claude {have} is above the supported range ({band})"
        )


def _heuristics_meta() -> dict[str, str]:
    if not HEURISTICS_PATH.is_file():
        return {}
    try:
        flat = parse_flat_yaml(HEURISTICS_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return {k: v for k, v in flat.items() if not k.startswith("signal_")}


def run_critique(
    proposal: dict[str, Any],
    *,
    model: str | None,
    user_settings_path: Path,
    supports_settings_flag: bool,
) -> tuple[int, str]:
    """Invoke ``claude auto-mode critique`` and return ``(exit_code, output)``.

    Both paths review the PROPOSAL, never whatever happens to sit on disk
    at the time. When the CLI accepts ``--settings`` the proposal's
    canonical bytes go into a private temp file named by that flag; the
    project's ``settings.local.json`` must not be used for this, because
    the proposal is not written there until after the critique has passed
    the gate, so pointing at it would review the previous content (or, in
    ``fresh`` mode, a path that does not exist).

    Otherwise the skill swaps ``~/.claude/settings.json`` for the
    duration of the invocation (the classifier reads from the user-level
    file). The swapped-in document is the user's real settings with the
    proposal's ``autoMode`` *merged* into it, never the proposal alone:
    the CLI needs the rest of the user's configuration to function, and a
    substituted file makes it return no critique at all. The swap is
    atomic with signal-handler restore; SIGKILL leaves a sentinel that
    ``--repair`` reclaims.

    Parameters
    ----------
    proposal
        The document under review.
    model
        Optional ``--model`` value.
    user_settings_path
        Path to ``~/.claude/settings.json``, used by the swap path only.
    supports_settings_flag
        Result of :func:`_critique_supports_settings_flag`, computed once
        by the caller. Probing again here would spawn a second
        ``claude auto-mode critique --help`` with its own 10 s timeout.
    """

    cli = _claude_cli()
    cmd = [cli, "auto-mode", "critique"]
    if model:
        cmd.extend(["--model", model])

    if supports_settings_flag:
        return _run_critique_settings_flag(cmd, proposal=proposal)

    _eprint(
        "claude auto-mode critique does not accept --settings on this CLI; "
        "swapping ~/.claude/settings.json transiently for the duration of "
        "the critique invocation (the proposal is merged into a copy of "
        "your real user settings, not substituted for them; atomic "
        "restore; --repair reclaims after SIGKILL)."
    )
    return _run_critique_swap(
        cmd,
        proposal=proposal,
        user_settings_path=user_settings_path,
    )


def _run_critique_settings_flag(
    cmd: list[str],
    *,
    proposal: dict[str, Any],
) -> tuple[int, str]:
    """Run the critique against the proposal via ``--settings``.

    Parameters
    ----------
    cmd
        ``claude auto-mode critique`` argv without ``--settings``.
    proposal
        The document under review. Its canonical bytes are what the CLI
        reads, so the critique reviews exactly what the hash gate covers.

    Returns
    -------
    tuple[int, str]
        ``(exit_code, combined stdout+stderr)``.
    """

    # The temp lives in a private 0700 mkdtemp rather than beside the
    # project's .claude/: anything left in that directory looks like real
    # skill state to --repair, shows up in `git status`, and is one
    # careless `git add .` away from being committed. A private temp dir
    # is outside every tracked tree and goes away wholesale below.
    tmp_dir = Path(tempfile.mkdtemp(prefix="automode-critique-"))
    settings_path = tmp_dir / "settings.json"
    try:
        # Mode at creation, never chmod after: the file holds the
        # proposal for as long as the subprocess runs.
        fd = os.open(
            settings_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            EXPECTED_SECRET_MODE,
        )
        try:
            os.write(fd, canonicalize(proposal))
            os.fsync(fd)
        finally:
            os.close(fd)
        proc = subprocess.run(
            cmd + ["--settings", str(settings_path)],
            capture_output=True, text=True, check=False,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    finally:
        # Unconditional: the temp must not outlive the call on any path.
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _run_critique_swap(
    cmd: list[str],
    *,
    proposal: dict[str, Any],
    user_settings_path: Path,
) -> tuple[int, str]:
    """Swap ``~/.claude/settings.json`` for the duration of the critique.

    Writes the user's real settings with the proposal merged into them
    (see :func:`_merge_for_critique`) into the user settings path, keeps
    the original at a stranded sentinel, restores it (or leaves a
    sentinel for ``--repair``) on any exit path. Merging rather than
    substituting matters because the CLI reads the whole user-level file
    to run: stripped of ``env``, ``hooks``, ``statusLine`` and the rest,
    it produces no critique at all.

    Parameters
    ----------
    cmd
        Fully built ``claude auto-mode critique`` argv.
    proposal
        The proposal document to overlay. It is read, never mutated, and
        never hashed here: the ``--approved-canonical-hash`` gate is
        computed by the caller over the proposal alone, so the merged
        document is purely transient.
    user_settings_path
        Path to ``~/.claude/settings.json``.
    """

    user_settings_path.parent.mkdir(parents=True, exist_ok=True)
    sentinel = user_settings_path.parent / (
        f".automode-config.preview-orig.{os.getpid()}"
    )
    swap_lock = user_settings_path.with_suffix(user_settings_path.suffix + ".lock")
    handle = lock_acquire(swap_lock)
    install_signal_release(handle)

    # Mode of the original, remembered so the restore reinstates it
    # rather than guessing. None means there was no original.
    original_mode: int | None = None
    # Only true once the transient document is actually on disk. Without
    # it a failure before the write would make the restore branch below
    # delete a user file the swap never touched.
    swapped = False

    try:
        # Sentinel first: it must hold the ORIGINAL bytes, captured
        # before anything overwrites the file. Inside the try so that a
        # failure here still releases the lock (a raise before it would
        # skip the finally entirely and strand the flock).
        if user_settings_path.is_file():
            original_mode = stat.S_IMODE(user_settings_path.stat().st_mode)
            # Written through _atomic_write at 0600, never shutil.copy2:
            # copy2 creates the destination at 0o666 & ~umask and only
            # then applies the source mode, so a sentinel holding the
            # user's secrets would exist world-readable in between.
            _atomic_write(
                sentinel,
                user_settings_path.read_bytes(),
                mode=EXPECTED_SECRET_MODE,
            )

        # Read the base only now, under the lock, so the whole
        # read-modify-write is serialised against concurrent swaps.
        base: Any = None
        if user_settings_path.is_file():
            try:
                base = load_json(user_settings_path)
            except Exception as exc:  # noqa: BLE001
                _eprint(
                    f"WARNING: could not read {user_settings_path} "
                    f"({exc}); the critique will run against the proposal "
                    f"alone and may therefore be degraded (the CLI usually "
                    f"needs your full user settings to produce a review). "
                    f"Your file is restored byte-for-byte afterwards."
                )
        merged = _merge_for_critique(proposal, base)
        _atomic_write(
            user_settings_path,
            canonicalize(merged),
            mode=EXPECTED_SECRET_MODE,
        )
        swapped = True
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    finally:
        try:
            if sentinel.is_file():
                # Restore atomically, mirroring the write it undoes: a
                # kill mid-shutil.copy2 would leave the user's real
                # settings truncated, which is worse than not restoring.
                _atomic_write(
                    user_settings_path,
                    sentinel.read_bytes(),
                    mode=original_mode or EXPECTED_SECRET_MODE,
                )
                sentinel.unlink(missing_ok=True)
            elif swapped:
                # No original existed, so remove what the swap created.
                user_settings_path.unlink(missing_ok=True)
        finally:
            lock_release(handle)


# ---------------------------------------------------------------------------
# Approved cache
# ---------------------------------------------------------------------------


def _update_approved_cache(
    cache_path: Path,
    *,
    label: str,
    sha256: str,
) -> None:
    """Update the project-local approved cache, atomic write, mode 0600."""

    existing: dict[str, Any] = {}
    if cache_path.is_file():
        try:
            data = load_json(cache_path)
            if isinstance(data, dict):
                existing = data
        except Exception:  # noqa: BLE001
            existing = {}
    existing[label] = {"hash": sha256, "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")}
    payload = canonicalize(existing)
    _atomic_write(cache_path, payload, mode=EXPECTED_SECRET_MODE)


# ---------------------------------------------------------------------------
# Stranded-state detection / --repair
# ---------------------------------------------------------------------------


# Sentinel copies of an original settings file, left behind when a swap
# died before its restore. --repair copies these BACK over the target.
STRANDED_SENTINEL_GLOB = ".automode-config.preview-orig.*"
# Half-written _atomic_write temps. They hold the NEW content, so
# --repair deletes them; restoring one would install a document nobody
# approved. They are caught here because a SIGKILL between os.open and
# os.replace leaves one holding real bytes. The glob is deliberately
# wide: _atomic_write names its temp `<target>.tmp.<pid>` for EVERY
# target it writes, so a narrower `settings*` pattern would miss
# `.auto_mode_approved.json.tmp.<pid>` (approved-cache bytes) and
# `.automode-config.preview-orig.<pid>.tmp.<pid>` (user-settings bytes).
STRANDED_TEMP_GLOB = "*.tmp.*"


def _stranded_files(files: ProjectFiles) -> list[Path]:
    # iterdir + fnmatch, not glob.glob: glob refuses to let a leading `*`
    # match a dotfile, so `*.tmp.*` would silently skip
    # `.auto_mode_approved.json.tmp.<pid>` and every other temp whose
    # target is itself a dotfile.
    out: list[Path] = []
    for base in (files.user_dir, files.project_dir):
        if not base.is_dir():
            continue
        try:
            entries = list(base.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_file():
                continue
            if any(
                fnmatch.fnmatch(entry.name, pattern)
                for pattern in (STRANDED_SENTINEL_GLOB, STRANDED_TEMP_GLOB)
            ):
                out.append(entry)
    return sorted(set(out))


def _is_stranded_sentinel(path: Path) -> bool:
    """Return whether ``path`` is an original-file sentinel, not a temp.

    Parameters
    ----------
    path
        One entry from :func:`_stranded_files`.

    Returns
    -------
    bool
        ``True`` for ``.automode-config.preview-orig.<pid>``, which holds
        the user's complete original bytes and must be restored;
        ``False`` for an ``_atomic_write`` temp, which must be deleted.
    """

    # The temp test comes first on purpose:
    # `.automode-config.preview-orig.<pid>.tmp.<pid>` carries the
    # sentinel prefix but is a half-written file, so it must be
    # discarded rather than installed over the user's settings.
    if fnmatch.fnmatch(path.name, STRANDED_TEMP_GLOB):
        return False
    return path.name.startswith(".automode-config.preview-orig.")


def detect_stranded(files: ProjectFiles) -> list[Path]:
    """Return stranded swap sentinels and write temps in user/project dirs.

    Note for the next reader: a concurrent run can catch the microsecond
    window in which a live ``_atomic_write`` temp exists and report
    ``EXIT_STRANDED_STATE`` where ``EXIT_LOCK_HELD`` would read better.
    That is cosmetic (both refuse to proceed, and the flock is what
    actually serialises the writers), and not worth a lock dance here.
    """

    return _stranded_files(files)


def _repair(files: ProjectFiles) -> int:
    """Reclaim stale flocks, restore orphans with ``.repair`` backups."""

    # Reclaim stale locks.
    for lock_path in (
        files.user_settings.with_suffix(files.user_settings.suffix + ".lock"),
        files.shared_settings.with_suffix(files.shared_settings.suffix + ".lock"),
        files.local_settings.with_suffix(files.local_settings.suffix + ".lock"),
    ):
        if lock_path.is_file():
            try:
                if reclaim_if_stale(lock_path):
                    _eprint(f"repaired stale lock: {lock_path}")
            except Exception as exc:  # noqa: BLE001
                _eprint(f"could not reclaim {lock_path}: {exc}")

    # Restore orphans.
    stranded = detect_stranded(files)
    if not stranded:
        _eprint("no stranded state detected; nothing to repair.")
        return EXIT_OK

    for orphan in stranded:
        if not _is_stranded_sentinel(orphan):
            # A half-written _atomic_write temp holds content nobody
            # approved, so it is discarded rather than installed.
            try:
                orphan.unlink()
                _eprint(f"discarded stranded write temp: {orphan}")
            except OSError as exc:
                _eprint(f"failed to remove {orphan}: {exc}")
                return EXIT_PERMISSION
            continue
        # Orphan is the original-file copy; the live target sits at the
        # parent dir's settings.json.
        target = orphan.parent / "settings.json"
        if target.is_file():
            _backup_file(target, suffix="repair")
        try:
            _atomic_write(
                target, orphan.read_bytes(), mode=EXPECTED_SECRET_MODE
            )
            orphan.unlink()
            _eprint(f"restored {target} from {orphan}")
        except OSError as exc:
            _eprint(f"failed to restore {target}: {exc}")
            return EXIT_PERMISSION
    return EXIT_OK


# ---------------------------------------------------------------------------
# Phase 0..4
# ---------------------------------------------------------------------------


def _detect_mode(files: ProjectFiles) -> str:
    if not files.local_settings.is_file():
        return "fresh"
    try:
        data = load_json(files.local_settings)
    except Exception:  # noqa: BLE001
        return "migrate"
    if isinstance(data, dict) and isinstance(data.get("autoMode"), dict):
        return "migrate"
    return "fresh"


def _interview(
    items: list[Any],
    *,
    label: str,
    interactive: bool,
) -> tuple[list[Any], list[tuple[Any, str]]]:
    """Walk ``items`` per-entry; returns ``(kept, decisions)``.

    ``decisions`` records ``(item, action)`` for non-keep choices so the
    caller can echo a summary. When ``interactive`` is False this is a
    pass-through (used by ``--migrate-strategy keep-all``).
    """

    if not interactive:
        return list(items), []

    kept: list[Any] = []
    decisions: list[tuple[Any, str]] = []
    for entry in items:
        prompt = (
            f"[{label}] {entry!r}\n"
            f"  [k]eep  [e]dit  [d]rop  [q]uit  > "
        )
        sys.stdout.write(prompt)
        sys.stdout.flush()
        try:
            answer = sys.stdin.readline().strip().lower() or "k"
        except (EOFError, KeyboardInterrupt):
            decisions.append((entry, "quit"))
            return kept, decisions
        if answer.startswith("k"):
            kept.append(entry)
        elif answer.startswith("d"):
            decisions.append((entry, "drop"))
        elif answer.startswith("q"):
            decisions.append((entry, "quit"))
            return kept, decisions
        elif answer.startswith("e"):
            sys.stdout.write(f"  new value (JSON, blank = keep): ")
            sys.stdout.flush()
            new_raw = sys.stdin.readline().strip()
            if not new_raw:
                kept.append(entry)
                continue
            try:
                new_val = json.loads(new_raw)
            except json.JSONDecodeError as exc:
                _eprint(f"  invalid JSON ({exc}); keeping original.")
                kept.append(entry)
                continue
            kept.append(new_val)
            decisions.append((entry, f"edit -> {new_val!r}"))
        else:
            kept.append(entry)
    return kept, decisions


def _adopt_into(
    adopted: dict[str, list[Any]],
    section: str,
    items: list[Any],
) -> None:
    """Append ``items`` to ``adopted[section]``, deduping order-preserving."""

    bucket = adopted.setdefault(section, [])
    for item in items:
        if item not in bucket:
            bucket.append(item)


def _phase1_adopt(
    files: ProjectFiles,
    *,
    interactive: bool,
) -> dict[str, Any]:
    """Read shared autoMode; return adopted entries by section.

    Sub-phase 1a walks ``.claude/settings.json`` (if present) and surfaces
    each ``autoMode`` rule to the four-key prompt. Accepted entries are
    pushed into ``adopted``, deduped order-preservingly.

    Sub-phase 1b is agent-driven: the calling agent reads CLAUDE.md /
    AGENTS.md / .claude/CLAUDE.md, applies judgment, and emits a proposal
    JSON that flows through the same critique + hash-gate + atomic-write
    pipeline as any other proposal.
    """

    adopted: dict[str, list[Any]] = {}

    # ---- Sub-phase 1a: shared file ------------------------------------
    if files.shared_settings.is_file():
        try:
            data = load_json(files.shared_settings)
        except Exception as exc:  # noqa: BLE001
            _eprint(f"phase 1a: could not parse {files.shared_settings}: {exc}")
            data = None
        auto = data.get("autoMode") if isinstance(data, dict) else None
        if isinstance(auto, dict):
            # Iteration order: official keys first, then legacy keys.
            # Legacy `deny` entries are presented as `soft_deny`
            # candidates with a warning; legacy `ask` entries are
            # surfaced with a warning that the bucket does not exist
            # in autoMode, then dropped.
            sections_to_walk = list(AUTOMODE_ARRAY_KEYS) + list(LEGACY_RENAME) + list(LEGACY_DROP)
            for section in sections_to_walk:
                items = auto.get(section)
                if not isinstance(items, list) or not items:
                    continue
                target_section = LEGACY_RENAME.get(section, section)
                if section in LEGACY_DROP:
                    _eprint(
                        f"\n[Phase 1a] shared {section!r} is not a valid autoMode "
                        f"bucket; surfacing entries for review (will be dropped "
                        f"unless edited into a valid section by hand)."
                    )
                elif section in LEGACY_RENAME:
                    _eprint(
                        f"\n[Phase 1a] shared {section!r} is the legacy name; "
                        f"surfacing entries as candidates for {target_section!r}."
                    )
                else:
                    _eprint(f"\n[Phase 1a] adopt-from-shared :: {section}")
                kept, decisions = _interview(
                    items, label=f"shared.{section}", interactive=interactive
                )
                kept = _strip_example_only(kept)
                if target_section in RULE_SECTIONS:
                    kept, dropped = _filter_dropped(kept)
                    for entry, reason in dropped:
                        _eprint(f"  ! dropped {entry!r}: {reason}")
                if section in LEGACY_DROP:
                    # autoMode has no bucket for these; drop after the
                    # user has had a chance to inspect.
                    for entry in kept:
                        _eprint(
                            f"  ! discarding {entry!r}: autoMode has no "
                            f"{section!r} section (see references/automode_doc_bible.md)."
                        )
                else:
                    _adopt_into(adopted, target_section, kept)
                for entry, action in decisions:
                    _eprint(f"  - {entry!r}: {action}")

    return adopted


def _phase2_signals(files: ProjectFiles) -> dict[str, Any]:
    """Run scan_project to collect signals; flatten into env hints."""

    try:
        from scan_project import build_report  # noqa: WPS433
    except ImportError:
        return {}
    report = build_report(
        files.project_root,
        include_shared=False,
        check_gitignore=False,
    )
    hints: dict[str, Any] = {
        "signals": [s for s in report["signals"] if s["present"]],
    }
    return hints


def _merge_proposal(
    *,
    base: dict[str, Any] | None,
    adopted: dict[str, list[Any]],
    proposal_override: dict[str, Any] | None,
) -> dict[str, Any]:
    """Combine ``base`` + ``adopted`` + ``proposal_override`` into one block.

    The result carries ``autoMode`` and nothing else. ``base`` is the
    project's existing ``settings.local.json``, whose other keys are
    deliberately NOT copied in: a proposal is autoMode-only by contract
    (see :func:`_validate_proposal`), and those keys are preserved at
    commit time by :func:`_local_commit_document` instead of round-
    tripping through a document the hash gate covers.
    """

    out: dict[str, Any] = {"autoMode": {}}
    if isinstance(base, dict):
        if isinstance(base.get("autoMode"), dict):
            out["autoMode"] = dict(base["autoMode"])
    for section, items in adopted.items():
        existing = out["autoMode"].get(section, [])
        if not isinstance(existing, list):
            existing = []
        merged = existing + [i for i in items if i not in existing]
        out["autoMode"][section] = merged
    if proposal_override:
        if isinstance(proposal_override.get("autoMode"), dict):
            out["autoMode"].update(proposal_override["autoMode"])
        # Other top-level keys of the override are NOT merged. The caller
        # rejects them outright before reaching here; silently carrying
        # them would put attacker-authored `hooks` into the commit.
    if "environment" not in out["autoMode"]:
        out["autoMode"]["environment"] = ["$defaults"]
    return out


def _migrate_strategy(
    base: dict[str, Any] | None,
    *,
    strategy: str,
) -> tuple[dict[str, Any], list[tuple[Any, str]]]:
    """Apply ``--migrate-strategy`` to ``base['autoMode']``.

    Returns ``(new_block, dropped_summary)``.
    """

    block: dict[str, Any] = {}
    if isinstance(base, dict) and isinstance(base.get("autoMode"), dict):
        block = {k: list(v) if isinstance(v, list) else v for k, v in base["autoMode"].items()}

    dropped_summary: list[tuple[Any, str]] = []
    if strategy == "keep-all":
        return block, dropped_summary
    if strategy == "drop-all":
        # Reset only the four official sections. Legacy `ask` / `deny`
        # keys are removed entirely so the migrated block matches the
        # current schema.
        for legacy in (*LEGACY_RENAME, *LEGACY_DROP):
            block.pop(legacy, None)
        block["allow"] = []
        block["soft_deny"] = []
        block["hard_deny"] = []
        block["environment"] = ["$defaults"]
        return block, dropped_summary
    if strategy == "fail":
        if block:
            raise ProposalValidationError(
                "--migrate-strategy=fail and an existing autoMode block "
                "is present; refusing to migrate."
            )
        return block, dropped_summary
    # interactive — leave block as-is; per-entry pruning happens upstream.
    return block, dropped_summary


# ---------------------------------------------------------------------------
# Pretty-printers
# ---------------------------------------------------------------------------


def _print_rollback(target: Path, backup: Path | None) -> None:
    if backup is None:
        _eprint(f"rollback: rm {target}  # no prior version existed")
    else:
        _eprint(f"rollback: cp {backup} {target}")


# ---------------------------------------------------------------------------
# Semantic lint gate
# ---------------------------------------------------------------------------


def _run_semantic_lint(
    proposal: dict[str, Any],
    *,
    project_root: Path,
    no_lint: bool,
    lint_strict: bool,
) -> int | None:
    """Lint the rule content and decide whether the run may continue.

    Findings are always printed when there are any, whatever their
    severity and whatever the flags. Errors block by default; warnings
    only block under ``lint_strict``. ``no_lint`` skips the lint outright
    and prints nothing, which is the escape hatch for a false positive.

    Parameters
    ----------
    proposal : dict
        The proposal about to be hashed.
    project_root : Path
        Project root handed to AM003 so it scans the project's own files
        rather than whatever directory the process happens to run in.
    no_lint : bool
        Skip the lint entirely. Wins over ``lint_strict``.
    lint_strict : bool
        Let warnings block as well as errors.

    Returns
    -------
    int or None
        ``EXIT_VALIDATION`` when the run must stop, ``None`` when it may
        continue. A blocking return happens before any caller prints the
        canonical hash, so an unfixed proposal is never approvable.
    """

    if no_lint:
        # Both flags together is nonsense rather than an argparse error,
        # so say which one won instead of silently picking.
        if lint_strict:
            _eprint(
                "--no-lint and --lint-strict contradict each other; "
                "--no-lint wins, so the semantic lint is skipped entirely."
            )
        return None

    findings = lint_proposal(proposal, project_root=project_root)
    report = format_findings(findings)
    if report:
        # format_findings already terminates with a newline; _eprint adds
        # its own, so strip one to avoid a stray blank line.
        _eprint(report.rstrip("\n"))

    blocking = [
        f for f in findings
        if lint_strict or f.severity == SEVERITY_ERROR
    ]
    if not blocking:
        return None

    _eprint(
        f"semantic lint: {len(blocking)} finding(s) blocked this proposal; "
        f"fix the rules above, or pass --no-lint to bypass the lint."
    )
    return EXIT_VALIDATION


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------


def _run(args: argparse.Namespace) -> int:
    files = resolve(args.project_root)

    # Repair short-circuits everything.
    if args.repair:
        return _repair(files)

    # Stranded-state scan BEFORE fresh-machine detection.
    stranded = detect_stranded(files)
    if stranded:
        _eprint("stranded state detected:")
        for s in stranded:
            _eprint(f"  - {s}")
        _eprint("run with --repair to recover.")
        return EXIT_STRANDED_STATE

    # Version-band probe (best-effort; missing CLI handled later).
    meta = _heuristics_meta()
    try:
        _check_version_band(meta)
    except OutOfBandVersionError as exc:
        _eprint(str(exc))
        return EXIT_OUT_OF_BAND

    # --settings capability probe (before any flock). When the CLI
    # lacks --settings the skill swaps ~/.claude/settings.json transiently
    # during the critique invocation; the deprecated
    # --allow-swap-file-fallback flag is now a no-op.
    settings_flag_supported = _critique_supports_settings_flag()
    if args.allow_swap_file_fallback:
        _eprint(
            "warning: --allow-swap-file-fallback is deprecated and has no "
            "effect; the swap-file path is now used automatically when the "
            "CLI lacks --settings."
        )

    # ------------------------------------------------------------------
    # Phase 0: detect mode
    # ------------------------------------------------------------------
    mode = args.mode if args.mode != "auto" else _detect_mode(files)

    # ------------------------------------------------------------------
    # Phase 1: adopt-from-shared
    # ------------------------------------------------------------------
    interactive = args.migrate_strategy == "interactive"
    adopted: dict[str, list[Any]] = {}
    try:
        adopted = _phase1_adopt(
            files,
            interactive=interactive and sys.stdin.isatty(),
        )
    except Exception as exc:  # noqa: BLE001
        _eprint(f"phase 1 failed: {exc}")
        return EXIT_VALIDATION

    # ------------------------------------------------------------------
    # Phase 2: scan signals (informational)
    # ------------------------------------------------------------------
    _phase2_signals(files)  # informational — no merge by default

    # ------------------------------------------------------------------
    # Build proposal
    # ------------------------------------------------------------------
    base_local: Any = None
    if files.local_settings.is_file():
        try:
            base_local = load_json(files.local_settings)
        except Exception as exc:  # noqa: BLE001
            _eprint(f"could not parse {files.local_settings}: {exc}")
            return EXIT_VALIDATION

    if mode == "migrate":
        try:
            migrated_block, _ = _migrate_strategy(
                base_local, strategy=args.migrate_strategy
            )
        except ProposalValidationError as exc:
            _eprint(str(exc))
            return EXIT_VALIDATION
        if isinstance(base_local, dict):
            base_local["autoMode"] = migrated_block
        else:
            base_local = {"autoMode": migrated_block}

    proposal_override: dict[str, Any] | None = None
    if args.proposal:
        try:
            proposal_override = load_json(Path(args.proposal))
        except FileNotFoundError:
            _eprint(f"proposal file not found: {args.proposal}")
            return EXIT_USAGE
        except Exception as exc:  # noqa: BLE001
            _eprint(f"could not parse proposal: {exc}")
            return EXIT_VALIDATION

        # Reject a proposal carrying anything but autoMode HERE, on the
        # raw file, before a single byte is written anywhere. _merge_
        # proposal drops such keys and _validate_proposal rejects them
        # again downstream, but neither would name the file the user
        # actually handed us.
        if isinstance(proposal_override, dict):
            extra = sorted(set(proposal_override) - {"autoMode"})
            if extra:
                _eprint(
                    f"proposal {args.proposal}: unknown top-level key "
                    f"{extra[0]!r}; 'autoMode' is the only permitted key. "
                    f"A proposal must never carry 'hooks', 'env', "
                    f"'permissions' or anything else: those are written "
                    f"straight into your settings files."
                )
                return EXIT_VALIDATION

    proposal = _merge_proposal(
        base=base_local if isinstance(base_local, dict) else None,
        adopted=adopted,
        proposal_override=proposal_override,
    )
    proposal = _strip_example_only(proposal)

    for section in RULE_SECTIONS:
        items = proposal["autoMode"].get(section)
        if isinstance(items, list):
            kept, dropped = _filter_dropped(items)
            for entry, reason in dropped:
                _eprint(f"dropped {section}[{entry!r}]: {reason}")
            proposal["autoMode"][section] = kept

    # Semantic lint of what the rules actually SAY. It runs AFTER
    # _filter_dropped, so the four DROPPED_PATTERN_LITERALS keep
    # auto-repairing with a message instead of tripping AM004's
    # `Tool(specifier)` shape check and turning a self-healing case into
    # a hard exit 2. It still runs before the canonical hash and before
    # the dry-run branch prints it: the agent driving this skill has to
    # see the findings while the proposal is editable, never after the
    # user approved a hash for it. A blocking finding therefore exits
    # without ever printing the sha256.
    lint_rc = _run_semantic_lint(
        proposal,
        project_root=files.project_root,
        no_lint=args.no_lint,
        lint_strict=args.lint_strict,
    )
    if lint_rc is not None:
        return lint_rc

    try:
        _validate_proposal(proposal)
    except ProposalValidationError as exc:
        _eprint(f"proposal failed schema validation: {exc}")
        return EXIT_VALIDATION

    canonical = canonicalize(proposal)
    proposal_hash = _sha256_bytes(canonical)

    if args.dry_run:
        sys.stdout.write(canonical.decode("utf-8"))
        _eprint(f"\ndry-run canonical sha256: {proposal_hash}")
        _eprint(f"to commit: rerun without --dry-run, passing")
        _eprint(f"  --approved-canonical-hash {proposal_hash}")
        return EXIT_OK

    if not args.approved_canonical_hash:
        _eprint(
            "non-dry-run requires --approved-canonical-hash <sha256>. "
            "Re-run with --dry-run first to obtain it."
        )
        return EXIT_USAGE

    if args.approved_canonical_hash != proposal_hash:
        _eprint(
            f"hash mismatch: approved={args.approved_canonical_hash} "
            f"computed={proposal_hash}"
        )
        return EXIT_HASH_MISMATCH

    # ------------------------------------------------------------------
    # Phase 3: critique + commit local
    # ------------------------------------------------------------------
    ensure_project_dir(files)
    if not settings_flag_supported:
        ensure_user_dir(files)

    local_lock = files.local_settings.with_suffix(
        files.local_settings.suffix + ".lock"
    )
    try:
        local_handle = lock_acquire(local_lock)
    except LockHeldError:
        _eprint(f"local settings lock held: {local_lock}")
        return EXIT_LOCK_HELD
    install_signal_release(local_handle)

    try:
        try:
            rc, output = run_critique(
                proposal,
                model=args.model,
                user_settings_path=files.user_settings,
                supports_settings_flag=settings_flag_supported,
            )
        except ClaudeCLIMissingError as exc:
            _eprint(str(exc))
            return EXIT_CLAUDE_CLI_MISSING
        except CritiqueContractError as exc:
            _eprint(str(exc))
            return EXIT_CRITIQUE_FAILED
        except OSError as exc:
            # A failed swap (unwritable ~/.claude, ENOSPC, EPERM on the
            # sentinel) must surface as an exit code, not a traceback.
            # The swap's own finally has already restored and unlocked.
            _eprint(f"critique setup failed: {exc}")
            return EXIT_PERMISSION

        sys.stdout.write(output)
        sys.stdout.write("\n")
        _archive_critique(
            files.project_dir,
            proposal_hash=proposal_hash,
            exit_code=rc,
            output=output,
        )
        _warn_history_not_ignored(files)
        if rc != 0:
            _eprint(f"critique exited {rc}")
            return EXIT_CRITIQUE_FAILED
        if not args.allow_empty_critique:
            try:
                _check_critique_substantive(output)
            except CritiqueContractError as exc:
                _eprint(str(exc))
                _eprint(f"archived output: {files.project_dir}/.automode-history")
                return EXIT_CRITIQUE_FAILED
        if args.strict_critique_sections:
            try:
                _check_critique_sections(
                    output,
                    allow_unknown=args.allow_unknown_critique_sections,
                )
            except CritiqueContractError as exc:
                _eprint(str(exc))
                return EXIT_CRITIQUE_FAILED

        backup = _backup_file(files.local_settings)
        # The proposal is autoMode-only, but the file it lands in is a
        # real settings file: write the existing document back with only
        # its autoMode block replaced, so the user's own permissions and
        # MCP keys survive the commit.
        commit_bytes = canonicalize(
            _local_commit_document(files.local_settings, proposal)
        )
        try:
            _atomic_write(files.local_settings, commit_bytes, mode=EXPECTED_SECRET_MODE)
        except PermissionError as exc:
            _eprint(f"permission denied writing {files.local_settings}: {exc}")
            return EXIT_PERMISSION

        _update_approved_cache(
            files.approved_cache,
            label="local",
            sha256=_automode_only_hash(proposal),
        )
        _print_rollback(files.local_settings, backup)
    finally:
        lock_release(local_handle)

    # ------------------------------------------------------------------
    # Phase 4: propose-to-shared (opt-in)
    # ------------------------------------------------------------------
    if args.write_shared:
        rc = _phase4_write_shared(files, proposal_hash=proposal_hash, canonical=canonical)
        if rc != EXIT_OK:
            return rc

    # ------------------------------------------------------------------
    # --hoist (rare): move a rule from local to user
    # ------------------------------------------------------------------
    if args.hoist:
        rc = _hoist_rule(files, rule=args.hoist)
        if rc != EXIT_OK:
            return rc

    return EXIT_OK


def _phase4_write_shared(
    files: ProjectFiles,
    *,
    proposal_hash: str,
    canonical: bytes,
) -> int:
    """Phase 4: write the same autoMode block into the shared file."""

    _eprint(
        "\nWARNING: writing autoMode into .claude/settings.json. The "
        "Claude Code permission classifier IGNORES autoMode in this "
        "file; this serves as a team manifest of intent only."
    )
    if sys.stdin.isatty():
        sys.stdout.write("Type 'I understand' to proceed: ")
        sys.stdout.flush()
        ans = sys.stdin.readline().strip()
        if ans != "I understand":
            _eprint("aborted Phase 4 (no confirmation)")
            return EXIT_USAGE

    shared_lock = files.shared_settings.with_suffix(
        files.shared_settings.suffix + ".lock"
    )
    try:
        handle = lock_acquire(shared_lock)
    except LockHeldError:
        _eprint(f"shared settings lock held: {shared_lock}")
        return EXIT_LOCK_HELD
    install_signal_release(handle)

    try:
        existing: dict[str, Any] = {}
        if files.shared_settings.is_file():
            try:
                data = load_json(files.shared_settings)
                if isinstance(data, dict):
                    existing = data
            except Exception as exc:  # noqa: BLE001
                _eprint(f"could not parse shared settings: {exc}")
                return EXIT_VALIDATION
        proposal_obj = json.loads(canonical.decode("utf-8"))
        existing["autoMode"] = proposal_obj.get("autoMode", {})
        new_canonical = canonicalize(existing)
        backup = _backup_file(files.shared_settings)
        try:
            _atomic_write(
                files.shared_settings, new_canonical, mode=0o644
            )
        except PermissionError as exc:
            _eprint(f"permission denied writing shared settings: {exc}")
            return EXIT_PERMISSION
        _update_approved_cache(
            files.approved_cache,
            label="shared",
            sha256=_automode_only_hash(existing),
        )
        _print_rollback(files.shared_settings, backup)
    finally:
        lock_release(handle)
    return EXIT_OK


def _hoist_rule(files: ProjectFiles, *, rule: str) -> int:
    """Move ``rule`` from local autoMode.allow to user autoMode.allow.

    Requires explicit interactive confirmation; refuses on
    non-interactive stdin.
    """

    if not sys.stdin.isatty():
        _eprint(
            "--hoist requires an interactive terminal (writing to "
            "~/.claude/settings.json needs explicit confirmation)."
        )
        return EXIT_USAGE

    _eprint(
        f"\nWARNING: --hoist will move {rule!r} from .claude/"
        f"settings.local.json into ~/.claude/settings.json (user "
        f"baseline). This is a per-user, cross-project change."
    )
    sys.stdout.write("Type 'hoist' to proceed: ")
    sys.stdout.flush()
    ans = sys.stdin.readline().strip()
    if ans != "hoist":
        _eprint("aborted --hoist")
        return EXIT_USAGE

    user_lock = files.user_settings.with_suffix(
        files.user_settings.suffix + ".lock"
    )
    local_lock = files.local_settings.with_suffix(
        files.local_settings.suffix + ".lock"
    )
    try:
        h_user = lock_acquire(user_lock)
    except LockHeldError:
        _eprint(f"user settings lock held: {user_lock}")
        return EXIT_LOCK_HELD
    try:
        h_local = lock_acquire(local_lock)
    except LockHeldError:
        lock_release(h_user)
        _eprint(f"local settings lock held: {local_lock}")
        return EXIT_LOCK_HELD
    install_signal_release(h_user)
    install_signal_release(h_local)

    try:
        local = load_json(files.local_settings) if files.local_settings.is_file() else {}
        user = load_json(files.user_settings) if files.user_settings.is_file() else {}
        if not isinstance(local, dict) or not isinstance(user, dict):
            _eprint("hoist: target files are not JSON objects.")
            return EXIT_VALIDATION
        local_allow = local.get("autoMode", {}).get("allow", [])
        if rule not in local_allow:
            _eprint(f"hoist: {rule!r} not in local autoMode.allow")
            return EXIT_USAGE
        local_allow.remove(rule)
        local.setdefault("autoMode", {})["allow"] = local_allow
        user.setdefault("autoMode", {}).setdefault("allow", [])
        if rule not in user["autoMode"]["allow"]:
            user["autoMode"]["allow"].append(rule)

        backup_local = _backup_file(files.local_settings)
        backup_user = _backup_file(files.user_settings)
        ensure_user_dir(files)
        _atomic_write(files.user_settings, canonicalize(user), mode=EXPECTED_SECRET_MODE)
        _atomic_write(files.local_settings, canonicalize(local), mode=EXPECTED_SECRET_MODE)
        _update_approved_cache(
            files.approved_cache,
            label="user",
            sha256=_automode_only_hash(user),
        )
        _update_approved_cache(
            files.approved_cache,
            label="local",
            sha256=_automode_only_hash(local),
        )
        _print_rollback(files.local_settings, backup_local)
        _print_rollback(files.user_settings, backup_user)
    except FileNotFoundError as exc:
        _eprint(str(exc))
        return EXIT_VALIDATION
    finally:
        lock_release(h_local)
        lock_release(h_user)
    return EXIT_OK


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apply_automode.py",
        description="Author / migrate / commit autoMode for a project.",
    )
    parser.add_argument(
        "--project-root",
        default=str(Path.cwd()),
        help="Project root (default: cwd).",
    )
    parser.add_argument(
        "--mode",
        choices=("auto", "fresh", "migrate"),
        default="auto",
        help="Pipeline mode (default: auto-detect from local file).",
    )
    parser.add_argument(
        "--proposal",
        help="JSON proposal file; required for non-interactive flows.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute canonical hash, do not write anything.",
    )
    parser.add_argument(
        "--approved-canonical-hash",
        help="SHA-256 of canonical bytes; required for non-dry-run.",
    )
    parser.add_argument(
        "--migrate-strategy",
        choices=("keep-all", "drop-all", "fail", "interactive"),
        default="interactive",
        help="How to treat existing autoMode entries during migrate.",
    )
    parser.add_argument(
        "--show-drift",
        action="store_true",
        help="Delegate to inspect_automode --show-drift; exit 6 on drift.",
    )
    parser.add_argument(
        "--model",
        help="Model passed to claude auto-mode critique.",
    )
    parser.add_argument(
        "--allow-swap-file-fallback",
        action="store_true",
        help=(
            "DEPRECATED no-op (kept for compat). The swap-file path is "
            "now used automatically when the CLI lacks --settings."
        ),
    )
    parser.add_argument(
        "--allow-empty-critique",
        action="store_true",
        help=(
            "Accept a critique that says nothing. By default an empty, "
            "near-empty, or 'no critique was generated' output fails the "
            "gate with exit 3 even though the binary exited 0."
        ),
    )
    parser.add_argument(
        "--strict-critique-sections",
        action="store_true",
        help=(
            "Validate critique output sections against the hardcoded contract "
            "(off by default — the binary's section names drift across versions; "
            "substantiveness, not layout, is the mandatory gate)."
        ),
    )
    parser.add_argument(
        "--allow-unknown-critique-sections",
        action="store_true",
        help=(
            "Forward-compat alias for --strict-critique-sections=loose. "
            "Off by default (validation is now opt-in via --strict-critique-sections)."
        ),
    )
    parser.add_argument(
        "--lint-strict",
        action="store_true",
        help=(
            "Let semantic-lint warnings block too (exit 2). By default only "
            "errors stop the run and warnings are printed for you to judge."
        ),
    )
    parser.add_argument(
        "--no-lint",
        action="store_true",
        help=(
            "Skip the semantic lint of rule content entirely and print "
            "nothing. The escape hatch for a false positive; wins over "
            "--lint-strict."
        ),
    )
    parser.add_argument(
        "--write-shared",
        action="store_true",
        help="Phase 4: also write to .claude/settings.json (opt-in).",
    )
    parser.add_argument(
        "--hoist",
        metavar="RULE",
        help="Move RULE from local autoMode.allow to user baseline.",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Reclaim stale flocks + restore orphans (mutually exclusive).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.repair and any(
        getattr(args, name)
        for name in (
            "dry_run",
            "approved_canonical_hash",
            "proposal",
            "write_shared",
            "hoist",
            "show_drift",
        )
    ):
        _eprint("--repair is mutually exclusive with all other modes.")
        return EXIT_USAGE

    if args.show_drift:
        try:
            from inspect_automode import build_report  # noqa: WPS433
        except ImportError as exc:
            _eprint(f"could not load inspect_automode: {exc}")
            return EXIT_USAGE
        files = resolve(args.project_root)
        report = build_report(files)
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
        return EXIT_DRIFT if report["any_drift"] else EXIT_OK

    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
