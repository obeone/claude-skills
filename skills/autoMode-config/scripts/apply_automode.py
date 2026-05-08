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
import datetime as _dt
import glob
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
HEURISTICS_PATH = SKILL_DIR / "assets" / "heuristics.yaml"
DROPPED_RULES_PATH = SKILL_DIR / "assets" / "dropped_rules.yaml"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _canonical import canonicalize, load_json, parse_flat_yaml  # noqa: E402
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

DROPPED_PATTERN_LITERALS = (
    "Bash(*)",
    "PowerShell(*)",
    "Bash(python*)",
    "Agent(*)",
)

REQUIRED_CRITIQUE_SECTIONS = frozenset({"## Major issues", "## Smaller issues"})

BACKUP_RETENTION = 5

AUTOMODE_ARRAY_KEYS = frozenset({"environment", "allow", "soft_deny", "deny", "ask"})


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


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _atomic_write(target: Path, payload: bytes, *, mode: int = EXPECTED_SECRET_MODE) -> None:
    """Atomically write ``payload`` to ``target`` with ``mode`` permissions.

    ``open(tmp, ...)`` -> ``os.write`` -> ``os.fsync`` -> ``os.replace``.
    """

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + f".tmp.{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp, flags, mode)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, target)
    try:
        os.chmod(target, mode)
    except PermissionError:
        pass


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
    - Extra top-level keys beyond ``autoMode`` are allowed (pass-through
      for keys like ``permissions``, ``env``, etc.).
    """

    if not isinstance(proposal, dict):
        raise ProposalValidationError(
            f"proposal: expected object, got {type(proposal).__name__}"
        )

    if "autoMode" not in proposal:
        raise ProposalValidationError("proposal: required key 'autoMode' is missing")

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


def _check_critique_sections(text: str, *, allow_unknown: bool) -> None:
    """Raise ``CritiqueContractError`` when section set drifts."""

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
            f"{sorted(extras)} (use --allow-unknown-critique-sections to "
            f"relax)"
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
    settings_path: Path | None,
    model: str | None,
    allow_swap_file_fallback: bool,
    user_settings_path: Path,
) -> tuple[int, str]:
    """Invoke ``claude auto-mode critique`` and return ``(exit_code, output)``.

    When the CLI accepts ``--settings``, the proposal is fed via that
    flag. Otherwise the swap-file path is taken — but only when
    ``allow_swap_file_fallback`` is True. The swap target is the user
    settings file (``~/.claude/settings.json``) since that is the file
    the classifier reads during the critique invocation.
    """

    cli = _claude_cli()
    canonical = canonicalize(proposal)
    cmd = [cli, "auto-mode", "critique"]
    if model:
        cmd.extend(["--model", model])

    use_settings_flag = _critique_supports_settings_flag()
    if use_settings_flag and settings_path is not None:
        cmd.extend(["--settings", str(settings_path)])
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

    if not allow_swap_file_fallback:
        raise CritiqueContractError(
            "this version of 'claude' does not accept --settings; pass "
            "--allow-swap-file-fallback to swap ~/.claude/settings.json "
            "during the critique invocation."
        )

    return _run_critique_swap(
        cmd,
        canonical=canonical,
        user_settings_path=user_settings_path,
    )


def _run_critique_swap(
    cmd: list[str],
    *,
    canonical: bytes,
    user_settings_path: Path,
) -> tuple[int, str]:
    """Swap ``~/.claude/settings.json`` for the duration of the critique.

    Writes the proposal canonical bytes into the user settings path,
    keeps the original at a stranded sentinel, restores it (or leaves a
    sentinel for ``--repair``) on any exit path.
    """

    user_settings_path.parent.mkdir(parents=True, exist_ok=True)
    sentinel = user_settings_path.parent / (
        f".autoMode-config.preview-orig.{os.getpid()}"
    )
    swap_lock = user_settings_path.with_suffix(user_settings_path.suffix + ".lock")
    handle = lock_acquire(swap_lock)
    install_signal_release(handle)

    if user_settings_path.is_file():
        shutil.copy2(user_settings_path, sentinel)
    try:
        _atomic_write(user_settings_path, canonical, mode=EXPECTED_SECRET_MODE)
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    finally:
        try:
            if sentinel.is_file():
                shutil.copy2(sentinel, user_settings_path)
                sentinel.unlink(missing_ok=True)
            else:
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


def _stranded_files(files: ProjectFiles) -> list[Path]:
    out: list[Path] = []
    for base in (files.user_dir, files.project_dir):
        if not base.is_dir():
            continue
        out.extend(
            Path(p) for p in glob.glob(str(base / ".autoMode-config.preview-orig.*"))
        )
    return sorted(out)


def detect_stranded(files: ProjectFiles) -> list[Path]:
    """Return any ``.preview-orig.<pid>`` files in user or project dirs."""

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
        # Orphan is the original-file copy; the live target sits at the
        # parent dir's settings.json.
        target = orphan.parent / "settings.json"
        if target.is_file():
            _backup_file(target, suffix="repair")
        try:
            shutil.copy2(orphan, target)
            os.chmod(target, EXPECTED_SECRET_MODE)
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


def _phase1_adopt(
    files: ProjectFiles,
    *,
    interactive: bool,
) -> dict[str, Any]:
    """Read shared autoMode and return adopted entries grouped by section."""

    adopted: dict[str, list[Any]] = {}
    if not files.shared_settings.is_file():
        return adopted
    try:
        data = load_json(files.shared_settings)
    except Exception as exc:  # noqa: BLE001
        _eprint(f"phase 1: could not parse {files.shared_settings}: {exc}")
        return adopted
    auto = data.get("autoMode") if isinstance(data, dict) else None
    if not isinstance(auto, dict):
        return adopted
    for section in ("allow", "deny", "ask", "environment"):
        items = auto.get(section)
        if not isinstance(items, list) or not items:
            continue
        _eprint(f"\n[Phase 1] adopt-from-shared :: {section}")
        kept, decisions = _interview(
            items, label=f"shared.{section}", interactive=interactive
        )
        kept = _strip_example_only(kept)
        if section in ("allow", "deny", "ask"):
            kept, dropped = _filter_dropped(kept)
            for entry, reason in dropped:
                _eprint(f"  ! dropped {entry!r}: {reason}")
        adopted[section] = kept
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
        files.project_root, include_shared=False, check_gitignore=False
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
    """Combine ``base`` + ``adopted`` + ``proposal_override`` into one block."""

    out: dict[str, Any] = {"autoMode": {}}
    if isinstance(base, dict):
        out.update({k: v for k, v in base.items() if k != "autoMode"})
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
        for k, v in proposal_override.items():
            if k != "autoMode":
                out[k] = v
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
        block["allow"] = []
        block["deny"] = []
        block["ask"] = []
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

    # --settings capability probe (before any flock).
    settings_flag_supported = _critique_supports_settings_flag()
    if not settings_flag_supported and not args.allow_swap_file_fallback:
        _eprint(
            "this 'claude' does not accept 'auto-mode critique --settings'.\n"
            "rerun with --allow-swap-file-fallback to use the swap-file "
            "path (writes to ~/.claude/settings.json transiently)."
        )
        return EXIT_USAGE

    # ------------------------------------------------------------------
    # Phase 0: detect mode
    # ------------------------------------------------------------------
    mode = args.mode if args.mode != "auto" else _detect_mode(files)

    # ------------------------------------------------------------------
    # Phase 1: adopt-from-shared
    # ------------------------------------------------------------------
    interactive = args.migrate_strategy == "interactive"
    adopted: dict[str, list[Any]] = {}
    if files.shared_settings.is_file():
        try:
            adopted = _phase1_adopt(files, interactive=interactive and sys.stdin.isatty())
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

    proposal = _merge_proposal(
        base=base_local if isinstance(base_local, dict) else None,
        adopted=adopted,
        proposal_override=proposal_override,
    )
    proposal = _strip_example_only(proposal)

    for section in ("allow", "deny", "ask"):
        items = proposal["autoMode"].get(section)
        if isinstance(items, list):
            kept, dropped = _filter_dropped(items)
            for entry, reason in dropped:
                _eprint(f"dropped {section}[{entry!r}]: {reason}")
            proposal["autoMode"][section] = kept

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
    if args.allow_swap_file_fallback and not settings_flag_supported:
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
                settings_path=files.local_settings if settings_flag_supported else None,
                model=args.model,
                allow_swap_file_fallback=args.allow_swap_file_fallback,
                user_settings_path=files.user_settings,
            )
        except ClaudeCLIMissingError as exc:
            _eprint(str(exc))
            return EXIT_CLAUDE_CLI_MISSING
        except CritiqueContractError as exc:
            _eprint(str(exc))
            return EXIT_CRITIQUE_FAILED

        sys.stdout.write(output)
        sys.stdout.write("\n")
        if rc != 0:
            _eprint(f"critique exited {rc}")
            return EXIT_CRITIQUE_FAILED
        try:
            _check_critique_sections(
                output,
                allow_unknown=args.allow_unknown_critique_sections,
            )
        except CritiqueContractError as exc:
            _eprint(str(exc))
            return EXIT_CRITIQUE_FAILED

        backup = _backup_file(files.local_settings)
        try:
            _atomic_write(files.local_settings, canonical, mode=EXPECTED_SECRET_MODE)
        except PermissionError as exc:
            _eprint(f"permission denied writing {files.local_settings}: {exc}")
            return EXIT_PERMISSION

        _update_approved_cache(
            files.approved_cache, label="local", sha256=proposal_hash
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
            sha256=_sha256_bytes(new_canonical),
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
            sha256=_sha256_bytes(canonicalize(user)),
        )
        _update_approved_cache(
            files.approved_cache,
            label="local",
            sha256=_sha256_bytes(canonicalize(local)),
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
        help="Permit swap-file path when the CLI lacks --settings.",
    )
    parser.add_argument(
        "--allow-unknown-critique-sections",
        action="store_true",
        help="Relax contract drift on unexpected critique sections.",
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
