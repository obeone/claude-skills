# Recovery — backups, stranded state, `--repair`

> Target ≤ 150 lines. Loaded when something has gone wrong and the agent (or user) needs to undo a write, recover from a crash mid-swap, or understand what `--repair` actually does.

## Rolling back the last write

After every successful apply, the skill prints a copy-pasteable rollback command on its own line:

```
rollback: cp ~/.claude/settings.json.bak.YYYY-MM-DDTHH-MM-SS ~/.claude/settings.json
```

The timestamp is filesystem-safe (UTC, ISO-8601 with hyphens replacing colons) so it pastes cleanly into a shell. To recover from the most recent apply, run that exact command. To recover from an older one, list the backups and pick:

```bash
ls -1t ~/.claude/settings.json.bak.* | head -5
cp ~/.claude/settings.json.bak.<chosen-ts> ~/.claude/settings.json
```

The skill keeps the **5 most recent** backups (by mtime) and prunes older ones on each successful apply. If you need a longer history, copy the backup elsewhere before the next apply.

## "I am locked out of `Bash`"

The most painful failure mode is an `autoMode.soft_deny` line so broad it blocks routine commands. If `~/.claude/settings.json` becomes the source of those blocks, you can still:

1. Open `~/.claude/settings.json` in a non-Claude editor (vim, VS Code without the extension, the macOS Finder's open-with).
2. Replace it with the most recent backup using the rollback command above (the rollback is plain `cp`, which always works regardless of autoMode state).
3. If even `cp` is blocked because Claude Code is sandboxing your session, reach for plain shell outside Claude (a different terminal tab works).

The mitigation lives in the rollback command being *outside the model's tool budget*. The skill's job is to make that command obvious; recovering does not require Claude Code at all.

## Backup retention

The skill keeps the 5 most recent backups. Three implications:

1. **History depth = 5 applies.** If you ran apply six times since a known-good state, the oldest backup may be gone.
2. **Manual snapshots persist.** Backups copied to a different location (e.g. `cp ~/.claude/settings.json.bak.<ts> ~/snapshots/`) are not pruned by the skill.
3. **Concurrent applies are flock-serialised**, so backup pruning is never racy with another apply.

To raise retention, the implementer can change the constant in `apply_automode.py`. Five was picked as a balance between disk cost and recoverability — a longer chain is rarely the right answer when each backup is one rollback away from being live again.

## Stranded state — `.preview-orig.<pid>`

The swap-file path (`--allow-swap-file-fallback`, when `--settings` is unsupported by the live `claude` binary) renames `~/.claude/settings.json` to `~/.claude/.auto-mode-config.preview-orig.<pid>` for the duration of the critique call. Normal exits restore the file in `try/finally`. SIGINT/SIGTERM/SIGHUP also restore via signal handlers.

`SIGKILL`, segfault, OOM-kill, and power loss bypass all of that. The result: an orphan `~/.claude/.auto-mode-config.preview-orig.<pid>` file and (probably) a stale lockfile.

The next `apply_automode.py` invocation detects this at startup, **before** any other action, and exits `9` (`StrandedStateDetected`) with:

```
ERROR: stranded state detected
  ~/.claude/.auto-mode-config.preview-orig.12345
Run `apply_automode.py --repair` to restore.
```

The detection runs **before** the fresh-machine flow so a stranded machine is never mistaken for a fresh one (which would silently overwrite the orphan with `{}`).

## `--repair`

```bash
uv run skills/auto-mode-config/scripts/apply_automode.py --repair
```

Behaviour:

1. **Acquire flock**, reclaiming if stale (dead PID or > 5 min). Stale is the common case after SIGKILL.
2. **Find orphans**: `glob ~/.claude/.auto-mode-config.preview-orig.*`.
3. **For each orphan**:
   - Validate it parses as JSON. If not → leave it in place and report (a corrupt orphan is *worse* than no orphan, so the user gets to triage).
   - If `~/.claude/settings.json` exists, write `~/.claude/settings.json.bak.<timestamp>.repair` (mode 0600) so the user can compare what was there before the restore.
   - `os.replace(orphan, ~/.claude/settings.json)`.
4. **Lock cleanup**: remove `~/.claude/settings.json.lock` if its payload's PID is dead or > 5 min old.
5. **Release flock**.
6. **Idempotent**: a second run on a now-clean state exits `0` with a no-op message.

`--repair` writes its `.repair`-suffixed backup *before* restoring the orphan so the user always has the chance to see what was about to be replaced. The backup is included in the keep-5 retention pool.

## Pre-existing `~/.claude/settings.json` with mode `0644`

A common edge case: the user installed Claude Code before this skill existed and `~/.claude/settings.json` is mode `0644` (world-readable). The skill's policy is **warn, do not auto-tighten**:

```
WARNING: ~/.claude/settings.json has mode 0644 (world-readable).
         Recommend `chmod 0600 ~/.claude/settings.json`.
         The skill leaves the mode untouched on this run.
```

Reason: silently tightening permissions on a file the user shares with another tool would be surprising. The user can run the recommended `chmod` themselves; future apply calls keep emitting the warning until the mode changes.

## When the lockfile is the problem

If `apply_automode.py` exits `7` (`LockHeldError`) and you are *certain* no other apply is running:

```bash
# Check who holds it
cat ~/.claude/settings.json.lock          # prints "<PID> <ISO8601>"
ps -p <PID> >/dev/null && echo alive || echo dead

# Either let the 5-minute TTL expire (next apply auto-reclaims):
# Just wait 5 minutes from the timestamp in the file and retry.

# Or use --repair to clean it up explicitly:
uv run skills/auto-mode-config/scripts/apply_automode.py --repair
```

`--repair` is the canonical "clean up after me" entry point. Removing the lockfile by hand also works but loses the fail-safe ordering (`--repair` does the orphan check before touching the lock).

## When `inspect_automode.py --show-drift` reports drift

Drift means the canonical bytes of your current `~/.claude/settings.json` no longer match what was last approved (cached in `~/.claude/.auto_mode_approved.json`). Common causes:

1. You edited the file by hand since the last apply.
2. Another tool (or a different invocation of this skill from a different worktree) wrote to the file.
3. You restored a backup without going through apply.

Drift exits `6` and is **non-fatal** — it just tells you the cached approval is stale. To re-establish ground truth, run a normal `apply_automode.py --mode migrate` cycle: the migrate flow shows you every entry, you confirm them, the gate captures a fresh hash, and the cache is updated on commit.

## See also

- `references/critique_workflow.md` — the swap-file mechanism that creates `.preview-orig.<pid>` files in the first place.
- `references/canonicalization.md` — what `~/.claude/.auto_mode_approved.json` stores and how `--show-drift` compares it.
- `references/migration.md` — using `--mode migrate` to re-baseline after manual edits.
