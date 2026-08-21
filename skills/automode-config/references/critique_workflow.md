# Critique workflow

How `apply_automode.py` invokes `claude auto-mode critique`, what it
treats as authoritative, and how it handles the two known
failure modes (CLI lacks `--settings`; CLI changes the section
contract).

## Path (b) — bytes are the contract

The hash gate is checked first, before the critique ever runs:
`sha256(canonical(proposal)) == --approved-canonical-hash`. A mismatch
exits `EXIT_HASH_MISMATCH` (8); a missing flag exits `EXIT_USAGE` (1).

Once the hash matches, the critique gate is not a single predicate,
it is a chain, and exit code 0 is only the first, weakest link:

- `critique_exit_code == 0` is necessary but proves nothing by
  itself. Non-zero exits `EXIT_CRITIQUE_FAILED` (3) immediately.
  The binary has been observed exiting 0 while printing prose
  failures instead of a review, e.g. `Failed to analyze rules:
  Could not resolve authentication method` and `No critique was
  generated. Please try again.` A bare exit-code check would let
  both through as "approved."
- `_check_critique_substantive(output)` runs by default (unless
  `--allow-empty-critique`) and rejects empty output, output under
  `MIN_CRITIQUE_CHARS` (24) non-whitespace characters, and output
  matching `DEGENERATE_CRITIQUE_PATTERNS` (the "no critique was
  generated" / "unable to generate a critique" phrasings). Failure
  exits `EXIT_CRITIQUE_FAILED` (3).
- `--strict-critique-sections`, opt-in, additionally requires the
  `## Major issues` / `## Smaller issues` headers (see "Contract
  drift" below). Off by default.

The skill never falls back to a prose-derived gate; the critique's
narrative output is shown verbatim to the user but does not feed
the predicate beyond these checks.

## `--settings` capability probe

Once per run, before any flock, the skill runs:

```
claude auto-mode critique --help 2>&1 | grep -- --settings
```

- If `--settings <path>` is supported: the proposal's own canonical
  bytes are written to a private, mode-0600 temp file inside a fresh
  `mkdtemp` directory (never inside `.claude/`), and that path is
  passed as `--settings`. The temp directory is removed unconditionally
  once the subprocess returns, success or failure.

  **This is a fix, not the original behaviour.** Before it, this path
  pointed `--settings` at the pre-existing `.claude/settings.local.json`,
  a file the proposal is not written to until *after* the critique
  passes the gate, and one that does not exist yet in `fresh` mode. The
  critique therefore reviewed stale or absent content while the hash
  gate still approved based on that output. Anyone who approved a
  proposal on an older build of this skill was not necessarily getting
  a critique of what they approved; the archived output under
  `.claude/.automode-history/` from that period should not be trusted
  as a review of the committed `autoMode` block.
- If `--settings` is absent: the skill swaps `~/.claude/settings.json`
  transiently for the duration of the critique invocation (see "Swap-file
  path" below). An informational notice is logged to stderr. The
  deprecated `--allow-swap-file-fallback` flag is now a no-op kept for
  backward compatibility.

The probe runs once and is cached for the lifetime of the
`apply_automode.py` process. It is not persisted across runs.

## Swap-file path

When the critique CLI omits `--settings`, the skill performs the
following sequence (all under the user-file flock, since the swap
target is `~/.claude/settings.json` — the critique CLI reads from
there):

1. Acquire the user-file lock.
2. If `~/.claude/settings.json` exists, copy it (mode preserved) to
   `~/.claude/.automode-config.preview-orig.<pid>`, the sentinel.
3. Read that same file as the merge base, then overlay the proposal's
   `autoMode` onto a copy of it and write the merged document as the
   new `~/.claude/settings.json`, mode 0600. This is a merge, not a
   substitution: handing the CLI the proposal alone strips the user's
   `env`, `hooks`, `statusLine`, `permissions`, and everything else,
   which makes the binary run amputated and return "No critique was
   generated" instead of a review. When the original is unreadable or
   absent, the merge degrades to the proposal alone and a warning is
   printed, since there is no base to overlay onto.
4. Handle `SIGTERM` and `SIGINT` (not `SIGHUP`, which is not
   installed) by releasing the lock and letting the interrupt continue
   to unwind normally. The restore itself happens in the `try`/`finally`
   wrapped around the critique invocation, which still runs on that
   unwind, on a normal return, and on any other exception.
5. Run `claude auto-mode critique --model <model>`.
6. In the `finally`: if the sentinel exists, restore it over
   `~/.claude/settings.json` (atomic write, original mode) and delete
   the sentinel; if no original existed in step 2, remove the file the
   swap created instead of restoring nothing.
7. Release the user-file lock.

If the process ends in a way that skips the `finally` entirely
(`SIGKILL`, `SIGHUP`, hard reboot), the preview-orig file is left
behind. That is **stranded state**: the next startup detects it and
exits 9 with a `--repair` pointer.

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

Under `--strict-critique-sections` only, the skill enforces the
section header set `{"## Major issues", "## Smaller issues"}` on the
critique markdown. Without that flag, this check never runs.

- Missing required section -> exit 3 (`EXIT_CRITIQUE_FAILED`), always,
  whether or not `--allow-unknown-critique-sections` is passed.
- Extra section header (e.g. `## Recommendations`) -> exit 3 unless
  `--allow-unknown-critique-sections` is passed. That flag tolerates
  *additional* headers only.
- Different casing or punctuation -> exit 3 (header match is exact
  byte-for-byte after trimming trailing whitespace). A renamed header
  fails as a missing one, not an extra one.

`--allow-unknown-critique-sections` is not the escape hatch for a
renamed required section. `_check_critique_sections` (apply_automode.py)
raises on `missing` unconditionally, before it ever consults the flag;
the flag only gates `extras`. A header rename is simultaneously a
missing required header and an extra one, so the flag changes nothing
for it: the run still exits 3. The CLI 2.1.237 drift cited below
(`## Highest-priority issues` in place of `## Major issues`) is exactly
this case: confirmed by running `--strict-critique-sections
--allow-unknown-critique-sections` against that header pair, which
still exits 3, not a bypass. Since the whole check is opt-in, the
actual escape hatch during a known incompatible upgrade is not
passing `--strict-critique-sections` at all. The substantiveness and
hash gates (see "Path (b)" above) still apply regardless.

## No item-level parsing

The skill does not parse the critique body's internal structure by
default; it only checks that output exists and clears
`MIN_CRITIQUE_CHARS` (see "Substantiveness gate" below). The one
exception is `REQUIRED_CRITIQUE_SECTIONS` (`## Major issues` / `##
Smaller issues`), and that is consulted only under the opt-in
`--strict-critique-sections`, never by default.

CLI 2.1.237 has been observed emitting `## Highest-priority issues`
instead of `## Major issues`, which is exactly why that header check
stayed opt-in: hardcoding a header set that the binary can rename
out from under the skill would turn routine CLI drift into a hard
failure. The bytes are the contract, not a layout the skill infers
meaning from.

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

Archived text can quote values from the user's real settings, since
the swap path's critique runs against a document built from them
(0600 alone does not stop `git add`). Right after archiving, the
skill checks whether `.claude/.automode-history/` is covered by a
`.gitignore` rule and, if not, warns on stderr with the exact line to
add.

## Help-snapshot fixture

`assets/critique_help_snapshot.txt` captures the live binary's
`claude auto-mode critique --help` output. Nothing in `scripts/` or
`tests/` currently reads or diffs against this file: it is a manual
capture point for whoever refreshes it by hand, not a wired-up check.
Treat it as documentation of the last-known `--help` output, not as
a guarantee that CLI flag drift is caught anywhere automatically.
