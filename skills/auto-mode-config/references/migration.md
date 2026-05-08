# Migrating an existing `autoMode` block

> Target ≤ 150 lines. Loaded when the user is on the `--mode migrate` path and the agent needs the full interactive semantics.

## When this applies

Migration runs when `~/.claude/settings.json` already has an `autoMode` block and the user wants to update or extend it. Three things distinguish it from `--mode fresh`:

1. The skill **must not** silently drop or rewrite any existing entry.
2. The user is offered a per-entry decision interactively.
3. Non-interactive runs **must** declare a strategy or refuse.

## Durable claims, not project snapshots

`autoMode.environment` lives in `~/.claude/settings.json`. That is a **user-global** file. The user is going to run this skill from many projects over time, and every entry written there outlives the project that prompted it. Treat each line as a **durable narrative claim about the user**, not a snapshot of "this repo right now".

Bad (project-shaped):

```
"This repository uses kubectl with the my-staging context."
```

Good (durable about the user):

```
"I work in Kubernetes day-to-day; using kubectl against staging-class contexts is part of my normal flow."
```

When the skill detects entries on load that look project-shaped (file paths, project basenames, hyper-specific tooling), it surfaces them per-item. It does **not** auto-classify, auto-tag, or auto-delete. The user makes the call.

## The interactive flow (Option 2b)

For each existing `autoMode.environment` entry, the skill prompts:

```
Entry 3 of 7:
  "Trusted internal domains: *.internal.example.com, ci.example.com"

  [k] keep as-is
  [e] edit (opens $EDITOR on this entry)
  [d] drop
  [q] quit (discards in-memory plan, no changes written)

> _
```

`[e]` opens the entry as a JSON snippet in `$EDITOR`. On save the skill validates that it parses; if not, the prompt repeats.

This loops over every entry in `environment`, then `allow`, then `soft_deny`. After the loop the skill applies any additions/edits the user passed via `--proposal <path>`, then proceeds to phase 2 (critique gate).

## Non-interactive strategies

`apply_automode.py --mode migrate` requires a strategy when there is no TTY:

| Strategy             | Behaviour                                                                                                                              |
| :------------------- | :------------------------------------------------------------------------------------------------------------------------------------- |
| `--migrate-strategy keep-all`  | Every existing entry is kept untouched. The proposal layers on top.                                                            |
| `--migrate-strategy drop-all`  | Every existing entry is dropped. The result is `["$defaults"]` per section before the proposal is applied.                     |
| `--migrate-strategy fail`      | Default. Refuse with exit `4` (`MigrationStrategyRequired`) and an actionable error listing the entry count.                   |

The default is **`fail`**, deliberately. A scripted run that hits stale entries silently picking `keep-all` would defeat the purpose of having the skill at all. The user must declare intent.

## Why no auto-tagging

An earlier design tried to *guess* which entries belonged to "another project" and auto-tag them. Two problems:

1. Without rapidfuzz (dropped pre-`v0.1.0` because the threshold was speculative), there is no defensible deterministic predicate. Substring matches against `os.path.basename(os.getcwd())` produce false positives whenever the user's basename is a common word.
2. Even with a predicate, automatic tagging is one step away from automatic deletion. Once a tag exists, future code will iterate over "tagged entries" and propose actions — and a bad heuristic compounds.

Option 2b's "present everything, decide nothing" stance is slower for users with 50+ entries (rare in practice for a personal `~/.claude/settings.json`) but unambiguously safe. If telemetry later shows a real need, a `--migrate-batch-size <N>` or filter flag can be added without redesign.

## What lands in the proposal

`--proposal <path>` is a JSON file with the additions and edits the user wants applied **after** the migrate loop. Schema:

```jsonc
{
  "environment_add": ["I work primarily on Forgejo-hosted personal projects."],
  "allow_add": ["Pushing to forge personal feature branches is part of my normal flow."],
  "soft_deny_add": ["Never run terraform apply against production."],
  "environment_replace": []   // intentional full-replace, requires --dangerously-skip-defaults
}
```

`*_add` entries layer on top of the post-migrate state. `*_replace` is reserved for users who really know what they are doing; the skill will refuse without `--dangerously-skip-defaults` and a confirmation banner.

## Atomicity of the migrate phase

The migrate loop runs entirely **in memory**. Nothing on disk changes until phase 4 (atomic write). The user can `[q]uit` at any per-entry prompt and the file is untouched. This is what makes per-item confirmation safe alongside the atomic-write principle: the per-item prompts build a plan; the atomic write commits it once.

## See also

- `references/critique_workflow.md` — what happens after the migrate loop completes (critique gate, hash, atomic write).
- `references/recovery.md` — restoring a backup if a migrate goes sideways post-write.
- `references/mental_model.md` — why `~/.claude/settings.json` is the only target and what that implies for project-shaped entries (see "Cross-scope merge").
