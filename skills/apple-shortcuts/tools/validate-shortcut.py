#!/usr/bin/env python3
"""Validate an Apple Shortcuts plist against the envelope and
per-action rules documented in this skill.

Exit codes:
    0 — valid.
    1 — invalid (errors reported).
    2 — could not read / parse input.
"""

from __future__ import annotations

import argparse
import json
import logging
import plistlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

LEGAL_CONTENT_ITEM_CLASSES = {
    "WFAppStoreAppContentItem",
    "WFArticleContentItem",
    "WFContactContentItem",
    "WFDateContentItem",
    "WFEmailAddressContentItem",
    "WFGenericFileContentItem",
    "WFImageContentItem",
    "WFiTunesProductContentItem",
    "WFLocationContentItem",
    "WFDCMapsLinkContentItem",
    "WFAVAssetContentItem",
    "WFPDFContentItem",
    "WFPhoneNumberContentItem",
    "WFRichTextContentItem",
    "WFSafariWebPageContentItem",
    "WFStringContentItem",
    "WFURLContentItem",
    # Coercion classes also accepted as valid
    "WFNumberContentItem",
    "WFBooleanContentItem",
    "WFDictionaryContentItem",
    "WFArrayContentItem",
}

LEGAL_WORKFLOW_TYPES = {
    "MenuBar",
    "QuickActions",
    "ActionExtension",
    "NCWidget",
    "Sleep",
    "Watch",
    "WatchKit",
}

LEGAL_SERIALIZATION_TYPES = {
    "WFTextTokenString",
    "WFTextTokenAttachment",
    "WFDictionaryFieldValue",
    "WFArrayParameterState",
    "WFNumberSubstitutableState",
    "WFContactFieldValue",
    "WFEmailAddressFieldValue",
    "WFGenericFieldValue",
}

CONTROL_FLOW_IDENTIFIERS = {
    "is.workflow.actions.conditional",
    "is.workflow.actions.repeat.count",
    "is.workflow.actions.repeat.each",
    "is.workflow.actions.choosefrommenu",
}

RANGE_KEY_RE = re.compile(r"^\{\s*(\d+)\s*,\s*(\d+)\s*\}$")
OBJECT_REPLACEMENT_CHAR = "\ufffc"
UUID_RE = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)


@dataclass
class Issue:
    """A validation finding."""

    severity: str  # "error" | "warning"
    message: str
    action_index: int | None = None


@dataclass
class Report:
    """Aggregate validation output."""

    valid: bool = True
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    def error(self, message: str, action_index: int | None = None) -> None:
        """Record an error."""
        self.valid = False
        self.errors.append(Issue("error", message, action_index))

    def warn(self, message: str, action_index: int | None = None) -> None:
        """Record a warning."""
        self.warnings.append(Issue("warning", message, action_index))

    def to_dict(self) -> dict[str, Any]:
        """Dict-serialize for JSON output."""
        return {
            "valid": self.valid,
            "errors": [self._issue_dict(i) for i in self.errors],
            "warnings": [self._issue_dict(i) for i in self.warnings],
        }

    @staticmethod
    def _issue_dict(issue: Issue) -> dict[str, Any]:
        """Serialize one issue."""
        payload: dict[str, Any] = {"message": issue.message}
        if issue.action_index is not None:
            payload["action_index"] = issue.action_index
        return payload


def load_plist(path: Path) -> dict[str, Any]:
    """Load a plist from disk. Supports XML and binary plist.

    Args:
        path: Filesystem path to the plist file.

    Returns:
        The top-level dict of the plist.

    Raises:
        SystemExit: If the file is unreadable or not a dict.
    """
    try:
        with path.open("rb") as fh:
            data = plistlib.load(fh)
    except FileNotFoundError:
        LOGGER.error("file not found: %s", path)
        raise SystemExit(2) from None
    except plistlib.InvalidFileException as exc:
        LOGGER.error("invalid plist: %s: %s", path, exc)
        raise SystemExit(2) from None
    if not isinstance(data, dict):
        LOGGER.error("plist root is not a dict")
        raise SystemExit(2)
    return data


def validate_envelope(plist: dict[str, Any], report: Report) -> None:
    """Check required top-level keys and their basic shape."""
    actions = plist.get("WFWorkflowActions")
    if actions is None:
        report.error("missing required key WFWorkflowActions")
    elif not isinstance(actions, list):
        report.error("WFWorkflowActions must be an array")

    input_classes = plist.get("WFWorkflowInputContentItemClasses")
    if input_classes is None:
        report.warn("missing WFWorkflowInputContentItemClasses (default to [])")
    elif not isinstance(input_classes, list):
        report.error("WFWorkflowInputContentItemClasses must be an array")
    else:
        for cls in input_classes:
            if cls not in LEGAL_CONTENT_ITEM_CLASSES:
                report.warn(f"unknown content item class: {cls}")

    wf_types = plist.get("WFWorkflowTypes", [])
    if wf_types and isinstance(wf_types, list):
        for t in wf_types:
            if t not in LEGAL_WORKFLOW_TYPES:
                report.warn(f"unknown WFWorkflowTypes value: {t}")

    min_ver = plist.get("WFWorkflowMinimumClientVersion")
    if min_ver is not None and not isinstance(min_ver, int):
        report.error("WFWorkflowMinimumClientVersion must be an integer")

    icon = plist.get("WFWorkflowIcon")
    if icon is not None:
        if not isinstance(icon, dict):
            report.error("WFWorkflowIcon must be a dict")
        else:
            glyph = icon.get("WFWorkflowIconGlyphNumber")
            color = icon.get("WFWorkflowIconStartColor")
            if glyph is not None and not isinstance(glyph, int):
                report.error("WFWorkflowIconGlyphNumber must be an integer")
            if color is not None and not isinstance(color, int):
                report.error("WFWorkflowIconStartColor must be an integer")


def collect_uuids(
    actions: list[dict[str, Any]],
    report: Report,
) -> dict[str, int]:
    """Collect UUID → action_index, reporting duplicates.

    Returns:
        Mapping of UUID strings to the index of the producing action.
    """
    uuids: dict[str, int] = {}
    for index, action in enumerate(actions):
        params = action.get("WFWorkflowActionParameters") or {}
        uuid = params.get("UUID")
        if uuid is None:
            continue
        if not isinstance(uuid, str) or not UUID_RE.match(uuid):
            report.warn(f"UUID is not a canonical UUIDv4: {uuid}", index)
        if uuid in uuids:
            report.error(
                f"duplicate UUID {uuid} at action {index} "
                f"(first at {uuids[uuid]})",
                index,
            )
        else:
            uuids[uuid] = index
    return uuids


def validate_action_shape(
    action: dict[str, Any],
    index: int,
    report: Report,
) -> None:
    """Check top-level action dict shape."""
    if not isinstance(action, dict):
        report.error(f"action {index} is not a dict", index)
        return
    identifier = action.get("WFWorkflowActionIdentifier")
    if identifier is None:
        report.error("missing WFWorkflowActionIdentifier", index)
    elif not isinstance(identifier, str):
        report.error("WFWorkflowActionIdentifier must be a string", index)
    params = action.get("WFWorkflowActionParameters")
    if params is not None and not isinstance(params, dict):
        report.error("WFWorkflowActionParameters must be a dict", index)


def validate_control_flow(
    actions: list[dict[str, Any]],
    report: Report,
) -> None:
    """Check paired start/middle/end for control-flow actions."""
    # group_id -> list of (action_index, mode)
    groups: dict[str, list[tuple[int, int]]] = {}
    for index, action in enumerate(actions):
        identifier = action.get("WFWorkflowActionIdentifier", "")
        if identifier not in CONTROL_FLOW_IDENTIFIERS:
            continue
        params = action.get("WFWorkflowActionParameters") or {}
        group_id = params.get("GroupingIdentifier")
        mode = params.get("WFControlFlowMode")
        if group_id is None:
            report.error(
                f"control flow action missing GroupingIdentifier",
                index,
            )
            continue
        if not isinstance(mode, int):
            report.error(
                f"WFControlFlowMode must be integer (got {type(mode).__name__})",
                index,
            )
            continue
        if mode not in (0, 1, 2):
            report.error(
                f"WFControlFlowMode must be 0, 1, or 2 (got {mode})",
                index,
            )
            continue
        groups.setdefault(group_id, []).append((index, mode))

    for group_id, entries in groups.items():
        modes = [m for _, m in entries]
        starts = modes.count(0)
        ends = modes.count(2)
        if starts != 1:
            first_idx = entries[0][0]
            report.error(
                f"group {group_id} should have exactly one mode 0 "
                f"(found {starts})",
                first_idx,
            )
        if ends != 1:
            first_idx = entries[0][0]
            report.error(
                f"group {group_id} should have exactly one mode 2 "
                f"(found {ends})",
                first_idx,
            )
        # Order: start must come before end
        start_indices = [idx for idx, m in entries if m == 0]
        end_indices = [idx for idx, m in entries if m == 2]
        if start_indices and end_indices:
            if start_indices[0] > end_indices[0]:
                report.error(
                    f"group {group_id}: start (mode 0) appears "
                    f"after end (mode 2)",
                    start_indices[0],
                )


def validate_variable_references(
    actions: list[dict[str, Any]],
    uuid_index: dict[str, int],
    report: Report,
) -> None:
    """Walk parameters recursively; check OutputUUID references.

    An action at index N may reference only UUIDs produced at index < N.
    Also checks U+FFFC counts vs attachmentsByRange entries.
    """
    for index, action in enumerate(actions):
        params = action.get("WFWorkflowActionParameters") or {}
        _walk_parameters(params, index, uuid_index, report)


def _walk_parameters(
    node: Any,
    action_index: int,
    uuid_index: dict[str, int],
    report: Report,
) -> None:
    """Recursive traversal checking attachments and serialization."""
    if isinstance(node, dict):
        ser_type = node.get("WFSerializationType")
        if ser_type is not None and ser_type not in LEGAL_SERIALIZATION_TYPES:
            report.warn(
                f"unknown WFSerializationType: {ser_type}",
                action_index,
            )

        if ser_type == "WFTextTokenString":
            value = node.get("Value")
            if isinstance(value, dict):
                _check_text_token_string(value, action_index, uuid_index, report)

        output_uuid = node.get("OutputUUID")
        if output_uuid is not None:
            _check_output_uuid(output_uuid, action_index, uuid_index, report)

        for v in node.values():
            _walk_parameters(v, action_index, uuid_index, report)
    elif isinstance(node, list):
        for v in node:
            _walk_parameters(v, action_index, uuid_index, report)


def _check_text_token_string(
    value: dict[str, Any],
    action_index: int,
    uuid_index: dict[str, int],
    report: Report,
) -> None:
    """Check string vs attachmentsByRange consistency."""
    string = value.get("string", "")
    attachments = value.get("attachmentsByRange", {})
    if not isinstance(string, str):
        return
    if not isinstance(attachments, dict):
        report.error("attachmentsByRange must be a dict", action_index)
        return
    for range_key, attachment in attachments.items():
        match = RANGE_KEY_RE.match(range_key)
        if not match:
            report.error(
                f"attachmentsByRange key not in {{position, length}} "
                f"format: {range_key!r}",
                action_index,
            )
            continue
        position = int(match.group(1))
        length = int(match.group(2))
        if length != 1:
            report.warn(
                f"attachmentsByRange length {length} is unusual "
                f"(expected 1)",
                action_index,
            )
        if position >= len(string) or position < 0:
            report.error(
                f"attachmentsByRange position {position} is "
                f"out of range for string of length {len(string)}",
                action_index,
            )
            continue
        char_at = string[position : position + length]
        if OBJECT_REPLACEMENT_CHAR not in char_at:
            report.error(
                f"attachmentsByRange at {range_key} does not align "
                f"with a U+FFFC character",
                action_index,
            )
        if isinstance(attachment, dict):
            output_uuid = attachment.get("OutputUUID")
            if output_uuid is not None:
                _check_output_uuid(
                    output_uuid, action_index, uuid_index, report
                )

    ffffc_count = string.count(OBJECT_REPLACEMENT_CHAR)
    if ffffc_count != len(attachments):
        report.warn(
            f"mismatch: {ffffc_count} U+FFFC chars in string but "
            f"{len(attachments)} attachmentsByRange entries",
            action_index,
        )


def _check_output_uuid(
    output_uuid: str,
    action_index: int,
    uuid_index: dict[str, int],
    report: Report,
) -> None:
    """Verify OutputUUID refers to an earlier action."""
    if not isinstance(output_uuid, str):
        return
    producer_idx = uuid_index.get(output_uuid)
    if producer_idx is None:
        report.error(
            f"OutputUUID {output_uuid} does not match any UUID in actions",
            action_index,
        )
    elif producer_idx >= action_index:
        report.error(
            f"OutputUUID {output_uuid} refers to action at index "
            f"{producer_idx} (must be < {action_index})",
            action_index,
        )


def validate(plist: dict[str, Any]) -> Report:
    """Run the full validation suite against a loaded plist.

    Args:
        plist: The parsed top-level dict.

    Returns:
        A Report with accumulated errors and warnings.
    """
    report = Report()
    validate_envelope(plist, report)
    actions = plist.get("WFWorkflowActions")
    if not isinstance(actions, list):
        return report
    for index, action in enumerate(actions):
        validate_action_shape(action, index, report)
    uuid_index = collect_uuids(actions, report)
    validate_control_flow(actions, report)
    validate_variable_references(actions, uuid_index, report)
    return report


def emit_human(report: Report) -> None:
    """Print a human-readable report to stdout."""
    if report.valid and not report.warnings:
        print("OK: shortcut is valid.")
        return
    if report.errors:
        print(f"ERRORS ({len(report.errors)}):")
        for err in report.errors:
            prefix = (
                f"  [action {err.action_index}] "
                if err.action_index is not None
                else "  "
            )
            print(f"{prefix}{err.message}")
    if report.warnings:
        print(f"WARNINGS ({len(report.warnings)}):")
        for warn in report.warnings:
            prefix = (
                f"  [action {warn.action_index}] "
                if warn.action_index is not None
                else "  "
            )
            print(f"{prefix}{warn.message}")
    print(f"valid: {report.valid}")


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Validate an Apple Shortcuts plist.",
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
        help="Python log level (DEBUG, INFO, WARNING, ERROR)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    path = Path(args.path)
    plist = load_plist(path)
    report = validate(plist)

    if args.human:
        emit_human(report)
    else:
        json.dump(report.to_dict(), sys.stdout, indent=2)
        sys.stdout.write("\n")

    return 0 if report.valid else 1


if __name__ == "__main__":
    sys.exit(main())
