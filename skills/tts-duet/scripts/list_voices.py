#!/usr/bin/env python3
"""List voices and presets known to the tts-duet skill.

Default output is a human-readable table; ``--json`` emits a stable
JSON document with the full catalog. ``--preset NAME`` restricts the
output to a single preset's voices (useful for shell pipelines).
``--validate`` checks that every voice referenced by
``assets/voice_pairs.yaml`` exists in ``assets/voices.yaml``; this is
the CI gate described in §5.1.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

SKILL_ROOT = Path(__file__).resolve().parent.parent
VOICES_PATH = SKILL_ROOT / "assets" / "voices.yaml"
PRESETS_PATH = SKILL_ROOT / "assets" / "voice_pairs.yaml"


def _load_yaml(path: Path) -> Any:
    """Parse ``path`` as UTF-8 YAML.

    Parameters
    ----------
    path : Path
        Source YAML file.

    Returns
    -------
    Any
        Whatever :func:`yaml.safe_load` returns. ``{}`` if the file
        parses as ``None`` (e.g. only comments).
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if data is not None else {}


def _iter_preset_voices(presets: dict[str, Any]) -> list[tuple[str, str]]:
    """Return the ``(preset, voice)`` pairs used by every preset.

    ``null`` / ``None`` slots (mono presets) are skipped.
    """
    pairs: list[tuple[str, str]] = []
    for preset_name, preset in presets.items():
        for key in ("speaker_a", "speaker_b"):
            voice = preset.get(key)
            if voice:
                pairs.append((preset_name, voice))
    return pairs


def _validate(
    voices: list[dict[str, Any]],
    presets: dict[str, Any],
) -> int:
    """Return the exit code of ``--validate``.

    Prints offending ``(preset, voice)`` pairs to stderr on failure.
    """
    known = {entry["name"] for entry in voices}
    missing = [
        (preset, voice)
        for preset, voice in _iter_preset_voices(presets)
        if voice not in known
    ]
    if not missing:
        return 0
    print(
        "ERROR: presets reference voices absent from voices.yaml:",
        file=sys.stderr,
    )
    for preset, voice in missing:
        print(f"  - preset={preset!r} voice={voice!r}", file=sys.stderr)
    return 1


def _format_text(
    voices: list[dict[str, Any]],
    presets: dict[str, Any],
    preset_filter: str | None,
) -> str:
    """Render the default text view."""
    lines: list[str] = []
    if preset_filter is None:
        lines.append("Voices:")
        for entry in voices:
            mark = "verified" if entry.get("verified") else "to verify"
            lines.append(
                f"  - {entry['name']:<16} "
                f"descriptor={entry.get('descriptor')!r:<14} "
                f"tonal={entry.get('tonal_hint')!s:<8} [{mark}]"
            )
        lines.append("")
        lines.append("Presets:")
        for name, preset in presets.items():
            flag = "experimental" if preset.get("experimental") else "stable"
            sb = preset.get("speaker_b") or "—"
            lines.append(
                f"  - {name:<18} {preset.get('speaker_a')!s} / {sb}"
                f"    ({preset.get('intent')}) [{flag}]"
            )
    else:
        preset = presets.get(preset_filter)
        if preset is None:
            print(f"ERROR: unknown preset {preset_filter!r}", file=sys.stderr)
            raise SystemExit(1)
        flag = "experimental" if preset.get("experimental") else "stable"
        sb = preset.get("speaker_b") or "—"
        lines.append(f"Preset {preset_filter} [{flag}]")
        lines.append(f"  intent    : {preset.get('intent')}")
        lines.append(f"  speaker_a : {preset.get('speaker_a')}")
        lines.append(f"  speaker_b : {sb}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. See module docstring."""
    parser = argparse.ArgumentParser(
        description="List voices and presets for the tts-duet skill.",
    )
    parser.add_argument(
        "--preset",
        metavar="NAME",
        help="Restrict output to a single preset.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the default text view.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help=(
            "Verify that every preset references a voice present in "
            "voices.yaml. Exit 1 if not."
        ),
    )
    args = parser.parse_args(argv)

    voices_doc = _load_yaml(VOICES_PATH)
    presets_doc = _load_yaml(PRESETS_PATH)
    voices: list[dict[str, Any]] = voices_doc.get("voices", [])
    presets: dict[str, Any] = presets_doc.get("presets", {})

    if args.validate:
        return _validate(voices, presets)

    if args.json:
        payload: dict[str, Any] = {"voices": voices, "presets": presets}
        if args.preset:
            if args.preset not in presets:
                print(f"ERROR: unknown preset {args.preset!r}", file=sys.stderr)
                return 1
            payload = {"preset": args.preset, **presets[args.preset]}
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(_format_text(voices, presets, args.preset))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
