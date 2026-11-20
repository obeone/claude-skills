---
name: cheap-orchestration
description: This skill should be used when planning how to split a task across subagents, writing a delegation spec, or deciding whether a unit runs inline, on a pinned cheaper agent (scout, editor, worker) or not at all. It holds the decision rule by task size and stakes, the pinned agent crew, the ordering and guard rules, spec and return templates, and the benchmark evidence behind each rule. The rules themselves live in the "Delegation & cost" section of CLAUDE.md; this skill is the detail and the rationale.
metadata:
  version: "2.1.0"
---

# Cheap Orchestration

The operative rules are in CLAUDE.md ("Delegation & cost"). This skill adds
the templates and the reasons, so the rules can be applied to cases they do
not name.

## Crew

Agents live in `~/.claude/agents/`, each with its model pinned in the
frontmatter. Never pass `model` on an `Agent` call: it overrides the pin.

| Agent | Model | Tools | Use for | Returns |
|---|---|---|---|---|
| `scout` | haiku | Read, Grep, Glob, Bash (read-only) | Questions about the code before a decision or a spec | 15 lines of `path:line` facts |
| `editor` | haiku | edits, Bash | Mechanical edits with no design choice | 10-line report |
| `worker` | sonnet | edits, Bash | Every other unit whose output is files | 10-line report |
| `reviewer` | opus | edits, Bash | Final restriction check and polish pass: default on long multi-part sessions, otherwise on request | 10-line report |

None has the `Agent` tool, so no subagent can fan out on its own.

Every `Agent` call starts its `description` with the model the agent runs on,
in brackets: `[Haiku] Where is X resolved`, `[Sonnet] Implement X`,
`[Opus] Final review`. The label is the only place the model shows up in the
transcript, so a unit sent to the wrong tier is visible at launch instead of
on the bill.

## Decision rule

1. **Inline**: one command, an edit of about 10 lines in one file, reasoning
   on output in hand, the final check, within a read budget of 2 read or
   search calls per turn before the first Agent call. A delegation costs a
   spec, a launch turn, a notification turn and the agent's own system prompt.
2. **High stakes, write it yourself**: published code others depend on,
   security, irreversible operations, or the user explicitly puts quality
   before cost.
   Delegation costs 0.3 to 0.5 of 5 in judged quality whatever the worker
   model, so only reads and mechanical sweeps go out.
3. **Otherwise delegate**, short or long. Long sessions save 38% from
   context isolation alone and about 65% with the Sonnet worker; short tasks
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
6. Long multi-part session: one `reviewer` pass, then the final check.

Evidence, numbers and what was dropped from v1:
[Evidence](references/evidence.md).
