"""Project-documentation scanner for autoMode candidate rules.

Reads a small, fixed set of project documentation files (``CLAUDE.md``,
``AGENTS.md``, ``.claude/CLAUDE.md``) and produces *suggestion* records
that map onto autoMode buckets:

- ``allow`` candidates of the form ``Bash(<token>:*)`` for every
  command-line token observed as the head of a line inside a fenced
  ``bash``/``sh``/``shell`` (or untagged) markdown code block. The
  scanner does not embed any opinion about *which* tools a project
  should allow — it only surfaces tokens the project itself documents.
- ``hard_deny`` candidates of the form ``Bash(git push * <branch>*)``
  for every branch name the documentation marks as protected (in
  English or French, via narrow regex patterns that are easy to
  audit). ``hard_deny`` lands in 2.1.136+; a classifier ignores it
  before that, so the version-band probe in ``apply_automode.py``
  should refuse the run on older binaries.

The module is stdlib-only and fail-soft: missing docs, unreadable
files, or zero matches all return empty lists rather than raising.

Public API
----------
scan(project_root: Path) -> dict
    Return ``{"tools": [...], "protected_branches": [...],
    "candidates": [...], "sources": [...]}`` where ``candidates``
    is a list of dicts ready to merge with ``scan_project``'s
    ``shared_adoption_candidates`` output.
"""

from __future__ import annotations

import re
from pathlib import Path


# Files we consider authoritative project documentation. Order matters
# only for tie-breaking the ``source`` recorded against each finding.
_DOC_FILES: tuple[str, ...] = (
    "CLAUDE.md",
    "AGENTS.md",
    ".claude/CLAUDE.md",
)


# Trivial shell builtins / coreutils we never propose as `Bash(<x>:*)`
# allow rules. Anything outside this set that appears at the head of a
# documented command becomes a candidate. Keeping this list short
# avoids opinions creeping in: anything project-specific (npm, uv, fj,
# helm, cargo, go, ...) is left alone and surfaced.
_TRIVIAL_TOKENS: frozenset[str] = frozenset(
    {
        "cd", "ls", "pwd", "cp", "mv", "rm", "mkdir", "rmdir", "touch",
        "ln", "echo", "printf", "cat", "head", "tail", "grep", "find",
        "sed", "awk", "tr", "cut", "sort", "uniq", "wc", "test",
        "true", "false", "exit", "return", "set", "unset", "export",
        "source", "eval", "exec", "[", "[[", "if", "then", "else",
        "elif", "fi", "for", "while", "do", "done", "case", "esac",
        "function", "time", "which", "type", "command", "alias",
    }
)


# Markdown fenced-code-block header. We accept ```bash, ```sh,
# ```shell, ```console (a common "demo" tag), or an untagged ```
# (which may still hold shell snippets in informal docs).
_FENCE_OPEN = re.compile(
    r"^```\s*(bash|sh|shell|console)?\s*$",
    re.IGNORECASE,
)
_FENCE_CLOSE = re.compile(r"^```\s*$")


# Leading line decorations we strip before tokenising. Order matters:
# we strip prompts first, then leading ``sudo`` (since the *real* tool
# is what comes after sudo).
#
# ``# `` is intentionally absent: in shell code blocks ``# foo`` is
# overwhelmingly a comment, not a root prompt. Treating it as a prompt
# would surface comment text (``# Analyze``, ``# Validate``) as tool
# candidates. The downstream ``_head_token`` skips lines that start
# with ``#`` after this decoration pass, so comments stay out of the
# tool catalogue.
_PROMPT_PREFIXES: tuple[str, ...] = ("$ ", "> ", "% ")


# A valid command-tool token: starts with a letter or underscore,
# contains only letters, digits, dot, dash, underscore, or plus,
# and is at most 64 characters long. No slashes (rejects path-traversal-
# shaped inputs like ``../../bin/rm`` or ``./scripts/foo.sh``), no
# leading dot or digit (rejects ``.hidden`` and pure-numeric strings).
_TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9._+-]{0,63}$")


# Branch-protection patterns. Each pattern captures a comma- and/or
# whitespace-separated branch list; we post-split on those characters.
# Patterns are intentionally narrow; false negatives are preferred to
# false positives (the prompt's `[k]eep / [e]dit / [d]rop` lets the
# user add anything we missed).
_PROTECTED_BRANCH_PATTERNS: tuple[re.Pattern[str], ...] = (
    # English: "never push (directly|to) ... main"
    re.compile(
        r"(?i)(?:never|do not|don't|do\s+not)\s+(?:force[- ]?)?push"
        r"[^.\n]{0,80}?(?:to|onto|into)\s+"
        r"([`'\"]?[A-Za-z0-9_,/\s.+-]+?[`'\"]?)\s*"
        r"(?:branch|directly|without|\.|\n|$)"
    ),
    # French: "ne pas (force[ -]?)push ... vers main"
    re.compile(
        r"(?i)(?:ne pas|jamais|n'est pas autoris[ée]?)\s+"
        r"(?:force[- ]?)?push"
        r"[^.\n]{0,80}?(?:vers|sur|à|au)\s+"
        r"([`'\"]?[A-Za-z0-9_,/\s.+-]+?[`'\"]?)\s*"
        r"(?:branche|directement|sans|\.|\n|$)"
    ),
    # Explicit listing: "Protected branches: main, develop, stable"
    # (also matches French "Branches protégées:" via its prefix).
    re.compile(
        r"(?im)(?:protected\s+branches?|branches?\s+prot[ée]g[ée]es?)"
        r"\s*[:=]\s*"
        r"([`'\"]?[A-Za-z0-9_,/\s.+-]+?)"
        r"(?:\.|\n|$)"
    ),
    # Markdown bullet-list form:
    #   - **Protected branches** (`main`, `develop`, `stable`): never push directly
    # The branch list is a parenthesised sequence of backtick-quoted names.
    re.compile(
        r"(?im)protected\s+branches?[^\n]{0,40}?[(:][^.\n]{0,200}?"
        r"((?:[\s,]*`[A-Za-z0-9_/.+-]+`)+)"
    ),
)


# A captured branch list is split on these characters. Empty fragments
# and obvious noise tokens are filtered out by `_clean_branch`.
_BRANCH_SPLIT_RE = re.compile(r"[\s,]+")


def _clean_branch(token: str) -> str | None:
    """Return a canonical branch name or ``None`` if ``token`` is noise."""

    t = token.strip().strip("`'\"").strip(".").strip()
    if not t:
        return None
    # A branch name fragment never contains glob-style wildcards; if we
    # captured one, the regex over-matched and we drop the fragment.
    if "*" in t or "?" in t:
        return None
    if len(t) > 64:
        return None
    # Tokens that are obvious English prepositions we accidentally swept
    # in (the regex captures past the verb when the sentence does not
    # end with a period).
    lower = t.lower()
    if lower in {"the", "and", "or", "any", "all", "remote", "branch", "branches"}:
        return None
    return t


def _strip_decoration(line: str) -> str:
    """Strip prompts + leading ``sudo`` from ``line``; return the rest."""

    s = line.strip()
    for prefix in _PROMPT_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    # Drop a leading ``sudo`` (and mixed flags/env-assignments like
    # ``sudo -E VAR=1 -u root npm install``). The two-loop approach
    # fails when flags and assignments are interleaved; replace with a
    # single loop that accepts one flag OR one env assignment per
    # iteration and stops as soon as neither matches.
    while s.startswith("sudo"):
        rest = s[4:]
        if not rest or rest[0] not in (" ", "\t"):
            break
        s = rest.lstrip()
        # Peel sudo's own leading args until we reach the real command.
        # Each pass accepts: a flag like ``-E`` / ``--preserve-env``,
        # or an env assignment like ``VAR=value`` (key must be
        # alphanum+underscore, no leading ``=``).
        while s:
            head, _, tail = s.partition(" ")
            if head.startswith("-"):  # flag
                s = tail.lstrip()
                continue
            if (
                "=" in head
                and not head.startswith("=")
                and head.split("=", 1)[0].replace("_", "").isalnum()
            ):  # env assignment VAR=value
                s = tail.lstrip()
                continue
            break
    return s


def _head_token(line: str) -> str | None:
    """Return the first whitespace-separated token of ``line`` if it
    looks like a command-tool name; otherwise ``None``."""

    s = _strip_decoration(line)
    if not s or s.startswith("#"):
        return None
    head, _, _ = s.partition(" ")
    if not head:
        return None
    if not _TOKEN_RE.match(head):
        return None
    if head in _TRIVIAL_TOKENS:
        return None
    return head


def _iter_shell_lines(text: str):
    """Yield individual shell lines from fenced code blocks in ``text``.

    Untagged fences are accepted but treated as "maybe shell"; we still
    apply the same head-token filter, so a Python snippet inside an
    untagged fence will simply produce no candidates (the head token
    doesn't match a shell tool name).
    """

    in_block = False
    for raw in text.splitlines():
        if not in_block:
            if _FENCE_OPEN.match(raw):
                in_block = True
            continue
        if _FENCE_CLOSE.match(raw):
            in_block = False
            continue
        yield raw


def _scan_tools(text: str) -> list[str]:
    """Return de-duplicated tool tokens observed in ``text``'s shell blocks.

    Order is preserved: the first occurrence of each token in the
    document wins, which keeps the candidate list deterministic and
    diff-friendly.
    """

    seen: dict[str, None] = {}
    for line in _iter_shell_lines(text):
        token = _head_token(line)
        if token is None:
            continue
        seen.setdefault(token, None)
    return list(seen.keys())


def _scan_protected_branches(text: str) -> list[str]:
    """Return protected branch names mentioned in ``text``."""

    seen: dict[str, None] = {}
    for pattern in _PROTECTED_BRANCH_PATTERNS:
        for match in pattern.finditer(text):
            captured = match.group(1) or ""
            for raw in _BRANCH_SPLIT_RE.split(captured):
                cleaned = _clean_branch(raw)
                if cleaned is not None:
                    seen.setdefault(cleaned, None)
    return list(seen.keys())


def _read_doc(root: Path, rel: str) -> str | None:
    p = root / rel
    if not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def scan(project_root: Path) -> dict:
    """Scan project docs and return suggestion records.

    Returns
    -------
    dict
        ``{"tools": [...], "protected_branches": [...],
        "candidates": [...], "sources": [...]}`` where ``candidates``
        is a list of dicts shaped like ``shared_adoption_candidates``
        entries (``section``, ``value``, ``source``, ``rationale``).
    """

    tools_seen: dict[str, str] = {}
    branches_seen: dict[str, str] = {}
    sources: list[str] = []

    for rel in _DOC_FILES:
        text = _read_doc(project_root, rel)
        if text is None:
            continue
        sources.append(rel)
        for token in _scan_tools(text):
            tools_seen.setdefault(token, rel)
        for branch in _scan_protected_branches(text):
            branches_seen.setdefault(branch, rel)

    candidates: list[dict] = []
    for token, source in tools_seen.items():
        candidates.append(
            {
                "section": "allow",
                "value": f"Bash({token}:*)",
                "source": source,
                "rationale": (
                    f"tool {token!r} appears at the head of a shell "
                    f"command in {source}"
                ),
            }
        )
    for branch, source in branches_seen.items():
        candidates.append(
            {
                "section": "hard_deny",
                "value": f"Bash(git push * {branch}*)",
                "source": source,
                "rationale": (
                    f"{source} marks {branch!r} as a protected branch; "
                    f"hard_deny blocks unconditionally and survives "
                    f"allow exceptions"
                ),
            }
        )

    return {
        "tools": list(tools_seen.keys()),
        "protected_branches": list(branches_seen.keys()),
        "candidates": candidates,
        "sources": sources,
    }
