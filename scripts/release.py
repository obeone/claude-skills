#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Cut a CalVer release tag (vYYYY.MM.MICRO) on origin/main, GPG-signed.

Meant to run locally (by hand or from launchd/cron) so the tag carries the
maintainer's signature. It only tags when something under skills/ changed
since the last release, so Dependabot bumps of CI actions never publish an
empty release. Pushing the tag triggers the Publish Skills workflow.

Usage:
    uv run scripts/release.py              # tag + push if skills/ changed
    uv run scripts/release.py --dry-run    # show what would happen
    uv run scripts/release.py --force -m "summary"  # release regardless
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

REMOTE = "origin"
BRANCH = "main"
WATCHED_PATH = "skills/"
CALVER_RE = re.compile(r"^v(\d{4})\.(\d{2})\.(\d+)$")
REPO_ROOT = Path(__file__).resolve().parent.parent


def git(*args: str) -> str:
    """Run a git command at the repo root and return its stripped stdout."""
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def next_tag(today: date, existing: list[str]) -> str:
    """Return the next vYYYY.MM.MICRO for today's month; legacy SemVer tags are ignored."""
    prefix = (today.year, today.month)
    micros = [
        int(m.group(3))
        for tag in existing
        if (m := CALVER_RE.match(tag)) and (int(m.group(1)), int(m.group(2))) == prefix
    ]
    micro = max(micros) + 1 if micros else 0
    return f"v{today:%Y.%m}.{micro}"


def summarize(subjects: list[str]) -> str:
    """Build the one-line tag summary from the released commit subjects."""
    if len(subjects) <= 1:
        return "".join(subjects)
    return f"{len(subjects)} changes: " + "; ".join(subjects[:3]) + (
        "; ..." if len(subjects) > 3 else ""
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print the plan, touch nothing")
    parser.add_argument("--force", action="store_true", help=f"release even if {WATCHED_PATH} is unchanged")
    parser.add_argument("-m", "--message", help="tag summary (default: built from commit subjects)")
    args = parser.parse_args()

    git("fetch", "--quiet", "--tags", REMOTE, BRANCH)
    target = f"{REMOTE}/{BRANCH}"
    target_sha = git("rev-parse", target)

    try:
        last_tag = git("describe", "--tags", "--abbrev=0", "--match", "v*", target)
    except subprocess.CalledProcessError:
        last_tag = ""

    if last_tag and git("rev-parse", f"{last_tag}^{{commit}}") == target_sha:
        print(f"{target} is already tagged as {last_tag}; nothing to release.")
        return 0

    log_range = f"{last_tag}..{target}" if last_tag else target
    subjects = git("log", "--no-merges", "--format=%s", log_range, "--", WATCHED_PATH).splitlines()
    if not subjects and not args.force:
        print(f"No change under {WATCHED_PATH} since {last_tag or 'the first commit'}; nothing to release.")
        return 0

    tag = next_tag(date.today(), git("tag", "--list", "v*").splitlines())
    if git("ls-remote", "--tags", REMOTE, f"refs/tags/{tag}"):
        print(f"error: {tag} already exists on {REMOTE}", file=sys.stderr)
        return 1

    summary = args.message or summarize(subjects) or "maintenance release"
    message = f"{tag} - {summary}"
    print(f"Tagging {target} ({target_sha[:12]}) as {tag}")
    print(f"  message: {message}")
    print(f"  since {last_tag or 'the first commit'}: {len(subjects)} commit(s) under {WATCHED_PATH}")
    if args.dry_run:
        return 0

    git("tag", "--sign", "--annotate", tag, "--message", message, target_sha)
    git("push", REMOTE, f"refs/tags/{tag}")
    print(f"Pushed {tag}; the Publish Skills workflow takes it from here.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        print(f"error: {' '.join(exc.cmd)} failed:\n{exc.stderr}", file=sys.stderr)
        sys.exit(exc.returncode)
