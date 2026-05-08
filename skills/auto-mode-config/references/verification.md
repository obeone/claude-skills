# Verification — 18 acceptance criteria as testable predicates

> Target ≤ 200 lines. Loaded when an agent needs the test plan, the stub-binary fixtures, or measurement commands for the acceptance criteria.

## How verification is structured

Three layers, run from a single `pytest` invocation:

```bash
cd /Users/obeone/Documents/geek/github/claude-skills/.worktrees/feat-skill-auto-mode-config
uv run --with pytest --with hypothesis -m pytest skills/auto-mode-config/tests/ -q
```

| Layer | File                                | Coverage                                                                                                  |
| :---- | :---------------------------------- | :-------------------------------------------------------------------------------------------------------- |
| 1     | `tests/test_canonical.py`           | 50 fixture round-trips + hypothesis property test + flat-YAML walker happy/sad paths + `load_json` byte-offset test (acceptance #1). |
| 2     | `tests/test_pipeline.py`            | 19 pipeline tests covering acceptance #5–#18 plus 4 inspect-side tests and a swap-file end-to-end smoke.   |
| 3     | `tests/fixtures/stub_claude/*`      | POSIX `/bin/sh` stub binaries that emit predetermined critique output. PATH-prepended in tests.            |

130 tests total at the time this skill ships. Green run is the primary gate.

## The 50 canonical fixtures

```
tests/fixtures/canonical/in_NN.json     # 00..09 hand-curated, 10..49 generated
tests/fixtures/canonical/out_NN.json    # canonical-form expected output
tests/fixtures/canonical/_generate.py   # deterministic fixture generator (stdlib random, seed 20260508)
tests/fixtures/canonical/seed.txt       # pinned seed + generator parameters
```

Hand-curated edge cases: unicode keys, deep nesting, top-level `null`, top-level array, top-level string, mixed types, very long string, escaped characters, empty object, single key. Generated cases use `random` with a pinned seed so any maintainer can reproduce them with `python tests/fixtures/canonical/_generate.py`.

## The 4 stub `claude` binaries

`tests/fixtures/stub_claude/` contains tiny shell scripts the test harness places on `PATH`:

| Stub                       | Purpose                                                                                |
| :------------------------- | :------------------------------------------------------------------------------------- |
| `claude_ok`                | Acts like a healthy binary: `--help` advertises `--settings`, `auto-mode critique` emits the documented Markdown structure with 0 issues, exit 0. |
| `claude_fail`              | Same surface, but `auto-mode critique` exits non-zero. Drives acceptance #10.          |
| `claude_drift`             | Emits a renamed section (e.g. `## Severe issues`). Drives acceptance #11.              |
| `claude_no_settings_flag`  | `--help` does NOT mention `--settings`. Drives the swap-file fallback path.            |

Tests prepend the stub directory to `PATH` and verify the skill's behaviour against each shape.

## The 18 acceptance predicates

| # | Predicate | Measurement |
|---|-----------|-------------|
| 1 | Round-trip byte-equal across 50 fixtures | `for f in tests/fixtures/canonical/in_*.json; do diff <(uv run scripts/_canonical.py < $f) ${f/in_/out_} || exit 1; done` (also a pytest test) |
| 2 | SKILL.md context-budget ≤ 25 600 bytes | `wc -c skills/auto-mode-config/SKILL.md` < 25600 |
| 3 | Apply dry-run < 30s on developer laptop | `time HOME=$(mktemp -d) uv run scripts/apply_automode.py --dry-run --mode fresh --proposal tests/fixtures/proposal_minimal.json` real-time. Soft predicate (laptop-class hardware). |
| 4 | No network on dry-run | Linux: `strace -e trace=connect uv run …` shows zero `connect()` to non-localhost. macOS: documented gap, not a hard predicate. |
| 5 | Concurrent invocation flock contention | `test_acc05_concurrent_lock_contention` — second process exits with code 7 within ~100ms. |
| 6 | Stale-lock reclaim | `test_acc06_stale_lock_reclaimed` — write `99999 2020-01-01T00:00:00Z` to lockfile, run apply, expect success. |
| 7 | Fresh-machine create | `test_acc07_fresh_machine_create` — `HOME=$(mktemp -d)` then run; assert `~/.claude/settings.json` exists with mode `0600` and parent dir `0700`. |
| 8 | Backup file mode 0600 | `test_acc08_backup_mode_0600` — apply twice, assert backup mode. |
| 9 | Atomic write survives SIGKILL between fsync and replace | Hard to assert deterministically inside a single Python process. The implementation uses `os.write → os.fsync → os.replace`, correct by construction. Lead may add an injection harness in a future iteration. |
| 10 | Critique exit-non-zero is hard fail | `test_acc10_critique_nonzero_hardfail` — stub `claude_fail`, assert apply exits 3. |
| 11 | Contract drift fails loudly | `test_acc11_contract_drift_hardfail` — stub `claude_drift`, assert `ContractDriftError` (exit 3). |
| 12 | Hash mismatch raises HashMismatchError | `test_acc12_hash_mismatch` — dry-run, mutate proposal, run apply with old hash; expect exit 8. |
| 13 | Migrate drop-all empties environment | `test_acc13_migrate_drop_all` — preload existing entries, apply with `--migrate-strategy drop-all`; assert `autoMode.environment == ["$defaults"]`. |
| 14 | Migrate keep-all is byte-equal | `test_acc14_migrate_keep_all_byte_equal` — preload entries, apply `--migrate-strategy keep-all` with no proposal changes; assert output bytes equal input canonical bytes. |
| 15 | `__example_only` anti-test | `test_acc15_example_only_anti_test` — input rule whose plain text contains literal `__example_only` survives; wrapper-form `{"__example_only": true, "value": <real>}` is stripped. |
| 16 | Missing `claude` CLI loud-fail | `test_acc16_missing_claude_cli` — `PATH=` clamp; assert exit 5 with installation pointer in stderr. |
| 17 | Stranded-state detection at startup | `test_acc17_stranded_state` — pre-create `.auto-mode-config.preview-orig.<pid>`; assert exit 9 with instruction to run `--repair`. |
| 18 | `--repair` restores from `.preview-orig` and is idempotent | `test_acc18_repair_restores` — orphan + dead lock; run `--repair`; assert orphan gone, lock removed, settings.json restored; second `--repair` is a no-op (exit 0). |

## Anti-tests (must NEVER happen)

The pipeline test module also includes negative assertions. The skill must:

- **Never write** to `<repo>/.claude/settings.json` (project-shared, committed). Even with `--migrate-strategy drop-all` on a project-shared file, the skill refuses.
- **Never bypass** the gate. There is no flag that disables the hash check for non-dry-run writes.
- **Never use** the swap-file path without `--allow-swap-file-fallback`. When `--settings` is unsupported and the flag is absent, exit 1 with explicit error.
- **Never silent-add** `Bash(*)`, `PowerShell(*)`, `Bash(python*)`, `Agent(*)` to `autoMode.allow`. These get dropped on entry and the migrator surfaces them per-item.
- **Never depend on rapidfuzz**. `tests/test_pipeline.py` does an `import` smoke that fails if rapidfuzz appears in any `# /// script` block under `scripts/`.

## Soft predicates (not green/red)

- #3 (runtime <30s): laptop-class hardware assumption. Document if running in a slower environment.
- #4 (no network): Linux strace-clean; macOS has no portable equivalent without sudo (`dtruss`). Acceptable gap.
- #9 (SIGKILL between fsync and replace): correct by construction; a deterministic test would require a `ptrace`-style injection harness.

## Re-running everything from scratch

```bash
cd /Users/obeone/Documents/geek/github/claude-skills/.worktrees/feat-skill-auto-mode-config
# Regenerate fixtures (deterministic, pinned seed)
uv run skills/auto-mode-config/tests/fixtures/canonical/_generate.py

# Re-canonicalize golden outputs (only if the serializer was intentionally changed)
for f in skills/auto-mode-config/tests/fixtures/canonical/in_*.json; do
  uv run skills/auto-mode-config/scripts/_canonical.py < "$f" > "${f/in_/out_}"
done

# Run the suite
uv run --with pytest --with hypothesis -m pytest skills/auto-mode-config/tests/ -q
```

If the serializer or the section contract changes intentionally, regenerate fixtures and `assets/critique_sample.md`, then re-run. Drifting from the golden files is a contract change and must be documented.

## See also

- `references/canonicalization.md` — the byte-level contract behind acceptance #1, #5, #12, #14.
- `references/critique_workflow.md` — what `claude_drift` and `claude_no_settings_flag` exercise.
- `references/recovery.md` — what acceptance #17 and #18 verify in human terms.
