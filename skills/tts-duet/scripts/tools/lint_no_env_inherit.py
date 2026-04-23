#!/usr/bin/env python3
"""
AST-based lint that forbids raw environment inheritance in ``subprocess``
calls under ``skills/tts-duet/scripts/``.

Rules
-----
1. Any call to ``subprocess.Popen``, ``subprocess.run``, ``subprocess.call``,
   ``subprocess.check_call``, or ``subprocess.check_output`` MUST pass an
   explicit ``env=`` keyword argument.
2. ``env=None`` is forbidden (implicit parent-environment inherit).
3. ``env=os.environ`` (or ``os.environ.copy()``, ``environ``) is forbidden.
4. ``env=<Call>`` is allowed when the callee resolves to
   ``safe_env``, ``_safe_env.safe_env``, ``_safe_env_nohup``, or
   ``_safe_env._safe_env_nohup``.
5. ``env=<Dict literal>`` is allowed (callers that build an allowlisted
   dict inline, e.g. tests).
6. ``env=<Name>`` is allowed when every assignment to that name in the
   enclosing function or module scope is itself an allowed source
   (Dict literal, ``safe_env(...)`` call, or ``_safe_env_nohup(...)``
   call). Augmented assignments (``env += ...``) or assignments from
   any other source invalidate the name.
7. Files listed (one path per line) in ``_lint_exempt.txt`` next to this
   script are skipped.

Exit codes
----------
- ``0``: no violations.
- ``1``: one or more violations (printed to stderr, one per line).
- ``2``: invocation error (missing target, unreadable file, etc.).

Usage
-----
::

    python lint_no_env_inherit.py <path> [<path> ...]

``<path>`` may be a file or directory. Directories are walked recursively
for ``*.py`` files.

Notes
-----
This lint mirrors §5.3 of the TTS-duet plan and AC-17. It is designed to
run both in CI and from a pytest self-test (see
``tests/test_lint_no_env_inherit.py``).
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

SUBPROCESS_CALLS: frozenset[str] = frozenset(
    {"Popen", "run", "call", "check_call", "check_output"}
)
"""Attribute names on the ``subprocess`` module that spawn a child."""

ALLOWED_ENV_CALL_NAMES: frozenset[str] = frozenset(
    {"safe_env", "_safe_env_nohup"}
)
"""Terminal names allowed as callees for ``env=<Call>``."""

EXEMPT_FILENAME = "_lint_exempt.txt"


@dataclass(frozen=True)
class Violation:
    """One lint violation, pinned to a file and line."""

    path: Path
    line: int
    col: int
    message: str

    def format(self) -> str:
        return f"{self.path}:{self.line}:{self.col}: {self.message}"


def _iter_python_files(targets: Iterable[Path]) -> Iterator[Path]:
    """Yield every ``.py`` file under the given targets, deduplicated."""
    seen: set[Path] = set()
    for target in targets:
        if target.is_file() and target.suffix == ".py":
            resolved = target.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield resolved
            continue
        if target.is_dir():
            for candidate in sorted(target.rglob("*.py")):
                resolved = candidate.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                yield resolved


def _load_exempt(script_dir: Path) -> set[Path]:
    """Read the exemption list, returning absolute resolved paths."""
    exempt_file = script_dir / EXEMPT_FILENAME
    if not exempt_file.is_file():
        return set()
    exempt: set[Path] = set()
    for raw in exempt_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        candidate = (script_dir / line).resolve()
        exempt.add(candidate)
    return exempt


def _is_subprocess_call(node: ast.Call) -> bool:
    """Detect ``subprocess.<fn>(...)`` where ``<fn>`` is a spawn function."""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr not in SUBPROCESS_CALLS:
        return False
    value = func.value
    if isinstance(value, ast.Name) and value.id == "subprocess":
        return True
    if isinstance(value, ast.Attribute) and value.attr == "subprocess":
        return True
    return False


def _extract_kwarg(node: ast.Call, name: str) -> ast.keyword | None:
    for kw in node.keywords:
        if kw.arg == name:
            return kw
    return None


def _callee_tail_name(node: ast.AST) -> str | None:
    """Return the rightmost attribute or Name of a call expression."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_allowed_env_value(value: ast.AST) -> bool:
    """Allow a dict literal or a call whose tail name is allowlisted."""
    if isinstance(value, ast.Dict):
        return True
    if isinstance(value, ast.Call):
        tail = _callee_tail_name(value.func)
        return tail in ALLOWED_ENV_CALL_NAMES
    return False


ScopeNode = ast.FunctionDef | ast.AsyncFunctionDef | ast.Module


def _collect_scope_assigns(
    scope: ScopeNode,
) -> dict[str, list[ast.AST]]:
    """Collect immediate (non-nested) simple-name assignments in ``scope``.

    ``ast.Assign`` and ``ast.AnnAssign`` targeting a single ``ast.Name``
    are indexed by the name. ``ast.AugAssign`` (``+=`` etc.) is recorded
    with a sentinel — we cannot prove augmented assignments keep the
    value safe, so any Name with an augmented update is rejected.

    Nested function definitions are not descended into — their bodies
    belong to their own scopes.
    """
    out: dict[str, list[ast.AST]] = {}
    _AUG_SENTINEL = ast.Constant(value=object())

    def visit(node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node is not scope:
            return
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out.setdefault(target.id, []).append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                out.setdefault(node.target.id, []).append(node.value)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            out.setdefault(node.target.id, []).append(_AUG_SENTINEL)
        for child in ast.iter_child_nodes(node):
            visit(child)

    for child in ast.iter_child_nodes(scope):
        visit(child)
    return out


def _name_resolves_safely(
    name_id: str,
    call_node: ast.Call,
    scope_stack: list[ScopeNode],
) -> bool:
    """Return True iff every assignment to ``name_id`` in any enclosing
    scope is an allowed source."""
    if not scope_stack:
        return False
    # Walk from the innermost enclosing scope outward. First scope that
    # defines the name is the one that wins; if not defined anywhere, we
    # cannot prove safety.
    for scope in reversed(scope_stack):
        assigns = _collect_scope_assigns(scope)
        if name_id in assigns:
            return all(_is_allowed_env_value(v) for v in assigns[name_id])
    return False


def _is_forbidden_env_value(value: ast.AST) -> tuple[bool, str]:
    """Return (is_forbidden, reason) for the common bad shapes."""
    if isinstance(value, ast.Constant) and value.value is None:
        return True, "env=None (implicit parent env inherit is forbidden)"
    if isinstance(value, ast.Attribute):
        tail = _callee_tail_name(value)
        if tail == "environ":
            return True, "env=os.environ (raw parent env inherit is forbidden)"
    if isinstance(value, ast.Name) and value.id == "environ":
        return True, "env=environ (raw parent env inherit is forbidden)"
    if isinstance(value, ast.Call):
        tail = _callee_tail_name(value.func)
        if tail == "copy" and isinstance(value.func, ast.Attribute):
            inner = _callee_tail_name(value.func.value)
            if inner == "environ":
                return True, "env=os.environ.copy() (raw parent env inherit is forbidden)"
    return False, ""


def _check_call(
    path: Path,
    node: ast.Call,
    scope_stack: list[ScopeNode],
) -> list[Violation]:
    violations: list[Violation] = []
    kwarg = _extract_kwarg(node, "env")
    if kwarg is None:
        violations.append(
            Violation(
                path=path,
                line=node.lineno,
                col=node.col_offset,
                message=(
                    "subprocess call missing explicit env= kwarg; "
                    "use safe_env(for_mcp=...) or _safe_env_nohup(...)"
                ),
            )
        )
        return violations
    value = kwarg.value
    forbidden, reason = _is_forbidden_env_value(value)
    if forbidden:
        violations.append(
            Violation(
                path=path,
                line=node.lineno,
                col=node.col_offset,
                message=reason,
            )
        )
        return violations
    if _is_allowed_env_value(value):
        return violations
    # Name reference: accept when every assignment in the enclosing
    # scope chain is itself an allowed source.
    if isinstance(value, ast.Name) and _name_resolves_safely(value.id, node, scope_stack):
        return violations
    violations.append(
        Violation(
            path=path,
            line=node.lineno,
            col=node.col_offset,
            message=(
                "env= must be a dict literal or a call to "
                "safe_env()/_safe_env_nohup(); got "
                f"{type(value).__name__}"
            ),
        )
    )
    return violations


def lint_source(path: Path, source: str) -> list[Violation]:
    """Parse ``source`` and return every violation found in it."""
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [
            Violation(
                path=path,
                line=exc.lineno or 1,
                col=exc.offset or 0,
                message=f"SyntaxError: {exc.msg}",
            )
        ]
    violations: list[Violation] = []
    scope_stack: list[ScopeNode] = []

    def visit(node: ast.AST) -> None:
        pushed = False
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)):
            scope_stack.append(node)  # type: ignore[arg-type]
            pushed = True
        if isinstance(node, ast.Call) and _is_subprocess_call(node):
            violations.extend(_check_call(path, node, scope_stack))
        for child in ast.iter_child_nodes(node):
            visit(child)
        if pushed:
            scope_stack.pop()

    visit(tree)
    return violations


def lint_paths(targets: Iterable[Path], exempt: set[Path]) -> list[Violation]:
    """Lint every Python file under ``targets`` minus ``exempt``."""
    violations: list[Violation] = []
    for path in _iter_python_files(targets):
        if path in exempt:
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            violations.append(
                Violation(
                    path=path,
                    line=1,
                    col=0,
                    message=f"could not read file: {exc}",
                )
            )
            continue
        violations.extend(lint_source(path, source))
    return violations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "AST lint that bans env=None / env=os.environ in subprocess "
            "calls under skills/tts-duet/scripts/."
        ),
    )
    parser.add_argument(
        "targets",
        nargs="+",
        type=Path,
        help="Files or directories to lint.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    for target in args.targets:
        if not target.exists():
            print(f"lint_no_env_inherit: target does not exist: {target}", file=sys.stderr)
            return 2
    script_dir = Path(__file__).resolve().parent
    exempt = _load_exempt(script_dir)
    violations = lint_paths(args.targets, exempt)
    for violation in violations:
        print(violation.format(), file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
