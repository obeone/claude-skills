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
import os
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

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

    def test_check_rejects_definitions_of_another_provider(self) -> None:
        """A Claude crew does not pass the Gemini check: models differ."""
        run("--provider", "claude", "--dest", str(self.dest), "--apply")
        code, out = run("--provider", "gemini", "--dest", str(self.dest), "--check")
        self.assertEqual(code, 1)
        self.assertIn("expected 'gemini-4-neon'", out)

    def test_check_rejects_an_agent_that_inherits_the_session_model(self) -> None:
        """A kept user file with model: inherit fails the check."""
        run("--provider", "claude", "--dest", str(self.dest), "--apply")
        worker = self.dest / "worker.md"
        worker.write_text(
            worker.read_text(encoding="utf-8").replace(
                "model: sonnet", "model: inherit"
            ),
            encoding="utf-8",
        )
        code, out = run("--provider", "claude", "--dest", str(self.dest), "--check")
        self.assertEqual(code, 1)
        self.assertIn("worker: model is 'inherit', expected 'sonnet'", out)
        self.assertNotIn("scout", out)

    def test_check_rejects_a_definition_declaring_another_name(self) -> None:
        """A file whose name key is not the role fails the check."""
        run("--provider", "codex", "--dest", str(self.dest), "--apply")
        scout = self.dest / "scout.toml"
        scout.write_text(
            scout.read_text(encoding="utf-8").replace(
                'name = "scout"', 'name = "other"'
            ),
            encoding="utf-8",
        )
        code, out = run("--provider", "codex", "--dest", str(self.dest), "--check")
        self.assertEqual(code, 1)
        self.assertIn("scout: definition declares name 'other'", out)

    def test_check_uses_the_same_tier_overrides_as_the_install(self) -> None:
        """A crew installed with --medium only passes a check that names it."""
        args = ("--provider", "codex", "--dest", str(self.dest))
        run(*args, "--apply", "--medium", "custom-mid")
        code, _ = run(*args, "--check")
        self.assertEqual(code, 1)
        code, _ = run(*args, "--check", "--medium", "custom-mid")
        self.assertEqual(code, 0)

    def test_description_names_the_overridden_model(self) -> None:
        """With a tier override the description leads with the real model."""
        run(
            "--provider", "codex", "--dest", str(self.dest), "--apply",
            "--medium", "custom-mid",
        )
        worker = tomllib.loads((self.dest / "worker.toml").read_text("utf-8"))
        self.assertTrue(worker["description"].startswith("custom-mid "))
        self.assertNotIn("Terra", worker["description"])

    def test_no_delegation_instruction_only_where_nothing_enforces_it(self) -> None:
        """Codex and Gemini roles carry the instruction, Claude files do not."""
        for provider in ("codex", "gemini", "claude"):
            run("--provider", provider, "--dest", str(self.dest / provider), "--apply")
        codex = tomllib.loads((self.dest / "codex" / "editor.toml").read_text("utf-8"))
        self.assertIn(setup_crew.NO_DELEGATION, codex["developer_instructions"])
        gemini = (self.dest / "gemini" / "worker.md").read_text(encoding="utf-8")
        self.assertIn(setup_crew.NO_DELEGATION, gemini)
        claude = (self.dest / "claude" / "worker.md").read_text(encoding="utf-8")
        self.assertNotIn(setup_crew.NO_DELEGATION, claude)

    def test_symlink_is_kept_and_its_target_untouched_without_force(self) -> None:
        """An agent symlinked from elsewhere is an existing entry."""
        self.dest.mkdir(parents=True)
        shared = Path(self._tmp.name) / "shared-worker.md"
        shared.write_text("shared\n", encoding="utf-8")
        (self.dest / "worker.md").symlink_to(shared)
        code, out = run("--provider", "claude", "--dest", str(self.dest), "--apply")
        self.assertEqual(code, 1)
        self.assertIn("kept, is a symlink", out)
        self.assertTrue((self.dest / "worker.md").is_symlink())
        self.assertEqual(shared.read_text(encoding="utf-8"), "shared\n")

    def test_force_replaces_the_symlink_not_its_target(self) -> None:
        """--force writes a regular file and leaves the shared target alone."""
        self.dest.mkdir(parents=True)
        shared = Path(self._tmp.name) / "shared-worker.md"
        shared.write_text("shared\n", encoding="utf-8")
        (self.dest / "worker.md").symlink_to(shared)
        code, _ = run(
            "--provider", "claude", "--dest", str(self.dest), "--apply", "--force"
        )
        self.assertEqual(code, 0)
        self.assertFalse((self.dest / "worker.md").is_symlink())
        self.assertIn("model: sonnet", (self.dest / "worker.md").read_text("utf-8"))
        self.assertEqual(shared.read_text(encoding="utf-8"), "shared\n")

    def test_dangling_symlink_never_creates_its_target(self) -> None:
        """Without --force a dangling symlink is kept and nothing lands elsewhere."""
        self.dest.mkdir(parents=True)
        elsewhere = Path(self._tmp.name) / "elsewhere.md"
        (self.dest / "scout.md").symlink_to(elsewhere)
        code, out = run("--provider", "claude", "--dest", str(self.dest), "--apply")
        self.assertEqual(code, 1)
        self.assertIn("kept, is a symlink", out)
        self.assertFalse(elsewhere.exists())

    def test_user_scope_follows_the_harness_configuration_directory(self) -> None:
        """CLAUDE_CONFIG_DIR and CODEX_HOME relocate the user-scope target."""
        profile = Path(self._tmp.name) / "profile"
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(profile)}):
            self.assertEqual(
                setup_crew.destination("claude", "user", None), profile / "agents"
            )
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(profile)}):
            self.assertEqual(
                setup_crew.destination("codex", "user", None), profile / "agents"
            )
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ["HOME"] = self._tmp.name
            self.assertEqual(
                setup_crew.destination("claude", "user", None),
                Path(self._tmp.name) / ".claude" / "agents",
            )

    def test_project_scope_ignores_the_configuration_directory(self) -> None:
        """--scope project stays in the current directory even when relocated."""
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/nowhere"}):
            self.assertEqual(
                setup_crew.destination("claude", "project", None),
                Path.cwd() / ".claude" / "agents",
            )

    def test_agent_file_without_front_matter_is_rejected(self) -> None:
        """A bundled file that lost its front-matter is an error, not a guess."""
        broken = Path(self._tmp.name) / "broken.md"
        broken.write_text("no front matter\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            setup_crew.parse_agent(broken)


if __name__ == "__main__":
    unittest.main()
