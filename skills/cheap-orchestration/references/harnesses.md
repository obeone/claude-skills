# Harnesses

How each harness defines a named agent with a pinned model, and what
`scripts/setup_crew.py` writes for it. Model identifiers go stale: check them
against your harness and replace one with `--small`, `--medium` or `--large`.

| | Claude Code | Codex CLI | Gemini CLI |
|---|---|---|---|
| User path | `~/.claude/agents/<name>.md` | `~/.codex/agents/<name>.toml` | `~/.gemini/agents/<name>.md` |
| Project path | `.claude/agents/<name>.md` | `.codex/agents/<name>.toml` | `.gemini/agents/<name>.md` |
| Format | Markdown, YAML front-matter | TOML | Markdown, YAML front-matter |
| Small | `haiku` | `gpt-6-luna` | `gemini-4-hydrogen` |
| Medium | `sonnet` | `gpt-6.1-terra` | `gemini-4-neon` |
| Large | `opus` | `gpt-6.2-sol` | `gemini-4-carbon` |
| Status | stable | stable | experimental |
| User directory override | `CLAUDE_CONFIG_DIR` | `CODEX_HOME` | none known |
| No nested delegation | enforced (no `Agent` tool) | instruction only | instruction only |

## Claude Code

Front-matter keys `name`, `description`, `model`, `tools`; the body is the
system prompt. The main loop launches an agent with the `Agent` tool and its
`subagent_type`. A `model` argument on the call overrides the pin, so never
pass one. The bundled definitions list no `Agent` tool, which is what keeps a
subagent from launching others: the limit is enforced by the harness.

## Codex CLI

Checked against Codex CLI 0.171.0, by Codex itself.

- One TOML file per role, picked up without registration in `config.toml`.
  Required keys: `name`, `description`, `developer_instructions`. `model`
  pins the model, `model_reasoning_effort` optionally pins the effort and
  `model_verbosity` the verbosity. The script writes those two only when
  asked (`--effort <agent>=<level>`, `--verbosity <level>`); a reinstall
  with `--force` and without them drops them.
- The parent calls `spawn_agent` with `agent_type="<name>"`. It may pass
  `model`, but the role is applied afterwards, so the pin in the role wins.
- A role cannot have its own sandbox: the child inherits the parent's. For an
  enforced read-only `scout`, run the parent with `codex --sandbox read-only`,
  or keep the scout in a separate read-only session. The bundled `scout` is
  read-only by instruction only.
- Depth: `max_depth = 1` under `[agents]` in `config.toml` blocks
  grandchildren on the V1 multi-agent runtime. V2 ignores it and has no
  per-role switch. The script therefore appends a no-delegation instruction
  to every role: on V2 that sentence is the only guard, not an enforced
  limit.
- Astra (`gpt-6.2-astra`) sits above Sol. It is above the large tier and has
  no place in delegation.

## Gemini CLI

As reported by Gemini with web search, not checked against an installed CLI.
Treat every line as unverified until you have run it.

- Subagents are experimental: set `"experimental": {"enableAgents": true}` in
  `settings.json`.
- Front-matter keys: `name`, `description`, `kind` (`local` or `remote`),
  `tools`, `model`, `temperature`, `max_turns`, `timeout_mins`, `mcpServers`.
  The body is the system prompt.
- The main session delegates from the `description`, or on an explicit
  `@<name>`. No way to override the pinned model at call time was found.
- An agent with no `tools` list inherits every tool of the parent. The script
  writes a list for `scout` only (`read_file`, `grep_search`). The editing
  agents get none and inherit. Every role gets a no-delegation instruction,
  which is a request and not an enforced limit: add a `tools` list yourself
  if you need a hard one.

## Loading at session start

Nothing has to load the skill at startup. What must be active from the first
turn is the rule text, and every harness already reads a user-level
instruction file at the start of each session:

| Harness | File read at startup | What goes in it |
|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md` | `assets/delegation-and-cost.md`, pasted as is |
| Codex CLI | `~/.codex/AGENTS.md` (`$CODEX_HOME/AGENTS.md` when set) | The same rules, plus the crew mapping below |
| Gemini CLI | not checked | |

The skill itself stays on demand: the harness lists its description and
loads the body when a delegation question comes up. On Codex, skills are read
from `~/.codex/skills/`; a symlink to the Claude copy keeps a single source.

The Codex file also needs the facts the generic rules leave open: the crew
lives in `~/.codex/agents/`, an agent is launched with `spawn_agent` and
`agent_type` set to its name, and the call never sets `model` or the
reasoning effort, which would replace the pin. Keep the model names in that
file in step with the installed roles, or leave them out and let
`--check` be the reference: a stale name there misleads the main loop about
the tier it pays for.

No hook is needed, and the benchmark argues against one. Preloading the skill
at session start (configuration E), a prompt router (D), mid-session nudges
(H) and a gate on model labels (G) all cost as much as or more than the
plain rules, with no quality gain; the cheapest configurations carried the
rules in the instruction file and no hook (Y, Q, S).

Check that both halves are in place:

```bash
uv run <skill directory>/scripts/setup_crew.py --provider codex --check
codex exec --skip-git-repo-check -s read-only "Without running any tool: does your loaded instruction context mention the cheap-orchestration skill? Answer yes or no and name the file."
```

For Claude Code, `--provider claude --check`, then ask the same question in
a new session.
