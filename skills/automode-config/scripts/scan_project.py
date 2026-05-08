#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Scan a project for autoMode trust signals.

Reads ``assets/heuristics.yaml`` for the catalog of probes (signal_NN
entries). Each probe runs against the project root and produces
``{id, label, present, why}``. Optionally, when
``--include-shared`` is set (the default), the project's
``.claude/settings.json`` is read and any ``autoMode`` entries are
surfaced as **adoption candidates** so callers can decide whether to
adopt them into ``.claude/settings.local.json``.

CLI flags
---------
--project-root <path>             Default: cwd.
--json                            Machine-readable output.
--include-shared / --no-include-shared
                                  Surface adoption candidates from the
                                  project's shared settings file.
--check-gitignore                 Warn (stderr) when
                                  ``.claude/settings.local.json`` isn't
                                  covered by any ``.gitignore`` rule.

Exits 0 in normal operation. Stdlib-only.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
HEURISTICS_PATH = SKILL_DIR / "assets" / "heuristics.yaml"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _canonical import load_json, parse_flat_yaml  # noqa: E402
from _paths import resolve  # noqa: E402


# Built-in fallback probe set. Used only when heuristics.yaml is absent
# or fails to parse, so the script can still produce a useful report.
_FALLBACK_SIGNALS: list[dict[str, str]] = [
    {
        "id": "signal_dockerfile",
        "label": "Dockerfile present",
        "probe": "file_exists",
        "target": "Dockerfile",
    },
    {
        "id": "signal_compose",
        "label": "Docker Compose file",
        "probe": "any_file_exists",
        "target": "compose.yaml,compose.yml,docker-compose.yaml,docker-compose.yml",
    },
    {
        "id": "signal_pkg_json",
        "label": "package.json present",
        "probe": "file_exists",
        "target": "package.json",
    },
    {
        "id": "signal_pyproject",
        "label": "pyproject.toml present",
        "probe": "file_exists",
        "target": "pyproject.toml",
    },
    {
        "id": "signal_gitignore",
        "label": ".gitignore present",
        "probe": "file_exists",
        "target": ".gitignore",
    },
    {
        "id": "signal_node_modules",
        "label": "node_modules directory",
        "probe": "dir_exists",
        "target": "node_modules",
    },
    {
        "id": "signal_uv_lock",
        "label": "uv.lock present",
        "probe": "file_exists",
        "target": "uv.lock",
    },
]


def _load_heuristics() -> tuple[list[dict[str, str]], dict[str, str], list[str]]:
    """Return ``(signals, meta, warnings)`` from ``heuristics.yaml``.

    The file is parsed with :func:`_canonical.parse_flat_yaml`, which
    only supports a flat ``key: value`` mapping. We translate that into
    the structured form the scanner needs by interpreting any key
    matching ``signal_NN_<field>`` as a field of signal ``signal_NN``.
    """

    warnings: list[str] = []
    if not HEURISTICS_PATH.is_file():
        warnings.append(
            f"heuristics.yaml not found at {HEURISTICS_PATH}; using "
            f"built-in fallback signals"
        )
        return _FALLBACK_SIGNALS, {}, warnings

    try:
        raw = HEURISTICS_PATH.read_text(encoding="utf-8")
        flat = parse_flat_yaml(raw)
    except Exception as exc:  # noqa: BLE001
        warnings.append(
            f"could not parse {HEURISTICS_PATH}: {exc}; using built-in "
            f"fallback signals"
        )
        return _FALLBACK_SIGNALS, {}, warnings

    meta: dict[str, str] = {}
    signals: dict[str, dict[str, str]] = {}
    for key, value in flat.items():
        if not key.startswith("signal_"):
            meta[key] = value
            continue
        # signal_NN_field=value, signal_NN_label=…, signal_NN_probe=…
        # We split on the LAST underscore so prefixes can have multiple
        # underscores (signal_pkg_json_label).
        head, _, field = key.rpartition("_")
        if not head or not field:
            continue
        sid = head
        signals.setdefault(sid, {"id": sid})[field] = value

    out: list[dict[str, str]] = []
    for sid, payload in signals.items():
        if "probe" not in payload or "target" not in payload:
            warnings.append(
                f"signal {sid!r} missing probe/target in heuristics.yaml; "
                f"skipped"
            )
            continue
        payload.setdefault("label", sid)
        out.append(payload)

    if not out:
        warnings.append(
            f"{HEURISTICS_PATH} contained no usable signals; using "
            f"built-in fallback"
        )
        return _FALLBACK_SIGNALS, meta, warnings

    out.sort(key=lambda s: s["id"])
    return out, meta, warnings


def _probe(signal: dict[str, str], root: Path) -> tuple[bool, str]:
    """Run ``signal``'s probe against ``root``; return ``(present, why)``."""

    probe = signal.get("probe", "file_exists")
    target = signal.get("target", "")
    if probe == "file_exists":
        p = root / target
        return p.is_file(), f"{target} {'present' if p.is_file() else 'absent'}"
    if probe == "any_file_exists":
        for cand in (t.strip() for t in target.split(",")):
            if cand and (root / cand).is_file():
                return True, f"{cand} present"
        return False, f"none of [{target}] present"
    if probe == "dir_exists":
        p = root / target
        return p.is_dir(), f"{target}/ {'present' if p.is_dir() else 'absent'}"
    if probe == "file_glob":
        for match in root.glob(target):
            if match.is_file():
                return True, f"{match.relative_to(root)} matches {target}"
        return False, f"no file matches {target}"
    return False, f"unknown probe type {probe!r}"


def _collect_shared_candidates(shared_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Return ``(candidates, warnings)`` from the shared settings file."""

    if not shared_path.is_file():
        return [], []
    warnings: list[str] = []
    try:
        data = load_json(shared_path)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"could not parse {shared_path}: {exc}")
        return [], warnings
    auto = (data or {}).get("autoMode") if isinstance(data, dict) else None
    if not isinstance(auto, dict):
        return [], warnings

    candidates: list[dict[str, Any]] = []
    for section in ("allow", "deny", "hard_deny", "ask"):
        items = auto.get(section)
        if not isinstance(items, list):
            continue
        for idx, item in enumerate(items):
            candidates.append(
                {
                    "section": section,
                    "index": idx,
                    "value": item,
                    "source": str(shared_path),
                }
            )
    env = auto.get("environment")
    if isinstance(env, list):
        for idx, item in enumerate(env):
            candidates.append(
                {
                    "section": "environment",
                    "index": idx,
                    "value": item,
                    "source": str(shared_path),
                }
            )
    return candidates, warnings


def _gitignore_patterns(root: Path) -> list[tuple[Path, str]]:
    """Return ``[(gitignore_dir, pattern), ...]`` from all ``.gitignore`` files."""

    patterns: list[tuple[Path, str]] = []
    for gi in root.rglob(".gitignore"):
        try:
            for line in gi.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                patterns.append((gi.parent, stripped.lstrip("/")))
        except (OSError, UnicodeDecodeError):
            continue
    return patterns


def _is_gitignored(root: Path, target: Path) -> bool:
    """Return True when ``target`` matches any gitignore pattern."""

    if not target.exists():
        # Match against the would-be path anyway.
        pass
    rel = target.relative_to(root) if target.is_absolute() else target
    rel_str = str(rel).replace(os.sep, "/")
    for gi_dir, pattern in _gitignore_patterns(root):
        try:
            sub = str(target.relative_to(gi_dir)).replace(os.sep, "/")
        except ValueError:
            continue
        if fnmatch.fnmatch(sub, pattern):
            return True
        if fnmatch.fnmatch(rel_str, pattern):
            return True
    return False


def _check_gitignore(local_path: Path, root: Path) -> str | None:
    """Return a warning string when ``local_path`` is not gitignored."""

    if _is_gitignored(root, local_path):
        return None
    return (
        f"warning: {local_path.relative_to(root)} is not covered by any "
        f".gitignore rule. This file may contain secrets and should not "
        f"be committed."
    )


def build_report(
    project_root: Path,
    *,
    include_shared: bool,
    check_gitignore: bool,
) -> dict[str, Any]:
    """Return the full scan report as a serializable dict."""

    files = resolve(project_root)
    signals, meta, warnings = _load_heuristics()

    findings: list[dict[str, Any]] = []
    for signal in signals:
        present, why = _probe(signal, files.project_root)
        findings.append(
            {
                "id": signal["id"],
                "label": signal.get("label", signal["id"]),
                "present": present,
                "why": why,
            }
        )

    candidates: list[dict[str, Any]] = []
    if include_shared:
        cand, warn = _collect_shared_candidates(files.shared_settings)
        candidates = cand
        warnings.extend(warn)

    gitignore_warning: str | None = None
    if check_gitignore:
        gitignore_warning = _check_gitignore(files.local_settings, files.project_root)

    return {
        "project_root": str(files.project_root),
        "user_settings": str(files.user_settings),
        "shared_settings": str(files.shared_settings),
        "local_settings": str(files.local_settings),
        "heuristics_meta": meta,
        "signals": findings,
        "shared_adoption_candidates": candidates,
        "warnings": warnings,
        "gitignore_warning": gitignore_warning,
    }


def _emit_human(report: dict[str, Any]) -> None:
    out = sys.stdout
    out.write(f"project_root: {report['project_root']}\n")
    out.write(f"user_settings:   {report['user_settings']}\n")
    out.write(f"shared_settings: {report['shared_settings']}\n")
    out.write(f"local_settings:  {report['local_settings']}\n")
    out.write("\nsignals:\n")
    for f in report["signals"]:
        mark = "Y" if f["present"] else "."
        out.write(f"  [{mark}] {f['id']:<28} {f['label']}  ({f['why']})\n")
    out.write("\nshared adoption candidates: ")
    cands = report["shared_adoption_candidates"]
    if not cands:
        out.write("(none)\n")
    else:
        out.write(f"{len(cands)}\n")
        for c in cands:
            out.write(f"  - {c['section']}[{c['index']}]: {c['value']!r}\n")
    if report["warnings"]:
        out.write("\nwarnings:\n")
        for w in report["warnings"]:
            out.write(f"  ! {w}\n")
    if report["gitignore_warning"]:
        sys.stderr.write(report["gitignore_warning"] + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scan_project.py",
        description="Scan a project for autoMode trust signals and "
        "adoption candidates.",
    )
    parser.add_argument(
        "--project-root",
        default=str(Path.cwd()),
        help="Project root to scan (default: cwd).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a human report.",
    )
    g = parser.add_mutually_exclusive_group()
    g.add_argument(
        "--include-shared",
        dest="include_shared",
        action="store_true",
        default=True,
        help="Surface autoMode entries from .claude/settings.json (default).",
    )
    g.add_argument(
        "--no-include-shared",
        dest="include_shared",
        action="store_false",
        help="Skip reading .claude/settings.json for adoption candidates.",
    )
    parser.add_argument(
        "--check-gitignore",
        action="store_true",
        help="Warn (stderr) when .claude/settings.local.json is not "
        "covered by any .gitignore rule.",
    )
    args = parser.parse_args(argv)

    report = build_report(
        Path(args.project_root),
        include_shared=args.include_shared,
        check_gitignore=args.check_gitignore,
    )
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
        if report["gitignore_warning"]:
            sys.stderr.write(report["gitignore_warning"] + "\n")
    else:
        _emit_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
