"""Semantic lint tests (AM001..AM004) for ``scripts/_lint_rules.py``.

Every rule gets both a firing case and the near-miss it must stay quiet
on, because the whole value of this module is that it does not cry wolf
on rules a human wrote deliberately. Known limits are pinned by tests of
their own, so a limit cannot quietly become a false positive later. The
shared plumbing (sys.path into ``scripts/``) comes from ``conftest.py``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

import _lint_rules  # noqa: E402  (path injected via conftest)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _proposal(**sections: list[Any]) -> dict[str, Any]:
    """Build a minimal proposal carrying only the given autoMode sections."""

    return {"autoMode": dict(sections)}


def _rules(findings: list[_lint_rules.Finding]) -> list[str]:
    """Return the rule ids of ``findings``, in order."""

    return [f.rule for f in findings]


def _only(
    findings: list[_lint_rules.Finding], rule: str
) -> list[_lint_rules.Finding]:
    """Filter ``findings`` down to a single rule id."""

    return [f for f in findings if f.rule == rule]


def _project(tmp_path: Path, files: dict[str, str]) -> Path:
    """Materialize a throwaway project tree and return its root."""

    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def _git_project(tmp_path: Path, tracked: dict[str, str], **untracked: str) -> Path:
    """Build a git work tree whose ``tracked`` files sit in the index.

    Files passed as keyword arguments are written but never added, so a
    test can prove the scan used ``git ls-files`` rather than the walk.
    """

    root = _project(tmp_path, tracked)
    subprocess.run(
        ["git", "init", "-q"], cwd=root, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "add", "-A"], cwd=root, check=True, capture_output=True
    )
    for name, content in untracked.items():
        (root / name).write_text(content, encoding="utf-8")
    return root


NFT_RULE = "Never run nft flush ruleset on any host"
NFT_LITERAL = "nft flush ruleset\n"


def _nft_findings(
    root: Path | None,
) -> list[_lint_rules.Finding]:
    """Lint the canonical AM003 rule against ``root``."""

    return _only(
        _lint_rules.lint_proposal(
            _proposal(hard_deny=[NFT_RULE]), project_root=root
        ),
        "AM003",
    )


# ---------------------------------------------------------------------------
# AM001: conditional clause in hard_deny
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,connective",
    [
        ("Never force-push to main unless the release lead approves", "unless"),
        ("Never delete a namespace except the ephemeral ones", "except"),
        ("Do not run terraform apply provided that a plan exists", "provided that"),
        ("Do not touch prod as long as the freeze holds", "as long as"),
        ("Do not touch prod so long as the freeze holds", "so long as"),
        ("Never drop a database only if a backup is missing", "only if"),
        ("Never deploy without an approved change ticket", "without"),
        ("Never rm -rf a mount if it is not a scratch dir", "if"),
        ("Never restart a node when traffic is draining", "when"),
        ("Never write to /etc, provided a fallback exists", "provided"),
        # Paraphrases of a connective already handled. "with the
        # exception of" is the one that matters most: \bexcept\b cannot
        # match inside "exception", so the most natural rewording of a
        # caught phrase used to slip through untouched.
        (
            "Never delete a namespace with the exception of ephemeral ones",
            "with the exception of",
        ),
        ("Never delete anything other than scratch files", "other than"),
        ("Never touch prod apart from a break-glass event", "apart from"),
        ("Never drop a table save for the temp ones", "save for"),
        ("Never deploy barring an approved change ticket", "barring"),
        ("Never run kubectl outside the staging context", "outside"),
        ("Never restart in cases where the operator insists", "in cases where"),
    ],
)
def test_am001_fires_on_each_conditional_connective(text: str, connective: str):
    """Every documented connective is caught and named in ``detail``."""

    findings = _only(
        _lint_rules.lint_proposal(_proposal(hard_deny=[text])), "AM001"
    )
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "error"
    assert finding.section == "hard_deny"
    assert finding.index == 0
    assert finding.detail == f"matched connective: {connective}"
    assert connective in finding.message


@pytest.mark.parametrize(
    "text",
    [
        "Never restart a node even when traffic is drained",
        "Never restart a node even if the operator insists",
        "Never restart a node regardless of when the window opens",
        "Never force-push to main, whenever the branch is protected",
        "Never delete a backup without exception",
        "Never delete a backup under no circumstances",
        "Never delete a backup, no matter when the request arrives",
        "Never delete a backup no matter if the request is urgent",
        "Never delete a backup no matter whether it is stale",
        "Never delete a backup, including when the operator insists",
        "Never delete a backup, including if a ticket exists",
    ],
)
def test_am001_stays_quiet_on_strengthening_phrases(text: str):
    """Phrases that widen a hard_deny must not read as a carve-out."""

    findings = _lint_rules.lint_proposal(_proposal(hard_deny=[text]))
    assert _only(findings, "AM001") == []


@pytest.mark.parametrize(
    "text,connective",
    [
        (
            "Never run the migration in step seven unless the DBA approves",
            "unless",
        ),
        ("Never keep more than eleven if a rotation is active", "if"),
        ("Never deploy to eleven regions when a freeze is active", "when"),
    ],
)
def test_am001_prefix_suppression_respects_word_boundaries(
    text: str, connective: str
):
    """A word merely ending in "even" cannot swallow the connective.

    Without a word boundary the "even " suppression fires on "seven ",
    "eleven ", and every other word with those letters at the end, and
    the rule silently misses a live carve-out.
    """

    findings = _only(
        _lint_rules.lint_proposal(_proposal(hard_deny=[text])), "AM001"
    )
    assert len(findings) == 1
    assert findings[0].detail == f"matched connective: {connective}"


def test_am001_stays_quiet_on_a_consequence_clause():
    """"otherwise" states a consequence, not an exception.

    Firing here would advise the author to move a correct hard_deny down
    to soft_deny, which is a security downgrade produced by a lint rule.
    """

    proposal = _proposal(
        hard_deny=["Never disable audit logging, otherwise we lose the trail"]
    )
    assert _only(_lint_rules.lint_proposal(proposal), "AM001") == []


@pytest.mark.parametrize(
    "text",
    [
        "Never delete a namespace that is not labelled ephemeral",
        "Never force-push to a branch not marked as scratch",
    ],
)
def test_am001_known_limit_conditions_without_a_connective(text: str):
    """A relative clause or a participle carries no connective.

    This pins a documented limit rather than a defect: catching these
    needs a parser, and the heuristics that would approximate one
    produce false positives whose remedy is "weaken your hard_deny".
    """

    assert _only(_lint_rules.lint_proposal(_proposal(hard_deny=[text])), "AM001") == []


def test_am001_ignores_conditionals_outside_hard_deny():
    """soft_deny and allow are overridable, so conditions are legitimate."""

    proposal = _proposal(
        soft_deny=["Avoid deleting a namespace unless it is ephemeral"],
        allow=["Read any file unless it holds a secret"],
    )
    assert _only(_lint_rules.lint_proposal(proposal), "AM001") == []


def test_am001_reports_first_connective_once_per_entry():
    """A rule with several conditions yields one finding, not one per word."""

    text = "Never deploy unless approved, and never restart when draining"
    findings = _only(
        _lint_rules.lint_proposal(_proposal(hard_deny=[text])), "AM001"
    )
    assert len(findings) == 1
    assert findings[0].detail == "matched connective: unless"


def test_am001_suppression_is_per_match_not_wholesale():
    """One absolute phrase does not deafen the rest of the sentence."""

    text = (
        "Never delete a backup without exception, unless the retention "
        "lead approves"
    )
    findings = _only(
        _lint_rules.lint_proposal(_proposal(hard_deny=[text])), "AM001"
    )
    assert len(findings) == 1
    assert findings[0].detail == "matched connective: unless"


# ---------------------------------------------------------------------------
# AM002: allow shadows soft_deny
# ---------------------------------------------------------------------------


def test_am002_fires_on_a_shared_salient_token():
    """A shared command token pairs the two rules for review."""

    proposal = _proposal(
        allow=["Run kubectl against the staging context freely"],
        soft_deny=["Avoid kubectl writes outside a reviewed manifest"],
    )
    findings = _only(_lint_rules.lint_proposal(proposal), "AM002")
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "warn"
    assert finding.section == "soft_deny"
    assert finding.index == 0
    assert "kubectl" in finding.detail
    assert "allow[0]" in finding.detail


def test_am002_message_prompts_rather_than_asserts():
    """The finding asks for confirmation; it does not declare a verdict.

    At this rule's precision an assertion that the soft_deny "will not
    be enforced" is wrong often enough to cost trust in the whole block.
    """

    proposal = _proposal(
        allow=["Run kubectl against the staging context freely"],
        soft_deny=["Avoid kubectl writes outside a reviewed manifest"],
    )
    message = _only(_lint_rules.lint_proposal(proposal), "AM002")[0].message
    assert "confirm" in message
    assert "will not be enforced" not in message


def test_am002_fires_on_a_shared_quoted_span():
    """Quoted spans are salient whatever they contain."""

    proposal = _proposal(
        allow=["Running `git push --force-with-lease` is fine on a topic branch"],
        soft_deny=["Think twice before `git push --force-with-lease`"],
    )
    findings = _only(_lint_rules.lint_proposal(proposal), "AM002")
    assert len(findings) == 1
    assert "git push --force-with-lease" in findings[0].detail


def test_am002_fires_on_a_shared_glob():
    """A branch glob is a target both sides can name."""

    proposal = _proposal(
        allow=["Allow git push to release/* branches"],
        soft_deny=["Avoid git push --force on release/* branches"],
    )
    findings = _only(_lint_rules.lint_proposal(proposal), "AM002")
    assert len(findings) == 1
    assert "release/*" in findings[0].detail


def test_am002_ignores_the_defaults_sentinel():
    """``$defaults`` is a sentinel, never a shared target."""

    proposal = _proposal(allow=["$defaults"], soft_deny=["$defaults"])
    assert _lint_rules.lint_proposal(proposal) == []


def test_am002_ignores_ordinary_english_overlap():
    """Plain prose words must not pair two unrelated rules."""

    proposal = _proposal(
        allow=["The agent may read the release notes when asked"],
        soft_deny=["The agent should not read the mail when asked"],
    )
    assert _only(_lint_rules.lint_proposal(proposal), "AM002") == []


def test_am002_known_limit_bare_noun_target():
    """A target named by a bare noun is a documented miss.

    Pairing on ordinary nouns would match nearly every rule against
    nearly every other, so ``staging`` alone does not pair these two.
    """

    proposal = _proposal(
        allow=["Read anything in the staging namespace"],
        soft_deny=["Do not write to the staging namespace"],
    )
    assert _only(_lint_rules.lint_proposal(proposal), "AM002") == []


def test_am002_suppresses_the_read_write_carve_out():
    """Allow the reads, soft_deny the writes: that is the correct idiom.

    Both rules name the same tool, which is a token collision and not a
    conflict. Firing here would report every well-formed config.
    """

    proposal = _proposal(
        allow=[
            "Run kubectl get and kubectl describe anywhere",
            "Run helm list on any release",
            "Run git log freely",
            "Run terraform plan on any workspace",
        ],
        soft_deny=[
            "Avoid kubectl apply outside a reviewed manifest",
            "Avoid helm upgrade without a diff",
            "Avoid git push to a shared branch",
            "Avoid terraform apply without approval",
        ],
    )
    assert _only(_lint_rules.lint_proposal(proposal), "AM002") == []


@pytest.mark.parametrize(
    "allow_rule",
    [
        "Run kubectl get/describe against any context",
        "Run kubectl get against any context",
        "Run kubectl get, kubectl describe against any context",
        "Run kubectl get and kubectl describe against any context",
    ],
)
def test_am002_suppression_covers_every_subcommand_list_shape(allow_rule: str):
    """Slash, comma, "and", or a single verb: all name read-only work.

    The slash form was the hole: requiring the whole following token to
    be alphabetic made "get/describe" name no subcommand at all, so the
    suppression never ran and the false positive stood.
    """

    proposal = _proposal(
        allow=[allow_rule],
        soft_deny=["Avoid kubectl apply without a reviewed manifest"],
    )
    assert _only(_lint_rules.lint_proposal(proposal), "AM002") == []


def test_am002_known_limit_subcommands_described_not_named():
    """A rule that describes its subcommands still pairs with its soft_deny.

    The carve-out is recognised by position, so an adjective where a
    subcommand should be leaves the pair undecidable. This pins the
    limit as an expected finding rather than leaving it to drift.
    """

    proposal = _proposal(
        allow=["Run read-only kubectl commands against any context"],
        soft_deny=["Avoid kubectl apply without a reviewed manifest"],
    )
    findings = _only(_lint_rules.lint_proposal(proposal), "AM002")
    assert len(findings) == 1
    assert "kubectl" in findings[0].detail


def test_am002_slash_does_not_invent_a_subcommand_from_a_glob():
    """A path or glob after a tool name is a target, not a subcommand."""

    assert _lint_rules._subcommands("Allow git push to release/* branches") == {
        "push"
    }


def test_am002_still_fires_when_the_allow_names_a_write_subcommand():
    """The suppression only covers an allow side that reads and nothing else."""

    proposal = _proposal(
        allow=["Run kubectl get and kubectl apply anywhere"],
        soft_deny=["Avoid kubectl apply outside a reviewed manifest"],
    )
    findings = _only(_lint_rules.lint_proposal(proposal), "AM002")
    assert len(findings) == 1


def test_am002_still_fires_when_the_soft_deny_names_no_subcommand():
    """An undecidable pair keeps its finding rather than losing it."""

    proposal = _proposal(
        allow=["Run kubectl get on any namespace"],
        soft_deny=["Avoid kubectl in the production cluster"],
    )
    findings = _only(_lint_rules.lint_proposal(proposal), "AM002")
    assert len(findings) == 1


def test_am002_emits_one_ordered_finding_per_colliding_allow():
    """Several allow collisions render deterministically, by allow index."""

    proposal = _proposal(
        allow=[
            "Run helm upgrade on the dev cluster",
            "Run helm rollback on the dev cluster",
        ],
        soft_deny=["Avoid helm operations without a diff"],
    )
    findings = _only(_lint_rules.lint_proposal(proposal), "AM002")
    assert len(findings) == 2
    assert all(f.section == "soft_deny" and f.index == 0 for f in findings)
    assert "allow[0]" in findings[0].detail
    assert "allow[1]" in findings[1].detail


def test_am002_sorts_shared_tokens_in_detail():
    """Shared tokens are listed sorted, so the detail line is stable."""

    proposal = _proposal(
        allow=["Run terraform plan and kubectl diff on any workspace"],
        soft_deny=["Avoid kubectl and terraform outside a review window"],
    )
    findings = _only(_lint_rules.lint_proposal(proposal), "AM002")
    assert len(findings) == 1
    assert findings[0].detail.startswith("shared tokens: kubectl, terraform;")


# ---------------------------------------------------------------------------
# AM003: hard_deny literal present in the project's own files
# ---------------------------------------------------------------------------


def test_am003_fires_and_names_the_offending_file(tmp_path: Path):
    """A forbidden command the repo itself ships is reported with its path."""

    root = _project(
        tmp_path,
        {"scripts/reset.sh": "#!/usr/bin/env bash\n" + NFT_LITERAL},
    )
    findings = _nft_findings(root)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "warn"
    assert finding.section == "hard_deny"
    assert finding.index == 0
    assert "nft flush ruleset" in finding.detail
    assert "scripts/reset.sh" in finding.detail


def test_am003_stays_quiet_when_the_literal_is_absent(tmp_path: Path):
    """No occurrence in the tree means no contradiction to report."""

    root = _project(tmp_path, {"README.md": "Nothing dangerous here.\n"})
    assert _nft_findings(root) == []


def test_am003_requires_a_project_root(tmp_path: Path):
    """Without a tree to scan the rule is skipped entirely."""

    _project(tmp_path, {"scripts/reset.sh": NFT_LITERAL})
    proposal = _proposal(hard_deny=[NFT_RULE])
    assert _only(_lint_rules.lint_proposal(proposal), "AM003") == []
    assert _nft_findings(None) == []


def test_am003_skips_oversized_files(tmp_path: Path):
    """A file above the size cap is never read, so it cannot match."""

    padding = "x" * (_lint_rules.MAX_SCANNED_FILE_BYTES + 1024)
    root = _project(tmp_path, {"huge.txt": padding + "\n" + NFT_LITERAL})
    assert _nft_findings(root) == []


def test_am003_bounds_the_read_against_a_growing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The cap is enforced on the bytes read, not on the earlier stat.

    ``stat`` then unbounded ``read`` is a TOCTOU: a file that grows
    between the two calls is read in full. Faking a small stat proves
    the read itself is what bounds the scan.
    """

    root = _project(
        tmp_path,
        {"grows.txt": "y" * (_lint_rules.MAX_SCANNED_FILE_BYTES + 512)
         + "\n" + NFT_LITERAL},
    )
    real_stat = Path.stat

    def _lying_stat(self, *args, **kwargs):
        result = real_stat(self, *args, **kwargs)
        if self.name == "grows.txt":
            return os.stat_result(
                (result.st_mode, result.st_ino, result.st_dev, result.st_nlink,
                 result.st_uid, result.st_gid, 1,
                 result.st_atime, result.st_mtime, result.st_ctime)
            )
        return result

    monkeypatch.setattr(Path, "stat", _lying_stat)
    assert _nft_findings(root) == []


def test_am003_skips_binary_files(tmp_path: Path):
    """A NUL byte in the first 8 KiB marks the file as binary and unread."""

    root = tmp_path / "project"
    root.mkdir()
    (root / "blob.bin").write_bytes(b"\x00\x01nft flush ruleset\n")
    assert _nft_findings(root) == []


def test_am003_reads_non_utf8_files(tmp_path: Path):
    """Undecodable bytes are replaced, not a reason to skip the file."""

    root = tmp_path / "project"
    root.mkdir()
    (root / "latin1.txt").write_bytes(
        "caf\N{LATIN SMALL LETTER E WITH ACUTE}\n".encode("latin-1")
        + NFT_LITERAL.encode("utf-8")
    )
    findings = _nft_findings(root)
    assert len(findings) == 1
    assert "latin1.txt" in findings[0].detail


def test_am003_extracts_quoted_literals(tmp_path: Path):
    """Backticked spans are searched as-is, no trigger verb needed."""

    root = _project(tmp_path, {"Makefile": "clean:\n\trm -rf /var/lib/data\n"})
    proposal = _proposal(hard_deny=["`rm -rf /var/lib/data` is forbidden"])
    findings = _only(
        _lint_rules.lint_proposal(proposal, project_root=root), "AM003"
    )
    assert len(findings) == 1
    assert "rm -rf /var/lib/data" in findings[0].detail


def test_am003_ignores_two_token_prose_fragments(tmp_path: Path):
    """"rm -rf" out of a sentence is prose, not a command to grep for.

    A two-token fragment matches half of any documentation-heavy tree,
    and a doc that mentions a forbidden command is not a contradiction.
    """

    root = _project(tmp_path, {"Makefile": "clean:\n\trm -rf /tmp/scratch\n"})
    proposal = _proposal(hard_deny=["Never run rm -rf on the repo"])
    assert _lint_rules._extract_literals("Never run rm -rf on the repo") == []
    assert _only(
        _lint_rules.lint_proposal(proposal, project_root=root), "AM003"
    ) == []


def test_am003_does_not_match_a_prefix_of_a_longer_command(tmp_path: Path):
    """A literal must sit at a token boundary in the file it matches.

    "uv run scripts" is not the command "uv run scripts/analyze.py", so
    a doc shipping the latter does not contradict a rule forbidding the
    former.
    """

    root = _project(
        tmp_path, {"README.md": "Run it with `uv run scripts/analyze.py`.\n"}
    )
    proposal = _proposal(hard_deny=["Never run uv run scripts by hand"])
    assert _only(
        _lint_rules.lint_proposal(proposal, project_root=root), "AM003"
    ) == []


def test_am003_does_not_open_a_quoted_span_on_an_apostrophe(tmp_path: Path):
    """An apostrophe inside a word cannot start a quoted literal.

    Treating it as one yields the fragment "t run the project" out of
    "Don't run the project's migration", which then gets grepped across
    the whole tree.
    """

    text = "Don't run the project's migration"
    assert _lint_rules._extract_literals(text) == []
    root = _project(tmp_path, {"notes.md": "t run the project\n"})
    assert _only(
        _lint_rules.lint_proposal(_proposal(hard_deny=[text]), project_root=root),
        "AM003",
    ) == []


def test_am003_prunes_noisy_directories(tmp_path: Path):
    """Vendored trees are not the project's own content."""

    root = _project(tmp_path, {"node_modules/pkg/index.js": NFT_LITERAL})
    assert _nft_findings(root) == []


def test_am003_skips_a_symlink_escaping_the_root(tmp_path: Path):
    """A symlink out of the tree must not be read.

    Following one would let a rule's literal be searched anywhere on the
    host, which is not what "the project's own files" means.
    """

    outside = tmp_path / "outside.txt"
    outside.write_text(NFT_LITERAL, encoding="utf-8")
    root = _project(tmp_path, {"README.md": "nothing here\n"})
    (root / "link.txt").symlink_to(outside)
    assert _nft_findings(root) == []


def test_am003_survives_a_symlinked_directory_cycle(tmp_path: Path):
    """A directory symlink pointing at its own ancestor cannot spin the walk."""

    root = _project(tmp_path, {"scripts/reset.sh": NFT_LITERAL})
    (root / "loop").symlink_to(root, target_is_directory=True)
    findings = _nft_findings(root)
    assert len(findings) == 1
    assert "scripts/reset.sh" in findings[0].detail


def test_am003_never_puts_file_content_in_the_detail(tmp_path: Path):
    """Only paths are reported, so a scanned secret cannot leak into output."""

    root = _project(
        tmp_path, {"deploy.sh": "SECRET=hunter2 nft flush ruleset\n"}
    )
    findings = _nft_findings(root)
    assert len(findings) == 1
    for finding in findings:
        assert "hunter2" not in finding.detail
        assert "hunter2" not in finding.message
        assert "hunter2" not in finding.rule_text


def test_am003_truncates_the_reported_path_list(tmp_path: Path):
    """Beyond the display cap the detail says so without a made-up count.

    Accumulation stops at the cap, so an exact total would be a number
    the scan never finished computing.
    """

    files = {
        f"f{index}.sh": NFT_LITERAL
        for index in range(_lint_rules.MAX_REPORTED_PATHS + 3)
    }
    root = _project(tmp_path, files)
    findings = _nft_findings(root)
    assert len(findings) == 1
    detail = findings[0].detail
    assert detail.endswith("(and more)")
    shown = detail.split("found in: ")[1].removesuffix(" (and more)")
    assert len(shown.split(", ")) == _lint_rules.MAX_REPORTED_PATHS


# ---------------------------------------------------------------------------
# AM003: the git-backed file listing and its fallbacks
# ---------------------------------------------------------------------------


def test_am003_uses_the_git_index_when_available(tmp_path: Path):
    """Tracked files are scanned; an untracked one is not.

    The untracked file carries the same literal, so a finding that names
    only the tracked path proves ``git ls-files`` drove the scan.
    """

    root = _git_project(
        tmp_path,
        {"tracked.sh": NFT_LITERAL},
        untracked_sh=NFT_LITERAL,
    )
    findings = _nft_findings(root)
    assert len(findings) == 1
    assert "tracked.sh" in findings[0].detail
    assert "untracked_sh" not in findings[0].detail


def test_git_tracked_files_returns_none_outside_a_work_tree(tmp_path: Path):
    """A non-zero git exit means "fall back to the walk"."""

    root = _project(tmp_path, {"README.md": "hi\n"})
    assert _lint_rules._git_tracked_files(root) is None


def test_git_tracked_files_returns_none_for_an_empty_index(tmp_path: Path):
    """A work tree with nothing staged also falls back to the walk."""

    root = _project(tmp_path, {"README.md": "hi\n"})
    subprocess.run(
        ["git", "init", "-q"], cwd=root, check=True, capture_output=True
    )
    assert _lint_rules._git_tracked_files(root) is None


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError("git"),
        subprocess.TimeoutExpired(cmd="git", timeout=10),
        OSError("boom"),
    ],
)
def test_am003_falls_back_to_the_walk_when_git_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Exception
):
    """Missing git, a timeout, or an OS error all degrade to the walk."""

    root = _git_project(tmp_path, {"tracked.sh": NFT_LITERAL})

    def _explode(*args, **kwargs):
        raise failure

    monkeypatch.setattr(_lint_rules.subprocess, "run", _explode)
    assert _lint_rules._git_tracked_files(root) is None
    findings = _nft_findings(root)
    assert len(findings) == 1
    assert "tracked.sh" in findings[0].detail


def test_am003_caps_the_walk_file_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The walk stops at the cap, in sorted order."""

    root = _project(
        tmp_path, {"a.txt": "harmless\n", "z.txt": NFT_LITERAL}
    )
    monkeypatch.setattr(_lint_rules, "MAX_SCANNED_FILES", 1)
    assert _lint_rules._walk_files(root, 1) == [root / "a.txt"]
    assert _nft_findings(root) == []


def test_am003_caps_the_git_file_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The same cap applies to the git-listed set."""

    root = _git_project(
        tmp_path, {"a.txt": "harmless\n", "z.txt": NFT_LITERAL}
    )
    assert _lint_rules._git_tracked_files(root) is not None
    monkeypatch.setattr(_lint_rules, "MAX_SCANNED_FILES", 1)
    assert _nft_findings(root) == []


# ---------------------------------------------------------------------------
# AM004: permissions pattern pasted into autoMode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("section", list(_lint_rules.SECTION_ORDER))
def test_am004_fires_on_a_whole_entry_pattern(section: str):
    """A bare ``Tool(specifier)`` entry is a permissions pattern anywhere."""

    findings = _only(
        _lint_rules.lint_proposal(_proposal(**{section: ["Bash(git push:*)"]})),
        "AM004",
    )
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "error"
    assert finding.section == section
    assert finding.index == 0
    assert "permissions" in finding.message
    assert finding.detail == "matched pattern: Bash(git push:*)"


@pytest.mark.parametrize(
    "text,expected",
    [
        ('"Bash(git push:*)"', "matched pattern: Bash(git push:*)"),
        ("Bash(git push:*).", "matched pattern: Bash(git push:*)"),
        ("- Bash(git push:*)", "matched pattern: Bash(git push:*)"),
        (
            "Bash(git push:*), Bash(git commit:*)",
            "matched patterns: Bash(git push:*), Bash(git commit:*)",
        ),
        (
            "mcp__github__create_issue(*)",
            "matched pattern: mcp__github__create_issue(*)",
        ),
        ("Bash(echo (hi))", "matched pattern: Bash(echo (hi))"),
        ("  Agent(*)  ", "matched pattern: Agent(*)"),
        ("* `Bash(rm:*)`;", "matched pattern: Bash(rm:*)"),
    ],
)
def test_am004_fires_on_every_paste_shape(text: str, expected: str):
    """A paste keeps its quotes, bullet, or full stop; it is still a paste."""

    findings = _only(
        _lint_rules.lint_proposal(_proposal(allow=[text])), "AM004"
    )
    assert len(findings) == 1
    assert findings[0].detail == expected


@pytest.mark.parametrize(
    "text",
    [
        "Treat Bash(git push:*) as already granted by permissions",
        "Bash(git push:*) is handled by the permissions block instead",
        "The classifier drops Bash(*) when auto mode starts",
        "Never run helm(3) style commands by hand",
        "Never force-push to main",
        "Deploy only after the pipeline (including the slow stage) is green",
    ],
)
def test_am004_stays_quiet_on_prose(text: str):
    """A sentence that merely cites a pattern is a valid autoMode rule."""

    assert _only(_lint_rules.lint_proposal(_proposal(allow=[text])), "AM004") == []


def test_am004_fires_on_a_list_cut_short():
    """A selection that kept its trailing comma is still a paste."""

    proposal = _proposal(allow=["Bash(git push:*), "])
    findings = _only(_lint_rules.lint_proposal(proposal), "AM004")
    assert len(findings) == 1
    assert findings[0].detail == "matched pattern: Bash(git push:*)"


# ---------------------------------------------------------------------------
# Cross-cutting behaviour
# ---------------------------------------------------------------------------


def test_defaults_sentinel_is_skipped_by_every_rule():
    """``$defaults`` never produces a finding, in any section."""

    proposal = _proposal(
        environment=["$defaults"],
        allow=["$defaults"],
        soft_deny=["$defaults"],
        hard_deny=["$defaults"],
    )
    assert _lint_rules.lint_proposal(proposal) == []


def test_example_only_wrappers_are_unwrapped_at_their_original_index():
    """An envelope is linted by its inner value and keeps its position."""

    proposal = _proposal(
        hard_deny=[
            "Never delete a production volume",
            {"__example_only": True, "value": "Bash(git push:*)"},
        ]
    )
    findings = _only(_lint_rules.lint_proposal(proposal), "AM004")
    assert len(findings) == 1
    assert findings[0].index == 1
    assert findings[0].rule_text == "Bash(git push:*)"


def test_non_string_entries_are_skipped_without_shifting_indexes():
    """A junk entry is ignored, and the entries after it keep their index."""

    proposal = _proposal(hard_deny=[42, None, "Bash(git push:*)"])
    findings = _only(_lint_rules.lint_proposal(proposal), "AM004")
    assert len(findings) == 1
    assert findings[0].index == 2


def test_missing_automode_block_returns_no_findings():
    """A proposal without an autoMode block is tolerated, not an error."""

    assert _lint_rules.lint_proposal({}) == []
    assert _lint_rules.lint_proposal({"autoMode": None}) == []
    assert _lint_rules.lint_proposal({"autoMode": ["not", "a", "dict"]}) == []
    assert _lint_rules.lint_proposal({"permissions": {"allow": []}}) == []


def test_rule_text_is_truncated_to_120_chars():
    """Long rules are ellipsized so a finding stays one readable line."""

    long_rule = "Never force-push " + "very " * 60 + "unless approved"
    findings = _only(
        _lint_rules.lint_proposal(_proposal(hard_deny=[long_rule])), "AM001"
    )
    assert len(findings) == 1
    assert len(findings[0].rule_text) == 120
    assert findings[0].rule_text.endswith("...")


def test_findings_are_sorted_by_section_then_index_then_rule():
    """Output order follows the documented section ranking, not rule order."""

    proposal = _proposal(
        allow=["Bash(git push:*)"],
        soft_deny=["Avoid kubectl writes", "Bash(kubectl apply:*)"],
        hard_deny=["Never run kubectl delete unless a snapshot exists"],
    )
    findings = _lint_rules.lint_proposal(proposal)
    keys = [(f.section, f.index, f.rule) for f in findings]
    assert keys == sorted(
        keys, key=lambda k: (_lint_rules.SECTION_ORDER.index(k[0]), k[1], k[2])
    )
    assert keys[0][0] == "allow"
    assert keys[-1][0] == "hard_deny"


_DETERMINISM_PROGRAM = textwrap.dedent(
    """
    import json
    import sys

    sys.path.insert(0, sys.argv[1])
    import _lint_rules

    proposal = {
        "autoMode": {
            "allow": [
                "Run helm upgrade on dev",
                "Run helm rollback on dev",
                "Allow git push to release/* branches",
                "Bash(git push:*)",
            ],
            "soft_deny": [
                "Avoid helm operations without a diff",
                "Avoid git push --force on release/* branches",
            ],
            "hard_deny": [
                "Never run nft flush ruleset on any host",
                "Never force-push to main unless the release lead approves",
                "Never run `rm -rf /var/lib/data` anywhere",
            ],
        }
    }
    findings = _lint_rules.lint_proposal(
        proposal, project_root=__import__("pathlib").Path(sys.argv[2])
    )
    sys.stdout.write(_lint_rules.format_findings(findings))
    """
)


def test_lint_output_is_stable_across_hash_seeds(
    tmp_path: Path, scripts_dir: Path
):
    """Two interpreters with different hash seeds render the same block.

    Calling the function twice inside one process cannot catch set
    iteration order leaking into the output, because a set's order is
    fixed for the life of the process. Separate interpreters with
    different ``PYTHONHASHSEED`` values can.
    """

    root = _project(
        tmp_path,
        {
            "a/one.sh": NFT_LITERAL,
            "b/two.sh": NFT_LITERAL,
            "Makefile": "clean:\n\trm -rf /var/lib/data\n",
        },
    )
    outputs = []
    for seed in ("0", "1", "524287"):
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                _DETERMINISM_PROGRAM,
                str(scripts_dir),
                str(root),
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        assert proc.returncode == 0, proc.stderr
        outputs.append(proc.stdout)
    assert outputs[0] == outputs[1] == outputs[2]
    assert "AM001" in outputs[0]
    assert "AM002" in outputs[0]
    assert "AM003" in outputs[0]
    assert "AM004" in outputs[0]


def test_lint_is_repeatable_within_one_process(tmp_path: Path):
    """Linting the same proposal twice returns the identical list."""

    root = _project(tmp_path, {"a/one.sh": NFT_LITERAL, "b/two.sh": NFT_LITERAL})
    proposal = _proposal(
        allow=["Run helm upgrade on dev", "Bash(git push:*)"],
        soft_deny=["Avoid helm operations without a diff"],
        hard_deny=[
            NFT_RULE,
            "Never force-push to main unless the release lead approves",
        ],
    )
    first = _lint_rules.lint_proposal(proposal, project_root=root)
    second = _lint_rules.lint_proposal(proposal, project_root=root)
    assert first == second
    assert set(_rules(first)) == {"AM001", "AM002", "AM003", "AM004"}


# ---------------------------------------------------------------------------
# format_findings
# ---------------------------------------------------------------------------


def test_format_findings_is_empty_for_no_findings():
    """Nothing to report renders as the empty string, not a header."""

    assert _lint_rules.format_findings([]) == ""


def test_format_findings_renders_ids_locations_and_details():
    """The rendered block carries rule ids, the section path, and details."""

    proposal = _proposal(
        allow=["Run kubectl apply against staging"],
        soft_deny=["Avoid kubectl writes without review"],
        hard_deny=["Never force-push to main unless the release lead approves"],
    )
    rendered = _lint_rules.format_findings(_lint_rules.lint_proposal(proposal))
    assert "AM001" in rendered
    assert "AM002" in rendered
    assert "autoMode.hard_deny[0]" in rendered
    assert "autoMode.soft_deny[0]" in rendered
    assert "  rule: " in rendered
    assert "  detail: " in rendered
    assert rendered.endswith("\n")
    assert rendered.isascii()


def test_format_findings_puts_errors_before_warnings():
    """Errors lead the block so the blocking problems are read first."""

    proposal = _proposal(
        allow=["Run kubectl apply against staging"],
        soft_deny=["Avoid kubectl writes without review"],
        hard_deny=["Never force-push to main unless the release lead approves"],
    )
    rendered = _lint_rules.format_findings(_lint_rules.lint_proposal(proposal))
    assert rendered.index("AM001") < rendered.index("AM002")
    assert rendered.startswith("error  AM001  ")
