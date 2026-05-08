---
name: auto-mode-config
description: "Author, validate, and migrate `autoMode` blocks in the user-level `~/.claude/settings.json`. Run `claude auto-mode critique` (with `defaults` and `config`) as the canonical validation gate, scan the current project for trust signals to seed `autoMode.environment`, and detect settings patterns auto mode silently breaks (broad allow rules dropped on entry, autoMode misplaced in shared project settings the classifier ignores, missing `$defaults` sentinel). Triggers on: auto mode, autoMode, $defaults, claude auto-mode, claude auto-mode critique, permission classifier, soft_deny, classifier denials, migrating from --dangerously-skip-permissions, YOLO mode, accept edits mode, plan mode."
metadata:
  version: "0.1.0"
tools:
  - Read
  - Write
  - Bash
---

# Auto Mode Config

Author, validate, and migrate `autoMode` rules in the **user-level** `~/.claude/settings.json`. The skill orchestrates `claude auto-mode critique` as the canonical validation gate, writes atomically with a timestamped backup, and refuses to commit unless the user has approved a sha256 of the exact bytes that will land on disk.

## Out of scope

- **Project-shared `<repo>/.claude/settings.json`** (committed). The classifier silently ignores `autoMode` here. The skill detects the misplacement on scan, points at it, and refuses to write to it.
- **Project-local `<repo>/.claude/settings.local.json`** (gitignored, project-scoped). Deferred to v0.3.0. The skill does not touch this file.
- **Managed (org-policy) settings**. Out of scope; admin tooling territory.
- **CLAUDE.md fuzzy-overlap detection**. Deferred to v0.2.0 — the threshold needs telemetry first.
- **Auto mode itself when ineligible**: the skill refuses generator/migrator on Pro / Bedrock / Vertex / Foundry. Inspection still works on any plan.

## Mental model in one paragraph

`autoMode` is a permission **classifier** layered on top of `permissions.{allow,ask,deny}`. It reads three array-of-prose fields — `environment`, `allow`, `soft_deny` — and decides whether each tool call is safe enough to skip the prompt. The literal string `"$defaults"` must be present in each section to inherit Anthropic's built-ins; omitting it replaces the section entirely. There is no `autoMode.deny` (hard blocks live in `permissions.deny`). The classifier reads `~/.claude/settings.json`, project-local, managed, and `--settings`; it explicitly does **not** read project-shared (committed) settings. Full details: `references/mental_model.md`.

```
tool call
  │
  ▼
permissions.deny — matches? ─► hard-block (no override)
  │ no
  ▼
classifier ← autoMode.{env,allow,soft_deny} + CLAUDE.md + user message
  │
  ▼
allow / soft-deny / fall through to a prompt
```

## Prerequisites

| Requirement                        | Check                                                                                                  |
| :--------------------------------- | :----------------------------------------------------------------------------------------------------- |
| Claude Code `>= 2.1.83`             | `claude --version`. The skill enforces `>=2.1.83,<3.0` from `assets/heuristics.yaml`; refuses with exit 10 outside the band. |
| Plan: Max / Team / Enterprise / API | Pro is **not** supported.                                                                              |
| Provider: Anthropic API             | Bedrock / Vertex / Foundry are **not** supported.                                                      |
| `claude` on `PATH`                  | The skill exits 5 with an installation pointer when missing.                                           |
| `uv` installed                      | Every script is PEP 723; `uv run path/to/script.py …` resolves deps automatically.                      |

## Workflow

### 1. Ask one explicit intent question

When the user invokes the skill, ask exactly this question — do not auto-classify from keywords:

> Are you (a) starting fresh / no autoMode yet, (b) updating or migrating existing rules, or (c) just inspecting / asking for advice?

The three branches map cleanly to the three scripts. Branch (c) is plan-agnostic; branches (a) and (b) gate on plan and version.

### 2a. Advisor (intent c)

Read `references/mental_model.md`. Answer the user's question. Mutate nothing. If they want to look at their own current state, route to the validator branch (2c).

### 2b. Generator — fresh start (intent a)

```bash
# 0. Scan the current project for trust signals (read-only).
uv run skills/auto-mode-config/scripts/scan_project.py

# 1. Dry-run apply — produces canonical preview + sha256.
uv run skills/auto-mode-config/scripts/apply_automode.py \
  --mode fresh \
  --proposal /tmp/autoMode-proposal.json \
  --dry-run
# → prints verbatim `claude auto-mode critique` output + canonical_sha256: <hex>

# 2. Approve the hash and commit.
uv run skills/auto-mode-config/scripts/apply_automode.py \
  --mode fresh \
  --proposal /tmp/autoMode-proposal.json \
  --approved-canonical-hash <hex from step 1>
```

The proposal file is a small JSON document with `environment_add`, `allow_add`, `soft_deny_add` arrays. Schema and example: `references/migration.md`. The starter template lives at `assets/automode_loaded.json` (JSONC with `__example_only` wrapper markers — see "The `__example_only` trap" below).

Fresh-machine flow (no `~/.claude/settings.json` yet) is automatic: the skill creates `~/.claude/` mode 0700 and the file mode 0600, writes `{}`, then proceeds. No backup is needed; the skill logs `no backup needed (fresh install)`.

### 2c. Validator (intent c, inspection)

```bash
# Print canonical preview + sha256 of the current settings.
uv run skills/auto-mode-config/scripts/inspect_automode.py

# Or check whether the file has drifted from the last approved canonical bytes.
uv run skills/auto-mode-config/scripts/inspect_automode.py --show-drift
# Exit 0 = equal, exit 6 = drift detected (informational; not a failure).
```

Allowed on any plan. Never writes. Drift detection compares the current canonical bytes against `~/.claude/.auto_mode_approved.json` (the cache `apply_automode.py` updates on every successful commit).

### 2d. Migrator (intent b)

```bash
# 0. Optional: scan the project to surface trust signals to add.
uv run skills/auto-mode-config/scripts/scan_project.py

# 1. Dry-run with explicit migration strategy.
uv run skills/auto-mode-config/scripts/apply_automode.py \
  --mode migrate \
  --proposal /tmp/autoMode-proposal.json \
  --migrate-strategy fail \
  --dry-run

# 2. Interactively confirm each existing entry.
#    (Runs phase-1 build in-memory; nothing on disk changes until step 3.)

# 3. Apply with the approved hash.
uv run skills/auto-mode-config/scripts/apply_automode.py \
  --mode migrate \
  --proposal /tmp/autoMode-proposal.json \
  --approved-canonical-hash <hex>
```

Existing `autoMode.environment` entries are presented one by one with `[k]eep / [e]dit / [d]rop / [q]uit`. Non-interactive runs **must** declare `--migrate-strategy keep-all|drop-all|fail`; default `fail` exits 4 to prevent silent mutation. Treat `autoMode.environment` as durable claims about the user, not project snapshots — full rationale in `references/migration.md`.

## The `$defaults` trap

The literal string `"$defaults"` must appear in each section (`environment`, `allow`, `soft_deny`) to inherit Anthropic's built-in rules. Each section is independent.

```jsonc
{
  "autoMode": {
    "environment": ["$defaults", "<your prose claim>"],
    "allow":       ["$defaults", "<your exception>"],
    "soft_deny":   ["$defaults", "<your additional block>"]
  }
}
```

Omitting `"$defaults"` replaces that section entirely with your custom entries. The classifier loses every Anthropic-curated rule it would otherwise inherit. The skill writes `"$defaults"` automatically; only `--dangerously-skip-defaults` (paired with a confirmation token) drops it. Run `claude auto-mode defaults` to print the built-ins so you know what you would be replacing.

## The `__example_only` wrapper

Examples in `assets/automode_loaded.json` are wrapped to make them structurally distinct from real rules:

```jsonc
{"__example_only": true, "value": "Example claim about the user — replace with your own."}
```

The migrate phase strips wrappers **by structure** (`isinstance(node, dict) and node.get("__example_only") is True and set(node.keys()) <= {"__example_only", "value"}`). A user rule whose plain-text content contains the literal string `__example_only` survives unchanged.

## CLI surface — `claude auto-mode {defaults,config,critique}`

| Subcommand | What it prints                                                   | When the skill calls it                                                     |
| :--------- | :--------------------------------------------------------------- | :-------------------------------------------------------------------------- |
| `defaults` | Built-in rules for each of `environment`, `allow`, `soft_deny`. | Advisor branch (informational), and during `--dangerously-skip-defaults` confirmation. |
| `config`   | The effective rule set with `$defaults` expanded in place.      | Advisor and validator branches (informational).                             |
| `critique` | Markdown report of risky entries (verbatim — see below).        | Phase 2 of every apply (`--dry-run` and commit).                            |

`critique` emits freeform Markdown with `# Critique of Custom Rules`, `## Major issues`, `## Smaller issues`, and `### N. <title>` blocks. **Exit code is 0 regardless of finding count.** There is no `severity` field and no `--json`. This skill does not parse severity from prose — Path (b): the user reads the verbatim output, the gate hashes the **settings bytes**, and the user explicitly approves the hash via `--approved-canonical-hash`. Full rationale: `references/critique_workflow.md`.

The skill probes once per run for `--settings` support (caches `claude auto-mode critique --help`). When `--settings` is present, the proposal lands in `~/.claude/.settings.json.proposal` and critique reads it directly. When `--settings` is absent, the swap-file fallback is gated behind `--allow-swap-file-fallback` (see `references/critique_workflow.md` for the race window and signal-handler restore).

## Atomic writes & backups

Every commit produces a timestamped backup before `os.replace`:

```
~/.claude/settings.json.bak.YYYY-MM-DDTHH-MM-SS
```

The skill prints the rollback command on its own line:

```
rollback: cp ~/.claude/settings.json.bak.YYYY-MM-DDTHH-MM-SS ~/.claude/settings.json
```

Backup retention: keep the 5 most recent (by mtime), prune older. Locking: `flock` on `~/.claude/settings.json.lock` with PID + ISO-8601 payload; stale (dead PID OR `> 5 min`) reclaims automatically; live contention exits 7 (`LockHeldError`). Recovery: `references/recovery.md`.

## Exit codes

| Code | Meaning                                                                                        |
| ---: | :--------------------------------------------------------------------------------------------- |
| 0    | Success.                                                                                       |
| 1    | Usage error / bad CLI args.                                                                    |
| 2    | Malformed input JSON (byte-offset reported).                                                   |
| 3    | `CritiqueFailed` — `claude auto-mode critique` exited non-zero, or contract drift detected.    |
| 4    | `MigrationStrategyRequired` — non-interactive migrate without `--migrate-strategy`.            |
| 5    | `claude` CLI not on `PATH`.                                                                    |
| 6    | `--show-drift` detected drift (informational, non-fatal).                                      |
| 7    | `LockHeldError` — flock held by another live, fresh process.                                   |
| 8    | `HashMismatchError` — `--approved-canonical-hash` did not match the freshly computed canonical hash. |
| 9    | `StrandedStateDetected` — orphan `*.preview-orig.<pid>` found; run `--repair` first.            |
| 10   | `OutOfBandError` — Claude Code version outside the declared band.                              |

## Edge cases — what the skill does

| Situation                                                                | Behaviour                                                                                                                  |
| :----------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------- |
| `~/.claude/settings.json` does not exist                                 | Fresh-machine flow: create `~/.claude/` mode 0700, file mode 0600, content `{}`, proceed. No backup.                       |
| `<repo>/.claude/settings.json` (shared, committed) contains `autoMode`   | Detected by `scan_project.py`; the skill refuses to write to it and points the user at user-level `~/.claude/settings.json`. |
| `permissions.allow` has `Bash(*)`, `Bash(python*)`, `Agent(*)`           | `scan_project.py` flags each. The migrate flow surfaces them per-item with a narrowed alternative from `assets/dropped_rules.yaml`. Auto mode would silently drop them on entry. |
| Mode 0644 (world-readable) `~/.claude/settings.json`                     | The skill warns and recommends `chmod 0600`; it does **not** auto-tighten.                                                 |
| `claude auto-mode critique` returns non-zero                             | Exit 3 (`CritiqueFailed`); stderr verbatim; no write attempted; no backup churn.                                           |
| Live critique output uses a renamed section (`## Severe issues`)         | Exit 3 (contract drift). Update `assets/critique_sample.md` with the new shape and re-run.                                 |
| User runs apply twice in the same second                                 | The flock holds; second invocation exits 7 (`LockHeldError`).                                                              |
| `SIGKILL` during the swap-file window                                    | Stranded `~/.claude/.auto-mode-config.preview-orig.<pid>` left on disk. Next run exits 9; user runs `--repair` to restore. |
| Approved hash drifts between dry-run and apply                           | Exit 8 (`HashMismatchError`). Re-run dry-run, capture fresh hash, re-approve.                                              |

Full recovery procedures (rollback, `--repair`, drift): `references/recovery.md`.

## Scripts

| Script                              | Purpose                                                                                  |
| :---------------------------------- | :--------------------------------------------------------------------------------------- |
| `scripts/_canonical.py`             | Shared module: canonical JSON serializer + flat YAML walker. Run with stdin → stdout for the round-trip property test. |
| `scripts/scan_project.py`           | Read-only project signal scanner. JSON output. Refuses out-of-band Claude Code version.  |
| `scripts/inspect_automode.py`       | Read-only diagnostics + `--show-drift`. Allowed on any plan.                             |
| `scripts/apply_automode.py`         | Generator + migrator + `--repair`. Atomic writer with hash + critique gate.              |

Each script's full flag set is in its `--help`. The team-plan contract for exit codes is uniform across all scripts.

## Acceptance & verification

The skill ships with 18 acceptance criteria as testable predicates and a `pytest` suite that covers them. Run from the worktree root:

```bash
uv run --with pytest --with hypothesis -m pytest skills/auto-mode-config/tests/ -q
# → 130 passed (50 canonical fixtures + hypothesis property + 18 acceptance + auxiliary)
```

Per-criterion measurement commands and the stub-`claude` fixture story: `references/verification.md`.

## References

- `references/mental_model.md` — what `autoMode` is, the three fields, cross-scope merge, fallback math, dropped-on-entry rules.
- `references/canonicalization.md` — canonical JSON form, sha256 contract, the round-trip property, the flat YAML walker.
- `references/critique_workflow.md` — Path (b), the `--settings` probe, the swap-file mechanism, contract-drift detection, signal handlers, the `### N.` walker.
- `references/migration.md` — Option 2b interactive flow, `--migrate-strategy`, durable claims vs project snapshots, why no auto-tagging.
- `references/verification.md` — 18 acceptance criteria with measurement commands, stub-`claude` fixtures, anti-tests.
- `references/recovery.md` — rollback, backup retention, `--repair`, stranded state, mode 0644 policy, drift response.

## Doc URLs (verbatim, do not fabricate)

- https://code.claude.com/docs/en/auto-mode-config
- https://code.claude.com/docs/en/permission-modes
- https://code.claude.com/docs/en/permissions
- https://code.claude.com/docs/en/settings
- https://code.claude.com/docs/en/server-managed-settings
- https://code.claude.com/docs/en/memory
- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/errors
- https://anthropic.com/engineering/claude-code-auto-mode
