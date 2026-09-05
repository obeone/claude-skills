---
name: automode-edit
description: "Edit the project autoMode block in plain language. The agent interprets the request, builds a proposal, runs critique + hash gate, and writes atomically to .claude/settings.local.json."
---

# /automode-edit `<query>`

Translate a natural-language request into a structured modification of
`.claude/settings.local.json` → `autoMode`, then drive the existing
six-phase apply pipeline. The agent is the interpreter; the deterministic
guards (schema validation, mistaken-pattern detection, critique gate,
hash gate, atomic write under flock) still apply.

`<query>` examples:

- `add a hard_deny rule that forbids pushing to main`
- `allow deploys to the staging namespace`
- `the github org is acme-corp, all repos under it are internal`
- `drop the soft_deny entry about npm install`
- `take ownership of the allow section (remove $defaults)`
- `restore $defaults in soft_deny`
- `rename the rule about migrations to mention the new ./scripts/migrate.sh path`

## Hard rules (do not violate)

1. **Prose, not patterns.** Rules are natural-language sentences. If the
   user dictates `Bash(...)`, `Read(...)`, `WebFetch(...)`, etc., refuse
   and explain that those belong in `permissions`, not in `autoMode`.
2. **Four sections only.** `environment`, `allow`, `soft_deny`,
   `hard_deny`. Reject any other section. Migrate legacy `deny` →
   `soft_deny`, drop `ask` with a warning.
3. **Never silently drop `"$defaults"`.** If the user's request implies
   removing the sentinel from a section, surface the consequence
   (which curated baseline they lose) and require an explicit confirm.
4. **Write target is `.claude/settings.local.json` only.** Never
   `--write-shared`, never touch `~/.claude/settings.json`, unless the
   user explicitly asks for it inside `<query>` and confirms again
   after the diff.
5. **No bypass of the pipeline.** Always go through `apply_automode.py`
   `--dry-run` → user confirm → `--approved-canonical-hash`. Never
   write the JSON file directly.
6. **Read before edit.** Re-read `.claude/settings.local.json` right
   before building the proposal; do not rely on cached content from
   earlier in the session.

## Step 1 — load current state

Resolve paths and read state with the project's own scripts:

```bash
uv run skills/automode-config/scripts/inspect_automode.py --json --file all
```

Then read the actual contents the inspector summarises:

- `.claude/settings.local.json` — primary target. If absent or has no
  `autoMode` key, the starting block is:
  ```json
  {
    "environment": ["$defaults"],
    "allow":       ["$defaults"],
    "soft_deny":   ["$defaults"],
    "hard_deny":   ["$defaults"]
  }
  ```
- `.claude/settings.json` — shared. Read for context only; warn the
  user when `autoMode` lives there (classifier ignores it).
- `~/.claude/settings.json` — user baseline. Read for context only.

If `inspect_automode.py` reports drift (canonical bytes ≠ approved
cache), stop and tell the user to re-run `apply_automode.py` to
re-approve the on-disk state before editing further.

## Step 2 — interpret `<query>`

Decide:

1. **Operation**: `add`, `remove`, `replace`, `toggle-$defaults`,
   `take-ownership`, or a combination.
2. **Section**: exactly one of `environment`, `allow`, `soft_deny`,
   `hard_deny`. If ambiguous, use the cheat-sheet:
   - "trusted/internal/our org/our buckets/our CI" → `environment`
   - "is allowed / can be auto-approved / exception" → `allow`
   - "never / don't / block / refuse" → `soft_deny` by default,
     **`hard_deny` only when the user uses unconditional language**
     ("never under any circumstance", "must not", "absolutely forbid",
     "even if I say so", "security boundary").
   - When unsure between `soft_deny` and `hard_deny`, ask the user.
3. **Wording**: rewrite the user's phrasing into a complete prose rule
   suitable for the classifier. A good rule is:
   - One sentence, declarative.
   - Names the target concretely (repo, branch, namespace, domain,
     bucket, CLI path).
   - States the action clearly (push, deploy, migrate, send, run).
   - Optionally explains the safety reason in a trailing clause.

   Examples of good rewrites:

   | User said | Rule written |
   |---|---|
   | "don't push to main" | "Never push or force-push to `main` or `release/*` branches on any remote." |
   | "staging is fine" | "Deploying to the `staging` namespace is allowed: staging is isolated and resets nightly." |
   | "our github org is acme" | "Source control: `github.com/acme-corp` and all repos under it are considered internal." |
4. **`$defaults` impact**:
   - If the operation removes `"$defaults"` from a section, mention which
     curated baseline rules disappear and require explicit confirm.
   - If the section currently lacks `"$defaults"` and the user's
     operation re-adds it, mention that the baseline returns.

## Step 3 — build the proposal

Assemble the full `autoMode` object (all four sections), not just a
patch. Preserve untouched sections verbatim, including `"$defaults"`
positions. Place new entries **after** `"$defaults"` unless the user
asks otherwise. Avoid duplicates: if a near-equivalent rule already
exists, surface it and ask whether to replace, keep both, or skip.

Write the proposal to `/tmp/automode-edit-proposal.<unix-ts>.json`:

```json
{
  "autoMode": {
    "environment": [ "$defaults", "…" ],
    "allow":       [ "$defaults", "…" ],
    "soft_deny":   [ "$defaults", "…" ],
    "hard_deny":   [ "$defaults", "…" ]
  }
}
```

## Step 4 — dry-run + show the diff

Run:

```bash
uv run skills/automode-config/scripts/apply_automode.py \
  --proposal /tmp/automode-edit-proposal.<unix-ts>.json \
  --mode auto \
  --dry-run
```

Capture the printed canonical sha256. If exit code is non-zero, show
the error and stop — do **not** retry blindly. Typical causes:

- `2` EXIT_VALIDATION — schema or section issue. Adjust the proposal.
- `3` EXIT_CRITIQUE_FAILED — `claude auto-mode critique` flagged the
  proposal. Read the critique output (printed and archived under
  `.claude/.automode-history/critique-<UTC>.md`) and ask the user how to
  resolve the flagged entries.
- `5` EXIT_CLAUDE_CLI_MISSING — tell the user to install/expose
  `claude`. Do not skip the gate.
- `10` EXIT_OUT_OF_BAND — the binary version is outside the skill's
  tested range. Surface the version and ask whether to proceed by
  re-running with explicit confirmation.

Then print a compact diff to the user:

```
section: <name>
  + <new rule>
  - <removed rule>
  ~ <rule moved/renamed>
```

Always show:

- Which section(s) changed.
- The exact new prose rule(s).
- Whether `"$defaults"` survived in every section.
- The canonical sha256 from the dry-run (so the user can audit).

Ask for explicit confirmation before Step 5. In auto mode the agent may
proceed without asking when the change is low-risk (a non-hard_deny
`add` that preserves all `"$defaults"` and matches the user's wording
1:1). Any `hard_deny` change, any `"$defaults"` removal, any
`--write-shared` request, or any ambiguous interpretation MUST ask.

## Step 5 — commit

```bash
uv run skills/automode-config/scripts/apply_automode.py \
  --proposal /tmp/automode-edit-proposal.<unix-ts>.json \
  --mode auto \
  --approved-canonical-hash <sha256-from-step-4>
```

Forward any non-zero exit code to the user with the matching cause
from the table in Step 4. Do **not** invent flags. Do **not** add
`--write-shared` unless the user asked for it in `<query>` and
re-confirmed at Step 4.

## Step 6 — report

Print:

- One line per section touched (`environment`, `allow`, `soft_deny`,
  `hard_deny`) with the operation summary.
- The rollback line from `apply_automode.py` verbatim.
- The new canonical sha256 (the hash that became the approved cache).
- A pointer to `.claude/.automode-history/` for the critique archive.

Example:

```
autoMode updated: .claude/settings.local.json
  hard_deny: + "Never push or force-push to `main` or `release/*` branches on any remote."
  ($defaults preserved in all four sections)

Rollback: cp -p .claude/.automode-config.backup.2026-05-11T14-22-13Z.a1b2c3d4e5f6 .claude/settings.local.json
canonical sha256: <new-hash>
critique log: .claude/.automode-history/critique-2026-05-11T14-22-13Z.md
```

## Cleanup

Delete `/tmp/automode-edit-proposal.<unix-ts>.json` on success. Leave
it on failure (the user may want to inspect or hand-edit then re-apply
with `apply_automode.py` directly).

## What this command must NOT do

- Touch `~/.claude/settings.json` or `.claude/settings.json` silently.
- Write JSON to the target file outside of `apply_automode.py`.
- Skip the critique gate or the hash gate.
- Invent autoMode sections (`ask`, `deny`, `audit`, etc.).
- Translate prose rules into `Tool(specifier)` patterns.
- Run `git add`, `git commit`, or any VCS operation.
- Continue when `inspect_automode.py --show-drift` reports drift on the
  target file — re-approve first.
