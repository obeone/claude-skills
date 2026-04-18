#!/usr/bin/env python3
"""Unit tests for the resume mismatch guard in generate_tts._run_pipeline.

Tests the ``!=`` condition: exit 1 when existing chunk WAV count does not
match the current plan AND at least one chunk file exists.

Run with::

    uv run --with pyyaml python skills/tts-duet/scripts/lib/_test_resume_guard.py

Exits 0 when all tests pass, 1 on any failure.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# The mismatch logic extracted verbatim from generate_tts._run_pipeline so
# we can test it in isolation without importing the full script (which needs
# google-genai, tqdm, etc.).
# ---------------------------------------------------------------------------

_CHUNK_RE = re.compile(r"\.chunk\d{3}\.wav$")


def _mismatch_detected(chunks_dir: Path, expected_count: int) -> bool:
    """Return True when the resume guard would trigger (exit 1 in the real script).

    Parameters
    ----------
    chunks_dir : Path
        Directory to scan for ``*.chunkNNN.wav`` files.
    expected_count : int
        Number of chunks the current plan expects.

    Returns
    -------
    bool
        ``True`` when ``len(existing) != expected_count and len(existing) > 0``.
    """
    existing = [
        p for p in chunks_dir.iterdir()
        if p.is_file() and _CHUNK_RE.search(p.name)
    ]
    return len(existing) != expected_count and len(existing) > 0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _run_tests() -> int:
    """Execute all tests; return the number of failures."""
    failures = 0

    # ------------------------------------------------------------------
    # Test 1: more files than plan → mismatch (original > case)
    # ------------------------------------------------------------------
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            for i in range(3):
                (d / f"output.chunk{i:03d}.wav").touch()
            result = _mismatch_detected(d, expected_count=2)
        assert result is True, "expected mismatch for 3 files vs 2 planned"
        print("OK: Test 1 — 3 files vs 2 planned → mismatch detected")
    except Exception as exc:
        print(f"FAIL: Test 1 — 3 files vs 2 planned: {exc}")
        failures += 1

    # ------------------------------------------------------------------
    # Test 2: fewer files than plan → mismatch (new != case; was missed by >)
    # ------------------------------------------------------------------
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "output.chunk000.wav").touch()
            result = _mismatch_detected(d, expected_count=3)
        assert result is True, "expected mismatch for 1 file vs 3 planned"
        print("OK: Test 2 — 1 file vs 3 planned → mismatch detected (was missed by old > guard)")
    except Exception as exc:
        print(f"FAIL: Test 2 — 1 file vs 3 planned: {exc}")
        failures += 1

    # ------------------------------------------------------------------
    # Test 3: exact match → no mismatch
    # ------------------------------------------------------------------
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            for i in range(2):
                (d / f"output.chunk{i:03d}.wav").touch()
            result = _mismatch_detected(d, expected_count=2)
        assert result is False, "expected no mismatch for 2 files vs 2 planned"
        print("OK: Test 3 — 2 files vs 2 planned → no mismatch")
    except Exception as exc:
        print(f"FAIL: Test 3 — 2 files vs 2 planned: {exc}")
        failures += 1

    # ------------------------------------------------------------------
    # Test 4: zero files → no mismatch (fresh run, nothing to guard)
    # ------------------------------------------------------------------
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            result = _mismatch_detected(d, expected_count=2)
        assert result is False, "expected no mismatch for 0 files (fresh run)"
        print("OK: Test 4 — 0 files vs 2 planned → no mismatch (fresh run)")
    except Exception as exc:
        print(f"FAIL: Test 4 — 0 files (fresh run): {exc}")
        failures += 1

    return failures


def main() -> int:
    """Run all tests and return 0 on success, 1 on any failure."""
    failures = _run_tests()
    if failures:
        print(f"\n{failures} test(s) FAILED.")
        return 1
    print("\nAll tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
