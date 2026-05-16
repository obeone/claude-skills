# Adaptation handoff (agent mode)

When `adapt_script.py` runs with `--backend agent`, the skill delegates
the raw-text-to-script rewrite to the calling agent instead of calling
the MCP `text_transform` tool. This consumes zero Gemini API tokens.

The pre-pass turns raw input (article, transcript, paper, notes, …)
into a runnable script in one of three shapes — `dialogue`, `mono`, or
`interview` — at a chosen target duration. The director pass (§ Director
in `SKILL.md`) is a *separate* enrichment step that runs later and adds
Director's Notes; do not confuse the two handoffs.

## Files written to `<job_dir>`

| File | Purpose |
| :--- | :------ |
| `adaptation-prompt.md` | Composed prompt: shape rule, target duration, language directive, optional style hint, raw input verbatim, and the strict output format. Hand this to the agent. |
| `adaptation-input.md` | Verbatim copy of the raw input. Useful diff anchor when reviewing the rewrite. |
| `HANDOFF.md` | Caller-facing instructions: read the prompt, write the rewrite, save it as `adapted-script.md`, hand the path to downstream tooling. |
| `status` | `status=awaiting_adaptation` plus `handoff=adaptation-prompt.md`. |

## Status transitions

```
running → awaiting_adaptation → (caller produces adapted-script.md)
       → caller passes adapted-script.md to generate_tts.py
```

`adapt_script.py` never auto-resumes. The caller decides when (and
whether) to feed the rewrite to the next stage.

## Strict output format expected

The rewrite saved to `adapted-script.md` MUST follow the format
described in `adaptation-prompt.md`:

```
## Transcript
<adapted script — Speaker labels matching the chosen shape>
```

Shape-specific rules embedded in the prompt:

- **dialogue** — `Speaker A:` / `Speaker B:` turns, alternating, each
  1-3 sentences. Never merge consecutive turns onto one line.
- **mono** — every paragraph as `Mono: …`. One idea per paragraph.
- **interview** — `Speaker A:` (interviewer) / `Speaker B:`
  (interviewee), strictly alternating Q/A, no narrator interjections.

The downstream `tts-duet` parser (`references/script_format.md`)
recognises both `Speaker A:` / `Speaker B:` and the normalised
`Speaker1:` / `Speaker2:` form.

## Relaunch (downstream generation)

```bash
python skills/tts-duet/scripts/generate_tts.py \
  --script <job_dir>/adapted-script.md \
  --director off \
  [other original flags]
```

`--director off` is recommended on the relaunch when the adaptation
backend was `gemini` (the rewrite already enriched the script). When
the adaptation backend was `agent` (this contract), the calling agent
chooses: it can either hand-write notes during this same pass, or let a
later `--director` run produce them.

## Why two backends?

`gemini` is the load-bearing default for unattended pipelines and for
small calling agents that should not spend their context on rewriting.
`agent` exists for two reasons:

1. **Cost and context.** A capable calling agent has richer context
   than a one-shot transform call (knows the project, the speaker,
   prior content) and pays nothing.
2. **Editorial control.** The caller can iterate on the prompt,
   adjust the target duration after seeing a first draft, or
   inspect/repair the rewrite before downstream chunking locks
   boundaries in.

There is intentionally no `off` backend: an unadapted raw text fed to
`generate_tts.py` would produce monologue-of-prose audio, the very
thing the skill exists to avoid (see `SKILL.md` Workflow rule).

## See also

- `references/director_handoff.md` — sibling contract for the
  Director's Notes pass.
- `references/script_format.md` — full input-format spec consumed
  downstream.
- `commands/tts-duet-setup.md` — where `adaptation.backend`, `shape`,
  and `language` defaults are configured.
