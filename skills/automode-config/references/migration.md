# Migration

Phases 1a, 1b, and 2 fold rules from existing sources into the proposal
the skill is about to write, but only Phase 1a actually interviews the
user. Its prompt (`_interview` in `apply_automode.py`) is a bare
`[{label}] {entry!r}` line followed by `[k]eep  [e]dit  [d]rop  [q]uit  >`.
Phase 1b is agent-driven with no interview of its own. Phase 2 currently
computes signals and discards them, see below. `--migrate-strategy`
non-interactive modes (`keep-all`, `drop-all`, `fail`) suppress Phase
1a's prompt.

Phase 1a exists because the classifier silently ignores `autoMode` in
the shared file: `_phase4_write_shared` prints exactly that warning
when writing there ("the Claude Code permission classifier IGNORES
autoMode in this file; this serves as a team manifest of intent
only"). Adopting a rule out of the shared file and into the local file
is how it starts being enforced at all.

## Phase 1a — adopt-from-shared

Triggered whenever `.claude/settings.json` contains an `autoMode`
block; `apply_automode.py` has no `--include-shared` flag of its own
to gate this (that flag belongs to `scan_project.py`, see
`references/cli.md`). The skill reads every entry in
`autoMode.environment`, `autoMode.allow`, `autoMode.soft_deny`, and
`autoMode.hard_deny` from the shared file, printing a one-line section
header before each (`[Phase 1a] adopt-from-shared :: <section>`), then
interviews each entry in turn:

```
[shared.environment] 'Source control: github.com/acme-corp and all repos under it'
  [k]eep  [e]dit  [d]rop  [q]uit  >
```

The section header (`[Phase 1a] adopt-from-shared :: <section>`) goes
to stderr via `_eprint`; the prompt itself goes to stdout. They only
appear as separate streams under redirection.

The prompt only appears when `--migrate-strategy interactive` (the
default) is in effect **and** stdin is a TTY; otherwise every entry is
kept unchanged with no prompt at all.

Legacy compatibility: if the shared file still uses the obsolete
`autoMode.deny` or `autoMode.ask` keys, entries from `deny` are
surfaced as `soft_deny` candidates with a warning. Entries from `ask`
are surfaced with a warning that the bucket does not exist, but
`[e]dit` cannot rescue them: whatever survives the interview for that
section is printed as `discarding <entry>: autoMode has no 'ask'
section` and never added to the proposal, kept or edited alike.
`[d]rop` is the only interview action that matches what actually
happens to an `ask` entry.

- `[k]eep` (or a blank line) adds the rule verbatim to the proposal.
- `[e]dit` accepts a replacement inline rather than opening an editor;
  see "What `[e]dit` accepts" below for the full mechanics.
- `[d]rop` discards the rule for this run. The decision is echoed once,
  in-phase (`  - <entry>: drop`), but nothing carries it further: there
  is no diff of dropped rules shown later, in Phase 4 or anywhere else.
- `[q]uit` ends the interview for the *current section only* and the
  walk continues with the next section. It does not exit Phase 1a as
  a whole, and no "quit at entry K of N" message is printed. Whatever
  in that section had not yet been reviewed is silently dropped:
  `_interview` returns only the `kept` list it built before quitting,
  so the unreviewed remainder never reaches the proposal. An EOF on
  stdin has the identical effect, since `_interview` catches
  `(EOFError, KeyboardInterrupt)` at the same point and treats it as
  `[q]uit` (see "`[q]uit` and Ctrl-C semantics" below).

## Phase 1b — agent-driven adoption from project docs

Triggered after Phase 1a (or first if shared has no `autoMode`). The
calling agent reads CLAUDE.md, AGENTS.md, and `.claude/CLAUDE.md` from
the project root, applies judgment, and writes a JSON proposal that
flows through `apply_automode.py --proposal <file>`.

The agent translates findings into **prose rules** (not
`Tool(specifier)` patterns) and slots them into the four official
autoMode sections — see `automode_doc_bible.md` for the schema:

- **environment**: trusted infrastructure (git org, buckets, internal
  domains, CI endpoints).
- **allow**: exceptions for routine internal operations the
  classifier's defaults flag as risky.
- **soft_deny**: project-specific destructive risks that `$defaults`
  does not cover.
- **hard_deny**: unconditional boundaries the docs say must never be
  auto-approved (protected branches, exfiltration vectors).

The agent writes a proposal JSON, then passes it to
`apply_automode.py --proposal <file> --dry-run` to obtain the canonical
hash, then reruns with `--approved-canonical-hash`. There is no
per-entry interview of this proposal: `_interview` is Phase 1a's
shared-file mechanism only and is never called on `--proposal`'s
content. What actually gates a Phase 1b proposal is the deterministic
guard chain described in `SKILL.md`, run in this order: the semantic
lint, schema validation, the hash gate, the critique gate.

## Phase 2: scan-project signals (computed, not currently acted on)

`_phase2_signals` (`apply_automode.py`) runs `scan_project.build_report`
against the project root and returns the signals that fired. The call
site discards the return value outright:

```
_phase2_signals(files)  # informational — no merge by default
```

There is no candidate printed, no `rationale` line, and no
`[k]eep / [e]dit / [d]rop / [q]uit` prompt. Nothing from this phase
reaches the proposal on its own. If you want a scan signal reflected
in the proposal, write it into the proposal JSON yourself (Phase 1b)
rather than relying on Phase 2 to surface it.

Separately: of the 20 `signal_*` entries in `assets/heuristics.yaml`,
only 4 (`signal_dockerfile`, `signal_compose`, `signal_pyproject`,
`signal_uv_lock`) currently match a probe with real detection logic in
`scan_project.py`. The rest are text descriptions that
`_load_heuristics` routes into `heuristics_meta` and never probes.
`scan_project.py` still probes 7 signals in total, not 4:
`signal_pkg_json`, `signal_gitignore`, and `signal_node_modules` have
working probes with no matching entry in the YAML at all, and are
appended unconditionally (`_load_heuristics`, `scan_project.py:154-158`).
Wiring the remaining unmatched YAML signals up is out of scope for
this branch.

## `--migrate-strategy` modes

The flag controls Phase 1a's shared-file interview (above) and, via
`--mode migrate`, how a pre-existing local `autoMode` block is
treated by `_migrate_strategy`. The two are not symmetric: only Phase
1a ever prompts. Default is `interactive`.

- `interactive` (default). Phase 1a interviews each shared-file entry
  as described above. The pre-existing *local* `autoMode` block, if
  any, is **not** interviewed under this strategy today: `_migrate_strategy`'s
  `interactive` branch returns it unchanged, the same effective
  outcome as `keep-all`, with no prompt of its own.
- `keep-all`. Every existing rule is folded in unchanged, in both
  contexts: `_migrate_strategy` returns the local block as-is, and
  Phase 1a's `_interview` is a pass-through, so no shared-file entry
  is dropped or edited. That is not byte-for-byte equality with the
  original file: `_merge_proposal` still injects
  `environment: ["$defaults"]` when the block has no `environment` key,
  `_strip_example_only` still unwraps example-only entries,
  `_filter_dropped` still removes any `DROPPED_PATTERN_LITERALS`
  match, and `canonicalize` still reformats the result. No prompt.
- `drop-all`. Every existing rule is dropped. `autoMode.environment`
  is reset to `["$defaults"]` (the curated baseline preserved); the
  `allow`, `soft_deny`, and `hard_deny` lists become empty arrays. No
  prompt. Legacy `deny` / `ask` keys are removed.
- `fail`. Refuses to migrate whenever the local file already has a
  non-empty `autoMode` block, unconditionally: this is a presence
  check, not a conflict check against the proposal's own rules. The
  skill exits 2 (`EXIT_VALIDATION`). Useful for CI-style runs where
  the operator wants no surprise inheritance at all.

`--migrate-strategy` and `--mode` interact as follows:

- Passing `--migrate-strategy` alongside `--mode fresh` raises no
  error; the two flags are not cross-validated. In `fresh` mode,
  `_migrate_strategy` (which only handles the pre-existing local
  block) is simply never called, so the flag's only effect is on
  Phase 1a's shared-file interview, which runs regardless of `--mode`.
- `--mode migrate --migrate-strategy drop-all` is the
  start-from-scratch button: it preserves `$defaults` and nothing
  else.
- `--mode migrate --migrate-strategy interactive` does not walk the
  pre-existing local rules today (see above). It is the default
  because it is also the mode combination that leaves Phase 1a's
  shared-file interview interactive, not because it reviews the local
  block.
- `--mode auto` defers to the file state: if the local file lacks
  `autoMode`, mode resolves to `fresh` and the strategy only affects
  Phase 1a's shared-file adoptions; if the local file has one, mode
  resolves to `migrate` and the strategy is also passed to
  `_migrate_strategy` for the pre-existing local block (subject to
  the `interactive` caveat above).

## What `[e]dit` accepts

There is no `$EDITOR` step. `_interview` prompts inline on the same
terminal:

```
  new value (JSON, blank = keep):
```

1. A blank line keeps the original entry unchanged.
2. Otherwise the line is parsed with `json.loads`. Invalid JSON
   prints the parse error and keeps the original. Nothing else about
   the value is checked at this point: no prefix-form check, no
   lookup against any file.
3. Whatever the JSON parses to (string, number, object, ...) replaces
   the entry outright. The schema validator (`_validate_proposal`)
   and the semantic lint run later, over the whole proposal, and are
   what actually reject a malformed or wrong-typed entry.
4. Separately, for `allow` / `soft_deny` / `hard_deny` entries,
   `_filter_dropped` compares each surviving entry (edited or not)
   against a fixed tuple, `DROPPED_PATTERN_LITERALS`
   (`Bash(*)`, `PowerShell(*)`, `Bash(python*)`, `Agent(*)`), and
   silently drops an exact match with a `! dropped ...: silently
   dropped by classifier` message.

**`assets/dropped_rules.yaml` is not part of this or any other check.**
`DROPPED_RULES_PATH` is defined once (`apply_automode.py`) and never
read again; the file exists on disk but nothing in `scripts/` parses
it. The effective drop list is `DROPPED_PATTERN_LITERALS` in
`apply_automode.py`; edit that tuple, not the YAML file, to add or
change a dropped literal.

## `[q]uit` and Ctrl-C semantics

`[q]uit` only exists inside Phase 1a's interview, and it is
per-section, not per-phase or whole-pipeline:

- Quitting one section's interview (e.g. `environment`) still walks
  the next section; it does not skip the rest of Phase 1a, regardless
  of what happened in the section that was quit.
- Phase 2 has no interview to quit (see above). Reaching Phase 3 does
  not depend on what happened in Phase 1a, but Phase 3 has its own
  earlier exits that have nothing to do with Phase 1a: `--dry-run`
  returns before the commit; a blocking semantic-lint finding, a
  schema failure, and a missing or mismatched
  `--approved-canonical-hash` all return before the critique even
  runs; a failed or non-substantive critique returns before the
  commit. The optional Phase 4 (`--write-shared`) only runs after a
  *successful* Phase 3 commit.
- The rollback line prints only after a successful local commit
  (`_print_rollback`, right after `_atomic_write`); none of the
  earlier exits above reach it.

`Ctrl-C` at a Phase 1a prompt does **not** abort the whole run:
`_interview` catches `(EOFError, KeyboardInterrupt)` at the point
where it reads the answer and treats it exactly like `[q]uit` for that
section. `_phase1_adopt` then continues with the next section as
usual, and the run proceeds through the lint, the hash gate, the
critique, and the commit.

`Ctrl-C` during the critique subprocess, on the swap-file fallback
path (when the CLI lacks `--settings`), does not restore the swapped
file from inside the signal handler either: `install_signal_release`
(`_locks.py:208-233`) installs handlers for `SIGTERM` and `SIGINT`
that release the flock and chain to the process's prior disposition
(or exit); it does not touch the swapped file. The restore is the
`finally` wrapped around the critique invocation
(`_run_critique_swap`), which runs as that signal unwinds through it,
not something the handler does directly. No write to the *local*
settings file has happened by that point either way: Phase 3's
`_atomic_write` for `.claude/settings.local.json` only runs after the
critique returns and passes every check above.
