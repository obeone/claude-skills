# Verification

Acceptance predicates, restated as testable items with a measurement
command per item. Pytest names follow the convention `test_acc01_…`
through `test_acc24_…`.

1. **Round-trip byte-equal across 50 canonical fixtures.**
   Measure: `uv run --with pytest -m pytest skills/automode-config/tests/test_canonical.py -k roundtrip -q`.
2. **`SKILL.md` <= 25 600 bytes.**
   Measure: `wc -c skills/automode-config/SKILL.md` -> first column <= 25600.
3. **`apply_automode.py --dry-run` runs in < 30 s on a developer laptop.**
   Measure: `time uv run skills/automode-config/scripts/apply_automode.py --dry-run --proposal skills/automode-config/tests/fixtures/proposal_minimal.json` -> wall < 30 s.
4. **`--dry-run` makes no non-localhost network calls.**
   Measure (Linux): `strace -f -e trace=connect uv run skills/automode-config/scripts/apply_automode.py --dry-run --proposal …` -> only AF_UNIX or 127.0.0.1/::1 connects. Macos soft check: lsof per child.
5. **Concurrent invocations: second exits 7 within ~100 ms.**
   Measure: launch two `apply_automode.py` against the same project; the second prints `EXIT_LOCK_HELD` and returns within 100 ms wall.
6. **Stale lock reclaimed (dead PID OR > 5 min old).**
   Measure: write `<file>.lock` with payload `999999 1970-01-01T00-00-00Z`; run apply; verify reclaim and successful write.
7. **Fresh-machine flow: no `.claude/settings.local.json` => mode 0600 + parent dir 0700.**
   Measure: in a tempdir with no `.claude/`, run `apply_automode.py --proposal ... --approved-canonical-hash ...`; `stat -f '%Lp' .claude` -> 700; `stat -f '%Lp' .claude/settings.local.json` -> 600.
8. **Backup file mode 0600.**
   Measure: after one apply, `stat -f '%Lp' .claude/.automode-config.backup.*` -> 600 for every match.
9. **Atomic write survives SIGKILL between fsync and replace.**
   Verify by construction (the temp file's existence is harmless; the live file is unchanged until `os.replace`). Test: kill the apply between fsync and replace; verify live file unchanged and the temp file is the only orphan.
10. **Critique exit-non-zero is hard-fail (exit 3).**
    Measure: stub `claude_fail` on PATH; run apply; expect exit 3.
11. **Contract drift fails loudly (exit 3).**
    Measure: stub `claude_drift` on PATH (replaces `## Major issues` with `## Major problems`); run apply; expect exit 3.
12. **Hash mismatch raises HashMismatchError (exit 8).**
    Measure: pass `--approved-canonical-hash deadbeef…`; expect exit 8.
13. **Migrate drop-all empties target's `autoMode.environment` to `["$defaults"]`.**
    Measure: seed the local file with non-empty `autoMode`; run `apply_automode.py --mode migrate --migrate-strategy drop-all`; verify the resulting `autoMode.environment == ["$defaults"]`.
14. **Migrate keep-all is byte-equal (no proposal change).**
    Measure: seed local; run with `--migrate-strategy keep-all`; verify the canonical bytes of the post-write local file equal the canonical bytes of the merged input.
15. **`__example_only` anti-test: structural wrapper stripped, substring preserved.**
    Measure: feed both forms in a fixture; verify the structural form is unwrapped at load and the substring is preserved verbatim in canonical bytes.
16. **Missing `claude` CLI => exit 5 with installation pointer.**
    Measure: run apply with `PATH=/tmp/empty`; expect exit 5 and a stderr line containing the installation URL.
17. **Stranded state detected at startup (exit 9 with `--repair` pointer).**
    Measure: touch `~/.claude/.automode-config.preview-orig.999999`; run apply; expect exit 9.
18. **`--repair` restores from `.preview-orig.<pid>` and is idempotent.**
    Measure: simulate stranded state; run `--repair`; verify live file restored and sentinel removed; run `--repair` again -> exit 0, no changes.
19. **Adopt-from-shared surfaces each entry interactively.**
    Measure: seed `.claude/settings.json` with an `autoMode` block of three rules; run `scan_project.py`; verify three adoption candidates in the output. Run `apply_automode.py` (interactive); verify the four-key prompt fires per entry.
20. **`--write-shared` opt-in; without it, `.claude/settings.json` is never modified.**
    Measure: run apply without the flag; `stat -f '%m'` on shared file unchanged. Run with `--write-shared`; verify the warning is reprinted at write time and the file is updated.
21. **Multi-file inspect reports presence + sha256 + drift status.**
    Measure: `inspect_automode.py --json` -> object with three keys (`user`, `local`, `shared`), each containing `present` (bool), `sha256` (string|null), `drift` (bool). Absence non-fatal.
22. **Auto fresh/migrate.**
    Measure: with no `.claude/settings.local.json`, `--mode auto` -> mode == fresh. With one, mode == migrate. `--mode fresh|migrate` overrides either way.
23. **`scan_project.py --check-gitignore` warns if local file not covered.**
    Measure: in a project with no `.gitignore`, run `scan_project.py --check-gitignore`; verify a stderr warning. Add `.claude/settings.local.json` to `.gitignore`; verify no warning. Exit code unchanged in either case.

24. **`hard_deny` round-trip and drop-all reset.**
    Measure: seed local file with non-empty `autoMode.hard_deny`; run `inspect_automode.py --json` and verify the `hard_deny` array is present in output. Run `apply_automode.py --mode migrate --migrate-strategy drop-all`; verify the resulting `autoMode.hard_deny == []`.

## Cross-checks

- No dangling references in `references/*.md` or `SKILL.md` -> grep
  for `references/[a-z_]+\.md` and verify each path resolves.
- `wc -l` on each `references/*.md` within its budget (200, 200,
  150, 200, 200, 150, 200).
- `_canonical.py` matches all 50 fixture pairs:
  `uv run --with pytest -m pytest skills/automode-config/tests/test_canonical.py -q`.
- `apply_automode.py --help`, `inspect_automode.py --help`, and
  `scan_project.py --help` all exit 0 and print the documented flags.
