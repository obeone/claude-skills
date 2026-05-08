#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Read-only project scanner for the ``auto-mode-config`` skill.

The scanner inspects the *current working directory only* (depth 0) for
the file-name signals declared in ``assets/heuristics.yaml`` and emits a
single JSON object on stdout. It is the advisor leg of the skill: it
produces seed material for ``autoMode.environment`` claims without
mutating anything on disk.

Behaviour
---------
- Probes ``claude --version`` and refuses to run when the detected
  Claude Code version is outside the band declared in
  ``heuristics.yaml`` (key ``claude_code_version_range``).
  Exit code: 10 (``OutOfBandError``) — matches the contract in
  ``team-plan.md``.
- Emits the JSON shape

  ::

      {
        "language_signals": [...],
        "build_tools": [...],
        "claude_md_present": bool,
        "claude_md_headings_count": int
      }

  Each signal label is the suffix of a ``signal_<label>:`` key in
  ``heuristics.yaml`` whose regex matches at least one entry in the
  current directory. Labels are deduplicated and emitted in
  alphabetical order.

Exit codes
----------
- 0 success
- 1 usage error
- 5 ``claude`` not on PATH
- 10 Claude Code version outside the supported band

The scanner does not read the contents of ``CLAUDE.md`` (the contract
explicitly says: presence and heading count only).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# Late stdlib-only import so this script remains usable in environments
# where ``_canonical`` happens to be on ``sys.path`` but not as a
# package neighbour (worktree symlinks etc.).
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import _canonical  # noqa: E402  (path manipulation must precede import)


HEURISTICS_PATH = SCRIPT_DIR.parent / "assets" / "heuristics.yaml"

# Build-tool signals (vs. language signals) — labels listed here are
# emitted under ``build_tools`` in the JSON output. Anything else flows
# into ``language_signals``.
BUILD_TOOL_LABELS = frozenset(
    {
        "docker",
        "compose",
        "make",
        "just",
        "taskfile",
        "bazel",
        "tool_versions",
    }
)


def _err(msg: str) -> None:
    """Write a single line to stderr (newline-terminated).

    Parameters
    ----------
    msg
        Message body, without trailing newline.
    """
    sys.stderr.write(msg + "\n")


def _parse_version(text: str) -> tuple[int, int, int] | None:
    """Extract the first ``MAJOR.MINOR.PATCH`` triple from ``text``.

    Parameters
    ----------
    text
        Output of ``claude --version`` (or any text containing one).

    Returns
    -------
    tuple of int, int, int or None
        ``(major, minor, patch)`` or ``None`` if no triple is present.
    """
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


_BAND_TOKEN_RE = re.compile(r"\s*(>=|<=|>|<|==)\s*(\d+)\.(\d+)(?:\.(\d+))?\s*")


def _parse_version_band(spec: str) -> list[tuple[str, tuple[int, int, int]]]:
    """Parse a comma-separated ``>=A.B.C,<X.Y`` band into predicates.

    Parameters
    ----------
    spec
        The raw value of ``claude_code_version_range`` from
        ``heuristics.yaml``.

    Returns
    -------
    list of tuple
        Pairs of ``(operator, (major, minor, patch))``. A two-component
        version like ``<3.0`` is normalised to ``(3, 0, 0)``.

    Raises
    ------
    ValueError
        If a token is malformed, with the offending fragment included.
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


def _band_allows(version: tuple[int, int, int], predicates: list[tuple[str, tuple[int, int, int]]]) -> bool:
    """Return True iff ``version`` satisfies every predicate.

    Parameters
    ----------
    version
        The detected ``(major, minor, patch)``.
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


def _probe_claude_version() -> tuple[int, int, int]:
    """Run ``claude --version`` and return the parsed triple.

    Returns
    -------
    tuple of int, int, int
        Detected version.

    Raises
    ------
    SystemExit
        Exits with code 5 if ``claude`` is not on PATH or its output
        cannot be parsed.
    """
    if shutil.which("claude") is None:
        _err(
            "scan_project.py: `claude` CLI not found on PATH. Install "
            "Claude Code (https://claude.com/product/claude-code) and "
            "ensure the binary is reachable, then re-run."
        )
        raise SystemExit(5)
    try:
        proc = subprocess.run(
            ["claude", "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        _err(f"scan_project.py: failed to invoke `claude --version`: {exc}")
        raise SystemExit(5) from None
    combined = (proc.stdout or "") + (proc.stderr or "")
    version = _parse_version(combined)
    if version is None:
        _err(
            "scan_project.py: could not parse a version triple from "
            f"`claude --version` output: {combined.strip()!r}"
        )
        raise SystemExit(5)
    return version


def _load_heuristics() -> tuple[str, dict[str, str]]:
    """Read and parse ``heuristics.yaml``.

    Returns
    -------
    tuple of str, dict
        ``(version_range, signal_patterns)`` where ``signal_patterns``
        maps the ``signal_`` suffix (the label) to the raw regex string.

    Raises
    ------
    SystemExit
        Exits with code 1 if ``heuristics.yaml`` is missing or
        malformed, or with code 1 if it lacks the required
        ``claude_code_version_range`` key.
    """
    if not HEURISTICS_PATH.is_file():
        _err(f"scan_project.py: heuristics file not found: {HEURISTICS_PATH}")
        raise SystemExit(1)
    try:
        flat = _canonical.parse_flat_yaml(HEURISTICS_PATH.read_text(encoding="utf-8"))
    except ValueError as exc:
        _err(f"scan_project.py: malformed heuristics file: {exc}")
        raise SystemExit(1) from None
    version_range = flat.get("claude_code_version_range")
    if not version_range:
        _err(
            "scan_project.py: heuristics.yaml missing required key "
            "'claude_code_version_range'"
        )
        raise SystemExit(1)
    signals: dict[str, str] = {}
    for key, value in flat.items():
        if not key.startswith("signal_"):
            continue
        label = key[len("signal_") :]
        if label == "":
            _err(f"scan_project.py: empty signal label in key {key!r}")
            raise SystemExit(1)
        signals[label] = value
    return version_range, signals


def _scan_directory(
    cwd: Path, signal_patterns: dict[str, str]
) -> tuple[list[str], list[str]]:
    """Apply each signal regex to the file names in ``cwd`` (depth 0).

    Parameters
    ----------
    cwd
        Directory to inspect; only its immediate children are read.
    signal_patterns
        Mapping of signal label to regex string.

    Returns
    -------
    tuple of list, list
        ``(language_signals, build_tools)`` — each a deduplicated,
        sorted list of label strings.

    Raises
    ------
    SystemExit
        Exits with code 1 if any pattern fails to compile.
    """
    try:
        entries = [p.name for p in cwd.iterdir()]
    except (PermissionError, OSError) as exc:
        _err(f"scan_project.py: cannot read directory {cwd}: {exc}")
        raise SystemExit(1) from None
    matched: set[str] = set()
    for label, pattern in signal_patterns.items():
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            _err(
                f"scan_project.py: invalid regex for signal_{label!s}: "
                f"{pattern!r} ({exc})"
            )
            raise SystemExit(1) from None
        for name in entries:
            if regex.search(name):
                matched.add(label)
                break
    languages = sorted(label for label in matched if label not in BUILD_TOOL_LABELS)
    build_tools = sorted(label for label in matched if label in BUILD_TOOL_LABELS)
    return languages, build_tools


def _claude_md_summary(cwd: Path) -> tuple[bool, int]:
    """Report ``CLAUDE.md`` presence and ATX heading count.

    Parameters
    ----------
    cwd
        Directory to inspect.

    Returns
    -------
    tuple of bool, int
        ``(present, headings_count)``. The count is ``0`` when the file
        is absent or unreadable. Only ATX-style headings (``#``-prefixed
        lines) are counted; setext (underlined) headings are ignored
        because the scanner makes no claim about content semantics.
    """
    path = cwd / "CLAUDE.md"
    if not path.is_file():
        return False, 0
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True, 0
    count = 0
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#") and not stripped.startswith("#!"):
            # ATX heading: at least one '#', then space or end-of-line.
            after_hashes = stripped.lstrip("#")
            if after_hashes == "" or after_hashes[0] in (" ", "\t"):
                count += 1
    return True, count


def _build_parser() -> argparse.ArgumentParser:
    """Return the CLI parser.

    Returns
    -------
    argparse.ArgumentParser
        Configured parser for ``--cwd`` and ``--skip-version-check``.
    """
    parser = argparse.ArgumentParser(
        prog="scan_project.py",
        description=(
            "Read-only scanner for the auto-mode-config skill. Emits a "
            "JSON summary of project signals on stdout."
        ),
    )
    parser.add_argument(
        "--cwd",
        type=Path,
        default=None,
        help="Directory to scan (default: current working directory).",
    )
    parser.add_argument(
        "--skip-version-check",
        action="store_true",
        help=(
            "Skip the `claude --version` band check. Intended for tests "
            "and CI; production callers should leave it off."
        ),
    )
    return parser


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
    cwd = (args.cwd or Path.cwd()).resolve()
    if not cwd.is_dir():
        _err(f"scan_project.py: --cwd is not a directory: {cwd}")
        return 1
    version_range, signal_patterns = _load_heuristics()
    if not args.skip_version_check:
        version = _probe_claude_version()
        try:
            predicates = _parse_version_band(version_range)
        except ValueError as exc:
            _err(f"scan_project.py: invalid claude_code_version_range: {exc}")
            return 1
        if not _band_allows(version, predicates):
            v_str = ".".join(str(n) for n in version)
            _err(
                f"scan_project.py: detected Claude Code {v_str} is "
                f"outside the supported band {version_range!r}. Refusing "
                "to scan; the heuristics may be stale for this version. "
                "Update the skill or run with --skip-version-check at "
                "your own risk."
            )
            return 10
    languages, build_tools = _scan_directory(cwd, signal_patterns)
    claude_md_present, headings = _claude_md_summary(cwd)
    payload: dict[str, Any] = {
        "language_signals": languages,
        "build_tools": build_tools,
        "claude_md_present": claude_md_present,
        "claude_md_headings_count": headings,
    }
    sys.stdout.buffer.write(_canonical.canonicalize(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
