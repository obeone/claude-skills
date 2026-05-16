# Install `tts-duet`

Agent-agnostic install instructions for the `tts-duet` skill (Claude
Code) and the `gemini-tts` MCP server (any MCP-aware CLI: Claude Code,
Codex, Gemini CLI, …).

Source of truth:
<https://raw.githubusercontent.com/obeone/claude-skills/main/skills/tts-duet/INSTALL.md>

If you are an LLM agent following these instructions, **do not skip
the runtime detection step** — the skill bundle is Claude-Code-only
and the MCP server is portable.

## 1. Detect your runtime

Identify which CLI you are running in **before doing anything**:

- `~/.claude/skills/` exists or `$CLAUDECODE` is set → **Claude Code**
  (full skill + MCP).
- `~/.codex/` exists or `$CODEX_HOME` is set → **Codex** (MCP only).
- `~/.gemini/` exists or `$GEMINI_CLI_*` is set → **Gemini CLI** (MCP
  only).
- Otherwise → ask the user which CLI they are using; do not guess.

State the detected runtime in one sentence before proceeding.

## 2. Pre-requisites (verify, do not assume)

- `uvx` on `$PATH` (`uv` v0.5+). If absent, install with
  `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- A valid `GEMINI_API_KEY` from <https://aistudio.google.com/app/apikey>.
- `unzip` and `curl` (only for the Claude Code path).

### Where the API key goes

The skill never reads the key — only the `gemini-tts` MCP child does.

**Recommended:** export `GEMINI_API_KEY` in the shell/session that
launches the host CLI. It can be sourced dynamically from your
password/secret manager, so the secret never sits in plaintext on
disk:

```bash
export GEMINI_API_KEY="$(your-password-manager read gemini-key)"
```

**Simpler fallback (Claude Code):** the user-level Claude settings
file `~/.claude/settings.json`, under a top-level `"env"` block
(stores the key in plaintext on disk; restart Claude Code after
editing):

```json
{
  "env": { "GEMINI_API_KEY": "your-key-here" }
}
```

Do not put the key in project-level config (`.claude/settings.json`
or `.claude/settings.local.json`) — the key is a user-level concern.
(Other MCP-aware CLIs read the key from their own MCP-server registry
`env` block — see §5.)

## 3. Claude Code path

```bash
mkdir -p ~/.claude/skills
curl -L https://github.com/obeone/claude-skills/releases/download/v4.0.0/tts-duet.skill \
  -o /tmp/tts-duet.skill
rm -rf ~/.claude/skills/tts-duet
unzip -q /tmp/tts-duet.skill -d ~/.claude/skills/
rm /tmp/tts-duet.skill
```

Verify install: `head -5 ~/.claude/skills/tts-duet/SKILL.md` should show
`name: tts-duet` and a `metadata.version` of `4.0.0` or higher.

Then register the MCP server (see §5) and restart Claude Code. The
slash command `/tts-duet-setup` writes user defaults to
`~/.config/tts-duet/config.yaml`.

## 3a. Claude desktop app path

The Claude desktop app (macOS/Windows) runs local MCP servers, so
`tts-duet` is fully functional there — generation included — unlike
claude.ai web (no local subprocess → the `gemini-tts` MCP cannot run,
the Step 0 preflight will correctly refuse).

1. **Skill bundle**: install the `.skill` the same way as any desktop
   skill — upload it from a [release](../../releases) in the app's
   skill settings. (If this machine also runs Claude Code, the bundle
   under `~/.claude/skills/tts-duet/` is independent of the desktop
   app's own skill store; install in whichever surface you use.)
2. **MCP server**: register `gemini-tts` in the desktop config, then
   fully quit and reopen the app.

   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`

   Merge the JSON snippet from §5 into the top-level `mcpServers`
   object of that file (never overwrite it).

### Where the key goes (desktop)

There is no shell `export` around a GUI app, so the recommended
shell-env path does not apply directly. Options, in order:

- **Secret-manager wrapper**: launch the desktop app from a terminal
  under your secret manager (e.g. `op run -- open -a Claude`) so
  `GEMINI_API_KEY` is in the app's environment; leave the MCP `env`
  block empty. Keeps the key out of plaintext.
- **Plaintext in the MCP `env` block** of `claude_desktop_config.json`
  (simpler; the key sits in plaintext in that file — your call).

Do **not** put the key in any project-level config. The desktop
config file is user-level, which is the correct scope.

## 4. Codex / Gemini CLI / generic MCP path

The skill bundle (`SKILL.md`, `commands/`, `references/`) is
Claude-Code-only. Skip §3 and only register the MCP server.

Locate the MCP-server registry for your CLI:

- **Codex**: `~/.codex/config.toml` (table: `[mcp_servers]`).
- **Gemini CLI**: `~/.gemini/settings.json` or per-project
  `.gemini/settings.json` (key: `mcpServers`).
- **Other**: ask the user where their MCP server registry lives.

After registration the following tools become available:

- `gemini-tts.tts_generate_chunk` — PCM dialogue, multi-speaker.
- `gemini-tts.tts_preview_voice` — single-voice audition.
- `gemini-tts.tts_count_tokens` — exact token count for a script.
- `gemini-tts.text_transform` — generic Gemini text pipe.
- `gemini-tts.meta_health` — readiness probe.

## 5. MCP server registration snippet

The pin `@v4.0.0` is intentional. **Do not change it without a reason**
— a floating `git+` ref breaks reproducibility (plan §6.4).

### JSON (Claude Code, Gemini CLI)

```json
{
  "mcpServers": {
    "gemini-tts": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/obeone/claude-skills@v4.0.0#subdirectory=skills/tts-duet/mcp",
        "gemini-tts-mcp"
      ],
      "env": {
        "GEMINI_API_KEY": "<paste-or-use-secret-manager>"
      }
    }
  }
}
```

Merge this into the existing top-level `mcpServers` object — never
overwrite the file.

### TOML (Codex)

```toml
[mcp_servers.gemini-tts]
command = "uvx"
args = [
  "--from",
  "git+https://github.com/obeone/claude-skills@v4.0.0#subdirectory=skills/tts-duet/mcp",
  "gemini-tts-mcp",
]
env = { GEMINI_API_KEY = "<paste-or-use-secret-manager>" }
```

### Secret-management variants (ask the user before choosing)

- **Plaintext**: paste the key directly. Simplest, leaks via shell
  history and config backups.
- **1Password**: launch the host CLI under `op run --env-file=…` and
  set `GEMINI_API_KEY=op://Personal/Gemini API/credential`. Do not put
  the `op://` reference inside the JSON `env` block — `uvx` will not
  expand it.
- **direnv**: leave `env` empty in the snippet, expose the key from a
  project-level `.envrc`, and start the host CLI from that directory.
- **Vault / `pass` / etc.**: same pattern as 1Password — wrap the host
  CLI launch.

## 6. Post-install smoke test

After restarting the host CLI, ask the agent:

> "Use the `gemini-tts` MCP to call `meta_health` and report
> `protocol_version` and `api_key_status`."

A working install returns:

```json
{
  "ok": true,
  "protocol_version": "1",
  "api_key_status": "ok",
  "package_version": "0.2.0",
  "model_availability": {
    "gemini-2.5-flash-preview-tts": true,
    "gemini-2.5-pro-preview-tts": true
  }
}
```

## 7. Updating

Bump the pinned tag in the registration snippet (e.g. `@v3.0.0` →
`@v3.1.0` once the next release ships) and restart the host CLI. `uvx` re-resolves the new revision
automatically. The `tts-duet.skill` bundle (Claude Code only) must be
re-downloaded from the matching release.

## 8. Uninstall

```bash
# Claude Code only — drop the skill bundle
rm -rf ~/.claude/skills/tts-duet
rm -rf ~/.config/tts-duet

# All paths — drop the MCP entry
# edit ~/.claude.json (Claude), ~/.codex/config.toml (Codex), or
# ~/.gemini/settings.json (Gemini CLI) and remove the "gemini-tts" key.
```

`uvx` keeps the resolved git revision in its cache (`~/.cache/uv/`).
Run `uv cache prune` if you also want to reclaim that space.
