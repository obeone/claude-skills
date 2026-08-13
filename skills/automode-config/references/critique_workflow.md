# Critique workflow

How `apply_automode.py` invokes `claude auto-mode critique`, what it
treats as authoritative, and how it handles the two known
failure modes (CLI lacks `--settings`; CLI changes the section
contract).

## Path (b) — bytes are the contract

The gate predicate for any non-dry-run write is:

```
critique_exit_code == 0
  AND
sha256(canonical(proposal)) == approved_hash
```

Both conditions must hold. The skill never falls back to a
prose-derived gate; the critique's narrative output is shown
verbatim to the user but does not feed the predicate. Severity
counts via the `### N.` walker (with `**N.**` fallback) are
informational only.

## `--settings` capability probe

Once per run, before any flock, the skill runs:

```
claude auto-mode critique --help 2>&1 | grep -- --settings
```

- If `--settings <path>` is supported: the critique is invoked on
  the proposal directly. Path: `claude auto-mode critique --settings
  <proposal-path> --model <model>`.
- If `--settings` is absent: the skill swaps
  `~/.claude/settings.json` transiently for the duration of the
  critique invocation (atomic restore; sentinel reclaimed by
  `--repair` after SIGKILL). An informational notice is logged to
  stderr. The deprecated `--allow-swap-file-fallback` flag is now a
  no-op kept for backward compatibility.

The probe runs once and is cached for the lifetime of the
`apply_automode.py` process. It is not persisted across runs.

## Swap-file path

When the critique CLI omits `--settings`, the skill performs the
following sequence (all under the user-file flock, since the swap
target is `~/.claude/settings.json` — the critique CLI reads from
there):

1. Acquire user-file flock.
2. Copy `~/.claude/settings.json` to
   `~/.claude/.automode-config.preview-orig.<pid>`.
3. Write the proposal as the new
   `~/.claude/settings.json` (canonical bytes, mode preserved from
   the original).
4. Install signal handlers (SIGINT, SIGTERM, SIGHUP) that restore
   the orig file before re-raising. Wrap the critique invocation in
   `try`/`finally` so the restore also runs on exit.
5. Run `claude auto-mode critique --model <model>`.
6. In the `finally`, restore the orig file via `os.replace` and
   delete the preview-orig sentinel.
7. Release the user-file flock.

If the process is killed in a way no signal handler can catch
(SIGKILL, hard reboot), the preview-orig file is left behind. That
is **stranded state**: the next startup detects it and exits 9 with
a `--repair` pointer.

The swap is in `~/.claude/`, not the project. This is because the
critique CLI reads from the user-level file regardless of which
project's local file we are about to write — the skill's persistence
target is the project file, but the validation invocation reads from
user-level. Stranded preview-orig files can therefore appear in
either `~/.claude/` (from swap-file fallback) or the project
`.claude/` (from interrupted Phase 3 before atomic replace, in
theory; in practice the atomic-replace design prevents this, and the
recovery walk checks both locations defensively).

## Contract drift

The skill enforces the section header set
`{"## Major issues", "## Smaller issues"}` on the critique markdown.

- Missing required section -> exit 3 (`EXIT_CRITIQUE_FAILED`).
- Extra section header (e.g. `## Recommendations`) -> exit 3
  unless `--allow-unknown-critique-sections` is passed.
- Different casing or punctuation -> exit 3 (header match is exact
  byte-for-byte after trimming trailing whitespace).

Contract drift is a hard fail because it indicates the critique CLI
has shifted its output format and the skill cannot trust the
informational walker counts. Users who want to bypass during a known
incompatible upgrade pass `--allow-unknown-critique-sections`; the
gate predicate (exit 0 AND hash) still applies.

## `### N.` walker

Inside each section, items are numbered with `### N.` headers
(observed in current binary). The walker counts these and also
falls back to `**N.**` (bold) form for compatibility with prior
critique output. Counts are printed alongside the prose so the user
sees `Major: N items, Smaller: M items` before the rendered
markdown.

The walker counts feed nothing else. They are not used in the gate
predicate; they are not persisted; they do not change exit codes.
The bytes are the contract.

## Substantiveness gate

Exit code 0 does not mean the proposal was reviewed. The binary has
been observed exiting 0 after printing only:

```text
Analyzing your auto mode rules…

No critique was generated. Please try again.
```

Gating on the exit code alone lets that through, which silently
promotes an unreviewed proposal past the hash gate. `apply_automode.py`
therefore also requires the output to be substantive: non-empty, at
least `MIN_CRITIQUE_CHARS` of non-whitespace text, and free of the
`DEGENERATE_CRITIQUE_PATTERNS` phrases. Failure is
`EXIT_CRITIQUE_FAILED`, raised **after** the archive is written so the
evidence survives. `--allow-empty-critique` bypasses the check.

This check asserts nothing about layout, so it does not break when the
binary renames its sections. Layout assertions live behind
`--strict-critique-sections` (see "Contract drift" above).

## Critique history

Every invocation, success or failure, writes its raw output to
`.claude/.automode-history/critique-<UTC>.md`, with a header carrying
the proposal hash, the binary's `--version`, and the exit code. The
directory is created at mode 0700 if missing; each archive file is
mode 0600. This is the audit trail for what the binary actually said
during a run, which matters most on `EXIT_CRITIQUE_FAILED`.

## Help-snapshot fixture

`assets/critique_help_snapshot.txt` captures the live binary's
`claude auto-mode critique --help` output. The skill diffs against
this fixture defensively in tests; if the diff is non-empty, the
test fails with a pointer to re-run the capture. This catches CLI
flag drift in a known-good test rather than at runtime.
