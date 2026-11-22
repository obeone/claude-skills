#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Tests for setup_crew.py.

Stdlib-only (`unittest`), no network: every test writes into a temporary
directory passed with ``--dest``, never into a real harness configuration.

Usage
-----
    uv run skills/cheap-orchestration/scripts/tests/test_setup_crew.py -v
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import setup_crew  # noqa: E402


def run(*argv: str) -> tuple[int, str]:
    """
    Run the command line and capture what it prints.

    Parameters
    ----------
    *argv : str
        Arguments passed to ``setup_crew.main``.

    Returns
    -------
    tuple[int, str]
        Exit code and standard output.
    """
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = setup_crew.main(list(argv))
    return code, out.getvalue()


class SetupCrewTest(unittest.TestCase):
    """Behaviour of the crew installer across providers."""

    def setUp(self) -> None:
        """Create the temporary target directory of the test."""
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dest = Path(self._tmp.name) / "agents"

    def test_dry_run_writes_nothing(self) -> None:
        """Without --apply the target directory is not even created."""
        code, out = run("--provider", "claude", "--dest", str(self.dest))
        self.assertEqual(code, 0)
        self.assertFalse(self.dest.exists())
        self.assertIn("would write", out)

    def test_claude_install_pins_each_agent_to_its_tier(self) -> None:
        """Each Claude definition carries the model of its tier."""
        code, _ = run("--provider", "claude", "--dest", str(self.dest), "--apply")
        self.assertEqual(code, 0)
        expected = {
            "scout": "haiku",
            "editor": "haiku",
            "worker": "sonnet",
            "reviewer": "opus",
        }
        for name, model in expected.items():
            text = (self.dest / f"{name}.md").read_text(encoding="utf-8")
            self.assertIn(f"\nmodel: {model}\n", text)
            self.assertTrue(text.startswith(f"---\nname: {name}\n"))

    def test_codex_install_is_valid_toml_with_gpt_models(self) -> None:
        """Codex roles parse as TOML and name the GPT model of their tier."""
        run("--provider", "codex", "--dest", str(self.dest), "--apply")
        worker = tomllib.loads((self.dest / "worker.toml").read_text("utf-8"))
        self.assertEqual(worker["name"], "worker")
        self.assertEqual(worker["model"], "gpt-6.1-terra")
        self.assertTrue(worker["description"].startswith("Terra "))
        self.assertIn("\n", worker["developer_instructions"])
        scout = tomllib.loads((self.dest / "scout.toml").read_text("utf-8"))
        self.assertEqual(scout["model"], "gpt-6-luna")

    def test_gemini_restricts_tools_of_the_read_only_agent_only(self) -> None:
        """Only scout gets a tool list on Gemini; editing agents inherit."""
        run("--provider", "gemini", "--dest", str(self.dest), "--apply")
        scout = (self.dest / "scout.md").read_text(encoding="utf-8")
        self.assertIn("kind: local\nmodel: gemini-4-hydrogen\ntools:\n", scout)
        worker = (self.dest / "worker.md").read_text(encoding="utf-8")
        self.assertIn("model: gemini-4-neon\n---\n", worker)
        self.assertNotIn("tools:", worker.split("\n---\n")[0])

    def test_tier_override_changes_only_that_tier(self) -> None:
        """--medium replaces the worker model and leaves the others alone."""
        run(
            "--provider", "codex", "--dest", str(self.dest), "--apply",
            "--medium", "custom-mid",
        )
        worker = tomllib.loads((self.dest / "worker.toml").read_text("utf-8"))
        scout = tomllib.loads((self.dest / "scout.toml").read_text("utf-8"))
        self.assertEqual(worker["model"], "custom-mid")
        self.assertEqual(scout["model"], "gpt-6-luna")

    def test_existing_different_file_is_kept_without_force(self) -> None:
        """A user's own definition survives, and the exit code says so."""
        self.dest.mkdir(parents=True)
        mine = self.dest / "scout.md"
        mine.write_text("mine\n", encoding="utf-8")
        code, out = run("--provider", "claude", "--dest", str(self.dest), "--apply")
        self.assertEqual(code, 1)
        self.assertEqual(mine.read_text(encoding="utf-8"), "mine\n")
        self.assertIn("kept, differs", out)
        self.assertTrue((self.dest / "worker.md").is_file())

    def test_force_replaces_an_existing_file(self) -> None:
        """--force overwrites a definition that differs."""
        self.dest.mkdir(parents=True)
        mine = self.dest / "scout.md"
        mine.write_text("mine\n", encoding="utf-8")
        code, _ = run(
            "--provider", "claude", "--dest", str(self.dest), "--apply", "--force"
        )
        self.assertEqual(code, 0)
        self.assertNotEqual(mine.read_text(encoding="utf-8"), "mine\n")

    def test_second_install_is_idempotent(self) -> None:
        """Installing twice reports every file as up to date."""
        run("--provider", "claude", "--dest", str(self.dest), "--apply")
        code, out = run("--provider", "claude", "--dest", str(self.dest), "--apply")
        self.assertEqual(code, 0)
        self.assertEqual(out.count("up to date"), 4)

    def test_check_fails_until_the_crew_is_complete(self) -> None:
        """--check exits 1 on a missing agent and 0 once all four exist."""
        code, out = run("--provider", "claude", "--dest", str(self.dest), "--check")
        self.assertEqual(code, 1)
        self.assertIn("scout", out)
        run("--provider", "claude", "--dest", str(self.dest), "--apply")
        (self.dest / "reviewer.md").unlink()
        code, out = run("--provider", "claude", "--dest", str(self.dest), "--check")
        self.assertEqual(code, 1)
        self.assertIn("reviewer", out)
        self.assertNotIn("scout", out)
        run("--provider", "claude", "--dest", str(self.dest), "--apply")
        code, _ = run("--provider", "claude", "--dest", str(self.dest), "--check")
        self.assertEqual(code, 0)

    def test_agent_file_without_front_matter_is_rejected(self) -> None:
        """A bundled file that lost its front-matter is an error, not a guess."""
        broken = Path(self._tmp.name) / "broken.md"
        broken.write_text("no front matter\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            setup_crew.parse_agent(broken)


if __name__ == "__main__":
    unittest.main()
