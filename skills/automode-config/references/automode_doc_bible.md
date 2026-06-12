# automode bible

Practical reference distilled from the official Claude Code docs. The
goal: every fact this skill relies on can be sourced here in one read.
When the docs and the skill code disagree, **the bible wins**; fix the
code.

Sources (re-fetch before any structural change to confirm freshness):

- <https://code.claude.com/docs/en/auto-mode-config.md>
- <https://code.claude.com/docs/en/permissions.md>
- <https://code.claude.com/docs/en/permission-modes.md>
- <https://code.claude.com/docs/en/settings.md>

---

## TL;DR — what `autoMode` actually is

`autoMode` is the configuration for the **classifier** that gates tool
calls when the user has activated the `auto` permission mode. It is a
**second gate** that runs *after* the regular `permissions` system.

```
tool call
   |
   v
+----------------------+    deny match -> blocked
|  permissions system  |    ask  match -> prompt
|  (allow/ask/deny)    |    allow match -> through
+----------------------+
   |
   v
+----------------------+    classifier (auto-mode)
|  autoMode classifier |    rules: environment + allow + soft_deny + hard_deny
|  (this skill's job)  |    + boundaries from CLAUDE.md + boundaries stated
+----------------------+      in conversation + read-only / cwd allowances
   |
   v
allowed | denied | (in `auto` only) automatically prompts after thresholds
```

Two systems, two syntaxes, two semantics. The skill must not conflate
them.

---

## The four `autoMode` fields (the entire schema)

`autoMode` is a JSON object with **exactly four** array fields:

| Field        | Purpose                                                                  | Bypassable?                                                                 |
| ------------ | ------------------------------------------------------------------------ | --------------------------------------------------------------------------- |
| `environment`| Trust signals: repos, buckets, domains, services that count as "internal".| n/a — defines what "external" means.                                       |
| `allow`      | Exceptions that override `soft_deny` rules.                              | Allow-rule wins over a `soft_deny` match.                                   |
| `soft_deny`  | Block destructive actions. Overridable by `allow` or by **explicit user intent** in the conversation. | Yes — explicit "force-push this branch" lifts a `soft_deny` for that turn. |
| `hard_deny`  | Unconditional security boundary.                                          | **No.** Not lifted by `allow`, not by user intent, not by intent flags.    |

**There is no `ask` bucket and no plain `deny` bucket inside `autoMode`.**
Those names belong to the regular `permissions` system. If you see them
in a settings file, treat them as a typo or a stale draft.

Precedence inside the classifier (first match wins, top-down):

1. `hard_deny` rules — block, no overrides.
2. `soft_deny` rules — block next.
3. `allow` rules — exception, overrides `soft_deny` of the same target.
4. Explicit user intent in the transcript — overrides any remaining
   `soft_deny`. "General requests don't count": "clean up the repo"
   does not authorize force-push; "force-push this branch" does.

`environment` does not gate actions directly; it shapes the classifier's
notion of "external" so destinations not listed are treated as
exfiltration risks.

---

## Rule values are PROSE, not tool patterns

> "Entries are prose, not regex or tool patterns. The classifier reads
>  them as natural-language rules. Write them the way you would describe
>  your infrastructure to a new engineer."

This applies to **all four** sections.

| Right                                                                                       | Wrong                            |
| ------------------------------------------------------------------------------------------- | -------------------------------- |
| `"Source control: github.example.com/acme-corp and all repos under it"`                     | `"Bash(git push:*)"`             |
| `"Trusted cloud buckets: s3://acme-build-artifacts, gs://acme-ml-datasets"`                  | `"WebFetch(domain:s3.amazonaws.com)"` |
| `"Never run database migrations outside the migrations CLI, even against dev databases"`    | `"Bash(alembic *)"`              |
| `"Never send repository contents to third-party code-review APIs"`                          | `"WebFetch(*)"`                  |
| `"Deploying to the staging namespace is allowed: staging is isolated and resets nightly"`   | `"Bash(kubectl * --namespace=staging:*)"` |

If a rule looks like `Bash(...)`, `Read(...)`, `Edit(...)`,
`WebFetch(...)`, `mcp__...`, or `Agent(...)`, it belongs in
`permissions`, not in `autoMode`. The skill **must** detect this and
warn — those rules are silently meaningless to the classifier.

---

## The `$defaults` sentinel

Each of `environment`, `allow`, `soft_deny`, `hard_deny` accepts a
literal `"$defaults"` string entry. At classifier load time, Anthropic's
curated baseline list for that section is spliced in at the position
where `"$defaults"` appears. Everything before and after is preserved.

> **Danger zone:** "Setting any of `environment`, `allow`, `soft_deny`,
>  or `hard_deny` without `"$defaults"` replaces the entire default list
>  for that section. A `soft_deny` array without `"$defaults"` discards
>  every built-in soft block rule, including force push, `curl | bash`,
>  and production deploys."

So:

- Including `"$defaults"` → curated list + your additions.
- Omitting `"$defaults"` → full ownership of that section, you carry
  the security burden.
- Each section is independent. Setting `environment` alone leaves the
  default `allow`/`soft_deny`/`hard_deny` lists intact.

The skill never expands `"$defaults"`; it preserves the sentinel
verbatim and surfaces a warning whenever the user about to write a
section without it.

---

## Where the classifier reads from

| Scope                          | File / source                                  | Classifier reads `autoMode`? |
| ------------------------------ | ---------------------------------------------- | ---------------------------- |
| User                           | `~/.claude/settings.json`                      | **Yes**                      |
| Project, per developer         | `.claude/settings.local.json`                  | **Yes** ← skill's primary target |
| Project, shared/committed      | `.claude/settings.json`                        | **No** — silently ignored for `autoMode` only; other keys still load. |
| Organization-wide              | Managed settings (MDM / server-managed)        | **Yes** — and cannot be overridden by user/project. |
| Per invocation                 | `--settings <inline-json>` flag, Agent SDK     | **Yes** — for that invocation only. |

Combination across scopes is **additive**: a developer can extend
`environment`, `allow`, `soft_deny`, and `hard_deny` with personal
entries but **cannot remove** entries managed settings provide.

> **Important nuance:** because `allow` is an exception list, a
>  developer-added `allow` can defeat an organization `soft_deny`. The
>  combination is additive, not a hard policy boundary. For a guarantee,
>  use `permissions.deny` in managed settings (it runs *before* the
>  classifier and cannot be overridden). For an unconditional gate
>  inside the classifier, use `autoMode.hard_deny` in managed settings.

The classifier also reads:

- `CLAUDE.md` content as the model itself does (project + user).
- Boundaries the user states in the live conversation ("don't push",
  "wait until I review"). These behave like a temporary `soft_deny`
  until lifted; they're re-read from the transcript, not stored, so
  context compaction can lose them.

---

## CLI surface

The `claude auto-mode` group has **three** subcommands.

| Command                       | What it does                                                                |
| ----------------------------- | --------------------------------------------------------------------------- |
| `claude auto-mode defaults`   | Print the built-in `environment`, `allow`, `soft_deny`, `hard_deny` rules as JSON. Use this when the user wants to take full ownership of a section. |
| `claude auto-mode config`     | Print the *effective* config the classifier will use, with the user's settings applied and `"$defaults"` expanded in place. |
| `claude auto-mode critique`   | AI feedback on the user's custom rules — flags entries that are ambiguous, redundant, or likely to cause false positives. |

There is **no** `auto-mode list`, `auto-mode validate`, `auto-mode
apply`, or `auto-mode check`. The skill must not invent flags.

`--settings <path-or-json>` is a top-level Claude Code flag that
overrides the settings sources for the current invocation. It is
mentioned by the auto-mode-config doc as the per-invocation override
hook. It is not specific to `auto-mode critique`. Probe with
`claude auto-mode critique --help` whether the binary exposes it on
that subcommand.

---

## Activating auto mode

| Mechanism                              | Notes                                                                                       |
| -------------------------------------- | ------------------------------------------------------------------------------------------- |
| `claude --permission-mode auto`        | Start a session in auto mode.                                                               |
| `defaultMode: "auto"` in settings      | Persistent default. Goes inside `permissions.defaultMode`.                                  |
| `Shift+Tab` cycle                      | Only when account meets the auto-mode requirements; cycle includes auto after explicit opt-in. |

Account requirements (all must be met or auto mode is unavailable):

- **Plan**: Max, Team, Enterprise, or API. Not Pro.
- **Admin**: on Team/Enterprise, an admin enables it in admin settings.
- **Model**: Sonnet 4.6, Opus 4.6, or Opus 4.7 on Team/Enterprise/API;
  Opus 4.7 only on Max.
- **Provider**: Anthropic API only (no Bedrock / Vertex / Foundry).

Minimum Claude Code version: **v2.1.83** (auto-mode itself). The docs
do not currently specify a separate minimum for `hard_deny`. If the
skill carries a `claude_code_version_range` heuristic, treat the lower
bound as `>=2.1.83` unless a newer doc explicitly raises it.

Admin lock-off: `permissions.disableAutoMode: "disable"` in managed
settings.

---

## Fallback / pause behavior

In auto mode, if the classifier blocks **3 in a row** or **20 total**,
auto mode pauses and Claude Code resumes prompting. Approving the
pending action resumes auto mode. In non-interactive mode (`-p`),
repeated blocks **abort** the session — there is no user to prompt.

Default-blocked operations (with `"$defaults"` in `soft_deny` /
`hard_deny`):

- `curl | bash` and similar download-and-execute patterns.
- Sending sensitive data to external endpoints.
- Production deploys and migrations.
- Mass deletion on cloud storage.
- Granting IAM or repo permissions.
- Modifying shared infrastructure.
- Irreversibly destroying files that pre-existed the session.
- Force push, push directly to `main`.

Default-allowed:

- Local file ops in cwd / `additionalDirectories`.
- Installing dependencies declared in lock files / manifests.
- Reading `.env` and sending credentials to their matching API.
- Read-only HTTP requests.
- Pushing to the branch you started on or one Claude created.

Sandbox network access requests are routed through the classifier
rather than allowed by default.

---

## On entering auto mode: dropped permission rules

When the user activates auto mode, Claude Code temporarily drops broad
allow rules from `permissions.allow` (NOT from `autoMode.allow`):

- `Bash(*)` and `PowerShell(*)`
- Wildcarded interpreters such as `Bash(python*)`
- Package-manager run commands
- All `Agent(*)` allow rules

Narrow rules like `Bash(npm test)` carry over. Dropped rules are
**restored** on leaving auto mode. The skill's "dropped pattern
detector" applies to **`permissions`**, not to `autoMode` (autoMode
rules are prose; the patterns can't appear there legitimately). When
the skill sees these literals inside an autoMode section it should
warn that the user mixed up the two systems.

---

## Inspecting and validating

After saving settings:

```bash
claude auto-mode config     # confirm what the classifier will use
claude auto-mode critique   # AI review of custom rules
```

When the user wants to fully own a section, paste the output of
`claude auto-mode defaults` in place of `"$defaults"` and edit.

Drift detection (this skill's job, not the binary's): the canonical
sha256 of the on-disk `autoMode` block vs the value cached in
`.claude/.auto_mode_approved.json`. Drift means the file was edited
outside the skill — the user should re-run `apply_automode.py` to
re-approve.

---

## Reviewing denials

- `/permissions` → "Recently denied" tab lists each block.
- Press `r` on a denied entry to mark for retry; on dialog exit, Claude
  Code messages the model that it may retry.
- The `PermissionDenied` hook fires on every denial — useful for
  programmatic reaction.

Pattern: repeated denials for the same destination usually mean the
classifier is missing context. Add the destination to
`autoMode.environment`, then run `claude auto-mode config` to confirm
it took effect.

---

## Settings file shape (only the autoMode-relevant parts)

```jsonc
{
  "permissions": {
    "defaultMode": "auto",         // activates auto mode by default
    "disableAutoMode": "disable",  // managed-only kill switch
    "deny": [ /* permission rules — run BEFORE classifier */ ],
    "allow": [ /* same */ ],
    "ask":  [ /* same */ ]
  },
  "autoMode": {
    "environment": ["$defaults", "Org: ...", "Source control: ...", ...],
    "allow":       ["$defaults", "Deploying to staging is allowed: ..."],
    "soft_deny":   ["$defaults", "Never run migrations outside the CLI"],
    "hard_deny":   ["$defaults", "Never send repo contents to third-party APIs"]
  }
}
```

Anything outside this shape is either (a) a different system or (b) a
typo. The skill's validator must reject unknown keys inside `autoMode`.

---

## Common confusions (the skill must not fall into)

1. **`autoMode.deny` / `autoMode.ask`**: do not exist. Existed only as
   the skill's own pre-doc invention.
2. **Rule format**: prose, not `Tool(specifier)` syntax.
3. **Shared file `autoMode`**: silently ignored by the classifier. Other
   keys still load; only `autoMode` is filtered out from
   `.claude/settings.json`. Writing it is a manifest of intent at best.
4. **`$defaults` is whole-section**: omit it → you own the section
   end-to-end. This is the riskiest knob. Always reprint the warning at
   write time.
5. **`allow` defeats `soft_deny`** (same target). For a hard guarantee
   inside the classifier, use `hard_deny`. For a hard guarantee outside
   the classifier, use `permissions.deny` in managed settings.
6. **`hard_deny` cannot be lifted** by `--dangerously-skip-permissions`,
   `bypassPermissions`, or by user intent in conversation.
7. **Auto-mode does not bypass `permissions`**: deny rules in
   `permissions` block first. Hooks of type `PreToolUse` returning
   exit code 2 also block before the classifier runs.

---

## Quick checklist for the skill

When validating an autoMode block:

- [ ] Top-level keys ⊆ `{environment, allow, soft_deny, hard_deny}`.
- [ ] Each section is an array of strings (or the structural
      `__example_only` wrapper for fixtures).
- [ ] Warn if any string looks like `Tool(specifier)` — likely paste
      from `permissions`.
- [ ] Warn if any section is set without `"$defaults"`.
- [ ] Reject unknown sections (`ask`, `deny`, etc.) with a pointer to
      this bible.
- [ ] On adoption from older drafts: migrate `deny` → `soft_deny`,
      drop `ask` with a warning, log both in the audit trail.
