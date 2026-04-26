---
name: tts-duet
description: "Author mono or dual-voice audio scripts and generate them with Gemini TTS. Use when you need to produce a podcast-style clip, voice-over, or narrated dialogue from text, estimate generation cost, audition voices, or run long TTS jobs in the background with notification. Triggers on: TTS, text-to-speech, podcast script, dialogue audio, voiceover, gemini-tts."
metadata:
  version: "2.4.0"
tools:
  - Read
  - Write
  - Edit
  - Bash
  - mcp__gemini_tts__tts_generate_chunk
  - mcp__gemini_tts__tts_preview_voice
  - mcp__gemini_tts__tts_count_tokens
  - mcp__gemini_tts__text_transform
  - mcp__gemini_tts__meta_health
---

# Gemini TTS — author and generate

Turn text into audio via Gemini's preview TTS models. The skill takes
you from raw input → adapted script → cost estimate → generated WAV/MP3,
with a background lane for jobs longer than a few minutes.

## Out of scope

- Voice cloning or custom voices (prebuilt voices only).
- SSML markup (Gemini TTS ignores it; use inline directives instead).
- Subtitles, timecodes, streaming output, upload to a host.

## Prerequisites

- `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) in the environment **for
  generation only**. The MCP child reads it; this skill never touches
  the secret. Parsing, estimation, voice listing, and preset validation
  all work offline.
- Python 3.10+ and `uv`. Each entry-point script declares its
  dependencies inline ([PEP 723](https://peps.python.org/pep-0723/)),
  so `uv run path/to/script.py …` resolves them automatically.
- Optional: `ffmpeg` (MP3), `kitten` / `alerter` (notifications).

## Workflow

The workflow has one non-negotiable rule and a few sensible defaults.

**Rule: never feed raw user text to TTS.** Always produce an adapted
script first. The user wants something listenable, not their own prose
read aloud — and the model handles dialogue better than monologue.

1. **Honour `prompt_at_call`** from `~/.config/tts-duet/config.yaml`
   when present. If the list contains `preset`, `style`, `shape`,
   `language`, `adaptation`, or `director`, re-ask the user for that
   field at call time instead of taking the saved default. Empty list
   (or no config) = take defaults silently.
2. **Adapt the input into a script.** Default shape: a two-voice
   dialogue with `Speaker A:` / `Speaker B:` turns, lively pacing,
   natural turn-taking. Honour explicit user requests for other shapes
   (mono narration, interview Q&A, debate, children's story, …). For
   long-form input (article, paper, transcript), summarise to a
   runnable length — ask the user for the target duration if unclear.
   Skip adaptation only when the input already follows the script
   format; even then, normalise speaker labels and confirm.
   Persist the adapted script to disk before generating so the user
   can review and iterate without round-tripping through the model.

   **Who does the adaptation** is read from
   `~/.config/tts-duet/config.yaml`'s `adaptation.backend` field, with
   `shape` and `language` defaults from the same file:
   - `agent` (default): you, the calling agent, do the summarisation
     and dialogue-writing using your own context. Free, no extra
     tokens, richer context than a one-shot transform.
   - `gemini`: invoke `scripts/adapt_script.py --backend gemini …` to
     delegate the rewrite to the MCP `text.transform` tool. Useful
     when the calling agent is small, when the user wants Gemini's
     editorial style end-to-end, or for unattended pipelines.

   `adapt_script.py` also accepts `--backend agent`, in which case it
   writes a `HANDOFF.md` + `adaptation-prompt.md` + `adaptation-input.md`
   triple to `--job-dir`, mirroring the director agent-mode contract.
   Full handoff spec: `references/adaptation_handoff.md`.

   Estimate the **target duration** from the input length before
   calling: ~150 wpm spoken, so a 750-word source maps to ~5 min
   audio. Confirm the figure with the user when unclear.

   If `adaptation` is listed in `prompt_at_call`, ask the user at every
   invocation instead of taking the default. The same trade-off applies
   to **Director's Notes** via `--director` (step 7); when adaptation
   is delegated to `gemini`, run with `--director off` to avoid a
   double rewrite.
3. **Pick voices.** `--preset` is the fastest path; `--voice1 / --voice2`
   or `--mono --voice` if you know the catalog. Experimental presets
   print a warning — audition first.
4. **Estimate offline** with `estimate_cost.py` (heuristic, no
   network). Use `--with-api` only when the user explicitly wants the
   exact `count_tokens` value.
5. **Audition** with `preview_voice.py` if the preset is experimental
   or the user is unsure.
6. **Propose generation** — once a key is set — with model, format,
   estimate, and a sync-vs-background recommendation. Wait for
   approval.
7. **Generate** with `generate_tts.py --yes --approved-cost-usd <X>`
   so a cost drift aborts non-interactively.
8. **Background** anything > ~5 min audio (`--background`). The child
   writes status transitions and fires a notification when done.

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

## Voice presets

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

## Quick reference

Typical end-to-end session:

```bash
# 0. (optional) Adapt raw input via the MCP — only when
#    adaptation.backend == gemini. Skip when the agent did it locally.
uv run scripts/adapt_script.py \
  --input raw.md --output script.md \
  --backend gemini --shape dialogue --language auto \
  --target-duration 300 --yes

# 1. Estimate
uv run scripts/estimate_cost.py --script script.md --model flash --json

# 2. Audition (optional)
uv run scripts/preview_voice.py Charon --play

# 3. Generate (sync)
uv run scripts/generate_tts.py \
  --script script.md --output ./out/episode \
  --preset podcast-chill --model flash --format mp3 \
  --approved-cost-usd 0.42 --yes

# 4. Or background, for long runs
uv run scripts/generate_tts.py [...] --background
```

Entry points (run any with `--help` for the full flag set):

- `adapt_script.py` — adaptation pre-pass (`--backend agent|gemini`).
  Writes a runnable script from raw input.
- `generate_tts.py` — primary CLI (sync or `--background`).
- `preview_voice.py` — single-voice audition.
- `estimate_cost.py` — offline heuristic; `--with-api` for exact count.
- `list_voices.py` — `--validate` is the CI gate (preset → voice
  consistency).

### Exit codes (`generate_tts.py`)

| Code | Meaning |
| :--: | :------ |
| 0 | Success. |
| 1 | Bad input, or required dependency missing under `--require-format`. |
| 2 | `--approved-cost-usd` breached. Stderr carries `cost_drift_pct=<float>`. |
| 3 | Per-chunk generation failure. Partial WAVs preserved under `<job-dir>/chunks/`. |
| 4 | WAV concatenation failure (inconsistent sample parameters). |

## Long jobs and chunking

`--background` allocates a short UUID, writes
`.tts-jobs/<id>/{script.md,config.json,status,job.log,pid}`, re-execs
detached, and the foreground prints the job ID and a `tail -f` hint.
The child transitions `pending → running → done` (or `failed` with
`failure_reason`) and fires a notification. The notifier never raises;
if every tier fails the `status` file is the only signal.

Chunking kicks in when estimated output > `--chunk-if-over-output-seconds`
(default 480 s) **or** input tokens > `--max-input-tokens` (default
30 000, requires `--with-api`). Splits always happen on speaker-turn
boundaries; a small click at boundaries is accepted.

## Director pass

`--director` rewrites the script with explicit Director's Notes and
per-turn cues before chunking. Three backends:

- `gemini` (default) — call the MCP `text.transform`. Output saved to
  `<job_dir>/director-output.md`. On failure, falls back to the
  original; the error lands in `config.json`'s `director.error` field.
- `agent` — the skill writes `director-prompt.md`, `director-input.md`,
  `HANDOFF.md` to the job dir, sets `status=awaiting_director`, and
  exits 0. The calling agent produces `director-output.md`, then
  relaunches with `--director off`. Zero MCP calls, zero tokens. **Not
  compatible with `--background`** — no supervised parent.
- `off` — feed the script verbatim.

Default backend is read from `~/.config/tts-duet/config.yaml`'s
top-level `director:` block. `$TTS_DUET_DIRECTOR` overrides both. Full
agent-mode contract: `references/director_handoff.md`.

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

Implementation quirks (system-instruction routing, notifier chain
order, calibration constants) live in `references/api_notes.md`.

## References

- `references/script_format.md` — full input-format spec.
- `references/voices_catalog.md` — 30-voice table + audition checklist.
- `references/api_notes.md` — Gemini quirks, pricing, internal flags.
- `references/director_handoff.md` — agent-mode artifact contract
  (Director's Notes pass).
- `references/adaptation_handoff.md` — agent-mode artifact contract
  (raw-text-to-script adaptation pre-pass).
- `assets/script_template.md` — runnable reference script (dialogue).
- `assets/script_examples.md` — one example per shape (dialogue, mono,
  interview) for copy-paste starting points.
- `assets/preview_text.md` — default preview snippet.
