# Migration

Phases 1a, 1b, and 2 fold rules from existing sources into the proposal
the skill is about to write. All three phases use the same per-entry
interactive prompt: `[k]eep / [e]dit / [d]rop / [q]uit`. Phases 1a and 1b
can be suppressed with `--migrate-strategy` non-interactive modes.

## Phase 1a — adopt-from-shared

Triggered when `.claude/settings.json` contains an `autoMode` block
and `--include-shared` is in effect (default). The skill reads each
entry in `autoMode.allow`, `autoMode.ask`, `autoMode.deny`,
`autoMode.hard_deny`, and `autoMode.environment` from the shared file.
For each entry not already in the proposal:

```
[Phase 1] Adopt from shared (.claude/settings.json):
  rule: Bash(uv run pytest:*)
  source: .claude/settings.json#autoMode.allow[3]
  reminder: shared autoMode is silently ignored by the classifier.
  [k]eep / [e]dit / [d]rop / [q]uit ?
```

- `[k]eep` adds the rule verbatim to the proposal at the same
  position in its target list.
- `[e]dit` opens `$EDITOR` (or `nano` if unset) on a temp file
  containing the rule; the edited result is parsed back. Parse
  errors return to the prompt.
- `[d]rop` discards the rule. The skill remembers dropped rules so
  Phase 4 can show "would have written N adoptions" diff cleanly.
- `[q]uit` exits Phase 1 cleanly. Already-decided entries are kept;
  remaining entries are dropped. The skill prints
  `quit at entry K of N` for the audit trail.

## Phase 1b — agent-driven adoption from project docs

Triggered after Phase 1a (or first if shared has no `autoMode`). The
calling agent reads CLAUDE.md, AGENTS.md, and `.claude/CLAUDE.md` from
the project root, applies judgment, and writes a JSON proposal that
flows through `apply_automode.py --proposal <file>`.

The agent uses the four-bucket model to classify what it finds:

- **allow**: tools the docs document as routine (test runners, linters,
  build tools, local dev commands).
- **ask**: anything ambiguous or potentially destructive that should
  surface a prompt.
- **deny**: paths/operations the docs warn against but a flag could
  legitimately override.
- **hard_deny**: protected branches, secrets paths, anything the docs
  say must NEVER be auto-approved. `hard_deny` overrides `allow` for
  the same target and is not bypassable by user-intent flags.

The agent writes a proposal JSON, then passes it to
`apply_automode.py --proposal <file> --dry-run` to obtain the canonical
hash, then reruns with `--approved-canonical-hash`. The same per-entry
four-key prompt (`[k]eep / [e]dit / [d]rop / [q]uit`) applies when the
pipeline is run interactively.

## Phase 2 — scan-project signals

Triggered after Phase 1 (or as the first interactive phase if shared
has no `autoMode`). The skill walks `assets/heuristics.yaml` against
the project root and emits a candidate per signal that fires:

```
[Phase 2] Scan signal: signal_dockerfile
  matched: ./Dockerfile
  candidate: Bash(docker build:*)
  rationale: <signal description from heuristics.yaml>
  [k]eep / [e]dit / [d]rop / [q]uit ?
```

The four-key prompt behaves identically to Phase 1. Skipping is
silent — if no signals fire, the phase prints nothing and Phase 3
runs.

## `--migrate-strategy` modes

Applies to both Phase 1a/1b (adoption) and the fold-in of any
pre-existing local `autoMode` (when `--mode migrate`). Default is
`interactive`.

- `interactive` (default). Per-entry four-key prompt as above.
- `keep-all`. Every existing rule is folded in unchanged. The
  proposal bytes are byte-equal to the merged input. No prompt.
- `drop-all`. Every existing rule is dropped. `autoMode.environment`
  is reset to `["$defaults"]` (the curated baseline preserved); the
  allow, ask, deny, and hard_deny lists become empty arrays. No prompt.
- `fail`. Any existing rule that conflicts with the proposal's
  rules causes the skill to exit 2 (`EXIT_VALIDATION`). Useful for
  CI-style runs where the operator wants no surprise inheritance.

`--migrate-strategy` and `--mode` interact as follows:

- `--mode fresh --migrate-strategy keep-all` is contradictory: there
  is no existing local rule to keep. The skill exits 1 with a
  message; the user picks one or the other.
- `--mode migrate --migrate-strategy drop-all` is the
  start-from-scratch button: it preserves `$defaults` and nothing
  else.
- `--mode migrate --migrate-strategy interactive` is the default
  walk for users who want to review.
- `--mode auto` defers to the file state: if the local file lacks
  `autoMode`, the strategy applies only to Phase 1 adoptions; if
  the local file has one, the strategy also applies to its rules.

## What `[e]dit` accepts

The editor receives a single rule on a single line. After the user
saves and exits, the skill:

1. Strips trailing whitespace and trailing newline.
2. Verifies the result parses as a valid permission rule (matches
   one of the known prefix forms, no banned patterns from
   `dropped_rules.yaml`).
3. On success, replaces the candidate with the edited rule.
4. On failure, prints the parser error and re-prompts with the
   four-key menu. The user can `[e]dit` again or `[d]rop`.

## `[q]uit` semantics

`[q]uit` is mid-phase, not whole-pipeline:

- Quitting Phase 1 leaves Phase 2 to run (if signals match).
- Quitting Phase 2 still runs Phase 3 with the partial proposal.
- The user gets the rollback line at the end either way.

To abort the whole run, `Ctrl-C` raises a `KeyboardInterrupt` that
propagates up; the signal handlers in Phase 3's swap-file fallback
restore any orig file before re-raising. No write is performed.
