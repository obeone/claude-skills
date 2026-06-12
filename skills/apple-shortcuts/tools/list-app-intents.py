#!/usr/bin/env python3
"""Scan installed apps for App Intents metadata.

For each app with `Contents/Resources/Metadata.appintents/extract
.actionsdata`, report the bundle ID and attempt to extract action
identifiers. When the binary format resists parsing, report
`parseable: false` with the bundle details so callers can follow up.

Scans by default:
    /Applications
    ~/Applications

Requires macOS.

Exit codes:
    0 — success.
    2 — not on macOS or fatal error.
"""

from __future__ import annotations

import argparse
import json
import logging
import plistlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

DEFAULT_SCAN_DIRS = [
    Path("/Applications"),
    Path.home() / "Applications",
]
SYSTEM_APPLICATIONS = Path("/System/Applications")


@dataclass
class AppReport:
    """Per-app intent extraction result."""

    bundle_id: str | None
    app_name: str
    app_path: str
    parseable: bool
    action_count: int
    actions: list[dict[str, Any]]
    error: str | None = None


def read_info_plist(app_bundle: Path) -> dict[str, Any]:
    """Load Info.plist from an app bundle."""
    info_path = app_bundle / "Contents" / "Info.plist"
    if not info_path.exists():
        return {}
    try:
        with info_path.open("rb") as fh:
            return plistlib.load(fh)
    except Exception as exc:
        LOGGER.debug("Info.plist parse failed for %s: %s", app_bundle, exc)
        return {}


def find_app_intents_metadata(app_bundle: Path) -> Path | None:
    """Locate the extract.actionsdata file inside the app bundle."""
    candidates = [
        app_bundle / "Contents" / "Resources" / "Metadata.appintents"
        / "extract.actionsdata",
        app_bundle / "Metadata.appintents" / "extract.actionsdata",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def extract_actions(metadata_path: Path) -> tuple[bool, list[dict[str, Any]], str | None]:
    """Attempt to parse extract.actionsdata.

    Returns:
        (parseable, actions, error_message).
    """
    try:
        with metadata_path.open("rb") as fh:
            data = plistlib.load(fh)
    except plistlib.InvalidFileException as exc:
        return False, [], f"not a plist: {exc}"
    except Exception as exc:
        return False, [], f"parse error: {exc}"

    actions = _walk_for_intents(data)
    return True, actions, None


def _walk_for_intents(node: Any) -> list[dict[str, Any]]:
    """Heuristic walk to find intent/action identifiers."""
    found: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _walk(x: Any, parent_title: str | None = None) -> None:
        if isinstance(x, dict):
            ident = None
            title = x.get("title") or x.get("name") or parent_title
            for key in (
                "intentClassName",
                "actionIdentifier",
                "identifier",
                "$className",
                "className",
            ):
                v = x.get(key)
                if isinstance(v, str) and "." in v:
                    ident = v
                    break
            if ident and ident not in seen:
                seen.add(ident)
                found.append({
                    "identifier": ident,
                    "title": title,
                })
            for v in x.values():
                _walk(v, title)
        elif isinstance(x, list):
            for v in x:
                _walk(v, parent_title)

    _walk(node)
    return found


def inspect_app(app_bundle: Path) -> AppReport | None:
    """Return an AppReport if the bundle carries App Intents metadata."""
    metadata_path = find_app_intents_metadata(app_bundle)
    if metadata_path is None:
        return None
    info = read_info_plist(app_bundle)
    bundle_id = info.get("CFBundleIdentifier")
    app_name = info.get("CFBundleName") or app_bundle.stem
    parseable, actions, error = extract_actions(metadata_path)
    return AppReport(
        bundle_id=bundle_id,
        app_name=app_name,
        app_path=str(app_bundle),
        parseable=parseable,
        action_count=len(actions),
        actions=actions,
        error=error,
    )


def find_bundle_by_id(
    search_dirs: list[Path], bundle_id: str
) -> Path | None:
    """Locate an app bundle by CFBundleIdentifier. First match wins."""
    for directory in search_dirs:
        if not directory.exists():
            continue
        for app in directory.glob("*.app"):
            info = read_info_plist(app)
            if info.get("CFBundleIdentifier") == bundle_id:
                return app
    return None


def scan_directory(directory: Path) -> list[AppReport]:
    """Report all apps under a directory that expose App Intents."""
    reports: list[AppReport] = []
    if not directory.exists():
        return reports
    for app in sorted(directory.glob("*.app")):
        try:
            report = inspect_app(app)
        except Exception as exc:
            LOGGER.debug("inspect failed for %s: %s", app, exc)
            continue
        if report is not None:
            reports.append(report)
    return reports


def serialize(report: AppReport, include_actions: bool) -> dict[str, Any]:
    """Serialize for JSON output."""
    payload: dict[str, Any] = {
        "bundle_id": report.bundle_id,
        "app_name": report.app_name,
        "app_path": report.app_path,
        "parseable": report.parseable,
        "action_count": report.action_count,
    }
    if include_actions:
        payload["actions"] = report.actions
    if report.error:
        payload["error"] = report.error
    return payload


def emit_human(reports: list[AppReport]) -> None:
    """Print a human-readable summary."""
    print(f"Scanned {len(reports)} apps with App Intents metadata.\n")
    for r in reports:
        flag = "parseable" if r.parseable else "NOT parseable"
        print(
            f"- {r.app_name} ({r.bundle_id or 'unknown'}) — "
            f"{r.action_count} actions, {flag}"
        )
        if r.error:
            print(f"  error: {r.error}")
        for action in r.actions[:10]:
            title = action.get("title") or "?"
            print(f"    {action['identifier']}  {title}")
        if r.action_count > 10:
            print(f"    ...and {r.action_count - 10} more")


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Scan for App Intents and list their action identifiers.",
    )
    parser.add_argument(
        "--bundle",
        help=(
            "CFBundleIdentifier to target (e.g. com.sindresorhus.Actions). "
            "Skips directory scan."
        ),
    )
    parser.add_argument(
        "--dir",
        action="append",
        dest="dirs",
        help=(
            "Directory to scan (defaults to /Applications and "
            "~/Applications). Repeatable."
        ),
    )
    parser.add_argument(
        "--include-system",
        action="store_true",
        help="Also scan /System/Applications",
    )
    parser.add_argument(
        "--human",
        action="store_true",
        help="Human-readable output",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Include full action lists in JSON output",
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

    if sys.platform != "darwin":
        LOGGER.error("this tool only runs on macOS")
        return 2

    search_dirs = [Path(d) for d in args.dirs] if args.dirs else list(DEFAULT_SCAN_DIRS)
    if args.include_system:
        search_dirs.append(SYSTEM_APPLICATIONS)

    reports: list[AppReport] = []
    if args.bundle:
        app = find_bundle_by_id(search_dirs, args.bundle)
        if app is None:
            LOGGER.error("no app found with bundle ID %s", args.bundle)
            return 1
        r = inspect_app(app)
        if r is None:
            LOGGER.error("app %s has no App Intents metadata", args.bundle)
            return 1
        reports.append(r)
    else:
        for directory in search_dirs:
            reports.extend(scan_directory(directory))

    if args.human:
        emit_human(reports)
    else:
        json.dump({
            "platform": sys.platform,
            "scanned_dirs": [str(d) for d in search_dirs],
            "apps": [serialize(r, include_actions=args.full) for r in reports],
        }, sys.stdout, indent=2)
        sys.stdout.write("\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
