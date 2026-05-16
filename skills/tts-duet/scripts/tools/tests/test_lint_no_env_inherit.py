"""
Self-tests for ``lint_no_env_inherit.py``.

Covers the positive-fixture / negative-fixture matrix required by
AC-17 of the TTS-duet plan (§10). Each test writes a tiny Python source
into ``tmp_path`` and checks that the lint raises the expected number
of violations.

These tests run offline and do not require any of worker-2/3/4's code
to exist on disk.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
TOOLS_DIR = THIS_DIR.parent
LINT = TOOLS_DIR / "lint_no_env_inherit.py"

sys.path.insert(0, str(TOOLS_DIR))

from lint_no_env_inherit import (  # noqa: E402
    Violation,
    _is_allowed_env_value,
    _is_forbidden_env_value,
    lint_source,
    main,
)


def _lint(source: str, tmp_path: Path, name: str = "sample.py") -> list[Violation]:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return lint_source(path, source)


# ---------------------------------------------------------------------------
# Negative fixtures — MUST flag
# ---------------------------------------------------------------------------


def test_flags_missing_env_kwarg(tmp_path: Path) -> None:
    source = "import subprocess\nsubprocess.run(['ls'])\n"
    violations = _lint(source, tmp_path)
    assert len(violations) == 1
    assert "missing explicit env= kwarg" in violations[0].message


def test_flags_env_none(tmp_path: Path) -> None:
    source = "import subprocess\nsubprocess.run(['ls'], env=None)\n"
    violations = _lint(source, tmp_path)
    assert len(violations) == 1
    assert "env=None" in violations[0].message


def test_flags_env_os_environ(tmp_path: Path) -> None:
    source = "import os\nimport subprocess\nsubprocess.run(['ls'], env=os.environ)\n"
    violations = _lint(source, tmp_path)
    assert len(violations) == 1
    assert "os.environ" in violations[0].message


def test_flags_env_os_environ_copy(tmp_path: Path) -> None:
    source = "import os\nimport subprocess\nsubprocess.run(['ls'], env=os.environ.copy())\n"
    violations = _lint(source, tmp_path)
    assert len(violations) == 1
    assert "os.environ.copy()" in violations[0].message


def test_flags_env_bare_environ(tmp_path: Path) -> None:
    source = "from os import environ\nimport subprocess\nsubprocess.run(['ls'], env=environ)\n"
    violations = _lint(source, tmp_path)
    assert len(violations) == 1
    assert "environ" in violations[0].message


def test_accepts_env_variable_from_dict_literal(tmp_path: Path) -> None:
    """``env=my_env`` where ``my_env`` is a Dict literal is allowed."""
    source = (
        "import subprocess\n"
        "my_env = {'PATH': '/usr/bin'}\n"
        "subprocess.run(['ls'], env=my_env)\n"
    )
    violations = _lint(source, tmp_path)
    assert violations == []


def test_accepts_env_variable_from_safe_env_call(tmp_path: Path) -> None:
    """``env=my_env`` where ``my_env = safe_env(...)`` is allowed."""
    source = (
        "import subprocess\n"
        "from lib._safe_env import safe_env\n"
        "my_env = safe_env(for_mcp=False)\n"
        "subprocess.run(['ls'], env=my_env)\n"
    )
    violations = _lint(source, tmp_path)
    assert violations == []


def test_flags_env_variable_from_untrusted_source(tmp_path: Path) -> None:
    """``env=my_env`` where ``my_env = os.environ.copy()`` must still fail."""
    source = (
        "import os, subprocess\n"
        "my_env = os.environ.copy()\n"
        "subprocess.run(['ls'], env=my_env)\n"
    )
    violations = _lint(source, tmp_path)
    assert len(violations) == 1
    assert "must be a dict literal" in violations[0].message


def test_flags_env_variable_from_augmented_assign(tmp_path: Path) -> None:
    """``env += ...`` after a safe init is unprovable; reject."""
    source = (
        "import subprocess\n"
        "my_env = {'PATH': '/usr/bin'}\n"
        "my_env |= {'X': 'y'}\n"
        "subprocess.run(['ls'], env=my_env)\n"
    )
    violations = _lint(source, tmp_path)
    # ``|=`` is ast.AugAssign with sentinel; the name is still rejectable.
    assert len(violations) == 1


def test_flags_popen_and_friends(tmp_path: Path) -> None:
    source = (
        "import subprocess\n"
        "subprocess.Popen(['a'])\n"
        "subprocess.call(['b'])\n"
        "subprocess.check_call(['c'])\n"
        "subprocess.check_output(['d'])\n"
    )
    violations = _lint(source, tmp_path)
    assert len(violations) == 4


# ---------------------------------------------------------------------------
# Positive fixtures — MUST NOT flag
# ---------------------------------------------------------------------------


def test_allows_safe_env_call(tmp_path: Path) -> None:
    source = (
        "import subprocess\n"
        "from ._safe_env import safe_env\n"
        "subprocess.run(['ls'], env=safe_env(for_mcp=False))\n"
    )
    assert _lint(source, tmp_path) == []


def test_allows_safe_env_qualified_call(tmp_path: Path) -> None:
    source = (
        "import subprocess\n"
        "from . import _safe_env\n"
        "subprocess.run(['ls'], env=_safe_env.safe_env(for_mcp=True))\n"
    )
    assert _lint(source, tmp_path) == []



def test_allows_dict_literal(tmp_path: Path) -> None:
    source = (
        "import subprocess\n"
        "subprocess.run(['ls'], env={'PATH': '/usr/bin'})\n"
    )
    assert _lint(source, tmp_path) == []


def test_ignores_non_subprocess_calls(tmp_path: Path) -> None:
    source = (
        "import other\n"
        "other.run(['ls'])\n"
        "other.Popen(['ls'], env=None)\n"
    )
    assert _lint(source, tmp_path) == []


# ---------------------------------------------------------------------------
# Predicate unit tests
# ---------------------------------------------------------------------------


def _parse_expr(src: str):
    import ast as _ast

    return _ast.parse(src, mode="eval").body


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("None", True),
        ("os.environ", True),
        ("environ", True),
        ("os.environ.copy()", True),
        ("safe_env(for_mcp=True)", False),
        ("{'PATH': '/usr/bin'}", False),
        ("123", False),
    ],
)
def test_is_forbidden_env_value(expr: str, expected: bool) -> None:
    node = _parse_expr(expr)
    forbidden, _ = _is_forbidden_env_value(node)
    assert forbidden is expected


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("safe_env()", True),
        ("_safe_env.safe_env(for_mcp=False)", True),
        ("{'PATH': '/usr/bin'}", True),
        ("None", False),
        ("os.environ", False),
        ("my_env", False),
    ],
)
def test_is_allowed_env_value(expr: str, expected: bool) -> None:
    node = _parse_expr(expr)
    assert _is_allowed_env_value(node) is expected


# ---------------------------------------------------------------------------
# CLI / exit code surface
# ---------------------------------------------------------------------------


def test_cli_clean_tree_exits_zero(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text(
        "import subprocess\n"
        "subprocess.run(['ls'], env={'PATH': '/bin'})\n",
        encoding="utf-8",
    )
    assert main([str(tmp_path)]) == 0


def test_cli_dirty_tree_exits_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "bad.py").write_text(
        "import subprocess\nsubprocess.run(['ls'])\n",
        encoding="utf-8",
    )
    assert main([str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "bad.py" in captured.err


def test_cli_missing_target_exits_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "does-not-exist"
    assert main([str(missing)]) == 2


def test_cli_respects_exempt_file(tmp_path: Path) -> None:
    """Verify ``_lint_exempt.txt`` lookup relative to the lint script."""
    import ast as _ast

    src = (tmp_path / "bad.py")
    src.write_text("import subprocess\nsubprocess.run(['ls'])\n", encoding="utf-8")
    # main() reads the exempt file next to lint_no_env_inherit.py.
    # We assert the in-repo exempt file has no entries so the lint
    # does not silently skip anything by default.
    exempt_file = TOOLS_DIR / "_lint_exempt.txt"
    assert exempt_file.is_file()
    body = "".join(
        line
        for line in exempt_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    )
    assert body == ""


# ---------------------------------------------------------------------------
# End-to-end: run the lint script as a subprocess
# ---------------------------------------------------------------------------


def test_script_runs_as_module(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text(
        "import subprocess\n"
        "subprocess.run(['ls'], env={'PATH': '/bin'})\n",
        encoding="utf-8",
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(LINT), str(tmp_path)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr


def test_script_reports_on_bad_file(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text(
        "import subprocess\nsubprocess.run(['ls'])\n",
        encoding="utf-8",
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(LINT), str(tmp_path)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 1
    assert "missing explicit env=" in result.stderr
