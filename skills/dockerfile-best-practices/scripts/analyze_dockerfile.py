#!/usr/bin/env python3
"""
Dockerfile analyzer - Detects common anti-patterns and suggests improvements.

Usage:
    python analyze_dockerfile.py <path_to_Dockerfile>
    python analyze_dockerfile.py <path_to_Dockerfile> --json

Rule IDs are stable: a retired ID is never reused, so a rule reference in an
old report always means the same thing.

Retired rules
-------------

=======  ==========  ==================  ====================================
Rule     Retired in  What it flagged     Why it was retired
=======  ==========  ==================  ====================================
DL004    3.0.0       Base image tags     It enforced the reversed doctrine
                     that pin an OS      "pin the runtime, never the OS" and
                     release             pushed users toward a floating tag
                     (``-bookworm``,     (``debian:stable-slim``) as if
                     ``-bullseye``, ...) mutability were a reproducibility
                                         feature. That directly contradicted
                                         DL002, which rejects ``:latest`` as
                                         an error precisely because it is
                                         mutable. OS-pinned tags are a
                                         legitimate stability choice and are
                                         no longer flagged.
DL005    3.0.0       Alpine tags that    Same defect as DL004: it suggested
                     pin a minor         ``alpine:3`` so patches would land
                     version             silently. Patches must land through
                     (``alpine:3.19``)   a renewal process (Renovate /
                                         Dependabot opening a PR), not
                                         through a tag that moves under you.
DL035    never       ``FROM`` without    Written during 3.0.0 development and
         shipped     an ``@sha256:``     dropped before release. It nudged
                     digest              toward digest pinning, which is good
                                         practice but not a requirement: a
                                         digest without renewal automation is
                                         just a tag that rots silently. Since
                                         digests are an option and not the
                                         doctrine, the rule would have fired
                                         on nearly every Dockerfile in
                                         existence for no actionable reason.
                                         The id is burned and is never reused.
=======  ==========  ==================  ====================================

DL002 (``:latest`` is an error) and DL003 (untagged image implies ``:latest``)
are intentionally kept. Removing DL004/DL005 is what makes them coherent: the
analyzer now holds a single position, that a mutable reference is never a
reproducibility guarantee, rather than rejecting ``:latest`` for its mutability
while recommending other mutable tags in the same breath.

3.0.0 also fixes a DL003 false positive: a bare ``FROM <stage-name>`` that
references an earlier ``FROM ... AS <stage-name>`` build stage (the standard
multi-stage pattern) no longer trips "untagged base image", since a build
stage has no registry tag to begin with. DL003 keeps its id and severity;
only the false positive is removed. DL002 was checked for the same shape of
bug and does not have it: its ``:latest`` regex requires a literal colon,
which a stage alias can never contain.

3.0.0 also fixes a DL021 false positive/negative pair with a single root
cause: the check matched "root" as a substring of the last token, so
``USER nonroot`` (the canonical account in ``gcr.io/distroless/*:nonroot``
images) was reported as root, and, because that branch never sets
``has_user``, ALSO triggered DL030 ("No non-root USER defined") on a file
that has one. The check now compares the exact user name, so ``nonroot``,
``USER 10001``, and similar are correctly accepted. As a side effect this
also makes DL021 catch ``USER 0``, which the substring check missed
entirely. DL021 keeps its id and severity.

New in 3.0.0
------------

DL036, DL037, and DL038 close the gap that let v2.0.0 ship its own two worst
defects (F-01, F-02) with a CLEAN analyzer report: none of DL001-DL035 could
have caught either one, so a green run of this script was never proof of
correctness for the one thing that mattered most. These three rules exist
specifically to prevent recurrence.

- **DL036** (error/info) - a ``--chown`` on COPY/ADD naming a user or group
  that cannot resolve in the current stage. Verified on BuildKit 29.4.0: this
  does NOT fail the build (the brief's "can't find uid for user" is the
  legacy pre-BuildKit builder's error and does not apply to the
  ``dockerfile:1`` frontend). The real, empirically confirmed behaviour is
  worse: ``--chown`` is silently discarded, the files land owned by root
  (0:0), and the app then fails at runtime on its first write, long after a
  green build. This was v2.0.0's F-01, present in 4 of its 6 language
  templates. Since nothing else in the pipeline can observe this (not the
  build, not ``docker build --check``, not CI, all exit 0), this static
  check is the only possible net, which makes it the single most valuable
  rule this analyzer runs. "error" severity fires only when the name IS
  created later in the same stage (the exact F-01 shape, near-zero false
  positives); "info" severity is a heuristic bonus for a name never created
  anywhere in the stage and not on a short built-in-account allowlist, which
  may be a real base-image account this analyzer cannot see.
- **DL037** (error/warning) - ``:latest`` (error, mirrors DL002) or an
  untagged reference (warning, mirrors DL003) in ``COPY --from=``. DL002
  only ever inspected ``FROM``, so ``COPY --from=ghcr.io/astral-sh/uv:latest``
  and ``COPY --from=composer:latest`` both shipped in v2.0.0 untouched. A
  stage reference (numeric index, ``AS`` alias, or a ``$VAR``) is never
  flagged; alias tracking is shared with DL003.
- **DL038** (warning) - a HEALTHCHECK invoking ``curl`` or ``wget`` that this
  stage never installs. This is v2.0.0's F-02: verified on BuildKit 29.4.0
  that neither binary ships on ``python:3.11-slim``, ``python:3.12-slim``,
  nor ``debian:stable-slim``, so the skill's own former rule-10 example
  (``HEALTHCHECK CMD wget ...`` on a slim base) could never have worked.
  ``curl`` is flagged unconditionally when absent (ships on neither family
  tested); ``wget`` is flagged only when the base image is confidently
  identified as non-alpine, since BusyBox provides it on every alpine-family
  image with no install step. An unidentifiable base (a bare variable, or an
  unrecognised custom/private registry ref) is never guessed at for the wget
  half. This covers only the "binary is absent" half of F-02; the other half
  (a probe that reports healthy on a non-2xx response) is a semantic
  question no static check can answer and is intentionally left to doctrine
  (SKILL.md rule 10).
"""

import sys
import re
import json
from pathlib import Path
from typing import List, Optional


class Issue:
    """Represents a detected issue in the Dockerfile."""

    def __init__(self, line_num: int, severity: str, rule: str, message: str, suggestion: str = ""):
        self.line_num = line_num
        self.severity = severity  # 'error', 'warning', 'info'
        self.rule = rule
        self.message = message
        self.suggestion = suggestion

    def __str__(self):
        icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}[self.severity]
        result = f"{icon} Line {self.line_num} [{self.rule}]: {self.message}"
        if self.suggestion:
            result += f"\n   → {self.suggestion}"
        return result

    def to_dict(self):
        return {
            "line": self.line_num,
            "severity": self.severity,
            "rule": self.rule,
            "message": self.message,
            "suggestion": self.suggestion,
        }


def _join_continuations(lines: list[str]) -> list[tuple[int, str]]:
    """Join backslash-continued lines into logical instructions.
    Returns list of (first_line_number, joined_instruction)."""
    result = []
    current = ""
    start_line = 1

    for i, line in enumerate(lines, 1):
        stripped = line.rstrip()
        if not current:
            start_line = i

        if stripped.endswith("\\"):
            current += stripped[:-1] + " "
        else:
            current += stripped
            if current.strip():
                result.append((start_line, current))
            current = ""

    if current.strip():
        result.append((start_line, current))

    return result


# Suffixes that Docker auto-extracts when ADD copies a LOCAL archive. Docker
# recognises tar plus the gzip/bzip2/xz compressions of it; .zip is NOT in this
# list because Docker does not unpack zip archives.
_LOCAL_ARCHIVE_SUFFIXES = (
    ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz", ".tbz2",
    ".tar.xz", ".txz", ".tar.z",
)


def _is_remote_url(src: str) -> bool:
    """Return True when an ADD source is an http(s) URL rather than a local path."""
    return src.lower().startswith(("http://", "https://"))


def _is_git_ref(src: str) -> bool:
    """Return True when an ADD source is a Git repository reference.

    Git refs are excluded from every DL006 branch: their integrity comes from
    the commit, and BuildKit resolves them itself. Recognised forms are the
    scp-like ``git@host:org/repo.git``, the ``git://`` scheme, and any URL whose
    path ends in ``.git`` (optionally followed by a ``#ref`` fragment).
    """
    lowered = src.lower()
    if lowered.startswith(("git@", "git://")):
        return True
    # Strip the optional "#branch" / "#tag:subdir" fragment before testing the
    # suffix, so https://host/repo.git#v1.0 is still recognised as a git ref.
    return lowered.split("#", 1)[0].endswith(".git")


def _check_add(line_num: int, instruction: str) -> List[Issue]:
    """Evaluate one ADD instruction against DL006.

    The pre-3.0.0 rule was inverted: it exempted ``ADD https://...`` and
    ``ADD *.tar``, so it stayed silent on the one case that genuinely needs
    verification (an unauthenticated remote fetch) while flagging harmless local
    uses. The rule now keys on what Docker actually does with each source form:

    - remote URL without ``--checksum``: warn, nothing verifies the payload;
    - remote URL with ``--checksum``: silent, this is the recommended pattern
      and is strictly better than ``RUN curl | tar`` (which DL017 flags);
    - git reference: silent, integrity comes from the commit;
    - local archive: warn, ADD silently auto-extracts it (a real surprise, and
      one that only applies locally: ADD does NOT extract a remote download);
    - plain local file or directory: warn, COPY is the explicit instruction.

    Parameters
    ----------
    line_num : int
        Line number of the instruction, for the reported issue.
    instruction : str
        The logical ADD instruction, continuations already joined.

    Returns
    -------
    list of Issue
        At most one issue; empty when the ADD is legitimate.
    """
    tokens = instruction.split()[1:]  # drop the ADD keyword itself

    flags = [t for t in tokens if t.startswith("--")]
    operands = [t for t in tokens if not t.startswith("--")]

    has_checksum = any(f.lower().startswith("--checksum=") for f in flags)
    keeps_git_dir = any(f.lower().startswith("--keep-git-dir") for f in flags)

    # The last operand is the destination; everything before it is a source.
    sources = operands[:-1] if len(operands) > 1 else operands
    if not sources:
        return []

    # --keep-git-dir is only meaningful for a git source, so treat its presence
    # as a git ADD even if the URL form is unusual.
    if keeps_git_dir or any(_is_git_ref(s) for s in sources):
        return []

    if any(_is_remote_url(s) for s in sources):
        if has_checksum:
            return []
        return [Issue(
            line_num, "warning", "DL006",
            "ADD downloads a remote artifact without checksum verification",
            "Add a digest: ADD --checksum=sha256:<hash> <url> <dest>"
        )]

    if any(s.lower().endswith(_LOCAL_ARCHIVE_SUFFIXES) for s in sources):
        return [Issue(
            line_num, "warning", "DL006",
            "ADD auto-extracts a local archive (implicit, easy to miss)",
            "Prefer COPY plus an explicit RUN tar -xf, or keep ADD only if the "
            "auto-extraction is intended and documented"
        )]

    return [Issue(
        line_num, "warning", "DL006",
        "Using ADD to copy a local path",
        "Use COPY for local files and directories; keep ADD for remote URLs "
        "with --checksum, git refs, or intentional archive extraction"
    )]


# --- DL036: --chown referencing a user/group not resolvable in this stage ---

_CREATE_ACCOUNT_RE = re.compile(
    r"\b(useradd|adduser|groupadd|addgroup)\b([^&;|]*)",
    re.IGNORECASE,
)
_USER_CREATE_COMMANDS = frozenset({"useradd", "adduser"})
_GROUP_CREATE_COMMANDS = frozenset({"groupadd", "addgroup"})
_CHOWN_RE = re.compile(r"--chown=(\S+)", re.IGNORECASE)

# A handful of accounts commonly baked into a base image, so their absence
# from THIS Dockerfile's own RUN instructions is not evidence they are
# missing. Deliberately short: this analyzer cannot inspect an arbitrary base
# image's /etc/passwd, so anything not on this list falls back to the
# "unresolved" (not "safe") bucket, reported at a lower severity precisely
# because it is a guess.
_WELLKNOWN_ACCOUNTS = frozenset({
    "node", "nobody", "www-data", "postgres", "redis", "nginx", "daemon",
    "nonroot",
})


def _created_accounts(instruction: str) -> List[tuple]:
    """Extract every user/group account created by a RUN instruction.

    Handles a RUN line that chains several commands with ``&&`` (the pattern
    every template in this skill uses: ``groupadd ... && useradd ...``) by
    scanning each ``useradd``/``adduser``/``groupadd``/``addgroup`` invocation
    independently, stopping at the next ``&&``/``;``/``|`` separator so a
    later command's flags are never absorbed into an earlier one's name.

    Parameters
    ----------
    instruction : str
        A logical RUN instruction, continuations already joined.

    Returns
    -------
    list of (str, str)
        Each pair is ``("user", name)`` or ``("group", name)``, one per
        account-creation command found. Both ``useradd``/``groupadd``
        (Debian/RHEL) and ``adduser``/``addgroup`` (BusyBox/Alpine) are
        recognised; in both families the account name is the command's final
        positional argument, which is the convention every template in this
        skill follows.
    """
    accounts = []
    for cmd, rest in _CREATE_ACCOUNT_RE.findall(instruction):
        tokens = rest.split()
        if not tokens:
            continue
        name = tokens[-1]
        kind = "user" if cmd.lower() in _USER_CREATE_COMMANDS else "group"
        accounts.append((kind, name))
    return accounts


def _chown_names_needing_resolution(instruction: str) -> List[tuple]:
    """Extract the (kind, name) pairs from a --chown flag that need name resolution.

    Parameters
    ----------
    instruction : str
        A logical COPY or ADD instruction.

    Returns
    -------
    list of (str, str)
        Each pair is ``("user", name)`` or ``("group", name)`` for a
        ``--chown`` component that names an account. A numeric id (no lookup
        happens for it) or a ``$VAR``/``${VAR}`` reference (not resolvable
        statically, and not resolvable to a wrong answer either) is omitted:
        neither can produce a real finding here.
    """
    match = _CHOWN_RE.search(instruction)
    if not match:
        return []

    parts = match.group(1).split(":", 1)
    kinds = ("user", "group")
    needed = []
    for kind, part in zip(kinds, parts):
        if part and not part.isdigit() and not part.startswith("$"):
            needed.append((kind, part))
    return needed


def _analyze_chown_ordering(logical_lines: list):
    """Pre-scan a whole Dockerfile for DL036: a --chown name that cannot resolve.

    ``--chown`` on COPY/ADD resolves its user/group NAMES (never numeric ids)
    against the CURRENT STAGE's own ``/etc/passwd``/``/etc/group`` at the
    moment the instruction runs during the build; each stage starts its own
    filesystem, so a name created in an earlier stage does not carry over
    either. Tracking therefore resets at every FROM.

    Verified against BuildKit 29.4.0: a name that cannot resolve does NOT
    fail the build. The `--chown` is silently discarded and the files land
    owned by root (0:0), so the container runs its app as an unprivileged
    user over root-owned files, which then fails on first write, at runtime,
    long after the (green) build and the (green) CI check. Nothing else in
    the pipeline can catch this: not the build, not `docker build --check`.
    This static check is the only net.

    Two independent findings are computed per --chown-bearing line:

    - "late": the name IS created in this stage, but only after this line.
      Near-zero false positives: this is precisely the F-01 ordering bug
      this rule exists to catch.
    - "unresolved": the name is not created anywhere in this stage, and is
      not one of a few well-known base-image built-in accounts. This is a
      heuristic (the account may legitimately ship in the base image, which
      this function cannot inspect), so the caller reports it at a lower
      severity than "late".

    Parameters
    ----------
    logical_lines : list of (int, str)
        Output of ``_join_continuations``: (line_number, instruction) pairs.

    Returns
    -------
    tuple of (dict, dict)
        ``(late, unresolved)``, each mapping a COPY/ADD line number to the
        list of offending names found on that line.
    """
    stage_idx = -1
    # Per stage: ordered (line_num, kind, name) creation events.
    creations_by_stage = {}
    # Per stage: (line_num, [(kind, name), ...]) needing resolution.
    chowns_by_stage = {}

    for line_num, instruction in logical_lines:
        stripped = instruction.strip()
        if not stripped or stripped.startswith("#"):
            continue
        upper = stripped.upper()

        if upper.startswith("FROM "):
            stage_idx += 1
            creations_by_stage.setdefault(stage_idx, [])
            chowns_by_stage.setdefault(stage_idx, [])
            continue

        if upper.startswith("RUN "):
            for kind, name in _created_accounts(stripped):
                creations_by_stage.setdefault(stage_idx, []).append((line_num, kind, name))
            continue

        if upper.startswith("COPY ") or upper.startswith("ADD "):
            needed = _chown_names_needing_resolution(stripped)
            if needed:
                chowns_by_stage.setdefault(stage_idx, []).append((line_num, needed))

    late = {}
    unresolved = {}

    for stage_idx, chowns in chowns_by_stage.items():
        creations = creations_by_stage.get(stage_idx, [])
        for line_num, needed in chowns:
            for kind, name in needed:
                created_at = [ln for ln, k, n in creations if k == kind and n == name]
                if created_at:
                    if min(created_at) > line_num:
                        late.setdefault(line_num, []).append(name)
                    # else: created earlier in the stage, resolves fine.
                elif name.lower() not in _WELLKNOWN_ACCOUNTS:
                    unresolved.setdefault(line_num, []).append(name)

    return late, unresolved


def _join_names(names: list) -> str:
    """Format a list of account names as a readable quoted phrase for a message.

    Parameters
    ----------
    names : list of str
        Account names to format.

    Returns
    -------
    str
        E.g. ``"'app'"``, ``"'app' and 'appgrp'"``, or ``"'a', 'b', and 'c'"``.
    """
    quoted = [f"'{n}'" for n in names]
    if len(quoted) == 1:
        return quoted[0]
    if len(quoted) == 2:
        return f"{quoted[0]} and {quoted[1]}"
    return ", ".join(quoted[:-1]) + f", and {quoted[-1]}"


# --- DL037: :latest / untagged registry ref in COPY --from= ---

_COPY_FROM_RE = re.compile(r"--from=(\S+)", re.IGNORECASE)


def _check_copy_from(line_num: int, instruction: str, stage_aliases: set) -> List[Issue]:
    """Evaluate one COPY instruction's --from= flag against DL037.

    ``COPY --from=`` accepts either a build stage (a numeric index or an
    ``AS`` alias) or a registry image reference; only the latter is a base
    image pull and inherits the FROM pinning doctrine (DL002/DL003). A stage
    reference is never flagged: BuildKit resolves it from the build graph,
    and it was never fetched from a registry to begin with.

    This mirrors DL002 for an explicit ``:latest`` tag (error, exactly the
    same doctrine violation as ``FROM x:latest``) and additionally applies
    the DL003 doctrine to an untagged reference (warning, implies ``:latest``
    by the same registry-resolution rule): both bugs shipped in v2.0.0
    (``ghcr.io/astral-sh/uv:latest``, ``composer:latest``), and DL002 alone
    cannot see either because it only inspects ``FROM``.

    Parameters
    ----------
    line_num : int
        Line number of the instruction, for the reported issue.
    instruction : str
        The logical COPY instruction, continuations already joined.
    stage_aliases : set of str
        Lowercased stage names declared by an earlier ``FROM ... AS <name>``,
        shared with the DL003 check so a stage reference is recognised the
        same way in both rules.

    Returns
    -------
    list of Issue
        At most one issue; empty when --from= is absent, numeric, a
        variable, a stage reference, or a pinned registry reference.
    """
    match = _COPY_FROM_RE.search(instruction)
    if not match:
        return []

    ref = match.group(1)

    # A numbered stage ("--from=0"), a variable ("--from=$BUILD_STAGE"), or a
    # declared stage alias ("--from=builder") are all intra-build references,
    # never a registry pull.
    if ref.isdigit() or ref.startswith("$") or ref.lower() in stage_aliases:
        return []

    # Judge the tag on the reference with any digest suffix removed: a digest
    # makes the pull immutable regardless of what the tag says, but the tag
    # is still misleading documentation, exactly as DL002 treats FROM.
    ref_without_digest = ref.split("@", 1)[0]

    if ref_without_digest.lower().endswith(":latest"):
        return [Issue(
            line_num, "error", "DL037",
            f"COPY --from={ref} pins :latest on a registry image",
            "Pin to a specific version, e.g. --from=ghcr.io/astral-sh/uv:0.11.29"
        )]

    if ":" not in ref_without_digest:
        return [Issue(
            line_num, "warning", "DL037",
            f"COPY --from={ref} is an untagged registry image (implies :latest)",
            "Pin to a specific version, e.g. --from=composer:2"
        )]

    return []


# --- DL038: HEALTHCHECK probe binary the image may not ship ---

def _from_image_ref(instruction: str) -> Optional[str]:
    """Extract the image reference token from a FROM instruction, skipping flags.

    The DL002/DL003 regex requires no flag prefix and simply fails to match a
    platform-flagged FROM (``FROM --platform=$BUILDPLATFORM node:22-alpine``),
    which is fine for those two rules (they decline rather than guess) but
    would leave DL038 blind to a very common multi-arch pattern. This helper
    discards every leading ``--flag`` token first, so the image reference is
    still found regardless of what precedes it.

    Parameters
    ----------
    instruction : str
        A logical FROM instruction, continuations already joined.

    Returns
    -------
    str or None
        The image reference token (may be a stage alias reference, a
        variable, or a real registry image; the caller decides what to do
        with each), or None if the instruction has no operand at all.
    """
    tokens = instruction.split()[1:]  # drop the FROM keyword itself
    while tokens and tokens[0].startswith("--"):
        tokens.pop(0)
    return tokens[0] if tokens else None


def _check_healthcheck_binary(
    line_num: int,
    instruction: str,
    base_image: Optional[str],
    installs_curl: bool,
    installs_wget: bool,
) -> List[Issue]:
    """Evaluate one HEALTHCHECK instruction against DL038.

    Verified empirically against three real images on BuildKit 29.4.0:
    neither ``curl`` nor ``wget`` ships on ``python:3.11-slim``,
    ``python:3.12-slim``, or ``debian:stable-slim``. This is F-02: the
    skill's own rule 10 example (``HEALTHCHECK CMD wget ...`` on a slim
    base) could never have worked. Alpine is the one well-established
    exception: BusyBox provides ``wget`` (never ``curl``) on every
    alpine-family image with no install step required.

    Scope is deliberately narrow to keep the false-positive rate low:

    - ``curl`` is flagged whenever it is not installed in this stage,
      regardless of base image, because the data above shows it ships on
      neither family tested, and no base image in this skill's templates is
      curl-specific.
    - ``wget`` is flagged only when the base image is confidently identified
      as NOT alpine-family and it is not installed in this stage. When the
      base image cannot be identified at all (a bare ``ARG``/variable
      reference) or is an unrecognised custom/private registry ref this
      function has no way to rule out BusyBox, so it stays silent rather
      than guess: a wrong guess here is exactly the noisy, ignorable finding
      this rule must avoid.
    - An interpreter-based probe (``python -c ...``, ``node -e ...``, an exec
      form calling the app's own binary) matches neither token and is always
      silent — the pattern this skill's own templates now recommend.

    The other half of F-02 (a probe that passes on a non-2xx response, e.g.
    ``requests.get()`` not raising on HTTP 500) is a semantic question this
    static check cannot answer and is intentionally out of scope; it is
    covered by doctrine (SKILL.md rule 10), not by this rule.

    Parameters
    ----------
    line_num : int
        Line number of the instruction, for the reported issue.
    instruction : str
        The logical HEALTHCHECK instruction, continuations already joined.
    base_image : str or None
        Lowercased image reference of the current stage, or None if it could
        not be determined.
    installs_curl : bool
        Whether an apt-get/apk install in this stage already installs curl.
    installs_wget : bool
        Whether an apt-get/apk install in this stage already installs wget.

    Returns
    -------
    list of Issue
        Zero, one, or two issues; curl and wget are independent checks.
    """
    issues = []

    if re.search(r"\bcurl\b", instruction) and not installs_curl:
        issues.append(Issue(
            line_num, "warning", "DL038",
            "HEALTHCHECK calls curl, which this stage never installs",
            "curl ships on neither Debian/Python slim nor Alpine images by "
            "default (verified on python:3.11-slim, python:3.12-slim, "
            "debian:stable-slim). Install it explicitly, or probe with a "
            "binary the image already has (an interpreter's own HTTP call, "
            "or busybox wget on an alpine-family base)"
        ))

    if (
        re.search(r"\bwget\b", instruction)
        and not installs_wget
        and base_image is not None
        and "$" not in base_image
        and "alpine" not in base_image
    ):
        issues.append(Issue(
            line_num, "warning", "DL038",
            "HEALTHCHECK calls wget, which this stage never installs and "
            "the base image is not alpine-family",
            "wget ships via BusyBox on alpine-family images only. On this "
            "base, install it explicitly or probe with a binary the image "
            "already has (e.g. an interpreter's own HTTP call)"
        ))

    return issues


def analyze_dockerfile(content: str) -> List[Issue]:
    """Analyze Dockerfile content and return list of issues."""
    issues = []
    lines = content.split("\n")
    logical_lines = _join_continuations(lines)

    has_user = False
    has_healthcheck = False
    has_label = False
    has_expose = False
    from_count = 0
    last_from_line = 0
    uses_apt = False
    has_apt_cache_config = False
    has_copy_chown_issue = False
    # Stage names declared so far by "FROM ... AS <name>", lowercased. A stage
    # can only be referenced after it is declared, so a single forward pass is
    # enough to tell "FROM builder" (an intra-build stage reference) apart from
    # "FROM some-registry-image" (a real image that DL002/DL003 should judge).
    stage_aliases: set[str] = set()
    # DL038 state, reset at every FROM: the current stage's base image (for
    # the alpine-family check) and whether this stage has already installed
    # curl/wget itself. Unlike stage_aliases, these must NOT survive past a
    # FROM: a new stage starts its own filesystem from scratch.
    stage_base_image: Optional[str] = None
    stage_installs_curl = False
    stage_installs_wget = False

    # Pre-scan for DL036: needs to see whether a --chown name is created
    # LATER in its stage, which the single forward pass below cannot know
    # about a line before reaching it.
    late_chowns, unresolved_chowns = _analyze_chown_ordering(logical_lines)

    # Check for syntax directive
    first_non_empty = next((l for l in lines if l.strip()), "")
    if not first_non_empty.strip().startswith("# syntax="):
        issues.append(Issue(
            1, "warning", "DL001",
            "Missing BuildKit syntax directive",
            "Add as first line: # syntax=docker/dockerfile:1"
        ))

    for line_num, instruction in logical_lines:
        stripped = instruction.strip()

        # Skip comments and empty lines
        if not stripped or stripped.startswith("#"):
            continue

        upper = stripped.upper()

        # --- FROM checks ---
        if upper.startswith("FROM "):
            from_count += 1
            last_from_line = line_num

            # Check for :latest tag
            #
            # No stage-alias guard needed here: an AS <name> alias can never
            # contain a colon (Docker only allows word characters, '.', '_',
            # '-' in a stage name), so this regex cannot match a bare stage
            # reference like "FROM builder" regardless of what the stage was
            # named. Confirmed: unlike DL003 below, DL002 has no false-positive
            # to fix.
            if re.search(r"FROM\s+[\w./-]+:latest", stripped, re.IGNORECASE):
                issues.append(Issue(
                    line_num, "error", "DL002",
                    "Using :latest tag on base image",
                    "Pin to specific version (e.g., python:3.12-slim)"
                ))

            # Check for untagged image (implies :latest)
            from_match = re.match(r"FROM\s+([\w./-]+)(\s|$)", stripped)
            if from_match:
                image = from_match.group(1)
                # A bare "FROM <name>" is only a real untagged registry image
                # when <name> was NOT declared as an earlier build stage via
                # "AS <name>". "FROM builder" referencing a previous
                # "FROM ... AS builder" is legal multi-stage syntax, not a
                # missing tag: stages have no registry tag to begin with.
                is_stage_ref = image.lower() in stage_aliases
                if not is_stage_ref and ":" not in image and "@" not in image and image not in ("scratch",):
                    issues.append(Issue(
                        line_num, "warning", "DL003",
                        f"Untagged base image '{image}' (implies :latest)",
                        "Pin to specific version"
                    ))

            # Register this stage's own alias (if any) so that LATER FROM
            # lines can recognize a reference to it. Must run after the checks
            # above: a stage can only be referenced once declared, never on
            # its own declaring line.
            alias_match = re.search(r"\sAS\s+([\w.-]+)\s*$", stripped, re.IGNORECASE)
            if alias_match:
                stage_aliases.add(alias_match.group(1).lower())

            # Reset DL038 state: a new stage starts its own filesystem, so
            # neither the previous stage's base image nor what it installed
            # carries over.
            image_ref = _from_image_ref(stripped)
            stage_base_image = image_ref.lower() if image_ref else None
            stage_installs_curl = False
            stage_installs_wget = False

        # --- ADD checks (DL006) ---
        if upper.startswith("ADD "):
            issues.extend(_check_add(line_num, stripped))

        # --- COPY checks (DL037) ---
        if upper.startswith("COPY "):
            issues.extend(_check_copy_from(line_num, stripped, stage_aliases))

        # --- COPY/ADD checks (DL036) ---
        if upper.startswith("COPY ") or upper.startswith("ADD "):
            late_names = late_chowns.get(line_num)
            if late_names:
                issues.append(Issue(
                    line_num, "error", "DL036",
                    f"--chown references {_join_names(late_names)}, created "
                    "later in this same stage",
                    "Move the RUN that creates the user (useradd/adduser) "
                    "and group (groupadd/addgroup) above this line. "
                    "Verified on BuildKit 29.4.0: this does NOT fail the "
                    "build, --chown is silently discarded and the files "
                    "land owned by root (0:0), then the app fails at "
                    "runtime on its first write, not at build time."
                ))
            unresolved_names = unresolved_chowns.get(line_num)
            if unresolved_names:
                issues.append(Issue(
                    line_num, "info", "DL036",
                    f"--chown references {_join_names(unresolved_names)}, "
                    "not created anywhere in this stage",
                    "If this account ships in the base image this is fine; "
                    "otherwise create it with useradd/adduser (and "
                    "groupadd/addgroup for the group) before this line, "
                    "since an unresolved --chown is silently discarded "
                    "rather than failing the build"
                ))

        # --- RUN checks ---
        if upper.startswith("RUN "):
            # apt-get tracking
            if "apt-get" in stripped:
                uses_apt = True

            # DL038: track curl/wget installed by THIS stage, so the
            # HEALTHCHECK check below knows what it can rely on.
            if "apt-get install" in stripped or "apk add" in stripped:
                if re.search(r"\bcurl\b", stripped):
                    stage_installs_curl = True
                if re.search(r"\bwget\b", stripped):
                    stage_installs_wget = True

            # apt-get install without cleanup (only if no cache mount)
            if "apt-get install" in stripped and "--mount=type=cache" not in stripped:
                if "rm -rf /var/lib/apt/lists" not in stripped:
                    issues.append(Issue(
                        line_num, "warning", "DL007",
                        "apt-get install without cleanup or cache mount",
                        "Use --mount=type=cache or add && rm -rf /var/lib/apt/lists/*"
                    ))

            # Missing cache mounts for package managers
            pkg_managers = [
                ("pip install", "/root/.cache/pip", "DL008"),
                ("pip3 install", "/root/.cache/pip", "DL008"),
                ("npm install", "/root/.npm", "DL009"),
                ("npm ci", "/root/.npm", "DL009"),
                ("yarn install", "/root/.yarn", "DL010"),
                ("yarn add", "/root/.yarn", "DL010"),
                ("go mod download", "/go/pkg/mod", "DL011"),
                ("go build", "/root/.cache/go-build", "DL011"),
                ("cargo build", "/usr/local/cargo/registry", "DL012"),
                ("composer install", "/tmp/cache", "DL013"),
                ("mvn ", "/root/.m2", "DL014"),
                ("gradle ", "/root/.gradle", "DL015"),
            ]

            for cmd, cache_target, rule in pkg_managers:
                if cmd in stripped and "--mount=type=cache" not in stripped:
                    issues.append(Issue(
                        line_num, "info", rule,
                        f"{cmd} without cache mount",
                        f"Add: --mount=type=cache,target={cache_target}"
                    ))

            # RUN cd instead of WORKDIR
            if re.match(r"RUN\s+cd\s+", stripped):
                issues.append(Issue(
                    line_num, "warning", "DL016",
                    "Using RUN cd instead of WORKDIR",
                    "Use: WORKDIR /path"
                ))

            # curl | sh anti-pattern
            if re.search(r"curl.*\|\s*(ba)?sh", stripped):
                issues.append(Issue(
                    line_num, "warning", "DL017",
                    "Piping curl to shell (curl | sh)",
                    "Download first, verify checksum, then execute for security"
                ))

            # apt-get upgrade
            if "apt-get upgrade" in stripped or "apt-get dist-upgrade" in stripped:
                issues.append(Issue(
                    line_num, "warning", "DL018",
                    "Running apt-get upgrade in Dockerfile",
                    "Use a newer base image instead of upgrading inside the container"
                ))

            # apt-get without --no-install-recommends
            if "apt-get install" in stripped and "--no-install-recommends" not in stripped:
                issues.append(Issue(
                    line_num, "info", "DL019",
                    "apt-get install without --no-install-recommends",
                    "Add --no-install-recommends to reduce image size"
                ))

            # Check for apt cache config
            if "docker-clean" in stripped or "Keep-Downloaded-Packages" in stripped:
                has_apt_cache_config = True

        # --- ARG/ENV secret checks ---
        if re.search(r"(ARG|ENV)\s+(.*?(PASSWORD|SECRET|TOKEN|KEY|CREDENTIAL|API_KEY))", stripped, re.IGNORECASE):
            # Exclude common non-secret patterns
            if not re.search(r"(GPG_KEY|KEYRING|KEY_FILE|KEYBOARD|KEYMAP)", stripped, re.IGNORECASE):
                issues.append(Issue(
                    line_num, "error", "DL020",
                    "Potential secret in ARG/ENV",
                    "Use: RUN --mount=type=secret,id=mysecret"
                ))

        # --- USER checks ---
        if upper.startswith("USER "):
            # Compare the resolved user exactly, not by substring: "root" was
            # a substring match, so "USER nonroot" (the canonical account in
            # gcr.io/distroless/*:nonroot images) was misreported as root, and
            # -- since it landed in this branch -- has_user was never set,
            # so DL030 then ALSO fired "No non-root USER defined" on a file
            # that has one. Only the user part before an optional ":group" is
            # compared; "0" is included because UID 0 is root regardless of
            # name, and was previously missed entirely.
            user_name = stripped.split()[-1].split(":", 1)[0].lower()
            if user_name in ("root", "0"):
                issues.append(Issue(
                    line_num, "warning", "DL021",
                    "Explicitly setting USER root",
                    "Create and use a non-root user for security"
                ))
            else:
                has_user = True

        # --- UID/GID checks ---
        uid_match = re.search(r"(useradd|adduser).*?-u\s+(\d+)", stripped)
        if uid_match:
            uid = int(uid_match.group(2))
            if uid < 10000:
                issues.append(Issue(
                    line_num, "warning", "DL022",
                    f"User created with UID {uid} (< 10000)",
                    "Use UID >10000 to avoid conflicts with host system users"
                ))

        gid_match = re.search(r"(groupadd|addgroup).*?-g\s+(\d+)", stripped)
        if gid_match:
            gid = int(gid_match.group(2))
            if gid < 10000:
                issues.append(Issue(
                    line_num, "warning", "DL023",
                    f"Group created with GID {gid} (< 10000)",
                    "Use GID >10000 to avoid conflicts with host system users"
                ))

        # --- COPY then chown anti-pattern ---
        if upper.startswith("COPY ") and "--chown" not in stripped:
            # Check if next logical instruction is RUN chown
            idx = next((j for j, (_, inst) in enumerate(logical_lines)
                        if inst.strip().startswith(f"RUN ") and "chown" in inst
                        and logical_lines[j-1][1].strip() == stripped), None)
            if idx is not None:
                has_copy_chown_issue = True

        # --- HEALTHCHECK ---
        if upper.startswith("HEALTHCHECK "):
            has_healthcheck = True
            issues.extend(_check_healthcheck_binary(
                line_num, stripped, stage_base_image,
                stage_installs_curl, stage_installs_wget
            ))

        # --- LABEL ---
        if upper.startswith("LABEL "):
            has_label = True

        # --- EXPOSE ---
        if upper.startswith("EXPOSE "):
            has_expose = True

        # --- WORKDIR without absolute path ---
        if upper.startswith("WORKDIR "):
            path = stripped.split(None, 1)[1] if len(stripped.split(None, 1)) > 1 else ""
            if path and not path.startswith("/") and not path.startswith("$"):
                issues.append(Issue(
                    line_num, "warning", "DL024",
                    f"WORKDIR uses relative path: {path}",
                    "Use absolute paths for WORKDIR"
                ))

        # --- ENTRYPOINT/CMD exec form check ---
        for directive in ("ENTRYPOINT", "CMD"):
            if upper.startswith(f"{directive} "):
                value = stripped[len(directive):].strip()
                if value and not value.startswith("["):
                    issues.append(Issue(
                        line_num, "warning", "DL025",
                        f"{directive} uses shell form, so the application never receives SIGTERM",
                        "Shell form runs the command under /bin/sh -c, which makes the shell "
                        "PID 1: it does not forward signals, so docker stop waits the full "
                        "grace period and then SIGKILLs. Use exec form "
                        f"({directive} [\"executable\", \"arg1\"]) to make the application PID 1 "
                        "and let it handle signals and shut down cleanly."
                    ))

    # --- Global checks ---

    # No non-root USER defined
    if not has_user:
        issues.append(Issue(
            len(lines), "warning", "DL030",
            "No non-root USER defined",
            "Add: RUN groupadd -r -g 10001 app && useradd -r -u 10001 -g app app && USER app"
        ))

    # No HEALTHCHECK (only if EXPOSE is present - likely a service)
    if not has_healthcheck and has_expose:
        issues.append(Issue(
            len(lines), "info", "DL031",
            "Service exposes ports but has no HEALTHCHECK",
            "Add HEALTHCHECK for container orchestration and monitoring"
        ))

    # No LABEL
    if not has_label:
        issues.append(Issue(
            len(lines), "info", "DL032",
            "No LABEL defined",
            "Add OCI labels: org.opencontainers.image.source, .description, .version"
        ))

    # Uses apt but no cache config
    if uses_apt and not has_apt_cache_config:
        # Check if cache mounts are used
        has_apt_cache_mount = any("--mount=type=cache" in inst and "apt" in inst
                                  for _, inst in logical_lines)
        if has_apt_cache_mount:
            issues.append(Issue(
                1, "warning", "DL033",
                "APT cache mount used without configuring APT to keep packages",
                "Add before apt operations: RUN rm -f /etc/apt/apt.conf.d/docker-clean; "
                "echo 'Binary::apt::APT::Keep-Downloaded-Packages \"true\";' > /etc/apt/apt.conf.d/keep-cache"
            ))

    # COPY then chown pattern
    if has_copy_chown_issue:
        issues.append(Issue(
            0, "info", "DL034",
            "COPY followed by RUN chown detected",
            "Use COPY --chown=user:group instead to avoid doubling the layer size"
        ))

    return issues


def main():
    json_output = "--json" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--json"]

    if len(args) != 1:
        print("Usage: analyze_dockerfile.py <path_to_Dockerfile> [--json]")
        sys.exit(1)

    dockerfile_path = Path(args[0])

    if not dockerfile_path.exists():
        print(f"Error: File not found: {dockerfile_path}")
        sys.exit(1)

    content = dockerfile_path.read_text()
    issues = analyze_dockerfile(content)

    if json_output:
        result = {
            "file": str(dockerfile_path),
            "issues": [i.to_dict() for i in issues],
            "summary": {
                "errors": len([i for i in issues if i.severity == "error"]),
                "warnings": len([i for i in issues if i.severity == "warning"]),
                "info": len([i for i in issues if i.severity == "info"]),
            }
        }
        print(json.dumps(result, indent=2))
        sys.exit(1 if result["summary"]["errors"] else 0)

    if not issues:
        print("✅ No issues found! Dockerfile looks good.")
        return

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    infos = [i for i in issues if i.severity == "info"]

    print(f"\n📋 Analysis of {dockerfile_path}\n")

    if errors:
        print("🔴 Errors:")
        for issue in errors:
            print(f"  {issue}\n")

    if warnings:
        print("🟡 Warnings:")
        for issue in warnings:
            print(f"  {issue}\n")

    if infos:
        print("🔵 Suggestions:")
        for issue in infos:
            print(f"  {issue}\n")

    print(f"\nTotal: {len(errors)} errors, {len(warnings)} warnings, {len(infos)} suggestions")

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
