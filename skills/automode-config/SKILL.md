---
name: automode-config
description: "Author, validate, and migrate Claude Code autoMode blocks at the project level. Models the four official autoMode sections (environment, allow, soft_deny, hard_deny — all arrays of prose rules, with `$defaults` per section). Primary target is .claude/settings.local.json (per-user-per-project, gitignored, classifier-read). Reads ~/.claude/settings.json (user baseline, read-only) and .claude/settings.json (shared, classifier-ignores autoMode) for adoption candidates. Phase 1b is agent-driven: the calling agent reads CLAUDE.md / AGENTS.md / .claude/CLAUDE.md and emits a proposal JSON that flows through the same critique + hash-gate + atomic-write pipeline. Runs `claude auto-mode critique` as the canonical gate. Atomic write under per-file flock with sha256 hash gate. Requires Claude Code 2.1.83+ (auto mode itself; see references/automode_doc_bible.md)."
metadata:
  version: "0.5.0"
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

## Mental model: three files and four sections

| File | Path | Classifier reads `autoMode`? | Skill behaviour | Mode |
|---|---|---|---|---|
| **User baseline** | `~/.claude/settings.json` | yes | Read-only by default. Optional `--hoist <rule>` moves a rule from local to user. | 0600 (warn if 0644) |
| **Project local** ← primary | `.claude/settings.local.json` | yes | Read + write (flock, atomic, backups, hash gate). **The skill's main target.** | 0600 |
| **Project shared** | `.claude/settings.json` | no (for `autoMode` only — other sections still read) | Read for adoption. Write only with explicit opt-in flag, with classifier-ignores warning. | 0644 (committed file) |

**Sections:** `autoMode` has exactly four array fields, each holding
**prose rules** (natural-language descriptions, not `Tool(specifier)`
patterns):

- `environment` — trust signals: repos, buckets, domains, services
  considered "internal".
- `allow` — exceptions that override `soft_deny` rules of the same
  target.
- `soft_deny` — destructive actions; overridable by `allow` or by
  explicit user intent stated in the conversation.
- `hard_deny` — unconditional security boundary; not lifted by `allow`,
  intent flags, or user statements.

Each section accepts the literal string `"$defaults"` to splice in
Anthropic's curated baseline at that position. Omitting `"$defaults"`
**replaces** the default list end-to-end; the skill warns at every
write that does so.

`autoMode` does **not** have an `ask` bucket and does **not** have a
plain `deny` bucket — those names belong to the regular `permissions`
system. The skill rejects unknown autoMode keys; legacy proposals
using `deny` are migrated to `soft_deny` with a warning, and `ask`
entries are dropped with a warning.

**Critical invariant:** the skill must never write `autoMode` into
the shared file silently. Writing requires `--write-shared` AND
user-confirmed prompt AND the warning is reprinted at write time.

For the full schema, semantics, CLI surface, and version requirements,
see `references/automode_doc_bible.md` — it is distilled from the
official Claude Code docs and is the authoritative reference for this
skill. For per-file gotchas, see `references/three_files.md`.

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
2. Translate findings into **prose rules** under one of the four
   official sections (see `references/automode_doc_bible.md`):
   - **environment**: trusted infrastructure the project uses (Git
     hosting org, buckets, internal domains, CI/registry endpoints).
   - **allow**: exceptions for routine internal operations the
     classifier's defaults flag as risky (e.g. "Pushing to feature
     branches under `feature/*` on github.com/acme is allowed").
   - **soft_deny**: destructive risks specific to the project that
     `$defaults` does not cover (e.g. "Never run database migrations
     outside `./scripts/migrate.sh`, even on dev databases").
   - **hard_deny**: unconditional boundaries the docs say must never be
     auto-approved (e.g. "Never push to `main` or `release/*`",
     "Never send repository contents to external code-review APIs").
3. Write the proposal as JSON to a file (e.g.
   `/tmp/automode-proposal.json`). Rules are **prose strings**, not
   `Tool(specifier)` patterns:
   ```json
   {
     "autoMode": {
       "environment": [
         "$defaults",
         "Source control: github.com/acme-corp and all repos under it",
         "CI/CD: Jenkins at ci.acme.com, Artifactory at artifacts.acme.com"
       ],
       "allow": [
         "$defaults",
         "Deploying to the staging namespace is allowed: staging is isolated and resets nightly"
       ],
       "soft_deny": [
         "$defaults",
         "Never run database migrations outside the migrations CLI"
       ],
       "hard_deny": [
         "$defaults",
         "Never force-push to main or release/* branches",
         "Never send repository contents to third-party code-review APIs"
       ]
     }
   }
   ```
4. Pass the file to `apply_automode.py --proposal <file>` (with `--dry-run`
   first to obtain the canonical hash, then with `--approved-canonical-hash`).

The deterministic guards still apply: schema validation, mistaken-pattern
detection (warns when an autoMode rule looks like a `permissions`
pattern), version-band probe, critique exit-code gate, sha256 hash gate,
atomic write under flock. The agent cannot bypass them.

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

`hard_deny` is the unconditional bucket. Entries block classified
operations regardless of any matching rule in `allow` or `soft_deny`,
and they are not lifted by user intent stated in conversation or by
intent flags such as `--dangerously-skip-permissions`. The skill reads
and writes `hard_deny` identically to the other autoMode sections.
`"$defaults"` works in `hard_deny` exactly as it does in `environment`,
`allow`, and `soft_deny`: include it to keep Anthropic's curated
baseline; omit it to take full ownership of the section.
`--migrate-strategy drop-all` resets `hard_deny` to `[]` (and likewise
for `allow` and `soft_deny`); `environment` is reset to
`["$defaults"]`.

For unconditional gates outside the classifier (i.e. blocked even when
auto mode is off), use `permissions.deny` in managed settings — those
run before the classifier and cannot be overridden by user/project
settings.

## The `$defaults` trap

`"$defaults"` is a string sentinel accepted in **all four** autoMode
sections (`environment`, `allow`, `soft_deny`, `hard_deny`). At load
time the classifier splices Anthropic's curated baseline for the
section at the position where the sentinel appears; the rest of the
array is preserved.

The skill **never expands it**; it preserves the sentinel verbatim and
at its declared position. Three implications:

- A user who deletes `"$defaults"` from any section **loses the curated
  baseline for that section**. For `soft_deny` that means losing
  built-in rules like force-push, `curl | bash`, and production-deploy
  blocks; for `hard_deny` it means losing the data-exfiltration and
  safety-bypass blocks. Scan and inspect outputs flag the missing
  sentinel per section so the user can decide intentionally.
- `--migrate-strategy drop-all` empties `allow` / `soft_deny` /
  `hard_deny` to `[]` and rewrites `autoMode.environment` to exactly
  `["$defaults"]`. It is the start-from-scratch button: existing user
  rules are removed but the curated `environment` baseline is
  preserved.
- Each section is independent. Setting `environment` alone leaves the
  default `allow`, `soft_deny`, and `hard_deny` lists intact.

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

- `references/automode_doc_bible.md` — **start here**. Authoritative,
  doc-distilled reference: schema, semantics, CLI surface, scope rules,
  version requirements. The skill code is built to match this file.
- `references/mental_model.md` — three files, four sections, six phases, decision tree.
- `references/three_files.md` — file relationships and per-file gotchas.
- `references/canonicalization.md` — byte contract, fixtures, idempotency, `parse_flat_yaml`.
- `references/critique_workflow.md` — `claude auto-mode critique`, `--settings` probe, automatic swap-file, contract drift.
- `references/migration.md` — Phase 1a/1b adoption, project-doc scan, four-key prompt, strategy modes.
- `references/recovery.md` — backup retention, `--repair`, stranded state, multi-file flock.
- `references/verification.md` — acceptance predicates with measurement commands.

## Documentation URLs (verified 2026-05-10)

- Configure auto mode: <https://code.claude.com/docs/en/auto-mode-config>
- Permissions: <https://code.claude.com/docs/en/permissions>
- Permission modes: <https://code.claude.com/docs/en/permission-modes>
- Settings: <https://code.claude.com/docs/en/settings>
