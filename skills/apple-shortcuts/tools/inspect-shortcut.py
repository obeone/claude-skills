#!/usr/bin/env python3
"""Inspect an Apple Shortcuts .shortcut or .plist file.

Produces a structured view of: envelope metadata, action list,
declared variables (Set Variable targets), magic variables (action
UUIDs with output names), detected third-party app bundles, and
warnings for unknown identifiers or deprecated actions.

Exit codes:
    0 — inspection succeeded.
    2 — could not read / parse input.
"""

from __future__ import annotations

import argparse
import json
import logging
import plistlib
import sys
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

THIRD_PARTY_PREFIXES = [
    ("com.sindresorhus.Actions", "Actions (Sindre Sorhus)"),
    ("dk.simonbs.datajar", "Data Jar"),
    ("com.tinyrobot.ToolboxPro", "Toolbox Pro"),
    ("dk.simonbs.Scriptable", "Scriptable"),
    ("AsheKube.app.a-Shell", "a-Shell"),
    ("dk.simonbs.Jayson", "Jayson"),
    ("de.sostudio.Pushcut", "Pushcut"),
    ("com.omz-software.Pythonista", "Pythonista"),
]

DEPRECATED_IDENTIFIERS = {
    "is.workflow.actions.postonfacebook": "Facebook integration removed",
    "is.workflow.actions.tweet": "Twitter integration removed in iOS 11+",
    "is.workflow.actions.tumblr.post": "Tumblr sharing deprecated",
    "is.workflow.actions.wordpress.post": "WordPress sharing deprecated",
    "is.workflow.actions.avairyeditphoto": "Aviary editor retired",
}


def load_plist(path: Path) -> dict[str, Any]:
    """Load a plist. Supports XML and binary."""
    try:
        with path.open("rb") as fh:
            data = plistlib.load(fh)
    except FileNotFoundError:
        LOGGER.error("file not found: %s", path)
        raise SystemExit(2) from None
    except plistlib.InvalidFileException as exc:
        LOGGER.error("invalid plist: %s", exc)
        raise SystemExit(2) from None
    if not isinstance(data, dict):
        LOGGER.error("root is not a dict")
        raise SystemExit(2)
    return data


def action_identifier(action: dict[str, Any]) -> str:
    """Return the action's identifier or '?' if missing."""
    return action.get("WFWorkflowActionIdentifier", "?")


def detect_third_party(identifier: str) -> str | None:
    """Return the human app name for a third-party identifier, else None."""
    for prefix, name in THIRD_PARTY_PREFIXES:
        if identifier.startswith(prefix):
            return name
    return None


def extract_magic_variables(
    actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return a list of {index, uuid, output_name, identifier} entries."""
    magic: list[dict[str, Any]] = []
    for idx, action in enumerate(actions):
        params = action.get("WFWorkflowActionParameters") or {}
        uuid = params.get("UUID")
        if not uuid:
            continue
        magic.append({
            "index": idx,
            "uuid": uuid,
            "output_name": params.get("CustomOutputName"),
            "identifier": action_identifier(action),
        })
    return magic


def extract_named_variables(
    actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return a list of {index, name, action} for Set/Get Variable actions."""
    named: list[dict[str, Any]] = []
    for idx, action in enumerate(actions):
        identifier = action_identifier(action)
        params = action.get("WFWorkflowActionParameters") or {}
        if identifier == "is.workflow.actions.setvariable":
            named.append({
                "index": idx,
                "operation": "set",
                "name": params.get("WFVariableName"),
            })
        elif identifier == "is.workflow.actions.appendvariable":
            named.append({
                "index": idx,
                "operation": "append",
                "name": params.get("WFVariableName"),
            })
        elif identifier == "is.workflow.actions.getvariable":
            name = None
            var = params.get("WFVariable")
            if isinstance(var, dict):
                value = var.get("Value") or {}
                name = value.get("VariableName") if isinstance(value, dict) else None
            named.append({
                "index": idx,
                "operation": "get",
                "name": name,
            })
    return named


def detect_third_party_apps(
    actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return distinct third-party apps referenced in identifiers."""
    seen: dict[str, str] = {}
    for action in actions:
        identifier = action_identifier(action)
        if identifier.startswith("is.workflow.actions.") or identifier == "?":
            continue
        app = detect_third_party(identifier) or "unknown third-party"
        seen.setdefault(identifier.split(".", 3)[0:3][-1], app)
        # Record under a key that roughly represents the bundle prefix
        for prefix, name in THIRD_PARTY_PREFIXES:
            if identifier.startswith(prefix):
                seen[prefix] = name
                break
        else:
            # Fallback: reverse-DNS first three components
            parts = identifier.split(".")
            if len(parts) >= 3:
                seen[".".join(parts[:3])] = app
    return [
        {"bundle_prefix": prefix, "app_name": name}
        for prefix, name in sorted(seen.items())
    ]


def collect_warnings(actions: list[dict[str, Any]]) -> list[str]:
    """Return warnings about deprecated or suspect actions."""
    warnings: list[str] = []
    for idx, action in enumerate(actions):
        identifier = action_identifier(action)
        if identifier in DEPRECATED_IDENTIFIERS:
            warnings.append(
                f"action {idx}: {identifier} — "
                f"{DEPRECATED_IDENTIFIERS[identifier]}"
            )
    return warnings


def build_summary(plist: dict[str, Any]) -> dict[str, Any]:
    """Produce the structured summary dict."""
    actions = plist.get("WFWorkflowActions") or []
    actions = actions if isinstance(actions, list) else []
    action_list = [
        {
            "index": idx,
            "identifier": action_identifier(action),
            "custom_output_name": (
                action.get("WFWorkflowActionParameters") or {}
            ).get("CustomOutputName"),
            "uuid": (
                action.get("WFWorkflowActionParameters") or {}
            ).get("UUID"),
        }
        for idx, action in enumerate(actions)
    ]
    icon = plist.get("WFWorkflowIcon") or {}
    return {
        "envelope": {
            "client_version": plist.get("WFWorkflowClientVersion"),
            "minimum_client_version": plist.get(
                "WFWorkflowMinimumClientVersion"
            ),
            "workflow_types": plist.get("WFWorkflowTypes") or [],
            "input_content_item_classes": plist.get(
                "WFWorkflowInputContentItemClasses"
            ) or [],
            "icon_glyph": icon.get("WFWorkflowIconGlyphNumber"),
            "icon_color": icon.get("WFWorkflowIconStartColor"),
            "import_questions_count": len(
                plist.get("WFWorkflowImportQuestions") or []
            ),
        },
        "action_count": len(actions),
        "actions": action_list,
        "magic_variables": extract_magic_variables(actions),
        "named_variables": extract_named_variables(actions),
        "third_party_apps": detect_third_party_apps(actions),
        "warnings": collect_warnings(actions),
    }


def emit_human(summary: dict[str, Any]) -> None:
    """Print a human-readable summary."""
    env = summary["envelope"]
    print(
        f"Shortcut — {summary['action_count']} actions, "
        f"client {env['client_version']}, "
        f"min {env['minimum_client_version']}"
    )
    types = env.get("workflow_types") or []
    if types:
        print(f"Types: {', '.join(types)}")
    if summary["third_party_apps"]:
        apps = ", ".join(a["app_name"] for a in summary["third_party_apps"])
        print(f"Third-party: {apps}")
    print()
    print("Actions:")
    for a in summary["actions"]:
        label = a["identifier"]
        if a.get("custom_output_name"):
            label += f"  [{a['custom_output_name']}]"
        print(f"  {a['index']:3d}. {label}")
    if summary["named_variables"]:
        print()
        print("Named variables:")
        for v in summary["named_variables"]:
            print(f"  action {v['index']}: {v['operation']} {v['name']!r}")
    if summary["warnings"]:
        print()
        print("Warnings:")
        for w in summary["warnings"]:
            print(f"  - {w}")


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Inspect an Apple Shortcuts plist or .shortcut file.",
    )
    parser.add_argument("path", help="Path to the plist or .shortcut file")
    parser.add_argument(
        "--human",
        action="store_true",
        help="Human-readable output instead of JSON",
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

    path = Path(args.path)
    plist = load_plist(path)
    summary = build_summary(plist)

    if args.human:
        emit_human(summary)
    else:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
