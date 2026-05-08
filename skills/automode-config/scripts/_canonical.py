"""Canonical JSON serialization, lenient JSON loading, and flat-YAML parsing.

This module is stdlib-only and is the byte-level contract for the
automode-config skill: every approved bytes representation flows through
``canonicalize`` so that hashes and round-trips are stable.

Public API
----------
canonicalize(obj) -> bytes
    Serialize ``obj`` with ``sort_keys=True``, ``indent=2``,
    ``ensure_ascii=False``, LF line endings, and a trailing newline.

load_json(path) -> object
    Load JSON from ``path`` and re-raise ``json.JSONDecodeError`` with a
    message that includes the byte offset, line, and column.

parse_flat_yaml(text) -> dict[str, str]
    Hand-rolled parser for the small subset of YAML used by the skill's
    asset files (``heuristics.yaml``, ``dropped_rules.yaml``). Refuses
    indentation, lists, empty values, and anchors. Keeps quoted values
    verbatim (without the surrounding quotes).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


CANONICAL_INDENT = 2
CANONICAL_SEPARATORS = (",", ": ")


def canonicalize(obj: Any) -> bytes:
    """Return the canonical UTF-8 byte representation of ``obj``.

    Parameters
    ----------
    obj : object
        Any JSON-serializable Python object.

    Returns
    -------
    bytes
        ``json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False)``
        followed by a single trailing ``\\n``, encoded as UTF-8.
    """

    text = json.dumps(
        obj,
        sort_keys=True,
        indent=CANONICAL_INDENT,
        ensure_ascii=False,
        separators=CANONICAL_SEPARATORS,
    )
    if not text.endswith("\n"):
        text += "\n"
    return text.encode("utf-8")


class FlatYAMLError(ValueError):
    """Raised when ``parse_flat_yaml`` encounters disallowed syntax."""


def load_json(path: str | Path) -> Any:
    """Load JSON from ``path`` and surface byte-offset on parse failure.

    Parameters
    ----------
    path : str or Path
        Filesystem path to a JSON file.

    Returns
    -------
    object
        The decoded JSON value.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    json.JSONDecodeError
        Re-raised with a message that includes byte offset, line, and
        column for easier diagnosis.
    """

    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = (
            f"{p}: invalid JSON at line {exc.lineno}, column {exc.colno} "
            f"(byte offset {exc.pos}): {exc.msg}"
        )
        raise json.JSONDecodeError(msg, exc.doc, exc.pos) from None


def _strip_inline_comment(value: str) -> str:
    """Strip an unquoted ``#`` comment from a flat-YAML scalar tail."""

    in_single = False
    in_double = False
    for i, ch in enumerate(value):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return value[:i].rstrip()
    return value.rstrip()


def _unquote(value: str) -> str:
    """Strip matching surrounding single or double quotes from ``value``."""

    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse_flat_yaml(text: str) -> dict[str, str]:
    """Parse a flat ``key: value`` YAML subset.

    The supported subset is intentionally narrow:

    - One ``key: value`` pair per line, no indentation.
    - No lists (``-`` prefix) and no nested mappings.
    - No empty values (``key:`` alone is rejected).
    - Quoted values are returned with the quotes removed but otherwise
      verbatim (``"# foo"`` keeps its ``#``).
    - ``#`` outside of quotes starts an inline comment, ``# ...`` lines
      are ignored, blank lines are ignored.

    Parameters
    ----------
    text : str
        The raw YAML text.

    Returns
    -------
    dict[str, str]
        Mapping from key to value, both as strings.

    Raises
    ------
    FlatYAMLError
        On indentation, list markers, empty values, duplicate keys, or
        any other syntax outside of the supported subset. The message
        includes the offending ``line:col``.
    """

    out: dict[str, str] = {}
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        if raw_line.startswith((" ", "\t")):
            raise FlatYAMLError(
                f"line {lineno}:1: indentation is not supported"
            )
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            raise FlatYAMLError(
                f"line {lineno}:1: list items are not supported"
            )
        if ":" not in stripped:
            raise FlatYAMLError(
                f"line {lineno}:1: expected 'key: value', got {stripped!r}"
            )
        key, _, rest = stripped.partition(":")
        key = key.strip()
        if not key:
            col = raw_line.index(":") + 1
            raise FlatYAMLError(
                f"line {lineno}:{col}: empty key"
            )
        value = _strip_inline_comment(rest.lstrip())
        if value == "":
            col = raw_line.index(":") + 2
            raise FlatYAMLError(
                f"line {lineno}:{col}: empty value (key {key!r})"
            )
        if key in out:
            raise FlatYAMLError(
                f"line {lineno}:1: duplicate key {key!r}"
            )
        out[key] = _unquote(value)
    return out


def _cli(argv: list[str]) -> int:
    """Tiny CLI for sanity-checking the canonical contract.

    Reads JSON from stdin, prints canonical bytes to stdout. Useful for
    smoke tests (``echo '{}' | uv run _canonical.py`` or piped fixtures).
    """

    if argv and argv[0] in ("-h", "--help"):
        sys.stdout.write(
            "Usage: _canonical.py < input.json\n"
            "\n"
            "Reads JSON on stdin, writes canonical bytes on stdout.\n"
            "(sort_keys=True, indent=2, ensure_ascii=False, trailing \\n)\n"
        )
        return 0
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"invalid JSON on stdin: {exc.msg}\n")
        return 2
    sys.stdout.buffer.write(canonicalize(obj))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
