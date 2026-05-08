# The three files

The skill operates on three settings files. Two are read by the
permission classifier for the `autoMode` key; the third is read only
for non-`autoMode` sections. The skill writes to one by default, the
second only with explicit opt-in, and the third only via `--hoist`.

## Summary

| File | Path | Classifier reads `autoMode`? | Skill default | Writable how |
|---|---|---|---|---|
| User baseline | `~/.claude/settings.json` | yes | read-only | `--hoist <rule-id>` |
| Project local (primary) | `.claude/settings.local.json` | yes | read+write | direct (Phase 3) |
| Project shared | `.claude/settings.json` | no | read-only | `--write-shared` (Phase 4) |

## User baseline — `~/.claude/settings.json`

- Per-user-global. Applies to every project on the host.
- Mode 0600 expected. If the file is mode 0644, the skill warns on
  startup but does not auto-`chmod` it; other tooling on the host may
  rely on the existing mode. The user fixes it manually if they
  agree with the warning.
- Read-only by default. The only mutation path is
  `apply_automode.py --hoist <rule-id>`, which moves a single rule
  from the local file to the user file and requires explicit
  confirmation. Hoisting acquires the user-file flock and writes
  atomically, same byte contract as the local file.
- The classifier reads `autoMode` here. Rules listed at this level
  apply to every project; users hoist rules they want host-wide.

## Project local — `.claude/settings.local.json`

- Per-user-per-project. Gitignored by default in most starters; the
  skill warns if `.claude/settings.local.json` is not covered by any
  `.gitignore` rule (`scan_project.py --check-gitignore`). The
  warning is stderr-only with no exit code change.
- Mode 0600. The skill creates the file at this mode and the parent
  `.claude/` directory at 0700 if either is missing.
- The primary target. Phase 3 always writes here. The classifier
  reads `autoMode` here.
- Backups in `.claude/.autoMode-config.backup.<ISO8601>.<sha256-12>`,
  retained 5 most recent per file, pruned on each successful apply.

## Project shared — `.claude/settings.json`

- Committed to the repo. Visible to teammates.
- Mode 0644 (committed file). The skill respects the file's mode.
- The classifier **silently ignores** the `autoMode` key when read
  from this file. Other sections (e.g. tool-specific settings,
  hooks declarations) are still honoured. The reason is policy, not
  bug: per-user permission rules cannot be safely shared across a
  team without per-user audit, so the classifier filters them out.
- Read for adoption (Phase 1): the skill surfaces every rule in the
  shared `autoMode` so the user can promote them into the local
  file. Each adoption is per-entry consent.
- Written only with `--write-shared` (Phase 4): the skill reprints
  the classifier-ignores warning at the prompt, shows the diff, and
  requires confirmation. Writing the shared file's `autoMode` makes
  it a team manifest of intent — useful for review and onboarding,
  not a rule the classifier will enforce.

## Gotchas

- **Shared-file `autoMode` is silently ignored.** This is the
  highest-impact misconception. A user who edits `.claude/settings.json`
  expecting their teammates' classifier to honour the rules will be
  surprised. The skill prints this warning at every read of shared
  `autoMode` and reprints it at every Phase 4 write.
- **Local file gitignore status varies.** Many project starters
  include `.claude/settings.local.json` in `.gitignore`; some do
  not. The skill warns but does not edit `.gitignore` for the user.
  Committing the local file leaks per-user permission decisions.
- **User file mode 0644.** Some installers create
  `~/.claude/settings.json` mode 0644. The skill warns on startup
  but does not modify the mode. Auto-tightening would be surprising
  for users whose other tools depend on the current mode.
- **Three independent flocks.** Each file has its own
  `<target>.lock` payload `<PID> <ISO8601>`. The skill acquires only
  the locks needed by the current phase. Phase 3 needs the local
  flock; Phase 4 needs the shared flock; `--hoist` needs both the
  local and the user flock. `--repair` reclaims all three.
- **`autoMode.environment` ordering.** The classifier reads the
  array in order. The canonical form preserves declared order; the
  skill never sorts the array. JSON object keys inside each entry
  are sorted (canonical-form requirement).
- **`$defaults` is a string sentinel, not an object.** The classifier
  substitutes Anthropic-curated trust signals at load time when
  `"$defaults"` appears in `environment`. The skill leaves it
  untouched. Removing it removes the curated baseline.
