#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Deterministic canonical-fixture generator.

Writes 50 input/output pairs (in_NN.json / out_NN.json) into the same
directory as this script.

The first 10 inputs are hand-curated edge cases (unicode keys, deep
nesting, top-level scalars, mixed types, very long strings, escapes,
empty object, single key). Inputs 10..49 are generated with the
stdlib ``random`` module seeded with the value stored in
``seed.txt`` (default: 20260508), making them reproducible.

Each ``in_NN.json`` is written verbatim from a Python object; the
matching ``out_NN.json`` is produced by importing
``scripts/_canonical.py`` and calling ``canonicalize`` on the parsed
JSON, so by construction every pair is a fixed point of the canonical
serializer.
"""

from __future__ import annotations

import importlib.util
import json
import random
import string
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent.parent
SKILL_DIR = TESTS_DIR.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
SEED_FILE = HERE / "seed.txt"


def _load_canonical():
    """Import ``_canonical`` from the sibling ``scripts/`` directory."""

    canonical_path = SCRIPTS_DIR / "_canonical.py"
    if not canonical_path.exists():
        raise FileNotFoundError(
            f"_canonical.py not found at {canonical_path}; cannot generate fixtures"
        )
    spec = importlib.util.spec_from_file_location("_canonical", canonical_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"failed to build spec for {canonical_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_seed() -> int:
    if SEED_FILE.exists():
        return int(SEED_FILE.read_text(encoding="utf-8").strip())
    return 20260508


def _hand_curated() -> list[Any]:
    """Return the 10 hand-curated edge cases."""

    very_long = "x" * 4096
    return [
        # 00: unicode keys + values
        {"clé": "valeur", "ключ": "значение", "鍵": "値"},
        # 01: deep nesting
        {
            "a": {
                "b": {
                    "c": {
                        "d": {"e": {"f": {"g": {"h": {"i": {"j": 1}}}}}}
                    }
                }
            }
        },
        # 02: top-level null
        None,
        # 03: top-level array
        [1, 2, 3, "four", None, True, False, {"k": "v"}],
        # 04: top-level string
        "hello world",
        # 05: mixed types in object
        {
            "string": "s",
            "int": 1,
            "float": 1.5,
            "bool_t": True,
            "bool_f": False,
            "null": None,
            "array": [1, 2, 3],
            "object": {"nested": True},
        },
        # 06: very long string
        {"long": very_long},
        # 07: escaped chars
        {
            "newline": "line1\nline2",
            "tab": "a\tb",
            "quote": "he said \"hi\"",
            "backslash": "C:\\Users\\test",
            "control": "",
        },
        # 08: empty object
        {},
        # 09: single key
        {"k": "v"},
    ]


def _rand_string(rng: random.Random, max_len: int = 24) -> str:
    n = rng.randint(0, max_len)
    alphabet = string.ascii_letters + string.digits + "_-. "
    return "".join(rng.choice(alphabet) for _ in range(n))


def _rand_value(rng: random.Random, depth: int = 0) -> Any:
    """Pick a JSON-serializable value at random; depth-limited."""

    if depth >= 4:
        kind = rng.choice(["string", "int", "float", "bool", "null"])
    else:
        kind = rng.choice(
            ["string", "int", "float", "bool", "null", "array", "object"]
        )
    if kind == "string":
        return _rand_string(rng)
    if kind == "int":
        return rng.randint(-10_000, 10_000)
    if kind == "float":
        # Use simple fractions to avoid IEEE-754 precision drift surprises.
        return rng.randint(-10000, 10000) / 100
    if kind == "bool":
        return rng.choice([True, False])
    if kind == "null":
        return None
    if kind == "array":
        return [_rand_value(rng, depth + 1) for _ in range(rng.randint(0, 5))]
    if kind == "object":
        return {
            _rand_string(rng, max_len=12) or f"k{i}": _rand_value(rng, depth + 1)
            for i in range(rng.randint(0, 5))
        }
    raise AssertionError("unreachable")


def _rand_root(rng: random.Random) -> Any:
    """Generate a random JSON root (object, array, or scalar)."""

    kind = rng.choice(["object", "array", "scalar"])
    if kind == "object":
        return {
            _rand_string(rng, max_len=12) or f"k{i}": _rand_value(rng, 1)
            for i in range(rng.randint(0, 6))
        }
    if kind == "array":
        return [_rand_value(rng, 1) for _ in range(rng.randint(0, 6))]
    return _rand_value(rng, 4)


def _write_pair(index: int, obj: Any, canonicalize) -> None:
    in_path = HERE / f"in_{index:02d}.json"
    out_path = HERE / f"out_{index:02d}.json"
    in_bytes = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    out_bytes = canonicalize(obj)
    in_path.write_bytes(in_bytes)
    out_path.write_bytes(out_bytes)


def main() -> int:
    canonical = _load_canonical()
    canonicalize = canonical.canonicalize
    seed = _read_seed()
    rng = random.Random(seed)
    cases = _hand_curated()
    if len(cases) != 10:
        raise AssertionError("expected exactly 10 hand-curated cases")
    for i, obj in enumerate(cases):
        _write_pair(i, obj, canonicalize)
    for i in range(10, 50):
        obj = _rand_root(rng)
        _write_pair(i, obj, canonicalize)
    print(f"generated 50 canonical fixtures into {HERE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
