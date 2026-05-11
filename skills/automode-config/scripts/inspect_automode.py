#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Inspect autoMode state across the 3 settings files.

Reports for each of (``user``, ``shared``, ``local``) whether the file
exists, the canonical SHA-256 of its ``autoMode`` payload (if any), and
whether that hash matches the value cached in
``.claude/.auto_mode_approved.json``.

CLI flags
---------
--project-root <path>         Default: cwd.
--show-drift                  Compare canonical bytes vs approved cache.
                              Exit 6 on any drift.
--json                        Machine-readable output.
--file {user,shared,local,all}  Default: ``all``.

Exit codes
----------
0  EXIT_OK         Normal report (or no drift when --show-drift set).
6  EXIT_DRIFT      ``--show-drift`` set and at least one file's hash
                   does not match the cache.

Stdlib-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _canonical import canonicalize, load_json  # noqa: E402
from _paths import ProjectFiles, resolve  # noqa: E402


EXIT_OK = 0
EXIT_DRIFT = 6


def _automode_block(data: Any) -> Any | None:
    if not isinstance(data, dict):
        return None
    return data.get("autoMode")


def _hash_canonical(obj: Any) -> str:
    return hashlib.sha256(canonicalize(obj)).hexdigest()


def _load_approved_cache(path: Path) -> dict[str, dict[str, str]]:
    """Return the approved-cache map; empty dict if absent or malformed.

    Schema (forward-compatible):
    ``{"user": {"hash": "..."}, "shared": {...}, "local": {...}}``
    """

    if not path.is_file():
        return {}
    try:
        data = load_json(path)
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for key in ("user", "shared", "local"):
        entry = data.get(key)
        if isinstance(entry, dict) and isinstance(entry.get("hash"), str):
            out[key] = {"hash": entry["hash"]}
    return out


def _inspect_one(label: str, path: Path) -> dict[str, Any]:
    """Return inspection record for ``path`` (one of user/shared/local)."""

    record: dict[str, Any] = {
        "label": label,
        "path": str(path),
        "exists": path.is_file(),
        "automode_present": False,
        "canonical_sha256": None,
        "parse_error": None,
    }
    if not record["exists"]:
        return record
    try:
        data = load_json(path)
    except FileNotFoundError:
        record["exists"] = False
        return record
    except Exception as exc:  # noqa: BLE001
        record["parse_error"] = str(exc)
        return record
    auto = _automode_block(data)
    if auto is None:
        return record
    record["automode_present"] = True
    record["canonical_sha256"] = _hash_canonical(auto)
    return record


def build_report(
    files: ProjectFiles,
    *,
    selected: tuple[str, ...] = ("user", "shared", "local"),
) -> dict[str, Any]:
    """Build the multi-file inspection report."""

    targets = {
        "user": files.user_settings,
        "shared": files.shared_settings,
        "local": files.local_settings,
    }
    approved = _load_approved_cache(files.approved_cache)

    files_report: dict[str, dict[str, Any]] = {}
    drift = False
    for label in selected:
        rec = _inspect_one(label, targets[label])
        cached = approved.get(label, {}).get("hash")
        rec["approved_sha256"] = cached
        if rec["automode_present"] and cached is not None:
            rec["drift"] = rec["canonical_sha256"] != cached
        elif rec["automode_present"] and cached is None:
            rec["drift"] = True
        elif not rec["automode_present"] and cached is not None:
            rec["drift"] = True
        else:
            rec["drift"] = False
        if rec["drift"]:
            drift = True
        files_report[label] = rec

    return {
        "project_root": str(files.project_root),
        "approved_cache_path": str(files.approved_cache),
        "approved_cache_present": files.approved_cache.is_file(),
        "files": files_report,
        "any_drift": drift,
    }


def _emit_human(report: dict[str, Any]) -> None:
    out = sys.stdout
    out.write(f"project_root: {report['project_root']}\n")
    out.write(
        f"approved cache: {report['approved_cache_path']}"
        f"  ({'present' if report['approved_cache_present'] else 'absent'})\n"
    )
    out.write("\n")
    for label, rec in report["files"].items():
        present = "yes" if rec["exists"] else "no"
        am = "yes" if rec["automode_present"] else "no"
        out.write(f"[{label}]  {rec['path']}\n")
        out.write(f"  exists:           {present}\n")
        out.write(f"  autoMode present: {am}\n")
        if rec["parse_error"]:
            out.write(f"  parse error:      {rec['parse_error']}\n")
            continue
        if rec["canonical_sha256"]:
            out.write(f"  canonical sha256: {rec['canonical_sha256']}\n")
        if rec["approved_sha256"]:
            out.write(f"  approved sha256:  {rec['approved_sha256']}\n")
        out.write(f"  drift:            {'yes' if rec['drift'] else 'no'}\n")
        out.write("\n")
    out.write(f"any drift: {'yes' if report['any_drift'] else 'no'}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="inspect_automode.py",
        description="Inspect autoMode state in user/shared/local settings.",
    )
    parser.add_argument(
        "--project-root",
        default=str(Path.cwd()),
        help="Project root to inspect (default: cwd).",
    )
    parser.add_argument(
        "--show-drift",
        action="store_true",
        help="Compare canonical bytes vs approved cache; exit 6 on drift.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    parser.add_argument(
        "--file",
        choices=("user", "shared", "local", "all"),
        default="all",
        help="Which file to report on (default: all).",
    )
    args = parser.parse_args(argv)

    selected: tuple[str, ...]
    if args.file == "all":
        selected = ("user", "shared", "local")
    else:
        selected = (args.file,)

    files = resolve(args.project_root)
    report = build_report(files, selected=selected)

    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        _emit_human(report)

    if args.show_drift and report["any_drift"]:
        return EXIT_DRIFT
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
