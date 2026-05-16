---
name: tts-duet
description: "Explicit-entry skill for Gemini TTS audio. Invoked deliberately via the /tts-duet command (generation) and /tts-duet-setup (configuration); not auto-triggered. Turns text into mono or dual-voice WAV/MP3 with an adaptation pre-pass, offline cost estimate, and voice audition. Long jobs run synchronously."
metadata:
  version: "3.0.0"
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

Turn text into audio via Gemini's preview TTS models: raw input →
adapted script → cost estimate → generated WAV/MP3. Long jobs run
synchronously; the skill never self-detaches.

## Command-first

This skill is consumed through explicit slash commands, **not** through
keyword auto-trigger. The full procedure lives in the command docs that
ship in this bundle:

- **`/tts-duet`** — the authoritative generation workflow (preflight →
  adapt → estimate → audition → generate). Spec:
  `commands/tts-duet.md`.
- **`/tts-duet-setup`** — interactive configuration of
  `~/.config/tts-duet/config.yaml` and `gemini-tts` MCP health probe.
  Spec: `commands/tts-duet-setup.md`.

Run `/tts-duet-setup` once before the first `/tts-duet` call.

## Out of scope

- Voice cloning or custom voices (prebuilt voices only).
- SSML markup (Gemini TTS ignores it; use inline directives instead).
- Subtitles, timecodes, streaming output, upload to a host.

## Prerequisites

- `GEMINI_API_KEY` reachable by the `gemini-tts` MCP **for generation
  only**. Recommended: `export GEMINI_API_KEY=...` in the shell that
  launches Claude Code (can be sourced from a password manager, so the
  key need not sit in plaintext on disk). Simpler fallback: the
  user-level `~/.claude/settings.json` `"env"` block (restart Claude
  Code after editing). The MCP child reads it; this skill never touches
  the secret. Parsing, estimation, voice listing, and preset validation
  all work offline.
- Python 3.10+ and `uv`. Each entry-point script declares its
  dependencies inline ([PEP 723](https://peps.python.org/pep-0723/)),
  so `uv run scripts/<name>.py …` resolves them automatically.
- Optional: `ffmpeg` (MP3), `kitten` / `alerter` (notifications).

## Entry-point scripts

Driven by `/tts-duet`; run any with `--help` for the full flag set.

- `adapt_script.py` — adaptation pre-pass (`--backend agent|gemini`).
- `generate_tts.py` — primary CLI (synchronous; `--check-key`
  preflights the MCP key).
- `preview_voice.py` — single-voice audition.
- `estimate_cost.py` — offline heuristic; `--with-api` for exact count.
- `list_voices.py` — `--validate` is the CI gate (preset → voice
  consistency).

## References

- `commands/tts-duet.md` — authoritative generation workflow.
- `commands/tts-duet-setup.md` — configuration + MCP probe.
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
