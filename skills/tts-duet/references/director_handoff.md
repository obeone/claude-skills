# Director handoff (agent mode)

When `generate_tts.py` runs with `--director agent`, the skill
delegates the script-rewrite step to the calling agent instead of
calling the MCP `text.transform` tool. This consumes zero Gemini API
tokens.

## Files written to `<job_dir>`

| File | Purpose |
| :--- | :------ |
| `director-prompt.md` | Composed prompt: genre vocabulary, existing-notes policy, raw script, and the strict output format. Hand this to the agent. |
| `director-input.md` | Verbatim copy of the input script. Useful diff anchor when reviewing the rewrite. |
| `HANDOFF.md` | Human-readable instructions: read the prompt, write the rewrite, relaunch. |
| `config.json` | Stamped with `director: {ran: false, backend: "agent", awaiting: true}` and `chunk_count: 0` (chunking has not run yet). |
| `status` | `status=awaiting_director` plus `handoff=director-prompt.md`. |

## Status transitions

```
running → awaiting_director → (caller produces director-output.md)
       → relaunch with --director off
       → running → done
```

The skill never auto-resumes. The caller decides when (and whether) to
relaunch.

## Strict output format expected

The rewrite saved to `director-output.md` MUST follow the format
described in `director-prompt.md`:

```
## Director's Notes
<two-to-four sentences in the genre vocabulary>

## Transcript
<enriched script, same Speaker labels, same turn count>
```

The `tts-duet` script parser recognises both the `## Director's Notes`
heading and `Speaker A:` / `Speaker B:` (or `Speaker1:` / `Speaker2:`)
turn labels. Preserving the turn count guarantees the chunk loop sees
the same boundaries the caller approved.

## Relaunch

```bash
python skills/tts-duet/scripts/generate_tts.py \
  --script <job_dir>/director-output.md \
  --director off \
  --job-dir <job_dir> \
  [other original flags]
```

`--director off` is mandatory on the relaunch — re-running the rewrite
on an already-enriched script would either no-op (`gemini` backend with
`existing_notes_policy: preserve`) or, worse, mangle the carefully
authored output.

## Why two backends?

`gemini` is the load-bearing default for unattended and synchronous
jobs. `agent` exists for two reasons:

1. **Cost control.** A capable calling agent can produce notes for
   free, and may have richer context than the MCP transform call.
2. **Editorial control.** The caller can iterate on the prompt or
   inspect the rewrite before it locks in chunk boundaries.

`off` is the escape hatch when the user already wrote the notes by
hand or wants to compare A/B with no rewrite at all.
