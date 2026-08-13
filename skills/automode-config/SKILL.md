---
name: automode-config
description: "Author, validate, and migrate Claude Code autoMode blocks (environment, allow, soft_deny, hard_deny) at project level. Writes .claude/settings.local.json behind a `claude auto-mode critique` gate, a sha256 hash gate, and an atomic locked write; reads the user and shared settings files for adoption candidates. Requires Claude Code 2.1.83+."
metadata:
  version: "0.7.0"
tools:
  - Read
  - Write
  - Bash
---

# automode-config

Authors, validates, and migrates `autoMode` blocks for **project-level**
Claude Code permissions. Default write target is
`.claude/settings.local.json`. The user file (`~/.claude/settings.json`)
and the shared file (`.claude/settings.json`) are read for adoption
candidates and never written without an explicit opt-in flag plus a
re-confirmation.

## Three files

| File | Path | Classifier reads `autoMode`? | This skill | Mode |
|---|---|---|---|---|
| User baseline | `~/.claude/settings.json` | yes | read-only (write only via `--hoist`) | 0600, warn on 0644 |
| **Project local** | `.claude/settings.local.json` | yes | **read + write, the main target** | 0600 |
| Project shared | `.claude/settings.json` | no | read for adoption; write needs `--write-shared` | 0644 |

## Four sections

`autoMode` has exactly four array fields, all holding **prose rules**,
not `Tool(specifier)` patterns. There is no `ask` bucket and no plain
`deny` bucket; those belong to `permissions`.

- `environment`: trust signals (repos, buckets, domains, services).
- `allow`: exceptions overriding `soft_deny` for the same target.
- `soft_deny`: destructive actions, overridable by `allow` or stated
  user intent.
- `hard_deny`: unconditional. Not lifted by `allow`, by stated intent,
  or by `--dangerously-skip-permissions`.

Each section accepts the literal `"$defaults"` to splice Anthropic's
curated baseline in at that position. **Omitting it replaces that
section's baseline end-to-end**, per section, independently. The skill
preserves the sentinel verbatim and never expands it; it warns on every
write that drops it.

## Procedure

```bash
# 1. See what the three files currently say, and what the project implies.
uv run scripts/inspect_automode.py
uv run scripts/scan_project.py --json

# 2. Build a proposal (see below), then dry-run it for the canonical hash.
uv run scripts/apply_automode.py --proposal proposal.json --mode auto --dry-run

# 3. Commit with that hash as the gate predicate.
uv run scripts/apply_automode.py --proposal proposal.json --mode auto \
    --approved-canonical-hash <sha256>
```

Step 3 runs `claude auto-mode critique`, archives its output to
`.claude/.automode-history/`, and refuses to write when the critique is
missing or says nothing. Mode `auto` picks `fresh` or `migrate` from
whether the local file already holds an `autoMode` block.

## Building the proposal

Before the dry-run, read `CLAUDE.md`, `AGENTS.md`, and
`.claude/CLAUDE.md` (skip any that are absent) and translate what they
say into prose rules. Emit one JSON file covering all four sections:

```json
{
  "autoMode": {
    "environment": ["$defaults", "Source control: github.com/acme-corp and all repos under it"],
    "allow": ["$defaults", "Deploying to the staging namespace is allowed: it is isolated and resets nightly"],
    "soft_deny": ["$defaults", "Never run database migrations outside the migrations CLI"],
    "hard_deny": ["$defaults", "Never force-push to main or release/* branches"]
  }
}
```

The deterministic guards apply regardless of what the agent proposes:
schema validation, mistaken-pattern detection, version-band probe,
critique gate, hash gate, atomic write under flock.

## Invariants

- Never write `autoMode` into the shared file silently: it needs
  `--write-shared`, a confirmed prompt, and the classifier-ignores
  warning reprinted at write time.
- Never expand `"$defaults"`; preserve it verbatim at its position.
- Never treat a zero exit from the critique as approval on its own.

## Slash command

`/automode-edit <query>` (`commands/automode-edit.md`) edits the local
block in plain language and drives the same pipeline. It never touches
the shared or user files unless the query asks and the user reconfirms.

## References

Load on demand, not upfront.

| File | Read it when |
|---|---|
| `references/cli.md` | you need a flag or an exit code |
| `references/automode_doc_bible.md` | the schema or the classifier's semantics is in question |
| `references/mental_model.md` | you need the full six-phase flow and decision tree |
| `references/three_files.md` | a per-file mode, gotcha, or precedence question comes up |
| `references/migration.md` | adopting existing rules, or picking a `--migrate-strategy` |
| `references/critique_workflow.md` | the critique misbehaves, drifts, or the swap-file path triggers |
| `references/canonicalization.md` | byte-level output, fixtures, or `__example_only` |
| `references/recovery.md` | a write failed, or you need rollback / `--repair` |
| `references/verification.md` | you are checking acceptance predicates |

Docs (verified 2026-05-10):
[auto mode](https://code.claude.com/docs/en/auto-mode-config),
[permissions](https://code.claude.com/docs/en/permissions),
[permission modes](https://code.claude.com/docs/en/permission-modes),
[settings](https://code.claude.com/docs/en/settings).
