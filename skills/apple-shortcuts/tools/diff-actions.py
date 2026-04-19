#!/usr/bin/env python3
"""Semantic diff between two Apple Shortcuts plist files.

Reports added, removed, modified, and reordered actions — not a
textual diff. Action identity is based on UUID when available, else
on position + identifier.

Exit codes:
    0 — no differences.
    1 — differences found.
    2 — could not parse input(s).
"""

from __future__ import annotations

import argparse
import json
import logging
import plistlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


@dataclass
class ActionEntry:
    """Canonical representation of one action."""

    index: int
    identifier: str
    uuid: str | None
    parameters_snapshot: str


@dataclass
class DiffReport:
    """Accumulated diff findings."""

    added: list[ActionEntry] = field(default_factory=list)
    removed: list[ActionEntry] = field(default_factory=list)
    modified: list[dict[str, Any]] = field(default_factory=list)
    reordered: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        """True when any change was found."""
        return bool(
            self.added or self.removed or self.modified or self.reordered
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialize."""
        return {
            "added": [_entry_to_dict(e) for e in self.added],
            "removed": [_entry_to_dict(e) for e in self.removed],
            "modified": self.modified,
            "reordered": self.reordered,
        }


def _entry_to_dict(entry: ActionEntry) -> dict[str, Any]:
    """Convert an ActionEntry to a JSON-safe dict."""
    return {
        "index": entry.index,
        "identifier": entry.identifier,
        "uuid": entry.uuid,
    }


def load_actions(path: Path) -> list[ActionEntry]:
    """Load and canonicalize a plist's actions."""
    try:
        with path.open("rb") as fh:
            data = plistlib.load(fh)
    except FileNotFoundError:
        LOGGER.error("file not found: %s", path)
        raise SystemExit(2) from None
    except plistlib.InvalidFileException as exc:
        LOGGER.error("invalid plist: %s", exc)
        raise SystemExit(2) from None

    actions = data.get("WFWorkflowActions") or []
    if not isinstance(actions, list):
        raise SystemExit(2)
    entries: list[ActionEntry] = []
    for idx, action in enumerate(actions):
        params = action.get("WFWorkflowActionParameters") or {}
        entries.append(ActionEntry(
            index=idx,
            identifier=action.get("WFWorkflowActionIdentifier", "?"),
            uuid=params.get("UUID"),
            parameters_snapshot=_canonicalize(params),
        ))
    return entries


def _canonicalize(obj: Any) -> str:
    """Deterministic JSON for semantic comparison.

    Sorts dict keys; datetimes and bytes stringified.
    """
    def default(x: Any) -> Any:
        if isinstance(x, bytes):
            return x.hex()
        if hasattr(x, "isoformat"):
            return x.isoformat()
        return str(x)

    return json.dumps(
        obj,
        sort_keys=True,
        ensure_ascii=False,
        default=default,
    )


def diff(old: list[ActionEntry], new: list[ActionEntry]) -> DiffReport:
    """Compute a semantic diff between two action lists."""
    report = DiffReport()
    old_by_uuid = {e.uuid: e for e in old if e.uuid}
    new_by_uuid = {e.uuid: e for e in new if e.uuid}

    # UUIDed: pair them up
    for uuid, new_entry in new_by_uuid.items():
        old_entry = old_by_uuid.get(uuid)
        if old_entry is None:
            report.added.append(new_entry)
            continue
        if old_entry.parameters_snapshot != new_entry.parameters_snapshot:
            report.modified.append({
                "uuid": uuid,
                "old_index": old_entry.index,
                "new_index": new_entry.index,
                "identifier": new_entry.identifier,
            })
        elif old_entry.index != new_entry.index:
            report.reordered.append({
                "uuid": uuid,
                "old_index": old_entry.index,
                "new_index": new_entry.index,
                "identifier": new_entry.identifier,
            })

    for uuid, old_entry in old_by_uuid.items():
        if uuid not in new_by_uuid:
            report.removed.append(old_entry)

    # Non-UUIDed entries compared positionally
    old_no_uuid = [e for e in old if not e.uuid]
    new_no_uuid = [e for e in new if not e.uuid]
    for pos in range(max(len(old_no_uuid), len(new_no_uuid))):
        old_entry = old_no_uuid[pos] if pos < len(old_no_uuid) else None
        new_entry = new_no_uuid[pos] if pos < len(new_no_uuid) else None
        if old_entry is None and new_entry is not None:
            report.added.append(new_entry)
        elif new_entry is None and old_entry is not None:
            report.removed.append(old_entry)
        elif (
            old_entry is not None
            and new_entry is not None
            and (
                old_entry.identifier != new_entry.identifier
                or old_entry.parameters_snapshot != new_entry.parameters_snapshot
            )
        ):
            report.modified.append({
                "uuid": None,
                "old_index": old_entry.index,
                "new_index": new_entry.index,
                "identifier": new_entry.identifier,
            })

    return report


def emit_human(report: DiffReport) -> None:
    """Print a human-readable diff."""
    if not report.has_changes:
        print("No differences.")
        return
    if report.added:
        print(f"Added ({len(report.added)}):")
        for e in report.added:
            print(
                f"  + [{e.index}] {e.identifier} "
                f"(uuid: {e.uuid or '-'})"
            )
    if report.removed:
        print(f"Removed ({len(report.removed)}):")
        for e in report.removed:
            print(
                f"  - [{e.index}] {e.identifier} "
                f"(uuid: {e.uuid or '-'})"
            )
    if report.modified:
        print(f"Modified ({len(report.modified)}):")
        for m in report.modified:
            print(
                f"  ~ {m['identifier']} "
                f"old_index={m['old_index']} "
                f"new_index={m['new_index']}"
            )
    if report.reordered:
        print(f"Reordered ({len(report.reordered)}):")
        for m in report.reordered:
            print(
                f"  ↔ {m['identifier']} "
                f"{m['old_index']} → {m['new_index']}"
            )


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Semantic diff between two Apple Shortcuts plists.",
    )
    parser.add_argument("old", help="Path to the old plist")
    parser.add_argument("new", help="Path to the new plist")
    parser.add_argument(
        "--human",
        action="store_true",
        help="Human-readable output",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        help="Python log level",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    old = load_actions(Path(args.old))
    new = load_actions(Path(args.new))
    report = diff(old, new)

    if args.human:
        emit_human(report)
    else:
        json.dump(report.to_dict(), sys.stdout, indent=2)
        sys.stdout.write("\n")

    return 1 if report.has_changes else 0


if __name__ == "__main__":
    sys.exit(main())
