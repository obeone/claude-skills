"""pytest fixtures shared across the automode-config test suite.

Adds the skill's ``scripts/`` directory to ``sys.path`` so tests can
``import _canonical`` etc., and exposes a few directory-locating
fixtures used by both the canonical and pipeline test modules.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = TESTS_DIR.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
FIXTURES_DIR = TESTS_DIR / "fixtures"

# Ensure the scripts directory is importable for in-process tests.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture(scope="session")
def skill_dir() -> Path:
    return SKILL_DIR


@pytest.fixture(scope="session")
def scripts_dir() -> Path:
    return SCRIPTS_DIR


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture(scope="session")
def canonical_fixtures_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "canonical"


@pytest.fixture(scope="session")
def stub_claude_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "stub_claude"


@pytest.fixture
def stub_claude_path_env(
    tmp_path: Path, stub_claude_dir: Path
) -> "callable":
    """Return a helper that builds a PATH containing only one stub claude.

    Usage::

        env = stub_claude_path_env("claude_ok")
        subprocess.run([...], env=env)
    """

    def _build(stub_name: str, *, extra_path: str | None = None) -> dict[str, str]:
        bin_dir = tmp_path / f"_stub_bin_{stub_name}"
        bin_dir.mkdir(exist_ok=True)
        target = bin_dir / "claude"
        if target.exists() or target.is_symlink():
            target.unlink()
        os.symlink(stub_claude_dir / stub_name, target)
        env = os.environ.copy()
        path_parts = [str(bin_dir)]
        if extra_path:
            path_parts.append(extra_path)
        # Keep /usr/bin so subprocess can still resolve sh, etc.
        path_parts.append("/usr/bin:/bin")
        env["PATH"] = ":".join(path_parts)
        return env

    return _build
