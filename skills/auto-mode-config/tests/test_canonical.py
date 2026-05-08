# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "hypothesis>=6.0",
#   "pytest>=8.0",
# ]
# ///
"""Pytest module for the shared canonical serializer.

Covers the predicates that the hash gate downstream depends on:

1. Every committed fixture round-trips byte-for-byte through the
   ``_canonical.py`` CLI (acceptance criterion #1).
2. ``canonicalize`` is idempotent on its own output for arbitrary
   well-formed JSON (hypothesis property test, seed pinned in
   ``seed.txt``).
3. ``parse_flat_yaml`` accepts the documented happy path and rejects
   nested or malformed input loudly (so heuristics drift fails fast).

Run with::

    uv run -m pytest skills/auto-mode-config/tests/test_canonical.py -q
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

# Make the local _canonical helper importable regardless of CWD.
HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent  # skills/auto-mode-config/
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from _canonical import canonicalize, load_json, parse_flat_yaml  # noqa: E402


FIXTURE_DIR = HERE / "fixtures" / "canonical"
SCRIPT = SKILL_ROOT / "scripts" / "_canonical.py"
SEED_FILE = FIXTURE_DIR / "seed.txt"


def _read_seed() -> int:
    """Return the integer seed pinned in ``seed.txt``.

    Returns
    -------
    int
        Generator seed used by both the fixture generator and this
        module's hypothesis-style property test.
    """
    text = SEED_FILE.read_text(encoding="utf-8")
    parsed = parse_flat_yaml(text)
    return int(parsed["seed"])


# Pinned to keep this test reproducible without re-reading the file
# from inside the @given decorator (which evaluates at import time).
SEED = _read_seed()


def _fixture_pairs() -> list[tuple[Path, Path]]:
    """Enumerate every ``(in_NN.json, out_NN.json)`` pair on disk.

    Returns
    -------
    list of (Path, Path)
        Sorted by NN to keep test IDs stable.
    """
    pairs: list[tuple[Path, Path]] = []
    for in_path in sorted(FIXTURE_DIR.glob("in_*.json")):
        out_path = FIXTURE_DIR / in_path.name.replace("in_", "out_", 1)
        pairs.append((in_path, out_path))
    return pairs


@pytest.mark.parametrize(
    ("in_path", "out_path"),
    _fixture_pairs(),
    ids=[p[0].stem for p in _fixture_pairs()],
)
def test_round_trip_fixture(in_path: Path, out_path: Path) -> None:
    """In-process: ``canonicalize(load_json(in)) == out_path bytes``."""
    expected = out_path.read_bytes()
    actual = canonicalize(load_json(in_path))
    assert actual == expected


@pytest.mark.parametrize(
    ("in_path", "out_path"),
    _fixture_pairs(),
    ids=[p[0].stem for p in _fixture_pairs()],
)
def test_round_trip_via_cli(in_path: Path, out_path: Path) -> None:
    """The CLI surface emits the same bytes as the in-process API."""
    expected = out_path.read_bytes()
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=in_path.read_bytes(),
        capture_output=True,
        check=True,
    )
    assert proc.stdout == expected


def test_idempotent_predicate_for_each_fixture() -> None:
    """``canonical(load(canonical(load(x)))) == canonical(load(x))``."""
    for in_path, _ in _fixture_pairs():
        once = canonicalize(load_json(in_path))
        twice = canonicalize(json.loads(once))
        assert once == twice, f"non-idempotent for {in_path.name}"


JSON_LEAVES = (
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**31), max_value=2**31)
    | st.floats(allow_nan=False, allow_infinity=False, width=64)
    | st.text(max_size=24)
)

JSON_VALUES = st.recursive(
    JSON_LEAVES,
    lambda children: st.lists(children, max_size=6)
    | st.dictionaries(
        keys=st.text(min_size=1, max_size=10),
        values=children,
        max_size=6,
    ),
    max_leaves=12,
)


@settings(
    derandomize=True,
    database=None,
    max_examples=80,
    deadline=None,
    suppress_health_check=list(HealthCheck),
)
@given(value=JSON_VALUES)
def test_canonical_is_idempotent_property(value: object) -> None:
    """Hypothesis property: canonicalize is idempotent on any JSON value.

    The seed pinned in ``seed.txt`` is referenced for documentation
    only — ``derandomize=True`` already makes the example sequence
    reproducible across runs.
    """
    assert SEED == 20260508  # tripwire: regenerate fixtures if this fires
    once = canonicalize(value)
    twice = canonicalize(json.loads(once))
    assert once == twice


def test_parse_flat_yaml_happy_path() -> None:
    """Happy-path keys, comments, and quoted values.

    The walker treats `` #`` (space + hash) as a trailing-comment
    introducer regardless of what follows. Values that need a literal
    ``#`` must be quoted (see ``key_d``).
    """
    text = (
        "# header comment\n"
        "key_a: value_a\n"
        "key_b: 'quoted value'\n"
        "key_c: \"double quoted\"\n"
        "\n"
        'key_d: "bare value with #hash inside"\n'
        "key_e: trailing # comment dropped\n"
    )
    parsed = parse_flat_yaml(text)
    assert parsed == {
        "key_a": "value_a",
        "key_b": "quoted value",
        "key_c": "double quoted",
        "key_d": "bare value with #hash inside",
        "key_e": "trailing",
    }


@pytest.mark.parametrize(
    "text",
    [
        "  indented: nope\n",
        "list:\n  - item\n",
        "no_separator_here\n",
        "empty_value:\n",
        ": empty key\n",
        "dup: a\ndup: b\n",
    ],
)
def test_parse_flat_yaml_rejects_nested_or_malformed(text: str) -> None:
    """Each malformed input raises ``ValueError`` with a line number."""
    with pytest.raises(ValueError):
        parse_flat_yaml(text)


def test_parse_flat_yaml_handles_blank_lines_and_comments() -> None:
    """Empty input and comment-only input parse to ``{}``."""
    assert parse_flat_yaml("") == {}
    assert parse_flat_yaml("# only a comment\n\n# another\n") == {}


def test_load_json_reports_byte_offset(tmp_path: Path) -> None:
    """Malformed JSON raises ``JSONDecodeError`` with the byte offset."""
    bad = tmp_path / "bad.json"
    bad.write_text('{"a": 1, "b": }\n', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError) as ei:
        load_json(bad)
    assert "byte offset" in str(ei.value)
