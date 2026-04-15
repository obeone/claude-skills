---
name: tts-duet
description: "Author mono or dual-voice audio scripts and generate them with Gemini TTS. Use when you need to produce a podcast-style clip, voice-over, or narrated dialogue from text, estimate generation cost, audition voices, or run long TTS jobs in the background with notification. Triggers on: TTS, text-to-speech, podcast script, dialogue audio, voiceover, gemini-tts."
metadata:
  version: "1.0.0"
tools:
  - Read
  - Write
  - Edit
  - Bash
---

# Gemini TTS Script

Author a mono- or dual-voice audio script, estimate cost without calling
the API, audition voices, then generate audio via Gemini TTS — with a
background-job lane for anything longer than a few minutes.

## 1. When to use (and not)

**Use this skill when** the user wants to:

- Convert a Markdown-ish script into audio (podcast, voice-over,
  explainer, reading).
- Compare the cost of `pro` vs. `flash` before committing.
- Audition individual voices before picking a preset.
- Run a long generation in the background with notification.

**Do not use this skill for:**

- Voice cloning or custom voices (Gemini prebuilt voices only).
- SSML markup (not supported by Gemini TTS).
- Subtitles / timecode alignment, streaming output, or upload.
- Retry / idempotency scaffolding — out of scope for v1.

## 2. Prerequisites

- `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) in the environment **for
  generation only**. Parsing, estimation, voice listing and preset
  validation work offline.
- Python 3.10+ and `uv` (recommended):
  `uv pip install -r skills/tts-duet/scripts/requirements.txt`.
- Optional: `ffmpeg` (MP3 transcoding), `kitten` (Kitty notification),
  `alerter` (macOS actionable notifications).

## 3. Workflow (agent-facing)

1. **Write / normalize** the script. See §5 and
   `references/script_format.md`.
2. **Pick voices** — a `--preset` is the fastest path; otherwise
   `--voice1 / --voice2` or `--mono --voice`. Experimental presets
   print a warning (§6).
3. **Estimate offline** with `estimate_cost.py` (heuristic; no
   network). Only call `--with-api` when the user explicitly wants the
   exact `count_tokens` value.
4. **Audition** one or both voices with `preview_voice.py` if the
   preset is experimental or the user is unsure.
5. **Propose generation** — only when a key is set — with model,
   format, estimate, and sync-vs-background recommendation. Wait for
   explicit approval.
6. **Generate** with `generate_tts.py --yes`, adding
   `--approved-cost-usd` so a drift aborts non-interactively.
7. **Background for long jobs** — anything > ~5 min audio. Child
   writes status transitions and fires a notification on `done`.

## 4. Repository layout

```
skills/tts-duet/
├── SKILL.md                              # this file
├── scripts/
│   ├── generate_tts.py                   # primary CLI
│   ├── preview_voice.py                  # single-voice audition
│   ├── estimate_cost.py                  # offline heuristic + --with-api
│   ├── list_voices.py                    # --validate is a CI gate
│   ├── requirements.txt
│   ├── dev-requirements.txt              # STT leakage test only
│   └── lib/                              # internal plumbing
│       ├── script_parser.py
│       ├── pricing.py                    # SSOT for cost/duration
│       ├── audio_io.py                   # PCM/WAV/MP3 helpers
│       ├── notify.py                     # notification chain
│       ├── _config.py                    # feature flag for §10
│       ├── _spike_system_instruction.py  # P0 spike artefact
│       └── _gen_api_notes_pricing.py
├── assets/
│   ├── voice_pairs.yaml
│   ├── voices.yaml
│   ├── script_template.md
│   └── preview_text.md
└── references/
    ├── script_format.md
    ├── voices_catalog.md
    └── api_notes.md
```

## 5. Script format (mini-spec)

- Optional `## Director's Notes` block at the top. Captured as the
  `notes` field of the parsed script.
- `Speaker A:` / `Speaker B:` or `Speaker1:` / `Speaker2:` labels
  delimit turns. Mixed forms are allowed and normalized.
- Inline directives such as `[ton: warm]` are kept in the text and
  also collected for debugging.
- No speaker labels → mono mode (single `Mono` turn).

Reference template: `assets/script_template.md`. Full spec:
`references/script_format.md`.

## 6. Voice presets

| Preset | Speaker A | Speaker B | Intent | Stability |
| :----- | :-------- | :-------- | :----- | :-------- |
| `podcast-chill` | Charon | Aoede | Warm + airy | **stable** |
| `interview-pro` | Rasalgethi | Callirrhoe | Informative + measured | experimental |
| `narration-duo` | Orus | Autonoe | Firm + bright | experimental |
| `deep-warm` | Algieba | Sulafat | Warm + low register | experimental |
| `mono-warm` | Algieba | — | Solo warm | experimental |
| `mono-informative` | Rasalgethi | — | Solo narrator | experimental |

Selecting any experimental preset prints:
`WARN: preset '<name>' is experimental; audition with preview_voice.py first`

Catalog of 30 voices: `references/voices_catalog.md`.

## 7. CLI reference

### `generate_tts.py`

```
generate_tts.py --script SCRIPT.md --output NAME
  [--preset podcast-chill | --voice1 Charon --voice2 Aoede | --mono --voice Algieba]
  [--model pro|flash|<full-id>]
  [--lang auto|fr|en|...]
  [--format wav|mp3|both]
  [--require-format]
  [--style "warm tone, calm pace"]
  [--max-duration SECONDS]
  [--background]
  [--chunk-if-over-output-seconds 480]
  [--max-input-tokens 30000]
  [--job-dir ./.tts-jobs/<uuid>/]
  [--approved-cost-usd FLOAT]
  [--yes] [--keep-wav]
```

### `preview_voice.py`

```
preview_voice.py VOICE_NAME [--text "..."] [--seconds 30] [--model flash] [--play]
```

### `estimate_cost.py`

```
estimate_cost.py --script FILE [--model pro|flash] [--with-api] [--json]
```

JSON output always includes `tokens_per_sec_estimate_band_pct: 30`.

### `list_voices.py`

```
list_voices.py [--preset NAME] [--json] [--validate]
```

`--validate` is the CI gate: exits 1 if any preset references a voice
absent from `voices.yaml`.

### Exit-code table

The authoritative exit-code table for `generate_tts.py`:

| Code | Meaning |
| :--: | :------ |
| 0 | Success. |
| 1 | Bad input, or a required dependency was missing while `--require-format` was set. |
| 2 | `--approved-cost-usd` breached; stderr carries `cost_drift_pct=<float>`. |
| 3 | Per-chunk generation failure. Partial WAVs preserved under `<job-dir>/chunks/`. |
| 4 | WAV concatenation failure (inconsistent sample parameters). |

## 8. Duration handling

- No padding, no truncation. `--max-duration` is **advisory** — the
  skill warns and continues.
- Chunking triggers when **either**:
  - Estimated output seconds > `--chunk-if-over-output-seconds`
    (default 480 = 8 min).
  - Input tokens > `--max-input-tokens` (default 30 000) when the
    user asked for the SDK's `count_tokens` (via `estimate_cost.py
    --with-api`).
- Splits always happen on speaker-turn boundaries. A small click at
  boundaries is accepted (documented trade-off).
- Director's Notes are duplicated per chunk **only** in the fallback
  inline-sentinel path (§10); otherwise they travel once via
  `system_instruction`.

## 9. Background jobs

`--background`:

1. Allocates a short UUID and creates `.tts-jobs/<id>/` containing:
   `script.md`, `config.json`, `status`, `job.log`, `pid`, and after
   the run `notification`.
2. Re-execs without `--background` using `nohup`, new session.
3. Foreground prints the job ID, job dir, and a `tail -f` hint.
4. Child writes `status=pending → running → done` (or
   `status=failed` plus `failure_reason`) then calls
   `lib.notify.notify(...)`. The winning tier is captured in
   `<job-dir>/notification` (one of `kitten|alerter|osascript|not-available`).

### Notification chain

1. **kitten** — requires Kitty (`$TERM=xterm-kitty` or
   `$KITTY_WINDOW_ID`) plus a writable parent PTY.
2. **alerter** — macOS only, `shutil.which("alerter")`.
3. **osascript** — macOS only, `display notification`.
4. **not-available** — every tier failed; the status file is the only
   signal.

The notifier never raises; failures are logged at DEBUG.

## 10. Limits & caveats

- Preview models only (`gemini-2.5-pro-preview-tts`,
  `gemini-2.5-flash-preview-tts`). The `--model <full-id>` escape
  hatch lets callers target GA IDs without waiting for a skill bump.
- Voice count capped at two per call.
- Response payload is **raw PCM** — always 24 kHz, 16-bit, mono — not
  a WAV file. The skill wraps it.
- Output is **token-priced**, not time-priced. Estimates use the
  `OUTPUT_TOKENS_PER_SECOND` constant in `scripts/lib/pricing.py` with
  a ±30 % band (recalibrate after 10 real runs — see
  `references/api_notes.md`).
- SDK pinned to `google-genai>=0.8,<1`; unpin once a GA ≥ 1.0 ships
  and the `system_instruction` spike is re-validated.
- **Linux without `notify-send`**: no notifier path is attempted (the
  Kitty route still works if applicable); rely on the `status` file.
- **Director's Notes leakage**: the P0 spike in
  `scripts/lib/_spike_system_instruction.py` decides whether notes go
  to `system_instruction` (flag `True`) or are inlined with a sentinel
  (flag `False`, duplicated per chunk). Flip
  `USE_SYSTEM_INSTRUCTION_FOR_NOTES` in
  `scripts/lib/_config.py` if the spike outcome changes.

## 11. References

- `references/script_format.md` — full input-format spec.
- `references/voices_catalog.md` — 30-voice table + pre-tag audition
  checklist.
- `references/api_notes.md` — Gemini quirks (PCM response shape,
  multi-speaker requirements, auto-generated pricing).
- `assets/script_template.md` — runnable reference script.
- `assets/preview_text.md` — default preview snippet.
