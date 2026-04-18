---
description: Interactively configure tts-duet defaults (model, format, preset, director behavior) and write to ~/.config/tts-duet/config.yaml or ./tts-duet.yaml
argument-hint: "[--scope user|project]"
---

# tts-duet-setup

Interactively build a `tts-duet` configuration file by collecting user
preferences through grouped questions, then write and validate the result.

## Instructions

### Step 1 — Determine scope

Parse `$ARGUMENTS` for `--scope user` or `--scope project`.

- If `--scope user` was given, set scope = `user` and target =
  `~/.config/tts-duet/config.yaml`.
- If `--scope project` was given, set scope = `project` and target =
  `./tts-duet.yaml` (current working directory).
- If neither was given, use the `AskUserQuestion` tool (load its schema
  first via ToolSearch with query `"select:AskUserQuestion"` if needed)
  to ask:

  > **Where should the config be written?**
  >
  > - `user` — `~/.config/tts-duet/config.yaml` (applies to all projects)
  > - `project` — `./tts-duet.yaml` (this project only, overrides user config)

  Set scope and target accordingly.

### Step 2 — Read existing config (if any)

Check whether the target file already exists:

- Use the Read tool to load its contents.
- If the file exists, display it to the user with the heading:
  **Current config at `<target>`** (fenced YAML block).
- If the file does not exist, note: "No existing config found — starting
  from defaults."

Parse the existing YAML (mentally) to pre-fill the prompts in Steps 3–4
with the current values. If the file does not exist, use the hardcoded
defaults:

```
defaults.model              = pro
defaults.format             = mp3
defaults.preset             = podcast-chill
defaults.approved_cost_usd  = (none)
director.mode               = auto
director.model              = flash
director.existing_notes     = keep
director.genre_default      = pedagogical
```

### Step 3 — Collect defaults preferences

Use the `AskUserQuestion` tool to ask all four `defaults` fields in a
single grouped question. Show the current/default value for each field in
brackets so the user can leave a field blank to keep it unchanged.

Question text (adapt as needed):

> **TTS generation defaults** — press Enter to keep the current value.
>
> 1. **model** [`<current>`] — which model tier?
>    Options: `pro` (higher quality, slower, ~3× cost) | `flash` (faster,
>    cheaper)
>
> 2. **format** [`<current>`] — output format?
>    Options: `mp3` | `wav` | `both`
>
> 3. **preset** [`<current>`] — voice preset?
>    Options: `podcast-chill` (stable) | `interview-pro` | `narration-duo` |
>    `deep-warm` | `mono-warm` | `mono-informative`
>
> 4. **approved_cost_usd** [`<current or "none">`] — hard cost cap in USD
>    before aborting (e.g. `0.50`). Leave blank or type `none` for no cap.

Apply the following parsing rules to the answers:

- Blank answer → keep the existing/default value unchanged.
- `none` or `null` for `approved_cost_usd` → store as YAML `null`.
- Validate `model` ∈ {`pro`, `flash`}; if invalid, use the current value
  and warn.
- Validate `format` ∈ {`mp3`, `wav`, `both`}; if invalid, use current
  and warn.
- Validate `preset` ∈ {`podcast-chill`, `interview-pro`, `narration-duo`,
  `deep-warm`, `mono-warm`, `mono-informative`}; if invalid, use current
  and warn.

### Step 4 — Collect director preferences

Use the `AskUserQuestion` tool to ask all four `director` fields in a
single grouped question.

Question text (adapt as needed):

> **Director pass settings** — the Director is an optional LLM pre-pass
> that enriches the script with pacing notes and inline directives before
> TTS. Press Enter to keep the current value.
>
> 1. **mode** [`<current>`] — when to run the director pass?
>    Options: `auto` (run when no Director's Notes section exists) |
>    `always` (run unconditionally) | `off` (never run)
>
> 2. **director model** [`<current>`] — which model for the director?
>    Options: `flash` (fast, cheap) | `pro` (higher quality)
>
> 3. **existing_notes** [`<current>`] — how to handle a pre-existing
>    `## Director's Notes` section?
>    Options: `keep` (leave untouched) | `replace` (overwrite) |
>    `enrich` (append to it)
>
> 4. **genre_default** [`<current>`] — default genre hint for the
>    director prompt?
>    Options: `pedagogical` | `news` | `storytelling` | `meditation` |
>    `casual` (or any free-text genre)

Apply parsing rules:

- Blank answer → keep existing/default value.
- Validate `mode` ∈ {`auto`, `always`, `off`}; if invalid, use current and warn.
- Validate `director.model` ∈ {`flash`, `pro`}; if invalid, use current and warn.
- Validate `existing_notes` ∈ {`keep`, `replace`, `enrich`}; if invalid, use current and warn.
- `genre_default` accepts any non-empty string.

### Step 5 — Merge with existing config

If the target file already existed, start from its full parsed content and
overlay only the keys the user explicitly changed (do not remove keys that
were not presented in the questions, e.g. future extension keys). If the
file was new, build from scratch with only the two sections `defaults` and
`director`.

Construct the final YAML content. Use this exact structure (always write
`approved_cost_usd: null` when no cap is set — do not omit the key):

```yaml
defaults:
  model: <value>
  format: <value>
  preset: <value>
  approved_cost_usd: <value or null>

director:
  mode: <value>
  model: <value>
  existing_notes: <value>
  genre_default: <value>
```

### Step 6 — Write the file

1. If target is `~/.config/tts-duet/config.yaml`, create parent
   directories as needed using `mkdir -p ~/.config/tts-duet/`.
2. Write the constructed YAML content to the target path using the Write
   tool.

### Step 7 — Validate the written file

Run the following command from the repo root (or any directory that has
`skills/tts-duet/scripts/` accessible) to confirm the written file loads
cleanly:

```bash
uv run --with pyyaml python -c "
import sys; sys.path.insert(0, 'skills/tts-duet/scripts')
from pathlib import Path
from lib.config import load_config
cfg = load_config(project_path=Path('/nonexistent'))
print('defaults.model =', cfg.defaults.model)
print('defaults.format =', cfg.defaults.format)
print('defaults.preset =', cfg.defaults.preset)
print('defaults.approved_cost_usd =', cfg.defaults.approved_cost_usd)
print('director.mode =', cfg.director.mode)
print('director.model =', cfg.director.model)
print('director.existing_notes =', cfg.director.existing_notes)
print('director.genre_default =', cfg.director.genre_default)
"
```

If the command exits non-zero or prints a traceback, report the error and
do not claim success.

For **project-scope** configs, pass the path explicitly to avoid
accidental cross-contamination:

```bash
uv run --with pyyaml python -c "
import sys
from pathlib import Path
sys.path.insert(0, 'skills/tts-duet/scripts')
from lib.config import load_config
cfg = load_config(project_path=Path('./tts-duet.yaml'))
print('defaults.model =', cfg.defaults.model)
print('director.mode =', cfg.director.mode)
"
```

### Step 8 — Report success

Print a confirmation message:

```
Config written to: <target>

  model              = <value>
  format             = <value>
  preset             = <value>
  approved_cost_usd  = <value>
  director.mode      = <value>
  director.model     = <value>
  director.existing_notes = <value>
  director.genre_default  = <value>

Run /tts-duet-setup --scope project to write a project-level override,
or edit the file directly at <target>.
```
