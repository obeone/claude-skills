#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Read-only diagnostics for ``~/.claude/settings.json``.

The inspector loads the user-level Claude Code settings file, computes
its canonical form via :mod:`_canonical`, and prints both the canonical
preview and the SHA-256 hash. It is the validator leg of the
``auto-mode-config`` skill: it never writes to disk, never invokes
``claude``, and is allowed on any plan tier.

Behaviour
---------
- Default: print canonical settings preview to stdout, terminating with
  ``canonical_sha256: <hex>`` on the last line.
- ``--show-drift``: load the cached approved canonical bytes from
  ``~/.claude/.auto_mode_approved.json`` (a verbatim canonical-bytes
  snapshot, written by ``apply_automode.py`` on a successful apply),
  diff against the current canonical via :func:`difflib.unified_diff`,
  and exit ``6`` when the two differ. Equality exits ``0``.
- Absent ``~/.claude/settings.json``: print
  ``no autoMode config found at ~/.claude/settings.json`` to stderr and
  exit ``0``. Drift mode against an absent settings file is treated as
  no drift (exit ``0``).

Exit codes
----------
- 0 success (or absent settings, or no drift)
- 1 usage error
- 2 malformed JSON in settings
- 6 ``--show-drift`` detected drift

The script is stdlib-only on purpose so it can run in any environment
the user can reach the ``~/.claude`` tree from.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import _canonical  # noqa: E402


SETTINGS_DEFAULT = "~/.claude/settings.json"
APPROVED_DEFAULT = "~/.claude/.auto_mode_approved.json"


def _err(msg: str) -> None:
    """Write a single newline-terminated line to stderr.

    Parameters
    ----------
    msg
        Message body, without trailing newline.
    """
    sys.stderr.write(msg + "\n")


def _expand(path: str) -> Path:
    """Expand ``~`` and resolve to an absolute path without symlink chase.

    Parameters
    ----------
    path
        Raw user-supplied or default path.

    Returns
    -------
    Path
        Absolute filesystem path.
    """
    return Path(path).expanduser().absolute()


def _load_settings(path: Path) -> tuple[bytes, str] | None:
    """Read settings, return canonical bytes and SHA-256.

    Parameters
    ----------
    path
        Settings file path.

    Returns
    -------
    tuple of bytes, str or None
        ``(canonical_bytes, sha256_hex)`` if present.
        ``None`` if the file does not exist.

    Raises
    ------
    SystemExit
        Exits ``2`` on malformed JSON.
    """
    if not path.exists():
        return None
    try:
        obj = _canonical.load_json(path)
    except json.JSONDecodeError as exc:
        _err(f"inspect_automode.py: {exc.msg}")
        raise SystemExit(2) from None
    canonical = _canonical.canonicalize(obj)
    return canonical, hashlib.sha256(canonical).hexdigest()


def _build_parser() -> argparse.ArgumentParser:
    """Return the CLI parser.

    Returns
    -------
    argparse.ArgumentParser
        Parser configured with ``--user-settings``, ``--show-drift``,
        ``--approved-cache``.
    """
    parser = argparse.ArgumentParser(
        prog="inspect_automode.py",
        description=(
            "Read-only diagnostics for ~/.claude/settings.json. Prints "
            "the canonical preview and SHA-256 hash. Use --show-drift "
            "to diff against the cached approved canonical bytes."
        ),
    )
    parser.add_argument(
        "--user-settings",
        default=SETTINGS_DEFAULT,
        help=f"Path to the user settings file (default: {SETTINGS_DEFAULT}).",
    )
    parser.add_argument(
        "--approved-cache",
        default=APPROVED_DEFAULT,
        help=(
            f"Path to the cached approved canonical bytes "
            f"(default: {APPROVED_DEFAULT})."
        ),
    )
    parser.add_argument(
        "--show-drift",
        action="store_true",
        help=(
            "Diff current canonical settings against the cached approved "
            "bytes; exit 6 when they differ."
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
    settings_path = _expand(args.user_settings)
    loaded = _load_settings(settings_path)
    if loaded is None:
        _err(f"no autoMode config found at {args.user_settings}")
        return 0
    canonical, sha = loaded
    if args.show_drift:
        approved_path = _expand(args.approved_cache)
        if not approved_path.exists():
            # No baseline yet — informational, not drift.
            sys.stdout.buffer.write(canonical)
            sys.stdout.write(f"canonical_sha256: {sha}\n")
            sys.stdout.write(
                "no approved baseline at "
                f"{args.approved_cache} (run apply_automode.py once to seed)\n"
            )
            return 0
        approved_bytes = approved_path.read_bytes()
        if approved_bytes == canonical:
            sys.stdout.buffer.write(canonical)
            sys.stdout.write(f"canonical_sha256: {sha}\n")
            sys.stdout.write("no drift against approved baseline\n")
            return 0
        # Drift detected — emit a unified diff.
        approved_text = approved_bytes.decode("utf-8", errors="replace")
        current_text = canonical.decode("utf-8")
        diff = difflib.unified_diff(
            approved_text.splitlines(keepends=True),
            current_text.splitlines(keepends=True),
            fromfile=str(approved_path),
            tofile=str(settings_path),
            n=3,
        )
        sys.stdout.write("=== drift vs approved baseline ===\n")
        for line in diff:
            sys.stdout.write(line)
        if not current_text.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.write(f"canonical_sha256: {sha}\n")
        return 6
    sys.stdout.buffer.write(canonical)
    sys.stdout.write(f"canonical_sha256: {sha}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
