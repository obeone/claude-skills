# Install `tts-duet`

Install instructions for the `tts-duet` Claude Code plugin (recommended),
the standalone `.skill` bundle, and the `gemini-tts` MCP server for any
MCP-aware CLI (Claude Code, Codex, Gemini CLI, …).

Source of truth:
<https://raw.githubusercontent.com/obeone/claude-skills/main/skills/tts-duet/INSTALL.md>

If you are an LLM agent following these instructions, **do not skip the
runtime detection step** (§4) for the non-plugin paths — the skill
bundle is Claude-Code-only and the MCP server is portable.

## 1. TL;DR — Plugin (recommended)

```bash
claude plugin marketplace add obeone/claude-skills
claude plugin install tts-duet@obeone-claude-skills
```

At the enable prompt, paste your Gemini API key into the sensitive
`gemini_api_key` field — it is stored in your system keychain, never in
a project file. After this, the **MCP tool surface
(`mcp__gemini_tts__*`) is one-step**: the `gemini_tts` MCP is registered
from the pinned PyPI spec `gemini-tts-mcp==0.3.0` with **no manual
`~/.claude.json` editing**.

**Flagship-pipeline residual (read this up front).** The full
`/tts-duet:tts-duet` generation pipeline drives a *second* MCP child
(spawned by `generate_tts.py`, not the plugin-registered server). That
child reads the key only from the **ambient** environment, so for the
full pipeline you must also make the key available ambiently:

```bash
export GEMINI_API_KEY="$(your-password-manager read gemini-key)"
```

…or add it to the user-level `~/.claude/settings.json` `"env"` block
(restart Claude Code after editing). This is a documented, accepted
contract — the one-step install covers the MCP surface; the full
generation pipeline additionally needs the ambient key.

Then:

```text
/tts-duet:tts-duet-setup     # warm-up + config + MCP health probe
/tts-duet:tts-duet           # generate
```

## 2. What you get

- A PyPI-backed, version-pinned MCP server `gemini_tts` exposing the
  five tools `mcp__gemini_tts__{tts_generate_chunk,tts_preview_voice,tts_count_tokens,text_transform,meta_health}`.
- The commands `/tts-duet:tts-duet` and `/tts-duet:tts-duet-setup`, plus
  the unchanged standalone `/tts-duet` skill entrypoint.
- The `tts-duet` skill itself (front-matter `name: tts-duet`).

Note the cosmetic plugin-name namespacing stutter
`/tts-duet:tts-duet` — this is expected and non-breaking; nothing was
renamed or removed.

## 3. Network posture (online-first)

The MCP resolves over the network on first use and after a plugin
refetch (a few seconds, like any `uvx`/`npx` tool). Gemini TTS calls
the Gemini API, so a network connection is required for the feature to
work at all. If you are offline, the plugin (like any Claude Code
plugin) is simply unavailable until you reconnect — this plan makes no
air-gapped guarantee. The `/tts-duet:tts-duet-setup` warm-up step
primes the resolver cache so the first real generation is not a cold
resolve.

## 4. Key handling per consumer

- **Consumer #1 — the plugin-registered `gemini_tts` MCP.** Key comes
  from the sensitive `userConfig` prompt → stored in the system
  keychain → injected into the server `env` as `GEMINI_API_KEY`. No
  plaintext, no `~/.claude.json` editing.
- **Consumer #2 — `generate_tts.py`'s own MCP child** (the full
  `/tts-duet:tts-duet` pipeline). Key comes **only** from the ambient
  `GEMINI_API_KEY` / `GOOGLE_API_KEY` (shell export or
  `~/.claude/settings.json` `"env"`). This is the documented residual
  from §1. The skill process itself never reads the key — only the MCP
  child does.

Do not put the key in project-level config (`.claude/settings.json` or
`.claude/settings.local.json`) — the key is a user-level concern.

## 5. Updating (no-double-version runbook)

Versions live in **exactly one place each**:

- The MCP package version is `mcp/pyproject.toml`
  (`gemini-tts-mcp`, currently `0.3.0`). The `plugin.json`
  `mcpServers.gemini_tts.args` pin and the `_VENDORED_FALLBACK` in
  `scripts/lib/mcp_client.py` pin the **same** `==0.3.0`.
- The plugin version is `plugin.json` `version` (currently `4.1.0`).
  The marketplace entry carries **no `version`** — if it did,
  `plugin.json` would win silently and break `claude plugin update`
  reasoning.

When the MCP package is bumped (e.g. `0.3.0 → 0.3.1`) you **must**
update all three pins (`mcp/pyproject.toml`, `plugin.json` args,
`_VENDORED_FALLBACK`) **and** bump `plugin.json` `version` — otherwise
`claude plugin update tts-duet` is a silent no-op. Then publish the new
version to PyPI (the `Publish gemini-tts-mcp to PyPI` workflow) and run
`claude plugin update tts-duet`.

The marketplace `source.ref` is pinned to the CalVer release tag
`v2026.05.3`. That tag is cut at the post-merge release gate per the
repository's tagging procedure; only then are users pointed at the
marketplace.

## 6. Standalone `.skill` bundle (Claude Code, secondary)

If you do not want the plugin, the legacy `.skill` bundle still works.

```bash
mkdir -p ~/.claude/skills
curl -L https://github.com/obeone/claude-skills/releases/download/v4.1.0/tts-duet.skill \
  -o /tmp/tts-duet.skill
rm -rf ~/.claude/skills/tts-duet
unzip -q /tmp/tts-duet.skill -d ~/.claude/skills/
rm /tmp/tts-duet.skill
```

Verify install: `head -5 ~/.claude/skills/tts-duet/SKILL.md` should show
`name: tts-duet` and a `metadata.version` of `4.1.0` or higher. Then
register the MCP server (§7) and restart Claude Code.

## 7. Legacy MCP registration snippet (pre-this-release path)

**This `git+…` manual-registration path is the legacy / pre-this-release
route.** The recommended route is the plugin (§1), which registers the
MCP from the pinned PyPI spec with no manual config editing. The legacy
snippet is retained for the standalone bundle, Codex, and Gemini CLI.

### JSON (Claude Code, Gemini CLI)

```json
{
  "mcpServers": {
    "gemini-tts": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/obeone/claude-skills@v4.1.0#subdirectory=skills/tts-duet/mcp",
        "gemini-tts-mcp"
      ],
      "env": {
        "GEMINI_API_KEY": "<paste-or-use-secret-manager>"
      }
    }
  }
}
```

### TOML (Codex)

```toml
[mcp_servers.gemini-tts]
command = "uvx"
args = [
  "--from",
  "git+https://github.com/obeone/claude-skills@v4.1.0#subdirectory=skills/tts-duet/mcp",
  "gemini-tts-mcp",
]
env = { GEMINI_API_KEY = "<paste-or-use-secret-manager>" }
```

Merge this into the existing top-level `mcpServers` object — never
overwrite the file.

### C2 air-gapped-legacy migration note

The resolver default in `scripts/lib/mcp_client.py` now points at the
PyPI spec `gemini-tts-mcp==0.3.0` (not the old git ref). This is **not
behavior-preserving for one cohort**: an air-gapped legacy install with
no `TTS_DUET_MCP_COMMAND`, no `mcp.command` in
`~/.config/tts-duet/config.yaml`, `gemini-tts-mcp` not on `$PATH`, and a
`~/.cache/uv` that holds only the old git `@v2.3.0` build (never the
PyPI wheel) **will fail offline**, because the default now resolves a
PyPI spec that host has never fetched. To keep that setup working,
either set `TTS_DUET_MCP_COMMAND` (or `mcp.command`) explicitly to the
git form above, or go online once so `uvx` can fetch the wheel. No
unqualified "behavior-preserving" claim is made for this cohort; under
the online-first posture this is an accepted, documented residual.

## 8. Naming note

`/tts-duet` (the standalone skill entrypoint) is unchanged. The plugin
commands are `/tts-duet:tts-duet` and `/tts-duet:tts-duet-setup` (the
plugin-name-prefixed stutter is accepted and cosmetic). No command was
removed or renamed.

## 9. Post-install smoke test

After enabling the plugin (or registering the legacy MCP) ask the
agent:

> "Use the `gemini_tts` MCP to call `meta_health` and report
> `protocol_version` and `api_key_status`."

A working install returns:

```json
{
  "ok": true,
  "protocol_version": "1",
  "api_key_status": "ok",
  "package_version": "0.3.0",
  "model_availability": {
    "gemini-2.5-flash-preview-tts": true,
    "gemini-2.5-pro-preview-tts": true
  }
}
```

`package_version: "0.3.0"` confirms the pinned PyPI spec resolved (not
the legacy `git+…@v2.3.0` fallback).

## 10. Troubleshooting

- **Confirm the active MCP source.** `/tts-duet:tts-duet-setup` Step 6
  prints the resolved MCP source per consumer; `generate_tts.py` also
  logs the resolved MCP command to stderr at startup. It must show the
  pinned PyPI `--from gemini-tts-mcp==0.3.0` form, not `git+…@v2.3.0`.
- **First-use resolve latency.** The first MCP call after install or a
  plugin refetch incurs a one-time `uvx` resolve+build (a few seconds).
  The `/tts-duet:tts-duet-setup` warm-up primes it.
- **Missing `uv`.** Install with
  `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- **The full pipeline reports no key.** The one-step install covers the
  MCP surface only. The full `/tts-duet:tts-duet` pipeline needs the
  Gemini key available **ambiently** (§1, §4) — export it or put it in
  `~/.claude/settings.json` `"env"`.

## 11. Uninstall

```bash
# Plugin
claude plugin uninstall tts-duet@obeone-claude-skills
claude plugin marketplace remove obeone-claude-skills

# Standalone .skill bundle (Claude Code only)
rm -rf ~/.claude/skills/tts-duet
rm -rf ~/.config/tts-duet

# Legacy manual MCP entry — edit ~/.claude.json (Claude),
# ~/.codex/config.toml (Codex), or ~/.gemini/settings.json (Gemini CLI)
# and remove the "gemini-tts" key.
```

`uvx` keeps resolved builds in its cache (`~/.cache/uv/`). Run
`uv cache prune` to reclaim that space.
