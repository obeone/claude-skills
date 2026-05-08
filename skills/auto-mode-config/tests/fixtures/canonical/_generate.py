# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""One-shot generator for canonical-fixture pairs.

Produces:
- ``in_10.json`` .. ``in_49.json`` — pseudo-random JSON values with
  the seed pinned in ``seed.txt`` (stdlib ``random`` only, so the
  output is reproducible across hypothesis versions).
- ``out_00.json`` .. ``out_49.json`` — canonical bytes for every input
  (hand-curated 00..09 plus generated 10..49).

Run from the repository root::

    uv run skills/auto-mode-config/tests/fixtures/canonical/_generate.py

The script is idempotent: re-running with the same seed produces
byte-identical fixtures. This file is committed so reviewers can
audit the generator parameters.
"""

from __future__ import annotations

import json
import random
import string
import sys
from pathlib import Path

# Make the local _canonical helper importable.
HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent.parent  # skills/auto-mode-config/
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from _canonical import canonicalize  # noqa: E402


SEED = 20260508
COUNT = 40
START_NN = 10  # in_10.json .. in_49.json
MAX_DEPTH = 3
MAX_BRANCH = 4

LEAF_KINDS = ("null", "bool", "int", "float", "str")
ALPHABET = string.ascii_letters + string.digits + " _-éàü"


def _gen_text(rng: random.Random, max_size: int = 12) -> str:
    """Return a short pseudo-random unicode-friendly string.

    Parameters
    ----------
    rng
        Seeded random source.
    max_size
        Hard upper bound on the string length.

    Returns
    -------
    str
        Generated text, possibly empty.
    """
    n = rng.randint(0, max_size)
    return "".join(rng.choice(ALPHABET) for _ in range(n))


def _gen_leaf(rng: random.Random) -> object:
    """Return a JSON-leaf value (no nesting).

    Parameters
    ----------
    rng
        Seeded random source.

    Returns
    -------
    object
        ``None``, a bool, an int, a finite float, or a string.
    """
    kind = rng.choice(LEAF_KINDS)
    if kind == "null":
        return None
    if kind == "bool":
        return rng.random() < 0.5
    if kind == "int":
        return rng.randint(-(2**31), 2**31)
    if kind == "float":
        # Bias away from extreme magnitudes so json.dumps stays readable.
        return rng.uniform(-1e6, 1e6)
    return _gen_text(rng)


def _gen_value(rng: random.Random, depth: int) -> object:
    """Return a JSON value (leaf or container) bounded by ``depth``.

    Parameters
    ----------
    rng
        Seeded random source.
    depth
        Remaining depth budget.

    Returns
    -------
    object
        Any JSON-serializable Python value.
    """
    if depth <= 0:
        return _gen_leaf(rng)
    roll = rng.random()
    if roll < 0.45:
        return _gen_leaf(rng)
    if roll < 0.72:
        size = rng.randint(0, MAX_BRANCH)
        return [_gen_value(rng, depth - 1) for _ in range(size)]
    size = rng.randint(0, MAX_BRANCH)
    out: dict[str, object] = {}
    for _ in range(size):
        key = _gen_text(rng, max_size=8) or f"k{rng.randint(0, 1000)}"
        out[key] = _gen_value(rng, depth - 1)
    return out


def _generate_inputs() -> list[object]:
    """Materialize ``COUNT`` deterministic JSON values.

    Returns
    -------
    list of object
        JSON-serializable values, one per generated fixture.
    """
    rng = random.Random(SEED)
    return [_gen_value(rng, MAX_DEPTH) for _ in range(COUNT)]


def main() -> int:
    """Write 40 ``in_NN.json`` and 50 ``out_NN.json`` fixtures.

    Returns
    -------
    int
        Always 0; raises on unexpected I/O failure.
    """
    # Generated inputs.
    examples = _generate_inputs()
    for offset, value in enumerate(examples):
        nn = START_NN + offset
        in_path = HERE / f"in_{nn:02d}.json"
        text = json.dumps(value, ensure_ascii=False, indent=2)
        in_path.write_bytes((text + "\n").encode("utf-8"))

    # Outputs for every input (hand-curated + generated).
    for nn in range(50):
        in_path = HERE / f"in_{nn:02d}.json"
        out_path = HERE / f"out_{nn:02d}.json"
        if not in_path.exists():
            raise FileNotFoundError(f"missing input fixture: {in_path}")
        obj = json.loads(in_path.read_bytes())
        out_path.write_bytes(canonicalize(obj))

    print(f"wrote {COUNT} inputs (in_{START_NN:02d}..in_{START_NN+COUNT-1:02d})")
    print("wrote 50 outputs (out_00..out_49)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
