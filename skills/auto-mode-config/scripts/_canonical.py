# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Shared canonical JSON serializer and small JSON/flat-YAML helpers.

This module is the single source of truth for byte-level canonicalization
of `~/.claude/settings.json` content within the ``auto-mode-config`` skill.
Every other script (``inspect_automode.py``, ``apply_automode.py``,
``scan_project.py``) MUST go through this module to guarantee that the
hash gate (``--approved-canonical-hash``) is reproducible across runs and
hosts.

Stability contract
------------------
- Output uses ``json.dumps(obj, sort_keys=True, indent=2,
  ensure_ascii=False)``.
- Output is encoded in UTF-8.
- A trailing ``\n`` is appended (LF only, never CRLF).
- The round-trip predicate
  ``canonical(load(canonical(load(x)))) == canonical(load(x))`` holds for
  any well-formed JSON value.

CLI contract
------------
When invoked as ``python _canonical.py`` (no arguments), reads JSON from
stdin and writes the canonical bytes to stdout. Used by acceptance
criterion #1 of the skill.

Flat YAML walker
----------------
``parse_flat_yaml`` reads a strictly flat ``key: value`` document with
``# comments`` and blank lines. It refuses anything that looks nested
(leading whitespace before keys, ``- `` list markers, ``:`` lines without
a value) so callers fail loudly if the heuristics file accidentally
introduces structure that the skill is not equipped to handle.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def canonicalize(obj: Any) -> bytes:
    """Return the canonical UTF-8 byte representation of ``obj``.

    Parameters
    ----------
    obj
        Any JSON-serializable Python value.

    Returns
    -------
    bytes
        UTF-8 bytes ending in a single ``\\n``.
    """
    text = json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def load_json(path: str | Path) -> Any:
    """Load JSON from ``path`` with an explicit byte-offset on failure.

    Parameters
    ----------
    path
        Filesystem path of the JSON document.

    Returns
    -------
    Any
        The decoded JSON value.

    Raises
    ------
    json.JSONDecodeError
        Re-raised with the byte offset preserved so callers can surface a
        precise diagnostic to the user.
    """
    p = Path(path)
    raw = p.read_bytes()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = (
            f"{p}: invalid JSON at byte offset {exc.pos} "
            f"(line {exc.lineno}, column {exc.colno}): {exc.msg}"
        )
        raise json.JSONDecodeError(msg, exc.doc, exc.pos) from None


def parse_flat_yaml(text: str) -> dict[str, str]:
    """Parse a strictly flat ``key: value`` YAML document.

    Supports ``# comments``, blank lines, and a single optional layer of
    inline quotes around the value (``"..."`` or ``'...'``). Refuses
    indentation, list markers, and bare ``key:`` lines without a value
    so accidental structure does not silently round-trip through the
    skill.

    Parameters
    ----------
    text
        Raw YAML source.

    Returns
    -------
    dict of str to str
        One entry per ``key: value`` line, in source order.

    Raises
    ------
    ValueError
        If a line cannot be parsed as a flat ``key: value`` pair, with
        the offending 1-based line number and an explanation of the
        failure mode.
    """
    out: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        # Strip trailing newline residue and right-pad whitespace,
        # but preserve leading spaces so we can detect indentation.
        line = raw.rstrip()
        if line == "":
            continue
        if line.lstrip().startswith("#"):
            continue
        if line[0] in (" ", "\t"):
            raise ValueError(
                f"line {lineno}: nested structure not supported "
                f"(unexpected indentation): {raw!r}"
            )
        if line.lstrip().startswith("- "):
            raise ValueError(
                f"line {lineno}: list markers not supported in flat YAML: {raw!r}"
            )
        if ":" not in line:
            raise ValueError(
                f"line {lineno}: missing ':' separator: {raw!r}"
            )
        key, _, rest = line.partition(":")
        key = key.strip()
        if key == "":
            raise ValueError(f"line {lineno}: empty key: {raw!r}")
        value = rest.strip()
        if value == "":
            raise ValueError(
                f"line {lineno}: empty value, nested structure not supported: {raw!r}"
            )
        # If the value is wrapped in matching quotes, take the quoted
        # contents verbatim — the quoted span hides any ``#`` it
        # contains, so no comment-stripping happens for quoted values.
        if (value.startswith('"') or value.startswith("'")) and len(value) >= 2:
            quote = value[0]
            end = value.find(quote, 1)
            if end == -1:
                raise ValueError(
                    f"line {lineno}: unterminated {quote} quote in value: {raw!r}"
                )
            value = value[1:end]
        else:
            # Bare value — strip an optional trailing inline comment.
            # Only ' #' counts as a comment introducer so embedded
            # hashes inside the value would still need quoting if a
            # space precedes them.
            comment_pos = value.find(" #")
            if comment_pos >= 0:
                value = value[:comment_pos]
            value = value.strip()
        if key in out:
            raise ValueError(f"line {lineno}: duplicate key {key!r}")
        out[key] = value
    return out


def _main() -> int:
    """Read JSON from stdin, write canonical bytes to stdout.

    Returns
    -------
    int
        Process exit code (0 on success, 2 on malformed JSON input).
    """
    raw = sys.stdin.buffer.read()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.stderr.write(
            f"_canonical.py: invalid JSON at byte offset {exc.pos} "
            f"(line {exc.lineno}, column {exc.colno}): {exc.msg}\n"
        )
        return 2
    sys.stdout.buffer.write(canonicalize(obj))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
