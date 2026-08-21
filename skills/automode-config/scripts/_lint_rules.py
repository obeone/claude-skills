"""Deterministic semantic lint over the content of autoMode rules.

The rest of the skill validates *structure*: the four array keys exist,
hold strings, and serialize to stable canonical bytes. Nothing looks at
what the rules actually say. This module closes that gap with four
content rules that catch proposals which are structurally perfect and
semantically self-defeating.

The precedence model the rules encode:

- ``hard_deny`` is unconditional. Nothing lifts it, not an ``allow``
  rule and not stated user intent.
- ``soft_deny`` is overridable, by an ``allow`` rule or by stated user
  intent.
- ``allow`` is an exception carve-out that wins over ``soft_deny`` for
  the same target.

Rules
-----
AM001 (error)
    A conditional connective inside a ``hard_deny`` rule. The condition
    is fiction: hard_deny is never lifted, so the rule silently reads
    broader than its author intended.
AM002 (warn)
    An ``allow`` rule opens a target that a ``soft_deny`` rule tries to
    close. Because allow wins, the soft_deny condition is dead text.
AM003 (warn)
    A ``hard_deny`` forbids a literal the project's own files ship,
    which usually means the rule contradicts the real workflow.
AM004 (error)
    A ``permissions`` pattern such as ``Bash(git push:*)`` pasted into
    an autoMode section, where the classifier reads it as meaningless
    prose.

Public API
----------
Finding
    Frozen dataclass describing one lint hit.
lint_proposal(proposal, *, project_root=None) -> list[Finding]
    Run every rule and return findings in deterministic order.
format_findings(findings) -> str
    Render findings as plain-ASCII text suitable for stderr.

Stdlib-only, no network. The only subprocess call is ``git ls-files``,
used to bound AM003's file scan, and every failure of it falls back to
a plain directory walk.
"""

from __future__ import annotations

import dataclasses
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable, Iterator


# ---------------------------------------------------------------------------
# Shared configuration
# ---------------------------------------------------------------------------

# Canonical section order. Findings sort by this rank first so output is
# stable regardless of the order the rules ran in.
SECTION_ORDER = ("environment", "allow", "soft_deny", "hard_deny")
_SECTION_RANK = {name: i for i, name in enumerate(SECTION_ORDER)}

# The classifier's own sentinel for "inherit the defaults". It is not a
# rule, so every lint rule skips it.
DEFAULTS_SENTINEL = "$defaults"

# Rule text is echoed back to the user; keep it to one readable line.
MAX_RULE_TEXT = 120

SEVERITY_ERROR = "error"
SEVERITY_WARN = "warn"


@dataclasses.dataclass(frozen=True)
class Finding:
    """One semantic lint hit against a single autoMode entry.

    Attributes
    ----------
    rule : str
        Rule identifier, for example ``"AM001"``.
    severity : str
        Either ``"error"`` or ``"warn"``.
    section : str
        The autoMode section holding the offending entry, one of
        ``environment``, ``allow``, ``soft_deny``, ``hard_deny``.
    index : int
        Zero-based position of the entry inside that section's array.
        The index is the one in the *original* proposal, so it stays
        correct for entries wrapped in ``{"__example_only": ...}``.
    rule_text : str
        The offending rule text, truncated to ``MAX_RULE_TEXT``.
    message : str
        One sentence: what is wrong and what to do instead.
    detail : str, optional
        Extra evidence, such as the matched literal, the paired rule,
        or the repository paths that contradict the rule.
    """

    rule: str
    severity: str
    section: str
    index: int
    rule_text: str
    message: str
    detail: str = ""


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _truncate(text: str, limit: int = MAX_RULE_TEXT) -> str:
    """Return ``text`` capped at ``limit`` characters, ellipsized if cut.

    Parameters
    ----------
    text : str
        Arbitrary text.
    limit : int, optional
        Maximum length of the returned string, ellipsis included.

    Returns
    -------
    str
        ``text`` unchanged when short enough, otherwise a prefix ending
        in ``"..."`` whose total length is exactly ``limit``.
    """

    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _unwrap_entry(entry: Any) -> str | None:
    """Return the rule string carried by ``entry``, or ``None``.

    Proposals may wrap an entry in a structural envelope such as
    ``{"__example_only": true, "value": "..."}``. The envelope is not a
    rule, so it is unwrapped and the inner string linted in its place.

    Parameters
    ----------
    entry : object
        A raw entry taken from an autoMode section array.

    Returns
    -------
    str or None
        The rule text, or ``None`` when the entry carries none (a
        number, a list, a dict without a string ``value``).
    """

    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        inner = entry.get("value")
        if isinstance(inner, str):
            return inner
    return None


def _iter_entries(section: Any) -> Iterator[tuple[int, str]]:
    """Yield ``(index, rule_text)`` for every lintable entry of a section.

    Non-string entries are skipped, envelopes are unwrapped, and the
    ``$defaults`` sentinel is dropped. The yielded index is always the
    position in the original array, so a skipped entry does not shift
    the ones after it.

    Parameters
    ----------
    section : object
        The value stored under an autoMode section key. Anything that
        is not a list yields nothing.

    Yields
    ------
    tuple[int, str]
        Zero-based index and the rule text at that index.
    """

    if not isinstance(section, list):
        return
    for index, entry in enumerate(section):
        text = _unwrap_entry(entry)
        if text is None:
            continue
        if text.strip() == DEFAULTS_SENTINEL:
            continue
        yield index, text


def _sections(proposal: Any) -> dict[str, list[tuple[int, str]]]:
    """Extract the lintable entries of every autoMode section.

    Parameters
    ----------
    proposal : object
        A parsed proposal document. A missing or non-dict ``autoMode``
        block yields an empty entry list for every section.

    Returns
    -------
    dict[str, list[tuple[int, str]]]
        Mapping from section name to its ``(index, rule_text)`` pairs,
        with one key per name in ``SECTION_ORDER``.
    """

    automode: Any = None
    if isinstance(proposal, dict):
        automode = proposal.get("autoMode")
    if not isinstance(automode, dict):
        automode = {}
    return {
        name: list(_iter_entries(automode.get(name)))
        for name in SECTION_ORDER
    }


# ---------------------------------------------------------------------------
# AM001: conditional clause in a hard_deny rule
# ---------------------------------------------------------------------------

# Connectives that introduce an escape hatch. Ordered longest-first so
# the alternation prefers "only if" over "if" and "provided that" over
# "provided" at the same start offset.
#
# "otherwise" is deliberately absent. "Never disable audit logging,
# otherwise we lose the trail" is a consequence clause, not a carve-out,
# and firing on it would advise the author to move a correct hard_deny
# down to soft_deny. A false positive that talks a user into weakening a
# hard_deny costs more than missing the rare carve-out phrased that way.
_CONDITIONAL_CONNECTIVES = (
    "unless",
    "except",
    # The most natural paraphrase of "except" slips past \bexcept\b,
    # which cannot match inside "exception".
    "with the exception of",
    "other than",
    "apart from",
    "save for",
    "barring",
    "outside",
    "in cases where",
    "provided that",
    "provided",
    "as long as",
    "so long as",
    "only if",
    "without",
    "if",
    "when",
)


def _phrase_pattern(phrase: str) -> str:
    """Compile ``phrase`` into a whitespace-tolerant regex fragment.

    Each word is escaped individually and rejoined with ``\\s+`` so that
    "as  long   as" and a line-wrapped rule still match. Escaping the
    whole phrase would not work: ``re.escape`` escapes the space itself
    (it is meaningful under ``re.VERBOSE``).

    Parameters
    ----------
    phrase : str
        A one-or-more word phrase.

    Returns
    -------
    str
        A regex fragment matching the phrase.
    """

    return r"\s+".join(re.escape(word) for word in phrase.split())


_CONDITIONAL_RE = re.compile(
    r"\b(?:"
    # Longest-first so the alternation prefers the more specific phrase
    # at any given start offset.
    + "|".join(
        _phrase_pattern(word)
        for word in sorted(_CONDITIONAL_CONNECTIVES, key=len, reverse=True)
    )
    + r")\b",
    re.IGNORECASE,
)

# Phrases that contain a connective but strengthen the rule instead of
# weakening it. A match falling inside one of these spans is suppressed.
_CONDITIONAL_SUPPRESSING_PHRASES = (
    "without exception",
    "under no circumstances",
    "no matter when",
    "no matter if",
    "no matter whether",
    "including when",
    "including if",
)

_SUPPRESSING_PHRASE_RE = re.compile(
    "|".join(
        _phrase_pattern(phrase)
        for phrase in _CONDITIONAL_SUPPRESSING_PHRASES
    ),
    re.IGNORECASE,
)

# Prefixes that invert the connective's meaning: "even when", "even if",
# "regardless of when". Anchored to the end of the text preceding the
# match, with a leading \b so that a word merely *ending* in those
# letters ("step seven unless...", "more than eleven if...") cannot
# swallow the connective behind it.
_CONDITIONAL_SUPPRESSING_PREFIX_RE = re.compile(
    r"\b(?:even|regardless\s+of)\s+$", re.IGNORECASE
)


def _find_conditional(text: str) -> str | None:
    """Return the first non-suppressed conditional connective in ``text``.

    Known limits, stated so the rule does not read as full coverage: a
    condition expressed as a relative clause ("Never delete a namespace
    that is not labelled ephemeral") or as a participle ("Never
    force-push to a branch not marked as scratch") carries no
    connective, so no connective list can catch it. Chasing those forms
    needs a parser, and the guessing heuristics that would approximate
    one produce false positives whose remedy is "weaken your hard_deny".

    Parameters
    ----------
    text : str
        A ``hard_deny`` rule.

    Returns
    -------
    str or None
        The matched connective, lowercased and whitespace-normalized,
        or ``None`` when the rule carries no live condition.
    """

    suppressed = [m.span() for m in _SUPPRESSING_PHRASE_RE.finditer(text)]
    for match in _CONDITIONAL_RE.finditer(text):
        start, end = match.span()
        # Inside "without exception" and friends the connective is part
        # of an absolute phrase, not a carve-out.
        if any(lo <= start and end <= hi for lo, hi in suppressed):
            continue
        # "even when" / "regardless of when" widen the rule instead of
        # narrowing it, so the connective is not a condition here.
        if _CONDITIONAL_SUPPRESSING_PREFIX_RE.search(text[:start]):
            continue
        return " ".join(match.group(0).lower().split())
    return None


def _lint_am001(sections: dict[str, list[tuple[int, str]]]) -> list[Finding]:
    """Flag conditional clauses inside ``hard_deny`` rules.

    Parameters
    ----------
    sections : dict[str, list[tuple[int, str]]]
        Output of :func:`_sections`.

    Returns
    -------
    list[Finding]
        One error-severity finding per offending ``hard_deny`` entry.
        A rule carrying several connectives yields a single finding
        naming the first one, because the fix rewrites the whole rule.
    """

    findings: list[Finding] = []
    for index, text in sections["hard_deny"]:
        connective = _find_conditional(text)
        if connective is None:
            continue
        findings.append(
            Finding(
                rule="AM001",
                severity=SEVERITY_ERROR,
                section="hard_deny",
                index=index,
                rule_text=_truncate(text),
                message=(
                    f'conditional connective "{connective}" in an '
                    "unconditional section; hard_deny is never lifted, so "
                    "move the conditional form to soft_deny or restate it "
                    "without the condition"
                ),
                detail=f"matched connective: {connective}",
            )
        )
    return findings


# ---------------------------------------------------------------------------
# AM002: an allow rule shadows a soft_deny rule
# ---------------------------------------------------------------------------

# Quoted spans are treated as one salient token each, whatever they
# contain: an author who quoted something meant to name a target.
#
# The single-quote alternative is fenced on both sides. Without the
# fence an apostrophe opens a span, so "Don't run the project's
# migration" yields the fragment "t run the project", which AM003 would
# then grep across the whole tree. An opening quote must sit at the
# start of the text or after whitespace, and the closing quote must be
# followed by whitespace, punctuation, or the end of the text.
_QUOTED_SPAN_RE = re.compile(
    r"`([^`]*)`"
    r"|\"([^\"]*)\""
    r"|(?<!\S)'([^']*)'(?=[\s,.;:!?)\]}]|$)"
)

# A bare word is salient when it looks like a path, a flag, a glob, or a
# dotted name.
_SALIENT_CHARS = ("/", ".", "-", "*", "_")

# ...or when it is a command the classifier is likely to gate on. This
# vocabulary is curated on purpose: a generic English word would pair
# unrelated rules and drown the real collisions.
_COMMAND_VOCABULARY = frozenset(
    {
        "kubectl", "helm", "terraform", "tofu", "ansible",
        "ansible-playbook", "git", "docker", "podman", "nft", "nftables",
        "iptables", "systemctl", "rm", "dd", "mkfs", "psql", "mysql",
        "mongo", "redis-cli", "flux", "argocd", "aws", "gcloud", "az",
        "ssh", "scp", "rsync", "curl", "npm", "pnpm", "yarn", "pip",
        "uv", "cargo", "make", "kustomize",
    }
)

# Punctuation-only or abbreviation tokens that pass the salience test
# for the wrong reason (they all contain a dot or a dash).
_TOKEN_STOPWORDS = frozenset({"e.g.", "i.e.", "etc.", "...", "--", "-", ".", "/"})

_TOKEN_TRAILING_PUNCT = ",.;:!?)"
_TOKEN_LEADING_PUNCT = "("

# Below this length a token carries no target information.
_MIN_TOKEN_LEN = 3


def _is_dropped_token(token: str) -> bool:
    """Return whether ``token`` must never count as a salient token.

    Parameters
    ----------
    token : str
        A already-lowercased candidate token.

    Returns
    -------
    bool
        ``True`` for shell variables, too-short tokens, and stopwords.
    """

    # "$defaults" and friends are sentinels, not targets.
    if token.startswith("$"):
        return True
    if len(token) < _MIN_TOKEN_LEN:
        return True
    if token in _TOKEN_STOPWORDS:
        return True
    # Stripping trailing punctuation turns "e.g." into "e.g", so check
    # the re-suffixed form too rather than letting abbreviations leak in.
    if token + "." in _TOKEN_STOPWORDS:
        return True
    return False


def _salient_tokens(text: str) -> set[str]:
    """Extract the tokens that identify what a rule is about.

    Two sources feed the set: every quoted or backticked span, and every
    whitespace token that either looks like a path/flag/glob or names a
    known command.

    Parameters
    ----------
    text : str
        A rule from ``allow`` or ``soft_deny``.

    Returns
    -------
    set[str]
        Lowercased salient tokens, possibly empty.
    """

    tokens: set[str] = set()

    for match in _QUOTED_SPAN_RE.finditer(text):
        # Exactly one group matches per span; the others are None.
        span = next((g for g in match.groups() if g is not None), "")
        candidate = span.strip().lower()
        if candidate and not _is_dropped_token(candidate):
            tokens.add(candidate)

    for raw in text.split():
        lowered = raw.lower()
        if lowered in _TOKEN_STOPWORDS:
            continue
        stripped = lowered.lstrip(_TOKEN_LEADING_PUNCT).rstrip(
            _TOKEN_TRAILING_PUNCT
        )
        if not stripped or _is_dropped_token(stripped):
            continue
        looks_like_target = any(ch in stripped for ch in _SALIENT_CHARS)
        if looks_like_target or stripped in _COMMAND_VOCABULARY:
            tokens.add(stripped)

    return tokens


# Subcommands that only read. The idiom this exists for is the correct
# one: allow a tool's read subcommands, soft_deny its write ones. Both
# rules then name the same tool, which is a token collision and not a
# conflict.
_READ_ONLY_SUBCOMMANDS = frozenset(
    {
        "get", "describe", "list", "logs", "log", "diff", "template",
        "plan", "status", "show", "view", "cat", "top", "explain",
    }
)

# Function words that can follow a tool name without being a
# subcommand. Restricted to articles, prepositions, conjunctions,
# copulas, and determiners: anything richer would be fitting the list to
# a fixture instead of to grammar.
_NON_SUBCOMMAND_WORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "on", "in", "to", "from",
        "against", "without", "outside", "for", "with", "at", "by",
        "into", "under", "over", "that", "which", "when", "if", "is",
        "are", "be", "only", "any", "all", "its", "this", "these",
        "those", "of", "as", "but", "not", "no", "never", "always",
    }
)

_SUBCOMMAND_STRIP_CHARS = "`\"'()[],.;:!?"


def _subcommands(text: str) -> set[str]:
    """Extract the subcommands a rule names, by position.

    Grammar is out of reach here, but one position is unambiguous: the
    token immediately following a known tool name is that tool's
    subcommand. Nothing else in a prose rule is read as a subcommand.

    Parameters
    ----------
    text : str
        A rule from ``allow`` or ``soft_deny``.

    Returns
    -------
    set[str]
        Lowercased subcommands, possibly empty.
    """

    tokens = [
        token.strip(_SUBCOMMAND_STRIP_CHARS).lower() for token in text.split()
    ]
    subcommands: set[str] = set()
    for position, token in enumerate(tokens[:-1]):
        if token not in _COMMAND_VOCABULARY:
            continue
        # "get/describe" names two subcommands in one token, the same
        # way "get, describe" names two across two tokens.
        parts = tokens[position + 1].split("/")
        # A subcommand is a bare word; a flag, a path, or a function
        # word means the sentence moved on without naming one. One bad
        # part disqualifies the whole token: a half-read list would
        # understate what the rule allows.
        if all(
            part.isalpha() and part not in _NON_SUBCOMMAND_WORDS
            for part in parts
        ):
            subcommands.update(parts)
    return subcommands


def _is_read_only_carve_out(
    allow_subcommands: set[str], soft_deny_subcommands: set[str]
) -> bool:
    """Return whether an allow/soft_deny pair is the read/write idiom.

    Parameters
    ----------
    allow_subcommands : set[str]
        Subcommands named by the ``allow`` rule.
    soft_deny_subcommands : set[str]
        Subcommands named by the ``soft_deny`` rule.

    Returns
    -------
    bool
        ``True`` when the allow side names only read-only subcommands
        and the soft_deny side names none of them, which makes the
        shared tool name a collision rather than a conflict. Either side
        naming no subcommand at all leaves the pair undecidable, so the
        finding stands.
    """

    if not allow_subcommands or not soft_deny_subcommands:
        return False
    if not allow_subcommands <= _READ_ONLY_SUBCOMMANDS:
        return False
    return not (soft_deny_subcommands & _READ_ONLY_SUBCOMMANDS)


def _lint_am002(sections: dict[str, list[tuple[int, str]]]) -> list[Finding]:
    """Flag ``allow`` and ``soft_deny`` rules that name the same target.

    What the rule sees: shared paths, globs, quoted spans, and tool
    names. What it does not see: a target named by a bare noun
    (``staging``, ``production``, a namespace name), because pairing on
    ordinary English words would match nearly every rule against nearly
    every other. A bare-noun collision is a known miss, not an oversight.

    The finding is a prompt, not a verdict. ``allow`` and ``soft_deny``
    exist precisely to carve up the same subsystem, so a shared token is
    the expected state as often as it is a defect, and the severity
    stays ``warn`` for that reason.

    The read/write carve-out is recognised by position: the token after
    a tool name is that tool's subcommand. A rule that describes its
    subcommands instead of naming them ("Run read-only kubectl commands
    against any context") therefore still pairs with its soft_deny. A
    positional extractor cannot reach that phrasing, and the fix is to
    name the subcommands, not to guess at adjectives.

    Parameters
    ----------
    sections : dict[str, list[tuple[int, str]]]
        Output of :func:`_sections`.

    Returns
    -------
    list[Finding]
        One warn-severity finding per colliding (allow, soft_deny) pair,
        attached to the ``soft_deny`` entry and ordered by allow index
        so repeated collisions render deterministically.
    """

    allow_entries = [
        (index, text, _salient_tokens(text), _subcommands(text))
        for index, text in sections["allow"]
    ]
    findings: list[Finding] = []
    for sd_index, sd_text in sections["soft_deny"]:
        sd_tokens = _salient_tokens(sd_text)
        if not sd_tokens:
            continue
        sd_subcommands = _subcommands(sd_text)
        for allow_index, allow_text, allow_tokens, allow_subs in allow_entries:
            shared = sorted(sd_tokens & allow_tokens)
            if not shared:
                continue
            if _is_read_only_carve_out(allow_subs, sd_subcommands):
                continue
            findings.append(
                Finding(
                    rule="AM002",
                    severity=SEVERITY_WARN,
                    section="soft_deny",
                    index=sd_index,
                    rule_text=_truncate(sd_text),
                    message=(
                        "this soft_deny and an allow rule name the same "
                        "target, and allow wins where they overlap; confirm "
                        "the allow rule does not swallow this soft_deny"
                    ),
                    detail=(
                        f"shared tokens: {', '.join(shared)}; "
                        f"paired with allow[{allow_index}]: "
                        f"{_truncate(allow_text)}"
                    ),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# AM003: a hard_deny literal the project itself ships
# ---------------------------------------------------------------------------

_COMMAND_TRIGGER_RE = re.compile(
    r"\b(?:run|runs|running|execute|executes|executing|invoke|invokes|"
    r"invoking|call|calls|calling)\b",
    re.IGNORECASE,
)

# Words that end a command phrase: past them the sentence has moved on
# from the command to its context.
_PHRASE_STOP_TOKENS = frozenset(
    {
        "on", "in", "to", "from", "against", "without", "unless",
        "outside", "except", "for", "with", "at", "by", "into", "under",
        "over", "that", "which", "when", "if", "and", "or",
        # Determiners: a command never contains one, so their presence
        # means the trigger verb was followed by prose ("run the
        # project's migration"), not by a command line.
        "the", "a", "an", "any", "all", "this", "these", "those", "its",
        "it",
    }
)

_PHRASE_MAX_TOKENS = 5
_PHRASE_TERMINATORS = (",", ".", ";", ":")
_LITERAL_STRIP_CHARS = "`\"' \t,.;:!?"
_MIN_LITERAL_LEN = 6

# A phrase the author did not delimit has to earn its way in. Two
# tokens is the length of ordinary prose ("rm -rf" out of "Never run
# rm -rf on the repo"), and a two-token fragment matches far too much of
# a documentation-heavy tree to mean anything. A span the author put in
# quotes is exempt: the quotes are the author saying where it ends.
_MIN_PHRASE_TOKENS = 3

# Characters that continue a token. A literal must not be flanked by
# one, so "uv run scripts" does not match inside
# "uv run scripts/analyze.py": a prefix of a longer command is not the
# command the rule forbids.
_LITERAL_EDGE = r"[\w./-]"

# Directory names never worth scanning: build output, caches, vendored
# dependencies, and nested worktrees.
_WALK_SKIP_DIRS = frozenset(
    {
        ".git", "node_modules", ".venv", "venv", "__pycache__",
        ".worktrees", "dist", "build", "target", ".tox", ".mypy_cache",
        ".pytest_cache",
    }
)

MAX_SCANNED_FILES = 5000
MAX_SCANNED_FILE_BYTES = 512 * 1024
_BINARY_SNIFF_BYTES = 8 * 1024
_GIT_TIMEOUT_SECONDS = 10
MAX_REPORTED_PATHS = 5


def _extract_literals(text: str) -> list[str]:
    """Extract the searchable literals a ``hard_deny`` rule forbids.

    Two extractors run: quoted or backticked spans, and command phrases
    following a trigger verb such as "run" or "invoke". A candidate
    survives only when it is long enough and looks like a command or a
    path rather than an ordinary word. An undelimited phrase must also
    clear ``_MIN_PHRASE_TOKENS``, which a quoted span does not: quoting
    is the author stating the boundaries themselves.

    Parameters
    ----------
    text : str
        A ``hard_deny`` rule.

    Returns
    -------
    list[str]
        Sorted, de-duplicated literals, kept in the case they were
        written so the file scan can match case-sensitively.
    """

    # (candidate, minimum token count) so quoted spans keep their
    # exemption from the prose-fragment floor.
    candidates: list[tuple[str, int]] = []

    for match in _QUOTED_SPAN_RE.finditer(text):
        span = next((g for g in match.groups() if g is not None), "")
        candidates.append((span, 1))

    for trigger in _COMMAND_TRIGGER_RE.finditer(text):
        taken: list[str] = []
        for token in text[trigger.end():].split():
            if len(taken) >= _PHRASE_MAX_TOKENS:
                break
            # A capitalized word starts a new clause, a terminated word
            # ends this one, and a stop token means the command is over.
            if token[:1].isupper():
                break
            if token.endswith(_PHRASE_TERMINATORS):
                break
            if token.lower() in _PHRASE_STOP_TOKENS:
                break
            taken.append(token)
        if taken:
            candidates.append((" ".join(taken), _MIN_PHRASE_TOKENS))

    literals: set[str] = set()
    for candidate, min_tokens in candidates:
        literal = candidate.strip(_LITERAL_STRIP_CHARS)
        if len(literal) < _MIN_LITERAL_LEN:
            continue
        # A single bare word matches far too much; require a multi-word
        # command or something path-shaped.
        if " " not in literal and "/" not in literal:
            continue
        if len(literal.split()) < min_tokens:
            continue
        literals.add(literal)
    return sorted(literals)


def _literal_matcher(literal: str) -> re.Pattern[str]:
    """Compile a boundary-fenced matcher for one literal.

    Parameters
    ----------
    literal : str
        The literal to search for, matched case-sensitively.

    Returns
    -------
    re.Pattern
        A pattern that matches ``literal`` only when it is not flanked
        by a token character, so a literal cannot match as the prefix or
        the suffix of a longer command or path.
    """

    return re.compile(
        r"(?<!" + _LITERAL_EDGE + r")"
        + re.escape(literal)
        + r"(?!" + _LITERAL_EDGE + r")"
    )


def _git_tracked_files(root: Path) -> list[Path] | None:
    """List the files git tracks under ``root``.

    Parameters
    ----------
    root : Path
        Directory to interrogate.

    Returns
    -------
    list[Path] or None
        Absolute paths of tracked regular files, or ``None`` when git is
        unavailable, ``root`` is not a work tree, or the call failed for
        any other reason. ``None`` means "fall back to a plain walk".
    """

    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    names = [
        chunk.decode("utf-8", "replace")
        for chunk in proc.stdout.split(b"\0")
        if chunk
    ]
    if not names:
        return None
    return [root / name for name in names]


def _walk_files(root: Path, limit: int) -> list[Path]:
    """Walk ``root`` collecting regular files, skipping noisy directories.

    The cap applies during enumeration, not after it: a tree far larger
    than the cap must not be listed in full just to throw most of it
    away. Entries are sorted per directory so the truncated prefix is
    the same set on every run rather than whatever order the filesystem
    hands back.

    ``os.walk`` does not follow directory symlinks, so a symlink loop
    cannot spin the walk.

    Parameters
    ----------
    root : Path
        Directory to walk.
    limit : int
        Stop after collecting this many paths.

    Returns
    -------
    list[Path]
        Absolute paths of the files found, at most ``limit`` of them.
    """

    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune in place so os.walk never descends into them at all.
        dirnames[:] = sorted(d for d in dirnames if d not in _WALK_SKIP_DIRS)
        for name in sorted(filenames):
            found.append(Path(dirpath) / name)
            if len(found) >= limit:
                return found
    return found


def _scan_candidate_files(root: Path) -> list[Path]:
    """Return the bounded, sorted file set AM003 is allowed to read.

    Every candidate is resolved and checked against the resolved root: a
    symlink pointing outside the project is not part of the project, and
    reading one would let a rule's literal be searched anywhere on the
    host. ``is_file`` on the unresolved path also rejects directories,
    FIFOs, sockets, and devices.

    Parameters
    ----------
    root : Path
        Project root.

    Returns
    -------
    list[Path]
        At most ``MAX_SCANNED_FILES`` existing regular files that live
        under ``root``, sorted so the scan result does not depend on
        filesystem ordering.
    """

    try:
        root_resolved = root.resolve()
    except OSError:
        return []

    files = _git_tracked_files(root)
    if files is None:
        candidates = _walk_files(root, MAX_SCANNED_FILES)
    else:
        candidates = sorted(set(files))[:MAX_SCANNED_FILES]

    kept: list[Path] = []
    for path in candidates:
        if not path.is_file():
            continue
        try:
            resolved = path.resolve()
        except OSError:
            continue
        # A symlink out of the tree is not the project's own content.
        if not resolved.is_relative_to(root_resolved):
            continue
        kept.append(path)
    return sorted(set(kept))


def _read_text_for_scan(path: Path) -> str | None:
    """Read ``path`` as text, or return ``None`` when it must be skipped.

    Files larger than ``MAX_SCANNED_FILE_BYTES`` and files whose first
    8 KiB contain a NUL byte are skipped: the former to bound the scan,
    the latter because a binary blob cannot contain a prose literal in
    any meaningful sense.

    The size check is enforced on the bytes actually read, not on the
    ``stat`` that preceded them. The ``stat`` is only a cheap early exit;
    a file that grows between the two calls is still bounded, and is
    still skipped rather than half-scanned.

    Parameters
    ----------
    path : Path
        File to read.

    Returns
    -------
    str or None
        The decoded text, or ``None`` when skipped or unreadable.
    """

    try:
        if path.stat().st_size > MAX_SCANNED_FILE_BYTES:
            return None
        with path.open("rb") as handle:
            head = handle.read(_BINARY_SNIFF_BYTES)
            if b"\0" in head:
                return None
            # One byte past the cap, so an oversized file is detected
            # rather than silently truncated into a partial scan.
            rest = handle.read(MAX_SCANNED_FILE_BYTES - len(head) + 1)
    except OSError:
        return None
    blob = head + rest
    if len(blob) > MAX_SCANNED_FILE_BYTES:
        return None
    return blob.decode("utf-8", "replace")


def _locate_literals(root: Path, literals: Iterable[str]) -> dict[str, list[str]]:
    """Find which project files contain each literal.

    Parameters
    ----------
    root : Path
        Project root, used to relativize the reported paths.
    literals : Iterable[str]
        Literals to search for, case-sensitively.

    Returns
    -------
    dict[str, list[str]]
        Mapping from literal to the repo-relative paths that contain it,
        in scan order, capped at one more than ``MAX_REPORTED_PATHS``.
        The extra entry is the caller's signal that more exist. Literals
        with no hit are absent from the mapping.

    Notes
    -----
    Accumulation stops per literal once the cap is reached, and the scan
    stops entirely once every literal has reached it. Reading the rest
    of a tree to count occurrences that no ``detail`` line can show is
    work with no reader.
    """

    wanted = sorted({lit for lit in literals if lit})
    hits: dict[str, list[str]] = {}
    if not wanted:
        return hits

    matchers = {literal: _literal_matcher(literal) for literal in wanted}
    cap = MAX_REPORTED_PATHS + 1

    for path in _scan_candidate_files(root):
        if all(len(hits.get(literal, ())) >= cap for literal in wanted):
            break
        pending = [
            literal
            for literal in wanted
            if len(hits.get(literal, ())) < cap
        ]
        text = _read_text_for_scan(path)
        if text is None:
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = path.as_posix()
        for literal in pending:
            if matchers[literal].search(text):
                hits.setdefault(literal, []).append(rel)
    return {literal: paths for literal, paths in hits.items() if paths}


def _lint_am003(
    sections: dict[str, list[tuple[int, str]]],
    project_root: Path | None,
) -> list[Finding]:
    """Flag ``hard_deny`` literals that the project's own files contain.

    Parameters
    ----------
    sections : dict[str, list[tuple[int, str]]]
        Output of :func:`_sections`.
    project_root : Path or None
        Project root to scan. ``None`` or a non-directory disables the
        rule entirely: without a tree there is nothing to contradict.

    Returns
    -------
    list[Finding]
        One warn-severity finding per (entry, matching literal).
    """

    if project_root is None or not project_root.is_dir():
        return []

    per_entry = [
        (index, text, _extract_literals(text))
        for index, text in sections["hard_deny"]
    ]
    all_literals = {lit for _, _, lits in per_entry for lit in lits}
    if not all_literals:
        return []

    hits = _locate_literals(project_root, sorted(all_literals))
    findings: list[Finding] = []
    for index, text, literals in per_entry:
        for literal in literals:
            paths = hits.get(literal)
            if not paths:
                continue
            shown = paths[:MAX_REPORTED_PATHS]
            # The scan stops counting past the cap, so the honest suffix
            # is "there are more", not a number it did not finish.
            suffix = " (and more)" if len(paths) > MAX_REPORTED_PATHS else ""
            findings.append(
                Finding(
                    rule="AM003",
                    severity=SEVERITY_WARN,
                    section="hard_deny",
                    index=index,
                    rule_text=_truncate(text),
                    message=(
                        "this hard_deny forbids a literal the project's own "
                        "files contain, which usually means the rule "
                        "contradicts the real workflow; narrow the rule or "
                        "confirm the occurrences are intentional"
                    ),
                    detail=(
                        f"literal: {literal}; found in: "
                        f"{', '.join(shown)}{suffix}"
                    ),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# AM004: a permissions pattern pasted into an autoMode section
# ---------------------------------------------------------------------------

# A tool name as `permissions` writes them. Case is not a signal:
# `mcp__github__create_issue(*)` is as real a pattern as `Bash(...)`.
_TOOL_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")

# Decorations a paste picks up on its way into a JSON array.
_BULLET_PREFIX_RE = re.compile(r"^[-*+]\s+")
_PATTERN_TRAILING_PUNCT = ".,;:!?"
_PATTERN_QUOTE_CHARS = "\"'`"
_PATTERN_SEPARATOR_RE = re.compile(r"\s*,\s*")


def _normalize_permission_entry(text: str) -> str:
    """Strip the decorations a pasted permissions pattern arrives with.

    A pattern copied out of ``settings.json`` or out of a bullet list
    keeps its quotes, its bullet marker, or the sentence's full stop.
    None of that changes what it is.

    Parameters
    ----------
    text : str
        The raw autoMode entry.

    Returns
    -------
    str
        The entry with surrounding whitespace, a leading bullet marker,
        a matched surrounding quote pair, and trailing sentence
        punctuation removed, applied repeatedly until it settles.
    """

    value = text.strip()
    # Layers nest ("- \"Bash(x)\"."), so peel until nothing changes.
    for _ in range(4):
        before = value
        value = _BULLET_PREFIX_RE.sub("", value).strip()
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in _PATTERN_QUOTE_CHARS
        ):
            value = value[1:-1].strip()
        value = value.rstrip(_PATTERN_TRAILING_PUNCT).strip()
        if value == before:
            break
    return value


def _match_permission_pattern(text: str, pos: int) -> int | None:
    """Return the end offset of a ``Tool(specifier)`` pattern at ``pos``.

    Parentheses are matched by depth rather than by a regex, so a
    specifier containing its own parentheses (``Bash(echo (hi))``) is
    read as one pattern instead of being cut at the first ``)``.

    Parameters
    ----------
    text : str
        The normalized entry.
    pos : int
        Offset to match at.

    Returns
    -------
    int or None
        Offset just past the closing parenthesis, or ``None`` when no
        pattern starts at ``pos``.
    """

    name = _TOOL_NAME_RE.match(text, pos)
    if name is None:
        return None
    cursor = name.end()
    if cursor >= len(text) or text[cursor] != "(":
        return None
    depth = 0
    while cursor < len(text):
        char = text[cursor]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return cursor + 1
        cursor += 1
    return None


def _permission_patterns(value: str) -> list[str]:
    """Return the patterns when ``value`` is nothing but patterns.

    Both shapes count: a single ``Tool(specifier)`` and a comma-separated
    list of them, which is what a multi-line selection out of
    ``permissions.allow`` collapses to.

    Parameters
    ----------
    value : str
        A normalized entry.

    Returns
    -------
    list[str]
        The patterns found, or an empty list when any part of ``value``
        is something else. Prose that merely mentions a pattern returns
        an empty list, because the prose around it does not match. A
        trailing separator is tolerated: a list cut short is still a
        paste, not a sentence.
    """

    patterns: list[str] = []
    cursor = 0
    length = len(value)
    while cursor < length:
        end = _match_permission_pattern(value, cursor)
        if end is None:
            return []
        patterns.append(value[cursor:end])
        cursor = end
        separator = _PATTERN_SEPARATOR_RE.match(value, cursor)
        if separator is None:
            break
        cursor = separator.end()
    if cursor != length:
        return []
    return patterns


def _lint_am004(sections: dict[str, list[tuple[int, str]]]) -> list[Finding]:
    """Flag ``permissions`` patterns used as autoMode rules.

    Parameters
    ----------
    sections : dict[str, list[tuple[int, str]]]
        Output of :func:`_sections`.

    Returns
    -------
    list[Finding]
        One error-severity finding per offending entry, in any section.
    """

    findings: list[Finding] = []
    for name in SECTION_ORDER:
        for index, text in sections[name]:
            normalized = _normalize_permission_entry(text)
            patterns = _permission_patterns(normalized)
            if not patterns:
                continue
            label = "pattern" if len(patterns) == 1 else "patterns"
            findings.append(
                Finding(
                    rule="AM004",
                    severity=SEVERITY_ERROR,
                    section=name,
                    index=index,
                    rule_text=_truncate(text),
                    message=(
                        "this is a permissions pattern, not an autoMode "
                        "rule; move it to permissions.allow or "
                        "permissions.deny and restate the intent here as a "
                        "prose sentence"
                    ),
                    detail=(
                        f"matched {label}: "
                        f"{_truncate(', '.join(patterns))}"
                    ),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def lint_proposal(
    proposal: dict, *, project_root: Path | None = None
) -> list[Finding]:
    """Run every semantic lint rule over an autoMode proposal.

    Parameters
    ----------
    proposal : dict
        A proposal document. A missing or non-dict ``autoMode`` block
        is tolerated and yields no findings.
    project_root : Path or None, optional
        Project root used by AM003 to look for contradictions between a
        ``hard_deny`` rule and the files the project ships. When
        ``None`` (the default) AM003 is skipped.

    Returns
    -------
    list[Finding]
        Findings sorted by section (environment, allow, soft_deny,
        hard_deny), then index, then rule id. The sort is stable, so
        several findings sharing that key keep the order their rule
        produced them in, which is itself deterministic.
    """

    sections = _sections(proposal)
    findings: list[Finding] = []
    findings.extend(_lint_am001(sections))
    findings.extend(_lint_am002(sections))
    findings.extend(_lint_am003(sections, project_root))
    findings.extend(_lint_am004(sections))
    return sorted(
        findings,
        key=lambda f: (_SECTION_RANK.get(f.section, len(SECTION_ORDER)),
                       f.index,
                       f.rule),
    )


def format_findings(findings: list[Finding]) -> str:
    """Render findings as human-readable multi-line text for stderr.

    Errors are grouped ahead of warnings; within a group the incoming
    order is preserved. Output is plain ASCII with no colour codes.

    Parameters
    ----------
    findings : list[Finding]
        Findings, typically straight from :func:`lint_proposal`.

    Returns
    -------
    str
        A trailing-newline-terminated block, or ``""`` when there is
        nothing to report.
    """

    if not findings:
        return ""

    ordered = [f for f in findings if f.severity == SEVERITY_ERROR]
    ordered += [f for f in findings if f.severity != SEVERITY_ERROR]

    blocks: list[str] = []
    for finding in ordered:
        lines = [
            f"{finding.severity:<5}  {finding.rule}  "
            f"autoMode.{finding.section}[{finding.index}]",
            f"  rule: {finding.rule_text}",
            f"  {finding.message}",
        ]
        if finding.detail:
            lines.append(f"  detail: {finding.detail}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"
