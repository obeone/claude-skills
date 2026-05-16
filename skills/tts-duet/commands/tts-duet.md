---
name: tts-duet
description: "Author and generate mono or dual-voice audio with Gemini TTS. Explicit entrypoint for the tts-duet skill: raw input -> adapted script -> cost estimate -> WAV/MP3. Long jobs run synchronously."
---

# /tts-duet `<input | request>`

Turn text into audio via Gemini's preview TTS models. This command is
the authoritative entrypoint for the `tts-duet` skill: it takes you
from raw input → adapted script → cost estimate → generated WAV/MP3.
Long jobs run synchronously; the skill never self-detaches.

`<input | request>` examples:

- `make a 5-minute chill podcast out of references/article.md`
- `voiceover for this paragraph in fr, single narrator`
- `audition the Charon voice before we commit`
- `interview-style dialogue from this transcript`

All deep specs live next to this command in the skill bundle
(`../references/`, `../assets/`, `../scripts/`). Paths below are
relative to `skills/tts-duet/`.

## Out of scope

- Voice cloning or custom voices (prebuilt voices only).
- SSML markup (Gemini TTS ignores it; use inline directives instead).
- Subtitles, timecodes, streaming output, upload to a host.

## Prerequisites

- `GEMINI_API_KEY` reachable by the `gemini-tts` MCP **for generation
  only**. The MCP child reads it; this command never touches the
  secret. Parsing, estimation, voice listing, and preset validation
  all work offline.

  **Recommended:** export `GEMINI_API_KEY` in the shell/session that
  launches Claude Code. It can be sourced dynamically from your
  password/secret manager, so the secret never sits in plaintext on
  disk:

  ```bash
  export GEMINI_API_KEY="$(your-password-manager read gemini-key)"
  ```

  **Simpler fallback:** the user-level Claude settings file
  `~/.claude/settings.json`, under a top-level `"env"` block (stores
  the key in plaintext on disk; restart Claude Code after editing):

  ```json
  {
    "env": { "GEMINI_API_KEY": "your-key-here" }
  }
  ```

  Do not put the key in project-level config (`.claude/settings.json`
  or `.claude/settings.local.json`) — the key is a user-level concern.
- Python 3.10+ and `uv`. Each entry-point script declares its
  dependencies inline ([PEP 723](https://peps.python.org/pep-0723/)),
  so `uv run scripts/<name>.py …` resolves them automatically.
- Optional: `ffmpeg` (MP3), `kitten` / `alerter` (notifications).
- Configuration comes from `~/.config/tts-duet/config.yaml`. Run
  `/tts-duet-setup` first if it is missing.

## Hard rule

**Never feed raw user text to TTS.** Always produce an adapted script
first. The user wants something listenable, not their own prose read
aloud — and the model handles dialogue better than monologue.

## Step 0 — preflight (fail fast)

**Before anything else**, confirm the `gemini-tts` MCP can see a
healthy Gemini API key. Call the Claude-managed MCP tool
`mcp__gemini_tts__meta_health`.

If the tool is unavailable, or the result is not healthy, or
`has_api_key` is false → **STOP immediately**. Do nothing else (no
adaptation, no estimate, no generation). Emit this remediation block
verbatim and wait:

> The `gemini-tts` MCP has no usable Gemini API key. The skill never
> reads the key itself — only the MCP child does.
>
> **Recommended:** export `GEMINI_API_KEY` in the shell/session that
> launches Claude Code. It can be sourced dynamically from your
> password/secret manager, so the secret never sits in plaintext on
> disk:
>
> ```bash
> export GEMINI_API_KEY="$(your-password-manager read gemini-key)"
> ```
>
> **Simpler fallback:** set it in the user-level
> `~/.claude/settings.json` `"env"` block (stores the key in plaintext
> on disk; restart Claude Code after editing):
>
> ```json
> // ~/.claude/settings.json
> {
>   "env": { "GEMINI_API_KEY": "your-key-here" }
> }
> ```
>
> Do not put the key in project-level config
> (`.claude/settings.json` or `.claude/settings.local.json`) — the key
> is a user-level concern. Then restart Claude Code (or re-launch with
> the env set) and re-run `/tts-duet`.

The CLI mirrors this probe: `generate_tts.py --check-key` exits `0`
when the MCP reports a present, healthy key and `1` (with the same
remediation on stderr) otherwise.

## Step 1 — honour call-time prompts

Read `~/.config/tts-duet/config.yaml`. If `prompt_at_call` lists any
of `preset`, `style`, `shape`, `language`, `adaptation`, or
`director`, re-ask the user for that field now instead of taking the
saved default. Empty list (or no config) = take defaults silently.

## Step 2 — adapt the input into a script

Default shape: a two-voice dialogue with `Speaker A:` / `Speaker B:`
turns, lively pacing, natural turn-taking. Honour explicit user
requests for other shapes (mono narration, interview Q&A, debate,
children's story, …). For long-form input (article, paper,
transcript), summarise to a runnable length — ask the user for the
target duration if unclear.

Skip adaptation only when the input already follows the script
format; even then, normalise speaker labels and confirm. Persist the
adapted script to disk before generating so the user can review and
iterate without round-tripping through the model.

**Who does the adaptation** is read from the config's
`adaptation.backend` field, with `shape` and `language` defaults from
the same file:

- `agent` (default): you, the calling agent, do the summarisation and
  dialogue-writing using your own context. Free, no extra tokens,
  richer context than a one-shot transform.
- `gemini`: invoke `scripts/adapt_script.py --backend gemini …` to
  delegate the rewrite to the MCP `text_transform` tool. Useful when
  the calling agent is small, when the user wants Gemini's editorial
  style end-to-end, or for unattended pipelines.

`adapt_script.py` also accepts `--backend agent`, in which case it
writes a `HANDOFF.md` + `adaptation-prompt.md` + `adaptation-input.md`
triple to `--job-dir`, mirroring the director agent-mode contract.
Full handoff spec: `references/adaptation_handoff.md`.

Estimate the **target duration** from the input length before
calling: ~150 wpm spoken, so a 750-word source maps to ~5 min audio.
Confirm the figure with the user when unclear. When adaptation is
delegated to `gemini`, run the later director pass with
`--director off` to avoid a double rewrite.

```bash
uv run scripts/adapt_script.py \
  --input raw.md --output script.md \
  --backend gemini --shape dialogue --language auto \
  --target-duration 300 --yes
```

## Step 3 — pick voices

`--preset` is the fastest path; `--voice1 / --voice2` or
`--mono --voice` if you know the catalog. Experimental presets print a
warning — audition first.

| Preset | Speaker A | Speaker B | Intent | Stability |
| :----- | :-------- | :-------- | :----- | :-------- |
| `podcast-chill` | Charon | Aoede | Warm + airy | **stable** |
| `interview-pro` | Rasalgethi | Callirrhoe | Informative + measured | experimental |
| `narration-duo` | Orus | Autonoe | Firm + bright | experimental |
| `deep-warm` | Algieba | Sulafat | Warm + low register | experimental |
| `mono-warm` | Algieba | — | Solo warm | experimental |
| `mono-informative` | Rasalgethi | — | Solo narrator | experimental |

Experimental presets print
`WARN: preset '<name>' is experimental; audition with preview_voice.py first`.
Catalog of 30 voices: `references/voices_catalog.md`.

## Step 4 — estimate offline

```bash
uv run scripts/estimate_cost.py --script script.md --model flash --json
```

Heuristic, no network. Use `--with-api` only when the user explicitly
wants the exact `count_tokens` value.

## Step 5 — audition (optional)

```bash
uv run scripts/preview_voice.py Charon --play
```

Do this when the preset is experimental or the user is unsure.

## Step 6 — propose generation, wait for approval

Once a key is set, present: model, format, and the cost estimate.
**Wait for explicit approval before generating.** In auto mode you may
proceed without asking only when the run is low-risk (short output,
stable preset, estimate well under any user-stated budget). Generation
runs synchronously; if the user wants the run detached, the calling
agent backgrounds the `/tts-duet` invocation via its own mechanism.

## Step 7 — generate

```bash
uv run scripts/generate_tts.py \
  --script script.md --output ./out/episode \
  --preset podcast-chill --model flash --format mp3 \
  --approved-cost-usd 0.42 --yes
```

`--yes --approved-cost-usd <X>` makes a cost drift abort
non-interactively instead of prompting.

### Director pass

`--director` rewrites the script with explicit Director's Notes and
per-turn cues before chunking. Three backends:

- `gemini` (default) — call the MCP `text_transform`. Output saved to
  `<job_dir>/director-output.md`. On failure, falls back to the
  original; the error lands in `config.json`'s `director.error` field.
- `agent` — the script writes `director-prompt.md`,
  `director-input.md`, `HANDOFF.md` to the job dir, sets
  `status=awaiting_director`, and exits 0. You produce
  `director-output.md`, then relaunch with `--director off`. Zero MCP
  calls, zero tokens.
- `off` — feed the script verbatim.

Default backend is read from the config's top-level `director:` block.
`$TTS_DUET_DIRECTOR` overrides both. Full agent-mode contract:
`references/director_handoff.md`.

### Exit codes (`generate_tts.py`)

| Code | Meaning |
| :--: | :------ |
| 0 | Success. |
| 1 | Bad input, or required dependency missing under `--require-format`. |
| 2 | `--approved-cost-usd` breached. Stderr carries `cost_drift_pct=<float>`. |
| 3 | Per-chunk generation failure. Partial WAVs preserved under `<job-dir>/chunks/`. |
| 4 | WAV concatenation failure (inconsistent sample parameters). |

Forward any non-zero exit code to the user with the matching cause. Do
**not** retry blindly.

## Step 8 — long jobs

Long jobs run **synchronously**: `generate_tts.py` does not
self-detach. If the user wants the run detached, the calling agent
backgrounds the whole `/tts-duet` invocation through its own mechanism
— the skill no longer forks a nohup child. Pass `--job-dir <dir>` to
persist `config.json`, `status`, `mcp-stderr.log`, and chunk artifacts
for inspection.

Chunking kicks in when estimated output >
`--chunk-if-over-output-seconds` (default 480 s) **or** input tokens >
`--max-input-tokens` (default 30 000, requires `--with-api`). Splits
always happen on speaker-turn boundaries; a small click at boundaries
is accepted.

## Script format

```markdown
## Director's Notes
Keep the energy friendly but measured. The hosts are old friends.

## Transcript
Speaker A: [ton: warm] Welcome back.
Speaker B: [pace: measured] Glad to be here.
```

- `## Director's Notes` (optional) bias delivery — tone, pace,
  pronunciation cues.
- `Speaker A:` / `Speaker B:` or `Speaker1:` / `Speaker2:` delimit
  turns. Case-insensitive, normalised to `Speaker1` / `Speaker2`.
- Inline directives like `[ton: warm]`, `[pace: slow]` stay in the
  text and bias the model.
- No speaker labels → mono mode.

Full spec and edge cases: `references/script_format.md`. Runnable
template: `assets/script_template.md`.

## Limits

- Preview models only (`gemini-2.5-pro-preview-tts`,
  `gemini-2.5-flash-preview-tts`). The `--model <full-id>` escape
  hatch lets callers target GA IDs without waiting for a skill bump.
- Two voices per call (one in mono mode).
- Output is **token-priced**, not time-priced. Estimates use a ±30 %
  band; recalibrate after 10 real runs (see `references/api_notes.md`).
- Response payload is raw PCM (24 kHz, 16-bit, mono); the skill wraps
  it as WAV.
- SDK pinned to `google-genai>=0.8,<1`.

## References

- `references/script_format.md` — full input-format spec.
- `references/voices_catalog.md` — 30-voice table + audition checklist.
- `references/api_notes.md` — Gemini quirks, pricing, internal flags.
- `references/director_handoff.md` — agent-mode artifact contract
  (Director's Notes pass).
- `references/adaptation_handoff.md` — agent-mode artifact contract
  (raw-text-to-script adaptation pre-pass).
- `assets/script_template.md` — runnable reference script (dialogue).
- `assets/script_examples.md` — one example per shape.
- `assets/preview_text.md` — default preview snippet.

## What this command must NOT do

- Read or echo `GEMINI_API_KEY` / `GOOGLE_API_KEY` (only the MCP child
  reads them); never write the key value into any file.
- Skip the Step 0 preflight, or generate when `meta_health` is
  unreachable / reports no key.
- Feed raw user prose to TTS without an adaptation pass.
- Generate before the cost estimate is shown and approved.
- Run a double rewrite (`adaptation: gemini` then `director: gemini`).
