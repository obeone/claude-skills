# Critique workflow — Path (b), swap-file, contract drift

> Target ≤ 200 lines. Loaded when an agent needs the precise semantics of phase 2 (`claude auto-mode critique` invocation), the swap-file fallback, or contract-drift detection.

## What `claude auto-mode critique` actually does

The binary takes the **current state** of `~/.claude/settings.json` (plus optional `--settings <path>` when supported) and emits a freeform Markdown report classifying entries it considers risky. Verified live behaviour as of `claude 2.1.133`:

- `--help` advertises only `--model <model>`. Whether `--settings <path>` is honoured is detected at runtime.
- Output is Markdown with:
  - `# Critique of Custom Rules` (H1 title)
  - `## Major issues` (required section)
  - `## Smaller issues` (required section)
  - Items rendered as `### N. <title>` blocks with body paragraphs underneath.
- **Exit code is `0` regardless of finding count.** A clean settings file and a settings file with nine major issues both exit 0.
- There is **no `severity` field**, no JSON output, no machine-readable contract.

Any approach that tried to infer severity from prose would be a bet on the prose format, which Anthropic does not promise to preserve. The skill's design (Path (b)) anchors elsewhere.

## Path (b) — user is the severity classifier

The skill prints the **verbatim** Markdown under a fenced header (`=== auto-mode critique ===`). The user (human or calling agent) reads it and decides whether to proceed. The gate predicate has nothing to do with the prose:

```
gate_passes = (critique_exit_code == 0)
            AND (sha256(canonicalize(proposal)) == --approved-canonical-hash)
```

`--ignore-critique-warnings` does not exist as a flag. There is nothing structured to ignore. The hash protects the **settings bytes**; the critique is a human-readable supplement.

## The `### N.` walker (informational only)

The skill walks the Markdown to print a count of items under each section as a courtesy. The walker:

1. Splits on `^## ` headers, locates `## Major issues` and `## Smaller issues`.
2. Inside each section, counts lines matching `^### \d+\.` (the documented format).
3. If that pattern produces zero matches but the section is non-empty, falls back to `^\*\*\d+\.` (bold-numbered variant).
4. If both fail, prints `(parser may be stale; raw output above is authoritative)` next to the count.

Critically, **the count is never a gate predicate**. A future format change that makes the count read `0` while the body lists 12 issues is a UX defect, not a safety defect — the verbatim output is what the user actually approves.

## Contract drift

The skill enforces one structural property: the section header set must be exactly `{"## Major issues", "## Smaller issues"}`.

| Live output                                            | Behaviour                                                                                |
| :----------------------------------------------------- | :--------------------------------------------------------------------------------------- |
| Required sections present, no extras                   | Proceed.                                                                                 |
| A required section is **missing** (e.g. renamed)       | Refuse with exit `3` (`ContractDriftError`). Update `assets/critique_sample.md`.         |
| **Extra** sections present, `--allow-unknown-critique-sections` not set | Refuse with exit `3`. Same remediation.                                  |
| Extra sections present, `--allow-unknown-critique-sections` set        | Print an advisory listing the extras, continue.                          |

When drift trips, the message points at `assets/critique_sample.md` (the committed fixture) so the maintainer knows what to update.

## `--settings` capability probe

Exactly once per run, before flock acquisition, the skill runs:

```bash
claude auto-mode critique --help 2>&1
```

and greps for `--settings`. The result is cached for the lifetime of the run.

| Probe result            | Path                                                                                                          |
| :---------------------- | :------------------------------------------------------------------------------------------------------------ |
| `--settings` supported  | Direct path: write proposal to `~/.claude/.settings.json.proposal` (mode 0600), invoke critique with `--settings` pointing at it. |
| `--settings` absent     | The default is to **refuse** with `EXIT_USAGE` and a pointer to `--allow-swap-file-fallback`.                  |
| `--settings` absent + `--allow-swap-file-fallback` | Swap-file mechanism (below).                                                              |

The probe runs **before** the lock so the binary's startup time is not held under contention.

## Swap-file mechanism (only with `--allow-swap-file-fallback`)

When the user explicitly opts in, the skill swaps the proposal into `~/.claude/settings.json` for the duration of the critique call:

```
1. Acquire flock on ~/.claude/settings.json.lock.
2. Register SIGINT, SIGTERM, SIGHUP handlers that restore .preview-orig.<pid> on exit.
3. Rename ~/.claude/settings.json → ~/.claude/.auto-mode-config.preview-orig.<pid>
4. Write proposal canonical bytes to ~/.claude/settings.json (mode 0600).
5. Invoke `claude auto-mode critique` (no --settings).
6. In `finally`: rename .auto-mode-config.preview-orig.<pid> → settings.json.
7. Release flock.
```

Risks accepted (documented loud and clear in error output):

- A parallel `claude` invocation in another terminal does **not** take this skill's flock and may read the proposal mid-swap. The race window is bounded by the critique runtime, not infinite, but real.
- `SIGKILL`, segfault, OOM-kill, and power loss all leave a stranded `.auto-mode-config.preview-orig.<pid>` file. The next run detects it (exit `9`) and refuses until `--repair` is run. `references/recovery.md` covers the recovery procedure.

The flag's existence is opt-in by design. When `--settings` lands upstream universally, this code path will be deprecated.

## flock and stale-lock reclaim

`~/.claude/settings.json.lock` is acquired with `fcntl.LOCK_EX | fcntl.LOCK_NB`. Lock payload: `<PID> <ISO8601>`. On contention:

- Read the existing payload.
- `os.kill(pid, 0)` to test liveness; if `OSError` → dead PID.
- Compare timestamp to `time.time()` against `LOCK_STALE_SECONDS` (300 = 5 min).
- Stale (dead OR `> 5 min` old) → reclaim (rewrite payload, proceed).
- Otherwise → exit `7` (`LockHeldError`) with the holder's PID and start time.

The lock scope is **inter-skill**: it coordinates between two `apply_automode.py` runs. It does not block a parallel `claude` reading `settings.json`. That's a property of advisory locks on POSIX.

## Network failure on critique

Critique calls a server-side model. Transient failures (network, rate limit, gateway) surface as a non-zero exit from the binary. The skill treats every non-zero exit identically: exit `3` (`CritiqueFailed`), surface stderr verbatim, leave the user's `~/.claude/settings.json` untouched, no backup created.

There is no automatic retry. The retry policy is *user re-runs the command*. This is deliberate: silent retry loops fight the loud-fail-on-drift principle.

## Atomic write sequence (after the gate passes)

```
1. Compute timestamp = time.strftime("%Y-%m-%dT%H-%M-%S", time.gmtime()).
2. Write backup: cp ~/.claude/settings.json ~/.claude/settings.json.bak.<timestamp>.
3. Write canonical to ~/.claude/settings.json.tmp.<pid>, mode 0600. fsync.
4. os.replace(tmp, settings.json).
5. Update ~/.claude/.auto_mode_approved.json with the canonical bytes (mode 0600).
6. Prune backups: keep the 5 most recent (by mtime).
7. Release flock (in finally).
8. Print rollback command:
     cp ~/.claude/settings.json.bak.<timestamp> ~/.claude/settings.json
```

Step 4 is the atomicity guarantee: `os.replace` is rename(2), which is atomic within a filesystem. Steps 1–3 produce the new file out-of-band; step 4 swaps it in; step 5 records what was approved.

## See also

- `references/canonicalization.md` — what "canonical bytes" means; the round-trip property.
- `references/migration.md` — phase 1 (proposal build) for the `--mode migrate` path.
- `references/recovery.md` — `--repair`, stranded-state detection, restoring a backup, mode 0644 pre-existing files.
- `references/verification.md` — the test suite that exercises this workflow with stub `claude` binaries.
