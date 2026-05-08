# Recovery

Backups, stranded state, `--repair`. The skill leaves enough breadcrumbs
that a re-run can always reach a consistent state, even after a kill.

## Backup retention

Per-file pool: 5 most recent backups, pruned on each successful
apply. Backup naming:

```
.claude/.autoMode-config.backup.<ISO8601>.<sha256-12>     # local file
.claude/.autoMode-config.backup.<ISO8601>.<sha256-12>     # shared file (Phase 4)
~/.claude/.autoMode-config.backup.<ISO8601>.<sha256-12>   # user file (--hoist only)
```

`<ISO8601>` is `YYYY-MM-DDThh-mm-ssZ` (colons replaced with hyphens
for portability). `<sha256-12>` is the first 12 hex chars of the
backup contents' sha256. Mode 0600 for all backups regardless of
the source file's mode. Pruning is per-file: each of the three pools
is maintained independently.

The rollback line printed at the end of Phase 3 references the most
recent backup of the local file:

```
Rollback: cp -p .claude/.autoMode-config.backup.2026-05-08T14-22-13Z.a1b2c3d4e5f6 .claude/settings.local.json
```

## Stranded state

Detected at startup, **before** any other action including fresh-
machine detection. Glob targets:

```
~/.claude/.autoMode-config.preview-orig.*
<project-root>/.claude/.autoMode-config.preview-orig.*
```

Any match in either location -> exit 9 (`EXIT_STRANDED_STATE`) with
the message:

```
Stranded preview-orig file(s) detected:
  ~/.claude/.autoMode-config.preview-orig.12345
Run with --repair to restore.
```

Stranded state appears when a swap-file critique invocation was
killed in a way no signal handler caught (SIGKILL, hard reboot,
power loss). The orig contents are intact; the live file is the
proposal mid-write. `--repair` restores by copying orig back to the
live path, then deleting the preview-orig sentinel.

## `--repair`

Mutually exclusive with all other modes. Performs:

1. Walk both stranded-state globs.
2. For each match, take the corresponding flock (user or local) with
   stale-TTL reclaim. If the lock is held by a live PID, exit 7;
   `--repair` does not preempt live writers.
3. Write a `.repair`-suffixed backup of the current live file
   before any restore: `<live>.repair-backup.<ISO8601>`.
4. `os.replace(preview_orig, live)` to restore.
5. Delete the preview-orig sentinel.
6. Walk all `<file>.lock` paths; reclaim any lock whose payload PID
   is dead or whose ISO8601 timestamp is older than five minutes.

Idempotency: running `--repair` twice is a no-op the second time.
The `.repair-backup` files are kept (they are the user's safety net
if the restore was wrong); they are not auto-pruned.

## Multi-file flock cleanup

Three locks, three reclaim paths:

```
~/.claude/settings.json.lock              # user-file flock
.claude/settings.local.json.lock          # local-file flock
.claude/settings.json.lock                # shared-file flock
```

Each lock payload is `<PID> <ISO8601>`. Reclaim conditions:

- Dead PID (kill -0 -> ESRCH) -> reclaim immediately.
- Live PID, lock older than five minutes -> reclaim with a warning.
- Live PID, lock newer than five minutes -> exit 7
  (`EXIT_LOCK_HELD`).

`--repair` reclaims all three unconditionally (subject to the live-
PID rule). Normal runs reclaim only the lock(s) for the phase they
need.

## When the lockfile is the problem

Two pathological cases:

- **PID reuse**: the original holder died, the OS reused the PID for
  an unrelated process. The TTL check (five minutes) catches this.
- **Filesystem with broken `flock`** (some FUSE mounts, NFSv3
  without `lockd`): the skill cannot acquire the lock. Exit 7 with a
  message pointing the user at the underlying filesystem. The
  workaround is to move the project to a local filesystem; the
  skill does not silently fall back to lockless writes.

## Order of startup checks

Strictly:

1. Stranded-state walk (both locations).
2. Version-band probe (`claude --version`).
3. `--settings` capability probe.
4. Per-phase flock acquisition.

Each check has its own exit code; failures are not retried.
