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
