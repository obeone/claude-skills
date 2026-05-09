---
name: automode-config
description: "Author, validate, and migrate Claude Code autoMode blocks at the project level (four-bucket allow/ask/deny/hard_deny model). Primary target is .claude/settings.local.json (per-user-per-project, gitignored, classifier-read). Reads ~/.claude/settings.json (user baseline, read-only) and .claude/settings.json (shared, classifier-ignores autoMode) for adoption candidates. Phase 1b is agent-driven: the calling agent reads CLAUDE.md / AGENTS.md / .claude/CLAUDE.md, applies judgment, and emits a proposal JSON that flows through the same critique + hash-gate + atomic-write pipeline as any other proposal. Runs `claude auto-mode critique` as the canonical Path (b) gate. Atomic write under per-file flock with sha256 hash gate. Requires Claude Code 2.1.136+."
metadata:
  version: "0.4.1"
tools:
  - Read
  - Write
  - Bash
---

# automode-config

A skill for authoring, validating, and migrating `autoMode` blocks
for **project-level** Claude Code permissions. The skill writes by
default to `.claude/settings.local.json` (per-user-per-project,
gitignored, read by the classifier). It reads two adjacent files —
`~/.claude/settings.json` and `.claude/settings.json` — and surfaces
their state without mutating them unless the user explicitly opts in.

## Out of scope

- Multi-project orchestration. The skill operates on the cwd's
  project only.
- Auto-`chmod` of pre-existing `~/.claude/settings.json` mode 0644.
  Warn-only; the user fixes it manually if they agree.
- Capturing real critique output from the binary into
  `assets/critique_sample.md`. Hand-crafted is the v0.1.0 fixture;
  real-binary capture is v0.2.0.
- A `--lint` mode for `.claude/settings.json` non-`autoMode`
  sections. This skill is autoMode-only.
- Retry-on-network-failure logic. The user re-runs.

## Mental model: three files and four rule buckets

| File | Path | Classifier reads `autoMode`? | Skill behaviour | Mode |
|---|---|---|---|---|
| **User baseline** | `~/.claude/settings.json` | yes | Read-only by default. Optional `--hoist <rule>` moves a rule from local to user. | 0600 (warn if 0644) |
| **Project local** ← primary | `.claude/settings.local.json` | yes | Read + write (flock, atomic, backups, hash gate). **The skill's main target.** | 0600 |
| **Project shared** | `.claude/settings.json` | no (for `autoMode` only — other sections still read) | Read for adoption. Write only with explicit opt-in flag, with classifier-ignores warning. | 0644 (committed file) |

**Rule buckets:** `autoMode` contains four independent rule lists:
`allow` (auto-approved), `ask` (surfaced to user), `deny` (blocked,
bypassable), and `hard_deny` (blocked unconditionally, not bypassable).
Plus `environment` (trust-signal array, separate from rule buckets).

**Critical invariant:** the skill must never write `autoMode` into
the shared file silently. Writing requires `--write-shared` AND
user-confirmed prompt AND the warning is reprinted at write time.

For full per-file gotchas (gitignore status, mode 0644 user file,
shared-file `autoMode` ignored), see `references/three_files.md`.

## Workflow: six phases (0 + 1a + 1b + 2 + 3 + 4)

```
[Phase 0] auto-detect fresh vs migrate (presence of autoMode in .claude/settings.local.json)
    |
    v
[Phase 1a] adopt-from-shared (if .claude/settings.json contains autoMode)
    |   per-entry interactive: [k]eep / [e]dit / [d]rop / [q]uit
    v
[Phase 1b] agent-driven adoption from project docs (CLAUDE.md / AGENTS.md / .claude/CLAUDE.md)
    |   per-candidate interactive: [k]eep / [e]dit / [d]rop / [q]uit
    v
[Phase 2] scan-project signals (Dockerfile, package.json, .gitignore, etc.)
    |   per-signal interactive: [k]eep / [e]dit / [d]rop / [q]uit
    v
[Phase 3] commit local: critique + hash gate + atomic write to .claude/settings.local.json
    |   prints rollback line, updates approved cache
    v
[Phase 4] propose-to-shared (opt-in via --write-shared, defaults to NO)
    |   shows diff, reprints classifier-ignores warning, atomic write to .claude/settings.json
    v
done.
```

Phase 0 is automatic and silent. Phases 1a, 1b, 2, 4 are skipped cleanly
when their precondition is absent. Phase 3 always runs.

Phase 3 archives every critique invocation (success and failure) to
`.claude/.automode-history/critique-<UTC>.md`. Section-header validation
of the critique output is opt-in via `--strict-critique-sections`; the
default gate is exit code == 0 only (binary section names drift across
versions).

### Phase 1b — agent-driven adoption from project docs

Before Phase 3 commits the proposal, the calling agent SHOULD enrich it
with rules implied by the project's documentation:

1. Read these files (skip silently if absent):
   - `<project>/CLAUDE.md`
   - `<project>/AGENTS.md`
   - `<project>/.claude/CLAUDE.md`
   - Optionally `~/.claude/CLAUDE.md` (user-global conventions; include
     only if the project hasn't redefined them)
2. Propose rules using the four-bucket model:
   - **allow**: tools the docs document as routine (test runners, linters,
     build tools, local dev commands).
   - **ask**: anything ambiguous or potentially destructive that should
     surface a prompt.
   - **deny**: paths/operations the docs warn against but a flag could
     legitimately override.
   - **hard_deny**: protected branches, secrets paths, anything the docs
     say must NEVER be auto-approved. `hard_deny` overrides `allow` for
     the same target and is not bypassable by user-intent flags.
3. Write the proposal as JSON to a file (e.g. `/tmp/automode-proposal.json`):
   ```json
   {
     "autoMode": {
       "allow":     ["Bash(<tool>:*)", "..."],
       "ask":       ["..."],
       "deny":      ["..."],
       "hard_deny": ["Bash(git push * <branch>*)", "..."],
       "environment": ["$defaults"]
     }
   }
   ```
4. Pass the file to `apply_automode.py --proposal <file>` (with `--dry-run`
   first to obtain the canonical hash, then with `--approved-canonical-hash`).

The deterministic guards still apply: schema validation,
classifier-dropped pattern filter, version-band probe (Claude Code 2.1.136+
for `hard_deny`), critique exit-code gate, sha256 hash gate, atomic write
under flock. The agent cannot bypass them.

## The single intent question

Asked silently from file state, never prompted: **does
`.claude/settings.local.json` already contain an `autoMode` block?**

- **No** -> mode `fresh`. The skill creates a new block. Phase 1a may
  still adopt from shared; Phase 1b may surface project-doc candidates;
  Phase 2 scans for signals; Phase 3 writes the block at mode 0600
  (parent dir 0700 if absent).
- **Yes** -> mode `migrate`. The skill rewrites the existing block
  using `--migrate-strategy` to fold rules
  (`keep-all`, `drop-all`, `interactive`, `fail`).

`--mode fresh|migrate` overrides the auto-detection.

## CLI surface

### `scan_project.py`

| Flag | Default | Purpose |
|---|---|---|
| `--project-root <path>` | cwd | Project root to scan. |
| `--json` | off | Machine-readable output. |
| `--include-shared` / `--no-include-shared` | on | Read `.claude/settings.json` `autoMode` for adoption candidates. |
| `--check-gitignore` | off | Warn if `.claude/settings.local.json` not in `.gitignore`. |

### `inspect_automode.py`

| Flag | Default | Purpose |
|---|---|---|
| `--project-root <path>` | cwd | Project root to inspect. |
| `--show-drift` | off | Compare each file's canonical bytes vs approved cache; exit 6 on drift. |
| `--json` | off | Machine-readable output. |
| `--file {user,shared,local,all}` | all | Restrict to one file. |

### `apply_automode.py`

| Flag | Default | Purpose |
|---|---|---|
| `--project-root <path>` | cwd | Project root. |
| `--mode {auto,fresh,migrate}` | auto | Pipeline mode; `auto` derives from local file. |
| `--proposal <path>` | required for non-interactive | JSON proposal to write. |
| `--dry-run` | off | Compute hash, no writes; preview rollback. |
| `--approved-canonical-hash <sha256>` | required for non-dry-run | Gate predicate. |
| `--migrate-strategy {keep-all,drop-all,fail,interactive}` | interactive | Existing-rule fold-in. |
| `--show-drift` | off | Alias delegating to `inspect_automode.py`. |
| `--model <model>` | (CLI default) | Passed to `claude auto-mode critique`. |
| `--allow-swap-file-fallback` | off | DEPRECATED no-op; swap-file is now automatic when `--settings` is missing. |
| `--strict-critique-sections` | off | Validate critique output sections against the hardcoded contract (off by default — exit_code == 0 is the real gate). |
| `--allow-unknown-critique-sections` | off | Forward-compat alias for `--strict-critique-sections=loose`. Off by default (validation is now opt-in). |
| `--write-shared` | off | Phase 4 opt-in: also write to `.claude/settings.json`. |
| `--hoist <rule-id>` | off | Move rule from local to user. |
| `--repair` | off | Restore orphans + reclaim locks; mutually exclusive with all other modes. |

## Exit codes

| Code | Name | Meaning |
|---|---|---|
| 0 | EXIT_OK | Success. |
| 1 | EXIT_USAGE | Missing flag, unsupported combo. |
| 2 | EXIT_VALIDATION | Proposal fails JSON schema. |
| 3 | EXIT_CRITIQUE_FAILED | Non-zero from `claude`, contract drift. |
| 4 | EXIT_PERMISSION | Filesystem permission denied. |
| 5 | EXIT_CLAUDE_CLI_MISSING | `claude` not on PATH. |
| 6 | EXIT_DRIFT | Canonical bytes != approved cache. |
| 7 | EXIT_LOCK_HELD | Live writer holds flock. |
| 8 | EXIT_HASH_MISMATCH | `--approved-canonical-hash` != actual. |
| 9 | EXIT_STRANDED_STATE | `.preview-orig.<pid>` orphans found. |
| 10 | EXIT_OUT_OF_BAND | `claude` version outside heuristics range. |

(11 codes counting `EXIT_OK`.)

## hard_deny semantics

`hard_deny` is an unconditionally enforced rule bucket. Entries in
`autoMode.hard_deny` block classified operations regardless of rules in
`allow`, `ask`, or `deny`. `hard_deny` overrides any rule for the same
target in other buckets. It is not bypassable by user-intent flags like
`--dangerously-skip-permissions`. Requires Claude Code 2.1.136+. The
skill reads and writes `hard_deny` identically to other rule sections;
the `$defaults` sentinel does not apply (it is a rule list, not an env
array). `--migrate-strategy drop-all` resets `hard_deny` to `[]`.

## The `$defaults` trap

`autoMode.environment` is a JSON array. The string sentinel
`"$defaults"` tells the classifier to substitute Anthropic-curated
trust signals at load time. The skill **never expands it**; it
preserves the sentinel verbatim and at its declared position. Two
implications:

- A user who deletes `"$defaults"` loses the curated baseline. The
  scan and inspect outputs flag missing `$defaults` so the user can
  decide intentionally.
- `--migrate-strategy drop-all` empties the lists but rewrites
  `autoMode.environment` to exactly `["$defaults"]`. It is the
  skill's start-from-scratch button, not a denuding button.

## The `__example_only` wrapper

Two forms, two meanings:

- **Structural form**: an object exactly equal to
  `{"__example_only": true, "value": <real>}`. The classifier
  loader strips the wrapper and uses `<real>` as the rule. The
  skill's canonicalization preserves the wrapper bytes; the loader
  unwraps at read time. Useful for asset/example fixtures that
  must round-trip canonical-equal but should be ignored at runtime.
- **Substring form**: the literal text `__example_only` inside any
  string value. Preserved verbatim; not interpreted. Use freely in
  rule names, comments, or paths.

`assets/automode_loaded.json` demonstrates both forms.

## Atomic write + rollback

Every write goes through `_canonical.canonical(obj) -> bytes`
followed by:

```
fd = os.open(target + ".tmp." + str(pid), O_WRONLY|O_CREAT|O_EXCL, 0600)
os.write(fd, canonical(obj))
os.fsync(fd)
os.close(fd)
os.replace(target + ".tmp." + str(pid), target)
```

The flock is held across the whole sequence. Backups are taken
before the replace. The rollback line printed at the end of Phase 3:

```
Rollback: cp -p .claude/.automode-config.backup.2026-05-08T14-22-13Z.a1b2c3d4e5f6 .claude/settings.local.json
```

Five backups per file are retained (per-file pool, pruned on each
successful apply). For `--repair` semantics, multi-file flock
cleanup, and stranded-state detection, see `references/recovery.md`.

## Critique history

Every critique invocation writes its raw output to
`.claude/.automode-history/critique-<UTC>.md` with a header containing
the proposal hash, the binary's `--version`, and the exit code. Useful
for auditing what the binary said during a run, especially on
`EXIT_CRITIQUE_FAILED`. The directory is created at mode 0700 if
missing; each archive file is mode 0600.

## Edge cases

- **`~/.claude/settings.json` mode 0644.** Some installers create
  the user file world-readable. The skill warns on startup but
  does not auto-`chmod`; auto-tightening is surprising for users
  whose other tools depend on the existing mode.
- **Local file not in `.gitignore`.** `scan_project.py
  --check-gitignore` warns to stderr if the project's
  `.gitignore` rules do not cover `.claude/settings.local.json`.
  No exit code change; the user fixes it manually.
- **Shared-file write reprints the classifier-ignores warning.**
  Phase 4 always reprints the warning at the prompt and the diff,
  even if the user passed `--write-shared`. The skill never lets
  the warning slide.
- **Swap-file is automatic.** When the critique CLI lacks
  `--settings`, the skill swaps `~/.claude/settings.json` transiently
  for the duration of the critique invocation (the classifier reads
  from user-level). The swap is atomic with signal-handler restore;
  SIGKILL leaves a sentinel that `--repair` reclaims. The deprecated
  `--allow-swap-file-fallback` flag is now a no-op. See
  `references/critique_workflow.md`.
- **Three independent flocks.** Each of the three files has its
  own `<target>.lock`. The skill acquires only the lock(s) needed
  by the current phase; `--repair` reclaims all three. See
  `references/recovery.md`.

## References

- `references/mental_model.md` — three files, four rule buckets, six phases, decision tree.
- `references/three_files.md` — file relationships and per-file gotchas (including `hard_deny` round-trip).
- `references/canonicalization.md` — byte contract, fixtures, idempotency, `parse_flat_yaml`.
- `references/critique_workflow.md` — Path (b), `--settings` probe, automatic swap-file, contract drift.
- `references/migration.md` — Phase 1a/1b adoption, project-doc scan, four-key prompt, strategy modes.
- `references/recovery.md` — backup retention, `--repair`, stranded state, multi-file flock.
- `references/verification.md` — acceptance predicates with measurement commands.

## Documentation URLs

- Claude Code permissions: <https://docs.claude.com/en/docs/claude-code/iam>
- Claude Code settings: <https://docs.claude.com/en/docs/claude-code/settings>
- Anthropic Engineering — autoMode design notes: <https://www.anthropic.com/engineering/claude-code-best-practices>
