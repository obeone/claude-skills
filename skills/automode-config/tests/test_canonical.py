"""Canonical-serializer tests (acceptance #1).

Covers:

- 50 in-process round-trip tests: load fixtures/canonical/in_NN.json,
  canonicalize, assert bytes == out_NN.json.
- 50 CLI round-trip tests: subprocess ``uv run scripts/_canonical.py``
  with stdin/stdout, assert stdout == out_NN.json.
- Idempotency: ``canonicalize(canonicalize(x)) == canonicalize(x)``.
- Hypothesis property test: ~80 examples, fixed point on JSON-
  serializable objects.
- ``parse_flat_yaml`` happy and sad paths.
- ``load_json`` byte-offset error message.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import _canonical  # noqa: E402  (path injected via conftest)

try:  # Hypothesis is in the run-with deps; import lazily so the rest of
    # the module can still load if it's missing.
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st

    _HYPOTHESIS_AVAILABLE = True
except Exception:  # pragma: no cover - hypothesis is required for the suite
    _HYPOTHESIS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


CANONICAL_INDEXES = list(range(50))


def _fixture_pair(canonical_fixtures_dir: Path, idx: int) -> tuple[Path, Path]:
    in_path = canonical_fixtures_dir / f"in_{idx:02d}.json"
    out_path = canonical_fixtures_dir / f"out_{idx:02d}.json"
    if not in_path.exists() or not out_path.exists():
        pytest.skip(
            f"canonical fixtures missing for index {idx:02d}; "
            "run tests/fixtures/canonical/_generate.py"
        )
    return in_path, out_path


# ---------------------------------------------------------------------------
# In-process round-trip (50 tests)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("idx", CANONICAL_INDEXES)
def test_canonical_inprocess_roundtrip(canonical_fixtures_dir: Path, idx: int):
    """canonicalize(load(in_NN)) == out_NN bytes."""

    in_path, out_path = _fixture_pair(canonical_fixtures_dir, idx)
    obj = json.loads(in_path.read_text(encoding="utf-8"))
    actual = _canonical.canonicalize(obj)
    expected = out_path.read_bytes()
    assert actual == expected, (
        f"canonical bytes mismatch for {in_path.name}:\n"
        f"actual:   {actual!r}\nexpected: {expected!r}"
    )


# ---------------------------------------------------------------------------
# CLI round-trip (50 tests)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("idx", CANONICAL_INDEXES)
def test_canonical_cli_roundtrip(
    canonical_fixtures_dir: Path, scripts_dir: Path, idx: int
):
    """``uv run _canonical.py`` reading stdin yields out_NN bytes."""

    in_path, out_path = _fixture_pair(canonical_fixtures_dir, idx)
    cli = scripts_dir / "_canonical.py"
    if not cli.exists():
        pytest.skip(f"{cli} not present")
    proc = subprocess.run(
        ["uv", "run", str(cli)],
        input=in_path.read_bytes(),
        capture_output=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"_canonical.py exited {proc.returncode}; "
        f"stderr={proc.stderr.decode('utf-8', 'replace')!r}"
    )
    expected = out_path.read_bytes()
    assert proc.stdout == expected, (
        f"CLI canonical output mismatch for {in_path.name}:\n"
        f"actual:   {proc.stdout!r}\nexpected: {expected!r}"
    )


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("idx", CANONICAL_INDEXES)
def test_canonical_idempotent(canonical_fixtures_dir: Path, idx: int):
    """canonicalize(canonicalize(x)) == canonicalize(x)."""

    in_path, _ = _fixture_pair(canonical_fixtures_dir, idx)
    obj = json.loads(in_path.read_text(encoding="utf-8"))
    once = _canonical.canonicalize(obj)
    twice = _canonical.canonicalize(json.loads(once.decode("utf-8")))
    assert once == twice


# ---------------------------------------------------------------------------
# Hypothesis property test
# ---------------------------------------------------------------------------


if _HYPOTHESIS_AVAILABLE:

    _json_leaves = st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-(10**9), max_value=10**9),
        st.floats(allow_nan=False, allow_infinity=False, width=32),
        st.text(max_size=32),
    )

    _json_values = st.recursive(
        _json_leaves,
        lambda children: st.one_of(
            st.lists(children, max_size=4),
            st.dictionaries(st.text(max_size=8), children, max_size=4),
        ),
        max_leaves=12,
    )

    @settings(
        max_examples=80,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(obj=_json_values)
    def test_canonical_hypothesis_fixed_point(obj: Any):
        """Round-tripping through canonical bytes is a fixed point."""

        once = _canonical.canonicalize(obj)
        # Bytes should be valid utf-8 JSON.
        decoded = json.loads(once.decode("utf-8"))
        twice = _canonical.canonicalize(decoded)
        assert once == twice


# ---------------------------------------------------------------------------
# parse_flat_yaml happy + sad paths
# ---------------------------------------------------------------------------


def test_parse_flat_yaml_simple_pairs():
    text = "key: value\nfoo: bar\n"
    out = _canonical.parse_flat_yaml(text)
    assert out == {"key": "value", "foo": "bar"}


def test_parse_flat_yaml_quoted_values_unquoted():
    text = 'k1: "with spaces"\nk2: \'single quoted\'\nk3: plain\n'
    out = _canonical.parse_flat_yaml(text)
    # Quoted values lose the surrounding quotes but are preserved verbatim
    # otherwise (e.g. an inner ``#`` is kept since it sat inside quotes).
    assert out["k1"] == "with spaces"
    assert out["k2"] == "single quoted"
    assert out["k3"] == "plain"


def test_parse_flat_yaml_quoted_value_keeps_hash():
    text = 'k: "value # not a comment"\n'
    out = _canonical.parse_flat_yaml(text)
    assert out["k"] == "value # not a comment"


def test_parse_flat_yaml_comments_and_blanks():
    text = (
        "# top comment\n"
        "\n"
        "k: v\n"
        "  # not a comment? still ignored\n"  # comments may appear with leading space
        "x: y\n"
    )
    # Leading whitespace anywhere is treated as indentation -> sad path.
    # The "  # not a comment" line starts with whitespace, so reject.
    with pytest.raises(ValueError):
        _canonical.parse_flat_yaml(text)


def test_parse_flat_yaml_comments_only_at_col_zero():
    text = "# header\nk: v\n# trailing\n"
    out = _canonical.parse_flat_yaml(text)
    assert out == {"k": "v"}


def test_parse_flat_yaml_rejects_indentation():
    text = "outer: 1\n  inner: 2\n"
    with pytest.raises(ValueError) as excinfo:
        _canonical.parse_flat_yaml(text)
    msg = str(excinfo.value).lower()
    assert "line" in msg and ("2" in msg or "indent" in msg)


def test_parse_flat_yaml_rejects_lists():
    text = "k:\n- a\n- b\n"
    with pytest.raises(ValueError):
        _canonical.parse_flat_yaml(text)


def test_parse_flat_yaml_rejects_empty_value():
    text = "key:\n"
    with pytest.raises(ValueError) as excinfo:
        _canonical.parse_flat_yaml(text)
    assert "empty" in str(excinfo.value).lower() or "value" in str(excinfo.value).lower()


def test_parse_flat_yaml_error_reports_line_or_col():
    text = "good: ok\nthis is malformed line\n"
    with pytest.raises(ValueError) as excinfo:
        _canonical.parse_flat_yaml(text)
    msg = str(excinfo.value).lower()
    # Error must mention either a line number or a column number.
    assert "line" in msg or "col" in msg


# ---------------------------------------------------------------------------
# load_json byte-offset error
# ---------------------------------------------------------------------------


def test_load_json_byte_offset_error(tmp_path: Path):
    """A malformed JSON file produces an error mentioning the byte offset."""

    bad = tmp_path / "bad.json"
    # 'k' at offset 0 is invalid JSON -> json.JSONDecodeError raised by
    # the stdlib parser at column 1 (offset 0).
    bad.write_text('{"k": "v",,}\n', encoding="utf-8")
    with pytest.raises(Exception) as excinfo:
        _canonical.load_json(bad)
    msg = str(excinfo.value).lower()
    # Must mention a byte/char offset to be useful.
    assert any(term in msg for term in ("byte", "offset", "char", "col"))


def test_load_json_round_trips_valid_file(tmp_path: Path):
    p = tmp_path / "ok.json"
    obj = {"a": 1, "b": [1, 2, 3]}
    p.write_text(json.dumps(obj) + "\n", encoding="utf-8")
    assert _canonical.load_json(p) == obj
