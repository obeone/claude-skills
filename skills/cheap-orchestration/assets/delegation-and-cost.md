## Delegation & cost

Main loop only; subagents ignore this section. Two budgets: tokens, and this
context window (everything read or printed here is re-read on every later
turn). Delegating saves mostly through context isolation, then through
cheaper models.

**Agents.** Delegate only to agents whose model is pinned in their own
definition, and never override the model at call time. Agents that inherit
the session model are never used for delegated work. Start every delegation's
description with the model the agent runs on, in brackets:
`[<small model>] Where is X resolved`, `[<medium model>] Implement X`,
`[<large model>] Final review`. An agent that is not installed is never
replaced by one that inherits the session model: its unit stays inline.

- `scout` (small tier, read-only): questions about the code, answered with
  `path:line`. Prefer it to reading files yourself.
- `editor` (small tier): mechanical edits only (docstrings, comments, renames,
  formatting, verbatim moves). Blocked or failing: give the unit to `worker`.
- `worker` (medium tier, edits and tests): every other unit whose output is
  files.
- `reviewer` (large tier, may edit): the final review of a long session
  (below); anything else only when the user asks. No other review or
  verification agents: verify with commands.

**Decide by size and stakes**, first match wins:

1. A single command, an edit of about 10 lines or fewer in one file (reading
   that file first included), reasoning about output you already have, the
   final check: inline. Read budget: at most 2 read or search calls per turn
   before the first delegation; beyond that, the questions go to `scout`. A
   task that grows past rule 1 midway: delegate the remainder.
2. High stakes: code you will publish for others to depend on, security
   sensitive code, irreversible operations, or the user explicitly puts
   quality before cost. Write it yourself; delegate only reads (`scout`) and
   mechanical sweeps (`editor`).
3. Everything else, short or long: split it into units and delegate each one
   (`worker`, `editor`, `scout`). Never give a unit to a large-tier subagent:
   on a short task it saves nothing.

**Order is binding.** When the task orders its parts, or a unit edits files
that an earlier unit's output refers to, launch exactly one of those units per
message and wait for its report before launching the next, even when they look
independent. Launch units in parallel only when the task does not order them
and they share no file. Reads never conflict: independent `scout` questions
always go out together in one message.

**Guards:**

- Tests: every spec that touches behaviour lists each requirement and named
  edge case from the task and asks for one test per item.
- References: as the last step before the final check, have every `path:line`
  written in docs or notes re-checked against the final tree and fixed
  (`scout` or `editor`). A reviewer that edits afterwards re-checks the
  references into the files it touched.

**Final review, long sessions only:** when the work is long (several ordered
parts that each took their own units, or 5 or more units in all), launch
`reviewer` once, alone, after every unit and the reference re-check are done
and before the final check. Give it the task text verbatim and the commit the
task started from; it reads the diff against that baseline itself, untracked
files included (never paste the diff). Short tasks get no reviewer, even with
several parts: there it costs about half again and adds no quality.

**Contracts:**

- Spec: the requirements verbatim, the constraints, the acceptance command.
  Let the agent read the code; do not pre-read files for it.
- Return: `worker` and `editor` at most 10 lines, `scout` at most 15, never
  code, diffs or file contents.
- Verify an agent through its report, `git diff --stat` and the tests, not by
  re-reading its files. Something wrong: send a precise fix spec to a new
  agent.
- Your own commands: trim every output. Never print a whole source file.
