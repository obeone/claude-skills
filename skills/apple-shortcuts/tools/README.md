# Tools

Scripts for validating, inspecting, and discovering Apple Shortcuts
actions. All produce JSON on stdout by default; `--human` switches to
readable output. Logs go to stderr.

## Script inventory

| Script                       | Purpose                                |
| ---------------------------- | -------------------------------------- |
| `validate-shortcut.py`       | Validate a plist against the skill's   |
|                              | format rules.                          |
| `inspect-shortcut.py`        | Dump a shortcut's actions, magic vars, |
|                              | named vars, third-party detections.    |
| `list-native-actions.py`     | Enumerate native action identifiers.   |
| `list-app-intents.py`        | Scan installed apps for App Intents    |
|                              | metadata (macOS only).                 |
| `find-action-identifier.py`  | Fuzzy-search actions by human name.    |
| `diff-actions.py`            | Semantic diff between two shortcuts.   |

## `validate-shortcut.py`

Validates a plist against the envelope and per-action rules in
`references/plist-format.md`, `references/variables-and-types.md`,
and `references/control-flow.md`.

### Usage

```bash
./validate-shortcut.py path/to/shortcut.plist          # JSON output
./validate-shortcut.py path/to/shortcut.plist --human  # Readable
```

### Checks

- Required top-level keys present.
- `WFWorkflowActions` is a list of well-shaped dicts.
- `WFWorkflowInputContentItemClasses` values are legal.
- UUIDs are unique across actions.
- `OutputUUID` references point to earlier actions.
- `attachmentsByRange` keys match `{position, length}` format.
- U+FFFC characters align with attachment positions.
- Control flow blocks (`GroupingIdentifier`) are paired.
- `WFControlFlowMode` is an integer in `{0, 1, 2}`.

### Exit codes

- `0` — valid.
- `1` — invalid.
- `2` — could not read/parse input.

### Sample JSON output

```json
{
  "valid": true,
  "errors": [],
  "warnings": [
    {
      "action_index": 3,
      "message": "unknown content item class: WFCustomContentItem"
    }
  ]
}
```

## `inspect-shortcut.py`

Summarizes a shortcut's structure.

### Usage

```bash
./inspect-shortcut.py path/to/shortcut.plist
./inspect-shortcut.py path/to/shortcut.plist --human
```

### Output fields

- `envelope` — version, icon, input classes, types.
- `action_count` — total action count.
- `actions` — list of `{index, identifier, custom_output_name, uuid}`.
- `magic_variables` — actions with a `UUID` (downstream-referenceable).
- `named_variables` — Set/Get/Append Variable usages.
- `third_party_apps` — detected third-party bundle prefixes.
- `warnings` — deprecated or suspect actions.

### Exit codes

- `0` — inspection succeeded.
- `2` — could not read/parse.

## `list-native-actions.py`

Lists `is.workflow.actions.*` identifiers.

### Usage

```bash
./list-native-actions.py          # JSON output
./list-native-actions.py --human
./list-native-actions.py --force-fallback   # Skip WorkflowKit parse
```

On macOS, tries to parse WorkflowKit's App Intents metadata at
`/System/Library/PrivateFrameworks/WorkflowKit.framework/
Metadata.appintents/extract.actionsdata`. On failure (or on non-mac)
falls back to the embedded index built from
`references/actions-native-full-index.md`.

### Exit codes

- `0` — success with authoritative source (WorkflowKit on macOS, or
  embedded on non-mac).
- `1` — fallback used on macOS (WorkflowKit not parseable).
- `2` — fatal error.

### Sample JSON output

```json
{
  "platform": "darwin",
  "source": "WorkflowKit",
  "notes": [],
  "actions": [
    {
      "identifier": "is.workflow.actions.gettext",
      "name": "Text",
      "category": "content",
      "source": "WorkflowKit"
    }
  ]
}
```

## `list-app-intents.py`

Scans installed apps for App Intents metadata and dumps the action
identifiers they declare.

### Usage

```bash
# Scan /Applications and ~/Applications
./list-app-intents.py

# Scan specific directories
./list-app-intents.py --dir /Applications --dir /Applications/Setapp

# Target one bundle
./list-app-intents.py --bundle com.sindresorhus.Actions

# Include /System/Applications (Apple first-party)
./list-app-intents.py --include-system

# Human-readable
./list-app-intents.py --human

# Full action lists in JSON (long output)
./list-app-intents.py --full
```

### Output

Each app report:

```json
{
  "bundle_id": "com.sindresorhus.Actions",
  "app_name": "Actions",
  "app_path": "/Applications/Actions.app",
  "parseable": true,
  "action_count": 172,
  "actions": [
    {
      "identifier": "GenerateUUIDIntent",
      "title": "Generate UUID"
    }
  ]
}
```

When the binary format resists parsing: `parseable: false` with an
`error` field.

### Failure modes

- App lacks `Metadata.appintents/extract.actionsdata` → skipped
  silently (returns empty scan result).
- Binary format is not a plist → `parseable: false`.
- macOS only; non-Darwin returns exit 2.

### Exit codes

- `0` — success.
- `1` — bundle not found (when `--bundle` given).
- `2` — not on macOS or fatal error.

## `find-action-identifier.py`

Fuzzy-search the catalog by human name or keyword.

### Usage

```bash
./find-action-identifier.py "send email"
./find-action-identifier.py "send email" --human
./find-action-identifier.py "send email" -n 10 --min-score 0.2
```

### Scoring

- Levenshtein distance between query and action name (weighted 0.4).
- Bag-of-words overlap with name + keywords (weighted 1.0).
- Scores range roughly 0 to 1.5; higher is better.

### Embedded catalog

~80 high-signal native actions + ~10 third-party entry points.
For the full native index, see
`references/actions-native-full-index.md`.

### Exit codes

- `0` — matches found.
- `1` — no match above `--min-score`.

## `diff-actions.py`

Semantic diff between two shortcuts — not textual.

### Usage

```bash
./diff-actions.py old.plist new.plist
./diff-actions.py old.plist new.plist --human
```

### Algorithm

- Actions with UUIDs are matched by UUID.
- Actions without UUIDs are matched by position among non-UUIDed
  actions.
- Reported buckets:
  - `added` — UUID not in old.
  - `removed` — UUID not in new.
  - `modified` — same UUID, different parameters snapshot.
  - `reordered` — same UUID, same parameters, different index.

### Exit codes

- `0` — no differences.
- `1` — differences found.
- `2` — could not parse input(s).

## Dependencies

All scripts use the Python standard library only (`plistlib`,
`argparse`, `json`, `pathlib`, `logging`). No external packages.
Python 3.10+ is required (union types with `|`).

No `uv` PEP-723 header is needed because there are no non-stdlib
imports. Scripts use `#!/usr/bin/env python3`.

## Running from elsewhere in the repo

All scripts read files by path — no CWD assumptions. Call from
anywhere:

```bash
python3 skills/apple-shortcuts/tools/validate-shortcut.py \
  skills/apple-shortcuts/templates/minimal-shortcut.plist
```

## Common failure modes

| Symptom                              | Cause                              |
| ------------------------------------ | ---------------------------------- |
| `SystemExit: 2`                      | File not found or not a plist.     |
| `UUID is not a canonical UUIDv4`     | UUID uses non-hex chars or wrong   |
| warning                              | length. Cosmetic; runtime OK.      |
| `attachmentsByRange position out of  | U+FFFC char missing from string,   |
|  range`                              | or ranges don't match.             |
| `list-app-intents.py: 0 apps found`  | Expected on Linux; only            |
|                                      | `--include-system` scans Apple     |
|                                      | built-ins on macOS.                |
| Tools missing on non-Darwin          | `list-app-intents.py` requires     |
|                                      | macOS. Other tools cross-platform. |
