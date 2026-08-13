# CLI surface and exit codes

Every script also answers `--help`. This file exists so `SKILL.md` does
not have to carry the tables in context on every turn.

## `scan_project.py`

| Flag | Default | Purpose |
|---|---|---|
| `--project-root <path>` | cwd | Project root to scan. |
| `--json` | off | Machine-readable output. |
| `--include-shared` / `--no-include-shared` | on | Read `.claude/settings.json` `autoMode` for adoption candidates. |
| `--check-gitignore` | off | Warn if `.claude/settings.local.json` is not covered by `.gitignore`. |

## `inspect_automode.py`

| Flag | Default | Purpose |
|---|---|---|
| `--project-root <path>` | cwd | Project root to inspect. |
| `--show-drift` | off | Compare each file's canonical bytes against the approved cache; exit 6 on drift. |
| `--json` | off | Machine-readable output. |
| `--file {user,shared,local,all}` | all | Restrict to one file. |

## `apply_automode.py`

| Flag | Default | Purpose |
|---|---|---|
| `--project-root <path>` | cwd | Project root. |
| `--mode {auto,fresh,migrate}` | auto | Pipeline mode; `auto` derives from the local file. |
| `--proposal <path>` | required for non-interactive | JSON proposal to write. |
| `--dry-run` | off | Compute the hash, write nothing, preview the rollback line. |
| `--approved-canonical-hash <sha256>` | required for non-dry-run | Gate predicate. |
| `--migrate-strategy {keep-all,drop-all,fail,interactive}` | interactive | How existing rules are folded in. |
| `--show-drift` | off | Alias delegating to `inspect_automode.py`. |
| `--model <model>` | (CLI default) | Passed to `claude auto-mode critique`. |
| `--allow-empty-critique` | off | Accept a critique that says nothing (see below). |
| `--strict-critique-sections` | off | Also validate the critique's section headers against the hardcoded contract. |
| `--allow-unknown-critique-sections` | off | Forward-compat loosening of the section check. |
| `--write-shared` | off | Phase 4 opt-in: also write `.claude/settings.json`. |
| `--hoist <rule-id>` | off | Move a rule from local to user. |
| `--repair` | off | Restore orphans and reclaim locks; mutually exclusive with every other mode. |
| `--allow-swap-file-fallback` | off | DEPRECATED no-op; the swap-file path is automatic when `--settings` is missing. |

## The critique gate has two layers

**Mandatory, version-agnostic:** the critique must actually say
something. Exit code 0 is not sufficient. The binary has been observed
exiting 0 with nothing but:

```text
Analyzing your auto mode rules…

No critique was generated. Please try again.
```

That output means the proposal was never reviewed, so it must not open
the hash gate. `apply_automode.py` fails with `EXIT_CRITIQUE_FAILED`
when the output is empty, shorter than `MIN_CRITIQUE_CHARS` of
non-whitespace text, or matches `DEGENERATE_CRITIQUE_PATTERNS`. The raw
output is archived first, so the evidence survives the failure. Pass
`--allow-empty-critique` to accept it anyway.

**Opt-in, brittle:** `--strict-critique-sections` asserts the exact set
of `##` headers. The binary renames its sections across versions, so
this stays off by default.

## Exit codes

| Code | Name | Meaning |
|---|---|---|
| 0 | EXIT_OK | Success. |
| 1 | EXIT_USAGE | Missing flag, unsupported combination. |
| 2 | EXIT_VALIDATION | Proposal fails the JSON schema. |
| 3 | EXIT_CRITIQUE_FAILED | Non-zero from `claude`, empty/degenerate critique, or contract drift. |
| 4 | EXIT_PERMISSION | Filesystem permission denied. |
| 5 | EXIT_CLAUDE_CLI_MISSING | `claude` is not on PATH. |
| 6 | EXIT_DRIFT | Canonical bytes differ from the approved cache. |
| 7 | EXIT_LOCK_HELD | A live writer holds the flock. |
| 8 | EXIT_HASH_MISMATCH | `--approved-canonical-hash` differs from the computed hash. |
| 9 | EXIT_STRANDED_STATE | `.preview-orig.<pid>` orphans found. |
| 10 | EXIT_OUT_OF_BAND | `claude` version outside the heuristics range. |
