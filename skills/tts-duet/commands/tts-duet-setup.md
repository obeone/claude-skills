---
name: tts-duet-setup
description: "Interactively configure tts-duet defaults and verify the gemini-tts MCP registration."
---

# /tts-duet-setup

Gather sane defaults for the `tts-duet` skill, persist them to
`~/.config/tts-duet/config.yaml`, and probe the `gemini-tts` MCP via
`meta.health`. Emit a copy-pasteable `~/.claude.json` registration
snippet (pinned to `@v2.2.0`) when the MCP is missing. **This command
never writes API keys and never mutates `~/.claude.json`.**

## Step 1 — gather defaults

Ask the user for:

- Preferred model alias (`pro` / `flash`). Default: `flash`.
- Default output format (`wav` / `mp3` / `both`). Default: `mp3`.
- Default preset (one of the `voice_pairs.yaml` entries, e.g.
  `podcast-chill`). Default: `podcast-chill`.
- Director backend (`agent` / `gemini` / `off`). Default: `gemini`.
  `agent` delegates the rewrite to the calling agent (incompatible
  with background runs); `gemini` uses the MCP `text.transform` tool;
  `off` skips the rewrite.
- Notification preference (`auto` / `silent`). Default: `auto`.

## Step 1bis — call-time prompts

Ask the user which fields the skill should **re-prompt at every
`/tts-duet` invocation** instead of taking the saved default. Present
this as a multi-select with the value of each field shown next to it
so the user understands what they are overriding:

- `preset` — re-pick the voice pair every time (defaults to the value
  from Step 1 when not selected).
- `style` — re-supply the freeform style hint passed via
  `generate_tts.py --style "..."` every time (saved value remains as a
  fallback when present).
- `director` — re-pick the director backend (`agent` / `gemini` /
  `off`) every time. Useful for users who alternate between background
  jobs (which require `gemini` or `off`) and interactive runs.
- `none` — keep the legacy behaviour: defaults are used silently.

Persist the chosen subset as a YAML list under the top-level
`prompt_at_call:` key (see Step 2). Selecting `none` (or making no
selection) writes `prompt_at_call: []`.

## Step 2 — write `~/.config/tts-duet/config.yaml`

Preserve any existing keys; only touch the fields gathered above and
the new `mcp:` section. Minimal schema:

```yaml
model: flash
format: mp3
preset: podcast-chill
director:
  backend: gemini   # agent | gemini | off — quote "off" to keep YAML 1.1 from coercing it to false
  model: gemini-2.5-flash
  temperature: 0.2
  existing_notes_policy: preserve
notify: auto
# Fields the skill re-prompts at every /tts-duet call instead of
# taking the default above. Subset of {preset, style, director}.
# Empty list = legacy "use defaults silently".
prompt_at_call: []
mcp:
  # Either a list or a single string (shlex-split at load time).
  command:
    - uvx
    - --from
    - git+https://github.com/obeone/claude-skills@v2.2.0#subdirectory=skills/tts-duet/mcp
    - gemini-tts-mcp
  chunk_retry_max: 2
  respawn_max: 3
  spawn_timeout_s: 120
```

`$TTS_DUET_MCP_COMMAND` always wins over `mcp.command` when set.

When writing `director.backend: off`, quote it as `"off"` — bare `off`
is coerced to `false` under YAML 1.1, which makes the file harder to
read (the parser tolerates both, but the on-disk form should match what
the user typed).

## Step 3 — probe `gemini-tts` MCP via `meta.health`

Call `mcp__gemini_tts__meta_health`. If the tool is available and
returns `status=ok`, print:

```
gemini-tts MCP: registered (package=<X.Y.Z>, protocol=<N>)
```

If the tool is **not** registered (the Claude Code agent has no
`mcp__gemini_tts__*` tool), emit the snippet below and instruct the
user to paste it into their `~/.claude.json` and reload:

```json
{
  "mcpServers": {
    "gemini-tts": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/obeone/claude-skills@v2.2.0#subdirectory=skills/tts-duet/mcp",
        "gemini-tts-mcp"
      ],
      "env": { "GEMINI_API_KEY": "${GEMINI_API_KEY}" }
    }
  }
}
```

Never attempt to edit `~/.claude.json` programmatically.

## Step 4 — summary line

Print one line per write target with pass/fail, e.g.:

```
config.yaml: wrote /Users/<user>/.config/tts-duet/config.yaml
gemini-tts MCP: not registered — snippet above
```

## Notes

- Skill-side scripts never read `GEMINI_API_KEY` / `GOOGLE_API_KEY`;
  the MCP does. Do not mention those variables except when echoing
  the snippet above.
- Exit code semantics are handled by the caller; this command returns
  plain text for the user and never raises.
