#!/usr/bin/env python3
"""Lightweight verification script for lib.config.

Run with::

    uv run --with pyyaml python skills/tts-duet/scripts/lib/_test_config.py

Exits 0 when all tests pass, 1 on any failure.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Allow running from any CWD
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.config import load_config  # noqa: E402


def _run_tests() -> int:
    """Execute all tests; return the number of failures."""
    failures = 0

    # ------------------------------------------------------------------
    # Test 1: load_config() with no files returns hardcoded defaults
    # ------------------------------------------------------------------
    try:
        cfg = load_config(
            user_path=Path("/nonexistent/user/config.yaml"),
            project_path=Path("/nonexistent/project/tts-duet.yaml"),
        )
        assert cfg.defaults.model == "pro", f"expected model='pro', got {cfg.defaults.model!r}"
        assert cfg.director.mode == "auto", f"expected mode='auto', got {cfg.director.mode!r}"
        assert cfg.defaults.format == "mp3", f"expected format='mp3', got {cfg.defaults.format!r}"
        assert cfg.defaults.preset == "podcast-chill", f"expected preset='podcast-chill', got {cfg.defaults.preset!r}"
        assert cfg.defaults.approved_cost_usd is None, f"expected approved_cost_usd=None, got {cfg.defaults.approved_cost_usd!r}"
        print("OK: Test 1 — no files → hardcoded defaults")
    except Exception as exc:
        print(f"FAIL: Test 1 — no files → hardcoded defaults: {exc}")
        failures += 1

    # ------------------------------------------------------------------
    # Test 2: project file overrides user file for defaults.model
    # ------------------------------------------------------------------
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            user_cfg = tmp / "user.yaml"
            project_cfg = tmp / "project.yaml"
            user_cfg.write_text("defaults:\n  model: pro\n", encoding="utf-8")
            project_cfg.write_text("defaults:\n  model: flash\n", encoding="utf-8")
            cfg = load_config(user_path=user_cfg, project_path=project_cfg)
        assert cfg.defaults.model == "flash", (
            f"expected project to win with model='flash', got {cfg.defaults.model!r}"
        )
        print("OK: Test 2 — project overrides user for defaults.model")
    except Exception as exc:
        print(f"FAIL: Test 2 — project overrides user for defaults.model: {exc}")
        failures += 1

    # ------------------------------------------------------------------
    # Test 3: cli_overrides wins over everything
    # ------------------------------------------------------------------
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            project_cfg = tmp / "project.yaml"
            project_cfg.write_text("defaults:\n  model: pro\n", encoding="utf-8")
            cfg = load_config(
                cli_overrides={"defaults": {"model": "flash"}},
                user_path=Path("/nonexistent/user/config.yaml"),
                project_path=project_cfg,
            )
        assert cfg.defaults.model == "flash", (
            f"expected cli to win with model='flash', got {cfg.defaults.model!r}"
        )
        print("OK: Test 3 — cli_overrides wins over project file")
    except Exception as exc:
        print(f"FAIL: Test 3 — cli_overrides wins over project file: {exc}")
        failures += 1

    # ------------------------------------------------------------------
    # Test 4: malformed YAML raises RuntimeError with path in message
    # ------------------------------------------------------------------
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bad_cfg = tmp / "bad.yaml"
            bad_cfg.write_text("defaults: {model: [unclosed\n", encoding="utf-8")
            raised = False
            try:
                load_config(
                    user_path=bad_cfg,
                    project_path=Path("/nonexistent/project.yaml"),
                )
            except RuntimeError as exc:
                raised = True
                assert str(bad_cfg) in str(exc), (
                    f"RuntimeError message does not contain path {bad_cfg!r}: {exc}"
                )
            assert raised, "Expected RuntimeError for malformed YAML, but none was raised"
        print("OK: Test 4 — malformed YAML raises RuntimeError with path")
    except Exception as exc:
        print(f"FAIL: Test 4 — malformed YAML raises RuntimeError with path: {exc}")
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
