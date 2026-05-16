# gemini-tts-mcp

Vendored MCP server that owns every Gemini API call used by the
[`tts-duet`](../) skill. The skill never reads `GEMINI_API_KEY` /
`GOOGLE_API_KEY` itself; it speaks to this server over stdio.

Status: **skeleton** (v0.2.0). Only `meta_health` is wired; TTS tools land
in the next commit.

## Install

Pinned install (preferred for end users):

```bash
uv tool install git+https://github.com/obeone/claude-skills@v2.4.0#subdirectory=skills/tts-duet/mcp
```

Or register directly in `~/.claude.json` via `uvx`:

```json
{
  "mcpServers": {
    "gemini-tts": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/obeone/claude-skills@v2.4.0#subdirectory=skills/tts-duet/mcp",
        "gemini-tts-mcp"
      ],
      "env": { "GEMINI_API_KEY": "${GEMINI_API_KEY}" }
    }
  }
}
```

Local development install:

```bash
uv tool install ./skills/tts-duet/mcp
```

## Reusability

The tool surface is TTS-domain-scoped (`tts.*` plus a generic
`text_transform` Gemini text pipe). Any future skill needing Gemini
access can register this same MCP — no tts-duet domain knowledge leaks
across the contract.

## Development

```bash
cd skills/tts-duet/mcp
uv sync
uv run pytest
uv run python -m gemini_tts_mcp --help
```
