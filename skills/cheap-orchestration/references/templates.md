# Spec and Return Templates

The examples use Claude Code's `Agent` call and Claude model names. On
another harness, keep the spec text and use its own delegation call; in the
label, write the model your agent actually runs on (`[Terra]`, `[Flash]`).

## Worker spec

```
Agent(subagent_type="worker", description="[Sonnet] Implement X",
      prompt="""
Task: <one sentence>.
Requirements (verbatim from the task):
- <req 1>
- <req 2, including named edge cases>
Constraints: <files not to touch, API to keep, style to follow>.
Tests: one test per requirement and named edge case above.
Acceptance: <exact command>, must pass.
Read the code you need yourself.
""")
```

No model override in the call. The return shape is in the agent definition (10 lines),
so the prompt does not repeat it.

## Editor spec

```
Agent(subagent_type="editor", description="[Haiku] Add docstrings to parser",
      prompt="""
Rule: <the one mechanical change, e.g. NumPy-style docstring on every
function and class lacking one>.
Targets: <paths or glob>. List every target first, then do all of them.
Do not change: logic, signatures, imports, untouched lines.
Check: <command that counts what is left, or the test command>.
""")
```

An editor that comes back blocked, or whose check fails, hands the unit to a
`worker` with the same spec.

## Scout question

```
Agent(subagent_type="scout", description="[Haiku] Where is X resolved",
      prompt="Where is <symbol> defined and called, and what does <test>
              expect? Answer with path:line per fact.")
```

## Ordered parts

```
message 1: Agent(worker, Part 1 spec)       -> wait for the report
message 2: Agent(worker, Part 2 spec)       -> wait for the report
message 3: Agent(editor, Part 3 rule)       -> wait for the report
message 4: Agent(scout or editor, re-check every path:line in NOTES.md)
message 5: Agent(reviewer, task text verbatim)   (long sessions only)
message 6: final test run, inline
```

## Reviewer spec (long sessions only)

```
Agent(subagent_type="reviewer", description="[Opus] Final review",
      prompt="""
Task text (verbatim):
<the whole task>
All units are done. Read git diff yourself.
""")
```

The restriction check, polish list and report shape are in the agent
definition. Never paste the diff into the prompt.

Never two ordered parts in the same message, even when they look
independent: a later part can move the lines an earlier part's notes cite.

## Parallel units

Units the task does not order and that share no file go in one message,
several `Agent` calls. Past about 6 concurrent agents the synthesis in the
main loop eats the savings.

## Return budgets in the main loop

| Delegation | Budget |
|---|---|
| scout | 15 lines |
| worker, editor, reviewer | 10 lines |
| a genuinely large answer | written to a file, path returned |

Never let raw grep output, whole files, full test logs or full diffs into the
main context.
