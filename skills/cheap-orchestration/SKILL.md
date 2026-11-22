---
name: cheap-orchestration
description: This skill should be used when planning how to split a task across subagents, writing a delegation spec, or deciding whether a unit runs inline, on a cheaper agent pinned to a smaller model tier (scout, editor, worker) or not at all. It holds the decision rule by task size and stakes, the pinned agent crew, the ordering and guard rules, spec and return templates, and the benchmark evidence behind each rule. The rules themselves live in the "Delegation & cost" section of your agent instruction file (CLAUDE.md, AGENTS.md); this skill is the detail and the rationale.
metadata:
  version: "2.4.1"
tools:
  - Agent
  - Bash
  - Read
---

# Cheap Orchestration

The operative rules belong in the instruction file your harness loads every
session (`CLAUDE.md`, `AGENTS.md`), under a "Delegation & cost" section. This
skill adds the templates and the reasons, so the rules can be applied to
cases they do not name.

## Tiers

The rules name tiers, not models. Map each tier to your provider once:

| Tier | Claude | GPT | Gemini |
|---|---|---|---|
| `large` | Opus | Sol | Carbon |
| `medium` | Sonnet | Terra | Neon |
| `small` | Haiku | Luna | Hydrogen |

The main loop usually runs on `large`. A model above `large` has no place in
delegation.

## Crew

Each agent has its model pinned in its own definition. Never override the
model at call time: the pin is the cost boundary.

| Agent | Tier | Tools | Use for | Returns |
|---|---|---|---|---|
| `scout` | small | read, search, read-only shell | Questions about the code before a decision or a spec | 15 lines of `path:line` facts |
| `editor` | small | edits, shell | Mechanical edits with no design choice | 10-line report |
| `worker` | medium | edits, shell | Every other unit whose output is files | 10-line report |
| `reviewer` | large | edits, shell | Final restriction check and polish pass: default on long multi-part sessions, otherwise on request | 10-line report |

No crew member launches another agent, so no subagent fans out on its own.
Claude Code enforces it (the definitions carry no `Agent` tool); on Codex
and Gemini it is an instruction in each role, see
[Harnesses](references/harnesses.md).

## Setup

The definitions ship in `assets/agents/`. Install them once per harness:

```bash
uv run scripts/setup_crew.py --provider claude          # dry run
uv run scripts/setup_crew.py --provider claude --apply
```

`--provider` takes `claude`, `codex` or `gemini` and writes the format that
harness reads, with the model of each tier. `--scope project` targets the
current repository, `--small`, `--medium` and `--large` replace a model
identifier. For Codex, `--effort <agent>=<level>` (repeatable) and
`--verbosity <level>` pin `model_reasoning_effort` and `model_verbosity` in
the roles. An existing file or symlink is kept unless `--force` is given,
and user scope follows `CLAUDE_CONFIG_DIR` or `CODEX_HOME` when set. The rule text
to add to the instruction file is `assets/delegation-and-cost.md`: in the
user-level file it applies from the first turn of every session, while this
skill only loads when needed. Harness
details: [Harnesses](references/harnesses.md).

Before the first delegation of a session, check the crew from the project
directory, with the script's full path and the same `--provider`, `--scope`
and tier overrides as the install:

```bash
uv run <skill directory>/scripts/setup_crew.py --provider <provider> --scope <user|project> --check
```

The check reads each definition: it fails on a missing agent, on a
definition from another provider, and on a model other than the tier's (a
kept file with `model: inherit`, for instance). If an agent fails it, its
units stay inline. Never fall back to an agent
that inherits the session model: that is the expensive path this skill
exists to avoid.

Every delegation call starts its description with the model the agent runs
on, in brackets: `[Haiku] Where is X resolved`, `[Terra] Implement X`,
`[Carbon] Final review`. The label is the only place the model shows up in the
transcript, so a unit sent to the wrong tier is visible at launch instead of
on the bill.

## Decision rule

1. **Inline**: one command, an edit of about 10 lines in one file, reasoning
   on output in hand, the final check, within a read budget of 2 read or
   search calls per turn before the first delegation. A delegation costs a
   spec, a launch turn, a notification turn and the agent's own system prompt.
2. **High stakes, write it yourself**: published code others depend on,
   security, irreversible operations, or the user explicitly puts quality
   before cost.
   Delegation costs 0.3 to 0.5 of 5 in judged quality whatever the worker
   model, so only reads and mechanical sweeps go out.
3. **Otherwise delegate**, short or long. Long sessions save 38% from
   context isolation alone and about 65% with a medium-tier worker; short tasks
   save about 40%, but only on pinned cheaper agents.
4. **Final review, long sessions only**: one `reviewer` pass recovered about
   0.2 of the 0.47 quality gap on a long session for +0.20 $ (still -58% vs
   vanilla); on a short task it added 49% cost and no quality.

## Workflow

1. Split into units; a unit is one agent's worth of work with its own
   acceptance check. Two units that touch the same file are one unit.
2. Order: ordered parts go one per message, each after the previous report.
3. Write each spec with [the templates](references/templates.md).
4. Verify through reports, `git diff --stat` and one test run.
5. Last unit before the final check: re-check every written `path:line`.
6. Long multi-part session: one `reviewer` pass, given the baseline noted
   before the first unit (a snapshot of the tree, so work that predates the
   task is never reverted), then the final check. The reviewer may edit, so it re-checks
   the `path:line` references into every file it touched.

Evidence, numbers and what was dropped from v1:
[Evidence](references/evidence.md). Full report and per-run dataset:
<https://github.com/obeone/claude-skills/tree/main/benchmarks/cheap-orchestration>. The numbers were measured on Claude
models with a large-tier main loop; on another provider the reasoning
transfers, the percentages are unverified.
