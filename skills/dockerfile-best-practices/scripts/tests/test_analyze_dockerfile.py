#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Regression tests for analyze_dockerfile.py rules added after 3.2.0.

Stdlib-only (`unittest`), no Docker, no network: each test feeds a synthetic
Dockerfile to `analyze_dockerfile()` and asserts on the rule ids it reports.

Usage
-----

    uv run skills/dockerfile-best-practices/scripts/tests/test_analyze_dockerfile.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType


def _load_analyzer() -> ModuleType:
    """Dynamically import the sibling analyze_dockerfile.py.

    Returns
    -------
    ModuleType
        The imported module under test.
    """
    module_path = Path(__file__).resolve().parent.parent / "analyze_dockerfile.py"
    spec = importlib.util.spec_from_file_location("analyze_dockerfile", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module under test from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ad = _load_analyzer()

_PREAMBLE = (
    "# syntax=docker/dockerfile:1\n"
    "FROM alpine:3.24\n"
    "RUN addgroup -g 10001 app && adduser -u 10001 -G app -S app\n"
)


def _rule_lines(content: str, rule: str) -> list[int]:
    """Return the line numbers at which `rule` fires on `content`.

    Parameters
    ----------
    content : str
        Dockerfile source.
    rule : str
        Rule id, e.g. ``"DL039"``.

    Returns
    -------
    list of int
        Line numbers of every issue carrying that rule id.
    """
    return [i.line_num for i in ad.analyze_dockerfile(content) if i.rule == rule]


class TestDL039EmptyChownGroup(unittest.TestCase):
    """DL039: ``--chown=<user>:`` silently meant GID 0 before frontend 1.28."""

    def test_named_user_trailing_colon_fires(self) -> None:
        self.assertEqual(_rule_lines(_PREAMBLE + "COPY --chown=app: a /a\n", "DL039"), [4])

    def test_numeric_user_trailing_colon_fires(self) -> None:
        self.assertEqual(_rule_lines(_PREAMBLE + "COPY --chown=10001: a /a\n", "DL039"), [4])

    def test_add_is_checked_too(self) -> None:
        self.assertEqual(_rule_lines(_PREAMBLE + "ADD --chown=app: a /a\n", "DL039"), [4])

    def test_full_user_group_is_silent(self) -> None:
        self.assertEqual(_rule_lines(_PREAMBLE + "COPY --chown=app:app a /a\n", "DL039"), [])

    def test_user_only_is_silent(self) -> None:
        # No colon at all resolves the primary group on every frontend measured.
        self.assertEqual(_rule_lines(_PREAMBLE + "COPY --chown=app a /a\n", "DL039"), [])

    def test_numeric_pair_is_silent(self) -> None:
        self.assertEqual(_rule_lines(_PREAMBLE + "COPY --chown=10001:10001 a /a\n", "DL039"), [])


class TestDL006Zstd(unittest.TestCase):
    """DL006 treats zstd tarballs as auto-extracted local archives (frontend 1.27+)."""

    def test_tar_zst_is_an_archive(self) -> None:
        issues = [i for i in ad.analyze_dockerfile(_PREAMBLE + "ADD app.tar.zst /opt/\n") if i.rule == "DL006"]
        self.assertEqual(len(issues), 1)
        self.assertIn("archive", issues[0].message)


if __name__ == "__main__":
    unittest.main()
