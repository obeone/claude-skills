# Mental model

Three files. Four sections. Six phases. One classifier that reads
only two of the three files and silently ignores the `autoMode` key
in the third. The skill never hides any of these facts; it surfaces
them at the points where the user can do something about them.

For the canonical schema (the source of truth this skill aligns with)
see `automode_doc_bible.md`.

## The three files and four sections

| File | Path | Classifier reads `autoMode`? |
|---|---|---|
| User baseline | `~/.claude/settings.json` | yes |
| Project local (primary target) | `.claude/settings.local.json` | yes |
| Project shared (committed manifest) | `.claude/settings.json` | no |

The primary target — the one the skill mutates by default — is
`.claude/settings.local.json`. The user baseline is read-only by
default; the only way to write to it is `--hoist <rule-id>`, which
moves a single rule from local to user with explicit confirmation.
The shared file is read for adoption candidates and only ever written
when the user passes `--write-shared`, with the
classifier-ignores warning reprinted at write time.

Each `autoMode` block has exactly four array fields:

- `environment` — trust signals (repos, buckets, domains, services)
  the classifier should treat as "internal".
- `allow` — exceptions that override `soft_deny` rules of the same
  target.
- `soft_deny` — destructive actions the classifier blocks; overridable
  by `allow` or by explicit user intent stated in conversation.
- `hard_deny` — unconditional security boundary; not lifted by any
  override.

All four hold **prose strings**, not `Tool(specifier)` patterns. Each
accepts the literal `"$defaults"` to splice in Anthropic's curated
baseline at that position. There is **no** `ask` and **no** plain
`deny` bucket inside `autoMode` — those names belong to the
`permissions` system.

## The six phases

`apply_automode.py` runs a six-phase pipeline. Phase 0 is automatic
detection; Phases 1a, 1b, 2, 4 are skipped cleanly when their precondition
is absent; Phase 3 always runs.

```
[Phase 0] auto-detect fresh vs migrate
            (presence of autoMode in .claude/settings.local.json)
                 |
                 v
[Phase 1a] adopt-from-shared (skipped if shared has no autoMode)
             per-entry: [k]eep / [e]dit / [d]rop / [q]uit
                 |
                 v
[Phase 1b] agent-driven adoption from project docs (CLAUDE.md / AGENTS.md / .claude/CLAUDE.md)
             per-candidate: [k]eep / [e]dit / [d]rop / [q]uit
                 |
                 v
[Phase 2] scan-project signals (skipped if no signals match)
            per-signal: [k]eep / [e]dit / [d]rop / [q]uit
                 |
                 v
[Phase 3] commit local: critique + hash gate + atomic write
            (always runs; prints rollback line; updates approved cache)
                 |
                 v
[Phase 4] propose-to-shared (skipped without --write-shared)
            shows diff; reprints classifier-ignores warning;
            atomic write to .claude/settings.json
                 |
                 v
                done.
```

## The decision tree

The single intent question — asked silently, derived from the file
state, never prompted — is: **does `.claude/settings.local.json`
already contain an `autoMode` block?**

- No -> mode `fresh`. Phase 1a may still adopt from shared; Phase 1b
  may surface project-doc candidates; Phase 2 scans for signals;
  Phase 3 writes a brand-new block to the local file at mode 0600
  (parent dir 0700 if absent).
- Yes -> mode `migrate`. Same Phase 1/2 path; Phase 3 rewrites the
  local file using `--migrate-strategy` to choose how the existing
  rules are folded in (`keep-all`, `drop-all`, `interactive`,
  `fail`).

`--mode fresh|migrate` overrides the auto-detection. `--mode auto`
(default) selects from the file state.

## What each phase does (and what it skips)

- **Phase 0 — detect.** Reads the local file once. No prompt, no
  output beyond a debug log line. Sets the run's mode unless
  `--mode` was passed.
- **Phase 1a — adopt-from-shared.** Reads the shared file. For each
  rule in `autoMode.environment|allow|soft_deny|hard_deny` not present
  in the proposal, asks `[k]eep / [e]dit / [d]rop / [q]uit`. Prints the
  classifier-ignores warning at the start so the user understands
  these rules currently do nothing. Legacy entries under `deny` are
  presented as candidates for the `soft_deny` bucket; entries under
  `ask` are surfaced with a warning that autoMode has no `ask` bucket
  (the user can edit them into a `soft_deny` rule or drop them).
  Skipped silently if shared has no `autoMode` or `--no-include-shared`
  was passed at scan.
- **Phase 1b — agent-driven adoption from project docs.** The calling
  agent reads CLAUDE.md, AGENTS.md, and `.claude/CLAUDE.md` from the
  project root, applies judgment, and writes a JSON proposal that flows
  through `apply_automode.py --proposal <file>`. Rules are **prose**
  (e.g. "Never force-push to main") slotted into the four official
  sections. The deterministic guards (schema validation,
  mistaken-pattern detection, critique gate, hash gate, atomic write)
  still apply; the agent cannot bypass them.
- **Phase 2 — scan-project.** Computes `scan_project` signals against
  the project root and discards the result; nothing merges into the
  proposal and there is no prompt (see `references/migration.md` for
  the current state). Only 4 of the 20 `signal_*` entries in
  `assets/heuristics.yaml` resolve to a working probe today; the rest
  are inert descriptions.
- **Phase 3 — commit local.** Always runs. Probes
  `claude auto-mode critique --help` for `--settings`. Runs the
  critique. Verifies the gate predicate
  `critique_exit_code == 0 AND sha256(canonical(proposal)) == approved_hash`.
  Acquires the local-file flock, writes atomically, prunes backups
  to 5 most recent, prints the rollback line.
- **Phase 4 — propose-to-shared.** Skipped unless `--write-shared`.
  Shows the diff against the shared file's current `autoMode`,
  reprints the classifier-ignores warning, prompts for confirm,
  acquires the shared-file flock, writes atomically.

## Per-phase flock policy

Each of the three files has its own flock. The skill acquires only
the locks for the phase it is in; it never holds all three at once.
Stale locks (dead PID or older than five minutes) are reclaimed.
`--repair` reclaims locks unconditionally and restores any orphaned
preview-orig files in either `~/.claude/` or the project `.claude/`.

## What lives elsewhere

- File-level relationships, classifier behaviour per file, and the
  gotchas around shared-file writes: see `three_files.md`.
- Byte-level canonical-form contract and fixture format: see
  `canonicalization.md`.
- Critique invocation, `--settings` probe, swap-file fallback,
  contract-drift handling: see `critique_workflow.md`.
- Adopt-from-shared mechanics, scan interview, migrate strategies:
  see `migration.md`.
- Backups, `--repair`, stranded state in both locations: see
  `recovery.md`.
- The 24 acceptance predicates as testable items: see
  `verification.md`.
