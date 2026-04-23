# Script Format

The `tts-duet` skill reads a Markdown-ish text file with up to
two sections:

1. An **optional** `## Director's Notes` heading. Text underneath is
   used to bias delivery (tone, pace, pronunciation cues). Depending on
   the value of `USE_SYSTEM_INSTRUCTION_FOR_NOTES` in
   `scripts/lib/_config.py`, the notes are either passed to the SDK's
   `system_instruction` field (clean path) or inlined at the top of
   the content with the sentinel `[director-notes-do-not-speak]`
   (fallback path).
2. A `## Transcript` section (heading optional) containing one or
   more speaker turns.

## Speaker turns

Two forms of speaker labels are accepted and treated as equivalent.
Labels are case-insensitive and whitespace between `Speaker` and the
identifier is optional:

```text
Speaker A: Welcome to the show.
Speaker B: Thanks for having me.
```

or

```text
Speaker1: Welcome to the show.
Speaker2: Thanks for having me.
```

Internally, the parser normalizes everything to `Speaker1` /
`Speaker2`, which are the labels the Gemini SDK's
`multi_speaker_voice_config` expects.

If no speaker labels are found in the file, the script is parsed in
**mono mode**: the whole content (minus Director's Notes) becomes one
`Mono` turn.

## Inline directives

Inline directives are square-bracketed `key: value` pairs that the
Gemini TTS model interprets directly. They are preserved verbatim in
the turn text and also aggregated in `ParsedScript.directives` for
debugging:

```text
Speaker A: [ton: warm] Good morning.
Speaker B: [pace: slow] [emphasis: mild] The story begins here.
```

Common keys: `ton`, `pace`, `emphasis`, `volume`, `lang`. The SDK is
lenient; unknown keys are ignored.

## Example

```markdown
## Director's Notes

Keep the energy friendly but measured. The hosts are old friends.

## Transcript

Speaker A: [ton: warm] Welcome back.
Speaker B: [pace: measured] Glad to be here.
Speaker A: What have you been up to?
Speaker B: I've been reading about the history of standard time zones.
```

## Parsing rules

- The first line matching `^\s*[Ss]peaker\s*(?P<id>[ABab12])\s*:` starts
  the transcript region; everything before it is preamble.
- Inside preamble, only the `## Director's Notes` block is retained;
  other text is dropped in dual mode (or merged into the mono turn in
  mono mode).
- Empty turns are skipped.
- Windows/Mac line endings are normalized by `str.splitlines()`; the
  skill writes LF-only output.

## See also

- `assets/script_template.md` — runnable reference template.
- `references/voices_catalog.md` — the voices you can pair.
- `references/api_notes.md` — Gemini quirks relevant to scripting.
