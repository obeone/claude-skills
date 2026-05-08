# Auto Mode — mental model

> Target ≤ 200 lines. Loaded on demand from SKILL.md when the agent needs the underlying semantics rather than a workflow step.

## What `autoMode` is

`autoMode` is a permission **classifier** layered on top of Claude Code's deterministic `permissions.{allow,ask,deny}` rules. It runs as a second gate after `permissions.deny` and decides whether each tool call is safe enough to proceed without a prompt. It is configured by a single block of natural-language prose, not by patterns or regex.

```
tool call
  │
  ▼
[permissions.deny]  ─── matches? ──► hard-block (cannot be overridden)
  │ no
  ▼
[classifier ← autoMode.{environment, allow, soft_deny} + CLAUDE.md + user-message intent]
  │
  ▼
allow / soft-deny / fall back to a prompt
```

The classifier reads three things only:

1. **User messages** — the conversation transcript on the user side.
2. **The agent's tool calls** — names + payloads.
3. **`CLAUDE.md`** content — both project and user.

It does **not** see tool *results* (anti-injection), assistant prose (anti-rationalisation), or thinking blocks. That is by design.

## The three fields

```jsonc
{
  "autoMode": {
    "environment": ["$defaults", "<prose>", "..."],
    "allow":       ["$defaults", "<prose>", "..."],
    "soft_deny":   ["$defaults", "<prose>", "..."]
  }
}
```

| Field         | Purpose                                                                                       |
| :------------ | :-------------------------------------------------------------------------------------------- |
| `environment` | What the classifier should treat as **inside your trust boundary** (org, SCM, buckets, …).     |
| `allow`       | Exceptions that override the classifier's default block list.                                  |
| `soft_deny`   | Additional blocks beyond the built-in ones.                                                    |

There is no `autoMode.deny`. Hard blocks live in `permissions.deny`. That distinction matters: `soft_deny` can be neutralised by an `allow` entry or by explicit user intent in conversation; `permissions.deny` cannot.

## The `$defaults` sentinel

The literal string `"$defaults"` in any of the three arrays expands at classifier load time to Anthropic's curated built-in entries for that section. Each section is independent:

- Include `"$defaults"` → built-ins are appended; your custom entries layer on top.
- **Omit** `"$defaults"` → full replacement of that section's built-ins. The classifier loses every Anthropic-curated rule it would otherwise inherit.

This is a one-line foot-gun. Run `claude auto-mode defaults` to print the built-ins so you know what you would be replacing. The skill writes `"$defaults"` into every section by default and only drops it if the user explicitly passes `--dangerously-skip-defaults`.

## Cross-scope merge

The classifier reads `autoMode` from these scopes, additively:

| Scope                                | Path                                                  | Read by classifier? |
| :----------------------------------- | :---------------------------------------------------- | :-----------------: |
| User                                 | `~/.claude/settings.json`                             | yes                 |
| Project (local, gitignored)          | `<repo>/.claude/settings.local.json`                  | yes                 |
| Project (shared, committed)          | `<repo>/.claude/settings.json`                        | **no**              |
| Managed (org policy)                 | OS-specific managed settings                          | yes                 |
| `--settings <path>` flag / Agent SDK | inline                                                | yes                 |

Project-shared `.claude/settings.json` is deliberately ignored: a cloned repo cannot inject classifier rules. This skill writes only to `~/.claude/settings.json`. If a user asks the skill to manage project-local autoMode, the skill politely refuses and points to a future v0.3.0 scope.

The merge is **additive**, not a hard policy boundary: a user `allow` can neutralise a managed `soft_deny`. The Anthropic doc states this explicitly. Treat managed `soft_deny` as guidance, not enforcement.

## The fallback contract

If the classifier blocks **3 consecutive** actions or **20 cumulative** actions in a session, autoMode pauses itself and Claude Code begins prompting again until the user re-engages. These thresholds are not configurable. In `--print` (non-interactive) mode the session aborts instead.

This is the safety floor: even an attacker who slips past every individual decision cannot grind silently through thousands of denials.

## Rules dropped on entry to autoMode

When a session enters autoMode, the following `permissions.allow` patterns are silently dropped because they grant arbitrary code execution:

- `Bash(*)`, `PowerShell(*)`
- Wildcarded interpreters: `Bash(python*)`, `Bash(node*)`, `Bash(ruby*)`, `Bash(sh*)`, etc.
- Broad package-manager runs: `Bash(npm run *)`, `Bash(pnpm run *)`, etc.
- `Agent(*)` and named-Agent allow rules.

Narrow rules (e.g. `Bash(npm test)`, `Bash(pytest)`) survive. The skill's `scan_project.py` flags any of the dropped patterns it finds in the user's settings so the user can either narrow them or accept the silent drop.

## Plan / version / provider gating

autoMode requires:

- A Max, Team, Enterprise, or API plan. Pro is **not** supported.
- The Anthropic API as provider. Bedrock / Vertex / Foundry are **not** supported.
- Claude Code `>= 2.1.83`.

`apply_automode.py` enforces the version range declared in `assets/heuristics.yaml` (`claude_code_version_range: ">=2.1.83,<3.0"`) and refuses with exit code `10` outside the band.

## Why this skill exists (in one paragraph)

A naked `autoMode` block is easy to write wrong: forget `"$defaults"` and you destroy the built-in rule list; place it in the shared `.claude/settings.json` and the classifier silently ignores it; let `permissions.allow` keep `Bash(*)` and the rule disappears the moment autoMode activates. The skill encodes those gotchas as machine-checked invariants, runs the canonical `claude auto-mode critique` against the proposal **before** writing, requires the user to echo back a sha256 of the canonical bytes they actually approved, and writes atomically with a timestamped backup so a bad write is one `cp` away from being undone. The skill is paperwork around the binary; the binary is the source of truth.

## See also

- `references/critique_workflow.md` — Path (b) (verbatim Markdown + hash gate), swap-file fallback, contract-drift detection.
- `references/migration.md` — Option 2b interactive migration flow.
- `references/canonicalization.md` — canonical JSON form and sha256 contract.
- `references/recovery.md` — rollback procedure and stranded-state repair.
