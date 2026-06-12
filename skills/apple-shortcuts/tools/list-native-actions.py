#!/usr/bin/env python3
"""List native WFWorkflowActionIdentifier values.

On macOS, attempts to parse App Intents metadata from WorkflowKit
at `/System/Library/PrivateFrameworks/WorkflowKit.framework/
Metadata.appintents/extract.actionsdata`. Falls back to the embedded
index built from `references/actions-native-full-index.md`.

Exit codes:
    0 — success.
    1 — partial success (fallback used).
    2 — fatal error.
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

WORKFLOWKIT_METADATA_PATH = Path(
    "/System/Library/PrivateFrameworks/WorkflowKit.framework/"
    "Metadata.appintents/extract.actionsdata"
)
WORKFLOWKIT_VERSIONS_METADATA = Path(
    "/System/Library/PrivateFrameworks/WorkflowKit.framework/"
    "Versions/A/Resources/Metadata.appintents/extract.actionsdata"
)

EMBEDDED_INDEX: list[dict[str, str]] = [
    {"identifier": "is.workflow.actions.gettext", "name": "Text",
     "category": "content"},
    {"identifier": "is.workflow.actions.text", "name": "Text (legacy)",
     "category": "content"},
    {"identifier": "is.workflow.actions.url", "name": "URL",
     "category": "content"},
    {"identifier": "is.workflow.actions.dictionary", "name": "Dictionary",
     "category": "content"},
    {"identifier": "is.workflow.actions.list", "name": "List",
     "category": "content"},
    {"identifier": "is.workflow.actions.number", "name": "Number",
     "category": "content"},
    {"identifier": "is.workflow.actions.date", "name": "Date",
     "category": "content"},
    {"identifier": "is.workflow.actions.setvariable",
     "name": "Set Variable", "category": "variables"},
    {"identifier": "is.workflow.actions.getvariable",
     "name": "Get Variable", "category": "variables"},
    {"identifier": "is.workflow.actions.appendvariable",
     "name": "Add to Variable", "category": "variables"},
    {"identifier": "is.workflow.actions.conditional",
     "name": "If / Otherwise / End If", "category": "control"},
    {"identifier": "is.workflow.actions.repeat.count",
     "name": "Repeat", "category": "control"},
    {"identifier": "is.workflow.actions.repeat.each",
     "name": "Repeat with Each", "category": "control"},
    {"identifier": "is.workflow.actions.choosefrommenu",
     "name": "Choose from Menu", "category": "control"},
    {"identifier": "is.workflow.actions.delay", "name": "Wait",
     "category": "control"},
    {"identifier": "is.workflow.actions.exit", "name": "Exit Shortcut",
     "category": "control"},
    {"identifier": "is.workflow.actions.nothing", "name": "Nothing",
     "category": "utility"},
    {"identifier": "is.workflow.actions.comment", "name": "Comment",
     "category": "utility"},
    {"identifier": "is.workflow.actions.count", "name": "Count",
     "category": "utility"},
    {"identifier": "is.workflow.actions.downloadurl",
     "name": "Get Contents of URL", "category": "web"},
    {"identifier": "is.workflow.actions.openurl", "name": "Open URLs",
     "category": "web"},
    {"identifier": "is.workflow.actions.url.expand", "name": "Expand URL",
     "category": "web"},
    {"identifier": "is.workflow.actions.url.getheaders",
     "name": "Get Headers of URL", "category": "web"},
    {"identifier": "is.workflow.actions.urlencode", "name": "URL Encode",
     "category": "web"},
    {"identifier": "is.workflow.actions.getwebpagecontents",
     "name": "Get Contents of Web Page", "category": "web"},
    {"identifier": "is.workflow.actions.runjavascriptonwebpage",
     "name": "Run JavaScript on Web Page", "category": "web"},
    {"identifier": "is.workflow.actions.detect.link",
     "name": "Get URLs from Input", "category": "web"},
    {"identifier": "is.workflow.actions.getvalueforkey",
     "name": "Get Dictionary Value", "category": "dict"},
    {"identifier": "is.workflow.actions.setvalueforkey",
     "name": "Set Dictionary Value", "category": "dict"},
    {"identifier": "is.workflow.actions.runworkflow",
     "name": "Run Shortcut", "category": "script"},
    {"identifier": "is.workflow.actions.runsshscript",
     "name": "Run Script over SSH", "category": "script"},
    {"identifier": "is.workflow.actions.hash", "name": "Hash",
     "category": "crypto"},
    {"identifier": "is.workflow.actions.base64encode",
     "name": "Base64 Encode", "category": "encoding"},
    {"identifier": "is.workflow.actions.math", "name": "Calculate",
     "category": "math"},
    {"identifier": "is.workflow.actions.number.random",
     "name": "Random Number", "category": "math"},
    {"identifier": "is.workflow.actions.ask", "name": "Ask for Input",
     "category": "ui"},
    {"identifier": "is.workflow.actions.alert", "name": "Show Alert",
     "category": "ui"},
    {"identifier": "is.workflow.actions.showresult",
     "name": "Show Result", "category": "ui"},
    {"identifier": "is.workflow.actions.viewresult",
     "name": "Quick Look", "category": "ui"},
    {"identifier": "is.workflow.actions.notification",
     "name": "Show Notification", "category": "ui"},
    {"identifier": "is.workflow.actions.speaktext", "name": "Speak Text",
     "category": "speech"},
    {"identifier": "is.workflow.actions.showdefinition",
     "name": "Show Definition", "category": "ui"},
    {"identifier": "is.workflow.actions.choosefromlist",
     "name": "Choose from List", "category": "ui"},
    {"identifier": "is.workflow.actions.setbrightness",
     "name": "Set Brightness", "category": "device"},
    {"identifier": "is.workflow.actions.setvolume", "name": "Set Volume",
     "category": "device"},
    {"identifier": "is.workflow.actions.vibrate",
     "name": "Vibrate Device", "category": "device"},
    {"identifier": "is.workflow.actions.airplanemode.set",
     "name": "Set Airplane Mode", "category": "device"},
    {"identifier": "is.workflow.actions.bluetooth.set",
     "name": "Set Bluetooth", "category": "device"},
    {"identifier": "is.workflow.actions.wifi.set", "name": "Set Wi-Fi",
     "category": "device"},
    {"identifier": "is.workflow.actions.cellulardata.set",
     "name": "Set Cellular Data", "category": "device"},
    {"identifier": "is.workflow.actions.lowpowermode.set",
     "name": "Set Low Power Mode", "category": "device"},
    {"identifier": "is.workflow.actions.flashlight",
     "name": "Set Flashlight", "category": "device"},
    {"identifier": "is.workflow.actions.getbatterylevel",
     "name": "Get Battery Level", "category": "device"},
    {"identifier": "is.workflow.actions.getdevicedetails",
     "name": "Get Device Details", "category": "device"},
    {"identifier": "is.workflow.actions.file.getlink",
     "name": "Get Link to File", "category": "files"},
    {"identifier": "is.workflow.actions.makezip", "name": "Make Archive",
     "category": "files"},
    {"identifier": "is.workflow.actions.unzip",
     "name": "Extract Archive", "category": "files"},
    {"identifier": "is.workflow.actions.print", "name": "Print",
     "category": "output"},
    {"identifier": "is.workflow.actions.previewdocument",
     "name": "Quick Look", "category": "ui"},
    {"identifier": "is.workflow.actions.getlastphoto",
     "name": "Get Latest Photos", "category": "photos"},
    {"identifier": "is.workflow.actions.getlastvideo",
     "name": "Get Latest Video", "category": "photos"},
    {"identifier": "is.workflow.actions.getlastscreenshot",
     "name": "Get Latest Screenshot", "category": "photos"},
    {"identifier": "is.workflow.actions.deletephotos",
     "name": "Delete Photos", "category": "photos"},
    {"identifier": "is.workflow.actions.trimvideo",
     "name": "Trim Media", "category": "media"},
    {"identifier": "is.workflow.actions.playsound", "name": "Play Sound",
     "category": "media"},
    {"identifier": "is.workflow.actions.scanbarcode",
     "name": "Scan QR/Barcode", "category": "camera"},
    {"identifier": "is.workflow.actions.pausemusic", "name": "Play/Pause",
     "category": "music"},
    {"identifier": "is.workflow.actions.skipback", "name": "Skip Back",
     "category": "music"},
    {"identifier": "is.workflow.actions.skipforward",
     "name": "Skip Forward", "category": "music"},
    {"identifier": "is.workflow.actions.getcurrentsong",
     "name": "Get Current Song", "category": "music"},
    {"identifier": "is.workflow.actions.share", "name": "Share",
     "category": "comms"},
    {"identifier": "is.workflow.actions.airdropdocument", "name": "AirDrop",
     "category": "comms"},
    {"identifier": "is.workflow.actions.readinglist",
     "name": "Add to Reading List", "category": "comms"},
    {"identifier": "is.workflow.actions.detect.contacts",
     "name": "Get Contacts from Input", "category": "detect"},
    {"identifier": "is.workflow.actions.detect.emailaddress",
     "name": "Get Email Addresses from Input", "category": "detect"},
    {"identifier": "is.workflow.actions.detect.phonenumber",
     "name": "Get Phone Numbers from Input", "category": "detect"},
    {"identifier": "is.workflow.actions.detect.images",
     "name": "Get Images from Input", "category": "detect"},
    {"identifier": "is.workflow.actions.format.date", "name": "Format Date",
     "category": "date"},
    {"identifier": "is.workflow.actions.text.changecase",
     "name": "Change Case", "category": "text"},
    {"identifier": "is.workflow.actions.text.match", "name": "Match Text",
     "category": "text"},
    {"identifier": "is.workflow.actions.text.replace",
     "name": "Replace Text", "category": "text"},
    {"identifier": "is.workflow.actions.text.split", "name": "Split Text",
     "category": "text"},
    {"identifier": "is.workflow.actions.text.combine",
     "name": "Combine Text", "category": "text"},
    {"identifier": "is.workflow.actions.getitemfromlist",
     "name": "Get Item from List", "category": "list"},
    {"identifier": "is.workflow.actions.getclipboard",
     "name": "Get Clipboard", "category": "clipboard"},
    {"identifier": "is.workflow.actions.setclipboard",
     "name": "Set Clipboard", "category": "clipboard"},
    {"identifier": "is.workflow.actions.getitemname", "name": "Get Name",
     "category": "utility"},
    {"identifier": "is.workflow.actions.setitemname", "name": "Set Name",
     "category": "utility"},
    {"identifier": "is.workflow.actions.getitemtype", "name": "Get Type",
     "category": "utility"},
    {"identifier": "is.workflow.actions.alarm.create", "name": "Create Alarm",
     "category": "alarm"},
    {"identifier": "is.workflow.actions.showincalendar",
     "name": "Show in Calendar", "category": "calendar"},
    {"identifier": "is.workflow.actions.getarticle", "name": "Get Article",
     "category": "reader"},
]


@dataclass
class Result:
    """Tool output container."""

    platform: str
    source: str
    actions: list[dict[str, Any]]
    notes: list[str]


def try_parse_workflowkit() -> list[dict[str, Any]] | None:
    """Try to parse WorkflowKit's App Intents metadata (macOS only).

    Returns:
        List of action dicts, or None if parsing failed.
    """
    for candidate in (
        WORKFLOWKIT_METADATA_PATH,
        WORKFLOWKIT_VERSIONS_METADATA,
    ):
        if candidate.exists():
            try:
                with candidate.open("rb") as fh:
                    data = plistlib.load(fh)
            except Exception as exc:
                LOGGER.debug("parse failed for %s: %s", candidate, exc)
                continue
            actions = _walk_for_identifiers(data)
            if actions:
                return actions
    return None


def _walk_for_identifiers(node: Any) -> list[dict[str, Any]]:
    """Heuristically extract identifier-like entries from nested data."""
    found: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _walk(x: Any) -> None:
        if isinstance(x, dict):
            ident = None
            for key in (
                "intentClassName",
                "actionIdentifier",
                "identifier",
                "intent",
            ):
                v = x.get(key)
                if isinstance(v, str) and "is.workflow.actions." in v:
                    ident = v
                    break
            if ident and ident not in seen:
                seen.add(ident)
                found.append({
                    "identifier": ident,
                    "name": x.get("title") or x.get("name"),
                    "category": x.get("category") or "unknown",
                    "source": "WorkflowKit",
                })
            for v in x.values():
                _walk(v)
        elif isinstance(x, list):
            for v in x:
                _walk(v)

    _walk(node)
    return found


def emit_human(result: Result) -> None:
    """Print a human-readable table."""
    print(f"Platform: {result.platform}")
    print(f"Source:   {result.source}")
    print(f"Actions:  {len(result.actions)}")
    for note in result.notes:
        print(f"Note:     {note}")
    print()
    for action in result.actions:
        name = action.get("name") or "?"
        category = action.get("category") or "?"
        print(
            f"  {action['identifier']:<55} {category:<15} {name}"
        )


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="List native WFWorkflowActionIdentifier values.",
    )
    parser.add_argument(
        "--human",
        action="store_true",
        help="Human-readable output",
    )
    parser.add_argument(
        "--force-fallback",
        action="store_true",
        help="Skip WorkflowKit parsing; use embedded index only",
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

    notes: list[str] = []
    parsed: list[dict[str, Any]] | None = None
    source = "embedded"

    if sys.platform == "darwin" and not args.force_fallback:
        parsed = try_parse_workflowkit()
        if parsed:
            source = "WorkflowKit"
        else:
            notes.append(
                "WorkflowKit metadata not parseable; using embedded index"
            )
    elif sys.platform != "darwin":
        notes.append(
            "not running on macOS; WorkflowKit unavailable, using "
            "embedded index"
        )

    actions = parsed if parsed else [
        {**entry, "source": "embedded"} for entry in EMBEDDED_INDEX
    ]

    result = Result(
        platform=sys.platform,
        source=source,
        actions=actions,
        notes=notes,
    )

    if args.human:
        emit_human(result)
    else:
        json.dump({
            "platform": result.platform,
            "source": result.source,
            "notes": result.notes,
            "actions": result.actions,
        }, sys.stdout, indent=2)
        sys.stdout.write("\n")

    # Fallback used on macOS is exit 1; embedded-only on non-mac is 0
    if sys.platform == "darwin" and source == "embedded":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
