#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Extract fenced ```dockerfile blocks from the skill's markdown and lint them.

This is the regression harness for the dockerfile-best-practices skill
itself: it walks SKILL.md, README.md, and references/*.md, pulls out every
fenced ```dockerfile block, and runs analyze_dockerfile.py's analyzer over
each one that looks like a complete, buildable Dockerfile. Findings are
reported against the *markdown* file and line, not a throwaway temp path,
because "line 4 of /tmp/xyz.dockerfile" is useless to someone fixing docs.

Selection rule (locked convention, see .omc/handoffs/team-plan.md decision D9;
revised after the first CI run against the real skill)
--------------------------------------------------------------------------

1. A block is validated only if it is a COMPLETE image definition: it has a
   ``FROM`` instruction AND a ``CMD`` or an ``ENTRYPOINT`` instruction.
2. A block is skipped as a snippet if it lacks a ``FROM``, or has a ``FROM``
   but no ``CMD``/``ENTRYPOINT``. No marker needed for either case.
3. A block is skipped regardless of shape if one of its comment lines starts
   with ``# Fragment:`` or ``# Anti-pattern:``.

The original rule ("validate any block with a FROM") validated 62 of 113
blocks and produced 50 failures, dominated by DL001 (no syntax directive) x32
and DL030 (no non-root USER) x46. Those two, plus DL031 and DL032, are
whole-image checks: they fire on three-line teaching snippets that merely
open with a FROM for context, which is noise, not a defect. Requiring a
CMD/ENTRYPOINT too restricts validation to blocks that are actually meant to
stand alone as a full image (the six language templates, the worked
examples), where those checks are meaningful.

Usage
-----

    uv run extract_dockerfile_blocks.py [--skill-root PATH] [--json]
    uv run extract_dockerfile_blocks.py --files a.md b.md [--json]
    uv run extract_dockerfile_blocks.py --emit-dir /tmp/blocks

Exit status is non-zero when any *validated* block produces an error- or
warning-severity finding. Info-level findings (e.g. DL032, "no LABEL
defined", which fires on most examples since they skip metadata for
brevity) never fail the run.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import List, Optional

# Matches a fenced-code opening line and captures its language tag, e.g.
# "```dockerfile" -> "dockerfile". A bare "```" (no language) is treated as
# having an empty language tag and can never be a dockerfile block.
_FENCE_OPEN_RE = re.compile(r"^```([\w.+-]*)\s*$")
# Matches only the bare closing fence: no language tag allowed here, so an
# opening fence for a *different* block (e.g. "```bash") is never mistaken
# for a close.
_FENCE_CLOSE_RE = re.compile(r"^```\s*$")
# A logical FROM instruction. Deliberately loose (D9 only asks "has a FROM");
# it does not need to be a *valid* FROM to count towards "complete image
# definition", since the analyzer itself will flag a malformed one.
_FROM_RE = re.compile(r"^\s*FROM\s", re.IGNORECASE)
# A logical CMD or ENTRYPOINT instruction, the other half of "complete image
# definition" per the revised D9 rule. Either one qualifies; a Dockerfile
# only ever needs one of them to define what the container runs.
_CMD_OR_ENTRYPOINT_RE = re.compile(r"^\s*(CMD|ENTRYPOINT)\s", re.IGNORECASE)
# D9's two literal marker prefixes. Case-sensitive and space-after-colon-free
# on purpose: it is a documented convention (D9), not a fuzzy heuristic, so a
# typo'd marker should NOT silently suppress validation.
_SKIP_MARKER_RE = re.compile(r"^\s*#\s*(Fragment|Anti-pattern):")

_SEVERITIES_THAT_FAIL = {"error", "warning"}


@dataclass
class FencedBlock:
    """A single fenced ```dockerfile code block extracted from a markdown file.

    Parameters
    ----------
    source_file : Path
        Markdown file the block came from.
    first_content_line : int
        1-indexed line number, in `source_file`, of the block's first line of
        content (the line immediately after the opening fence).
    lines : list of str
        The block's content lines, in order, with the fence lines themselves
        stripped off.
    """

    source_file: Path
    first_content_line: int
    lines: List[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        """Return the block content as a single newline-joined string."""
        return "\n".join(self.lines)


def discover_markdown_files(skill_root: Path) -> List[Path]:
    """Find the markdown files this skill documents itself in.

    Parameters
    ----------
    skill_root : Path
        Root directory of the skill (the directory containing SKILL.md).

    Returns
    -------
    list of Path
        SKILL.md and README.md (if present) followed by every references/*.md
        file, sorted for deterministic output. Missing files are silently
        omitted rather than erroring, since not every skill ships a README.
    """
    candidates = [skill_root / "SKILL.md", skill_root / "README.md"]
    candidates += sorted((skill_root / "references").glob("*.md"))
    return [p for p in candidates if p.is_file()]


def extract_fenced_blocks(markdown_path: Path) -> List[FencedBlock]:
    """Extract every fenced ```dockerfile block from one markdown file.

    Parameters
    ----------
    markdown_path : Path
        Markdown file to scan.

    Returns
    -------
    list of FencedBlock
        One entry per fenced block whose opening fence language tag is
        ``dockerfile`` (case-insensitive), in document order.
    """
    text = markdown_path.read_text(encoding="utf-8")
    lines = text.split("\n")

    blocks: List[FencedBlock] = []
    in_fence = False
    fence_lang = ""
    fence_start_line = 0  # 1-indexed line number of the block's first content
    fence_content: List[str] = []

    for line_no, line in enumerate(lines, start=1):
        if not in_fence:
            open_match = _FENCE_OPEN_RE.match(line)
            if open_match:
                in_fence = True
                fence_lang = open_match.group(1)
                fence_start_line = line_no + 1
                fence_content = []
            continue

        # Inside a fence: a bare "```" closes it, anything else is content.
        if _FENCE_CLOSE_RE.match(line):
            if fence_lang.lower() == "dockerfile":
                blocks.append(FencedBlock(
                    source_file=markdown_path,
                    first_content_line=fence_start_line,
                    lines=fence_content,
                ))
            in_fence = False
            fence_lang = ""
            fence_content = []
        else:
            fence_content.append(line)

    if in_fence:
        # Malformed markdown (unterminated fence). Report it but do not
        # crash the whole run over one bad file.
        print(
            f"warning: {markdown_path}: fenced block starting near line "
            f"{fence_start_line - 1} is never closed, ignoring it",
            file=sys.stderr,
        )

    return blocks


def classify_block(block: FencedBlock) -> "tuple[str, Optional[str]]":
    """Apply the (revised) D9 selection rule to one extracted block.

    Parameters
    ----------
    block : FencedBlock
        Block to classify.

    Returns
    -------
    tuple of (str, str or None)
        ``(status, skip_reason)``. ``status`` is ``"validated"`` or
        ``"skipped"``. ``skip_reason`` is one of ``"fragment"``,
        ``"anti-pattern"``, ``"no-from"``, ``"no-cmd-entrypoint"`` when
        skipped, else ``None``.

    Notes
    -----
    The explicit ``# Fragment:``/``# Anti-pattern:`` marker always wins,
    "regardless of shape" per D9 point 3: a block can be a complete image
    definition and still be a deliberately-wrong or non-buildable example
    that must not be linted. Only once no marker is present does shape
    matter: a block needs both a ``FROM`` and a ``CMD``/``ENTRYPOINT`` to
    count as a complete image, because DL001/DL030/DL031/DL032 are
    whole-image checks that are meaningless on a fragment (see the module
    docstring for why this replaced the original "any FROM" rule).
    """
    for line in block.lines:
        marker = _SKIP_MARKER_RE.match(line)
        if marker:
            kind = marker.group(1)
            return "skipped", "fragment" if kind == "Fragment" else "anti-pattern"

    if not any(_FROM_RE.match(line) for line in block.lines):
        return "skipped", "no-from"

    if not any(_CMD_OR_ENTRYPOINT_RE.match(line) for line in block.lines):
        return "skipped", "no-cmd-entrypoint"

    return "validated", None


def load_analyzer() -> ModuleType:
    """Dynamically import the sibling analyze_dockerfile.py as a module.

    Returns
    -------
    ModuleType
        The imported module, exposing ``analyze_dockerfile(content: str)``.

    Notes
    -----
    analyze_dockerfile.py is a plain script, not an installed package, and
    this extractor must work when invoked from any working directory (as CI
    does). Loading it by explicit file path avoids relying on `sys.path`
    tricks or packaging, and calling `analyze_dockerfile()` in-process (as
    opposed to shelling out to the script once per block) is both simpler and
    avoids one Python startup per block.
    """
    analyzer_path = Path(__file__).resolve().parent / "analyze_dockerfile.py"
    spec = importlib.util.spec_from_file_location("analyze_dockerfile", analyzer_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load analyzer module from {analyzer_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def map_issue_line(block: FencedBlock, issue_line_num: int) -> int:
    """Translate an analyzer line number (block-relative) to a source line.

    Parameters
    ----------
    block : FencedBlock
        The block the issue was found in.
    issue_line_num : int
        1-indexed line number as reported by `analyze_dockerfile()`, counted
        from the start of the block's own content.

    Returns
    -------
    int
        1-indexed line number in `block.source_file`.

    Notes
    -----
    The analyzer's per-instruction issues use a genuine 1-indexed line number
    within the content it was given. Its file-level issues (e.g. "no USER
    defined") reuse ``len(lines)`` or, in one case, ``0`` as a placeholder
    rather than pointing at a specific instruction. The same linear offset
    (`first_content_line - 1`) is applied uniformly: a placeholder of ``0``
    lands one line before the block's content, i.e. on the opening fence
    itself, which still points a reader at the right block.
    """
    return block.first_content_line - 1 + issue_line_num


@dataclass
class BlockReport:
    """Analysis outcome for one extracted block, ready for reporting.

    Parameters
    ----------
    source_file : str
        Display path of the markdown file the block came from.
    first_content_line : int
        1-indexed source line of the block's first content line.
    status : str
        ``"validated"`` or ``"skipped"``.
    skip_reason : str or None
        Populated when `status` is ``"skipped"``.
    issues : list of dict
        Analyzer findings, with `line` already mapped back to `source_file`.
    """

    source_file: str
    first_content_line: int
    status: str
    skip_reason: Optional[str]
    issues: List[dict]

    @property
    def failed(self) -> bool:
        """Return True when a validated block has an error- or warning-level finding."""
        return self.status == "validated" and any(
            i["severity"] in _SEVERITIES_THAT_FAIL for i in self.issues
        )


def analyze_blocks(
    markdown_files: List[Path], analyzer: ModuleType
) -> "tuple[List[BlockReport], dict]":
    """Extract, classify, and lint every dockerfile block in a set of files.

    Parameters
    ----------
    markdown_files : list of Path
        Markdown files to scan, in the order they should be reported.
    analyzer : ModuleType
        The imported analyze_dockerfile module (see `load_analyzer`).

    Returns
    -------
    tuple of (list of BlockReport, dict)
        ``(reports, blocks_by_report)``. ``reports`` has one entry per
        extracted block (validated or skipped), in document order within
        each file, files in the given order. ``blocks_by_report`` maps
        ``id(report)`` to the originating `FencedBlock`, so callers that need
        the raw block text (e.g. `emit_validated_blocks`) do not require
        `BlockReport` itself to carry it around.
    """
    reports: List[BlockReport] = []
    blocks_by_report: dict = {}

    for markdown_path in markdown_files:
        for block in extract_fenced_blocks(markdown_path):
            status, skip_reason = classify_block(block)
            issues: List[dict] = []

            if status == "validated":
                for issue in analyzer.analyze_dockerfile(block.text):
                    mapped = issue.to_dict()
                    mapped["line"] = map_issue_line(block, issue.line_num)
                    issues.append(mapped)

            report = BlockReport(
                source_file=str(block.source_file),
                first_content_line=block.first_content_line,
                status=status,
                skip_reason=skip_reason,
                issues=issues,
            )
            reports.append(report)
            blocks_by_report[id(report)] = block

    return reports, blocks_by_report


def emit_validated_blocks(reports: List[BlockReport], blocks_by_report: dict, emit_dir: Path) -> None:
    """Write every validated block's content to disk as a standalone Dockerfile.

    Parameters
    ----------
    reports : list of BlockReport
        Reports produced by `analyze_blocks`, used only to filter down to
        validated blocks and to name the emitted files.
    blocks_by_report : dict
        Maps ``id(report)`` to the originating `FencedBlock`, since
        `BlockReport` itself does not retain the raw content.
    emit_dir : Path
        Directory to write into. Created if missing.

    Notes
    -----
    This exists for the T-16 CI job: `docker build --check` needs real files
    on disk, and re-deriving "which blocks count as validated" with separate
    logic in the workflow would risk drifting from this script's D9
    selection rule. A manifest.json alongside the emitted files records the
    original markdown source and line for each one.
    """
    emit_dir.mkdir(parents=True, exist_ok=True)
    manifest = []

    for index, report in enumerate(reports):
        if report.status != "validated":
            continue
        block = blocks_by_report[id(report)]
        # Deterministic, collision-free filename: index avoids clashing when
        # multiple blocks share a source file and line count coincidentally.
        stem = Path(report.source_file).stem
        out_name = f"{index:03d}-{stem}-L{report.first_content_line}.dockerfile"
        out_path = emit_dir / out_name
        out_path.write_text(block.text + "\n", encoding="utf-8")
        manifest.append({
            "file": out_name,
            "source_file": report.source_file,
            "first_content_line": report.first_content_line,
        })

    (emit_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def print_text_report(reports: List[BlockReport], files_scanned: int) -> None:
    """Print a human-readable report followed by the summary line.

    Parameters
    ----------
    reports : list of BlockReport
        Reports to print.
    files_scanned : int
        Number of markdown files that were scanned (including ones with zero
        blocks), for the summary line.
    """
    skip_reason_counts: dict = {}
    validated_count = 0
    failure_count = 0

    for report in reports:
        if report.status == "skipped":
            skip_reason_counts[report.skip_reason] = skip_reason_counts.get(report.skip_reason, 0) + 1
            continue

        validated_count += 1
        location = f"{report.source_file}:{report.first_content_line}"

        if not report.issues:
            print(f"✅ {location}: clean")
            continue

        if report.failed:
            failure_count += 1
            icon = "❌"
        else:
            icon = "ℹ️"
        print(f"{icon} {location}:")
        for issue in report.issues:
            sev_icon = {"error": "\U0001f534", "warning": "\U0001f7e1", "info": "\U0001f535"}[issue["severity"]]
            print(f"  {sev_icon} line {issue['line']} [{issue['rule']}]: {issue['message']}")
            if issue["suggestion"]:
                print(f"     → {issue['suggestion']}")

    skip_summary = ", ".join(f"{count} {reason}" for reason, count in sorted(skip_reason_counts.items())) or "none"
    print(
        f"\nSummary: {files_scanned} files scanned, {len(reports)} dockerfile "
        f"blocks found, {validated_count} validated, "
        f"{sum(skip_reason_counts.values())} skipped ({skip_summary}), "
        f"{failure_count} failures"
    )


def build_json_report(reports: List[BlockReport], files_scanned: int) -> dict:
    """Build the machine-readable report structure for `--json`.

    Parameters
    ----------
    reports : list of BlockReport
        Reports to serialize.
    files_scanned : int
        Number of markdown files scanned.

    Returns
    -------
    dict
        JSON-serializable report with a `summary` block and a `blocks` list,
        mirroring the conventions of analyze_dockerfile.py's `--json` output.
    """
    skip_reason_counts: dict = {}
    validated_count = 0
    failure_count = 0
    blocks_out = []

    for report in reports:
        if report.status == "skipped":
            skip_reason_counts[report.skip_reason] = skip_reason_counts.get(report.skip_reason, 0) + 1
        else:
            validated_count += 1
            if report.failed:
                failure_count += 1

        blocks_out.append({
            "source_file": report.source_file,
            "first_content_line": report.first_content_line,
            "status": report.status,
            "skip_reason": report.skip_reason,
            "issues": report.issues,
            "failed": report.failed,
        })

    return {
        "summary": {
            "files_scanned": files_scanned,
            "blocks_found": len(reports),
            "validated": validated_count,
            "skipped": sum(skip_reason_counts.values()),
            "skip_reasons": skip_reason_counts,
            "failures": failure_count,
        },
        "blocks": blocks_out,
    }


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Parameters
    ----------
    argv : list of str, optional
        Argument vector to parse; defaults to `sys.argv[1:]`.

    Returns
    -------
    argparse.Namespace
        Parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--skill-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Skill directory containing SKILL.md/README.md/references/ (default: this script's own skill)",
    )
    source.add_argument(
        "--files",
        type=Path,
        nargs="+",
        help="Explicit list of markdown files to scan instead of the skill-root convention (mainly for testing)",
    )
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable JSON report")
    parser.add_argument(
        "--emit-dir",
        type=Path,
        default=None,
        help="Also write every validated block to this directory as a standalone .dockerfile, plus a manifest.json",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point: extract, classify, lint, report, and set the exit code.

    Parameters
    ----------
    argv : list of str, optional
        Argument vector; defaults to `sys.argv[1:]`.

    Returns
    -------
    int
        Process exit status: 0 when no validated block has an error- or
        warning-severity finding, 1 otherwise (or on a hard failure such as
        a missing skill root).
    """
    args = parse_args(argv)

    if args.files:
        markdown_files = [p for p in args.files if p.is_file()]
        missing = [p for p in args.files if not p.is_file()]
        for path in missing:
            print(f"warning: {path}: not found, skipping", file=sys.stderr)
    else:
        if not args.skill_root.is_dir():
            print(f"Error: skill root not found: {args.skill_root}", file=sys.stderr)
            return 1
        markdown_files = discover_markdown_files(args.skill_root)

    analyzer = load_analyzer()
    reports, blocks_by_report = analyze_blocks(markdown_files, analyzer)

    if args.emit_dir:
        emit_validated_blocks(reports, blocks_by_report, args.emit_dir)

    if args.json:
        report_dict = build_json_report(reports, len(markdown_files))
        print(json.dumps(report_dict, indent=2))
    else:
        print_text_report(reports, len(markdown_files))

    any_failure = any(r.failed for r in reports)
    return 1 if any_failure else 0


if __name__ == "__main__":
    sys.exit(main())
