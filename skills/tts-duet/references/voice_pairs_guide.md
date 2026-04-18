# Voice pairing guide

Actionable recommendations for choosing Gemini 2.5 TTS voices by use case,
plus the authoring/directing rules that make the output sound natural
instead of robotic. Read this before writing a script so the `--preset` or
`--voice1 / --voice2` flags land on the right combination.

> **Catalog status**: 30 voices are exposed by the Gemini 2.5 TTS preview
> models. Only 5 are verified in this skill's `assets/voices.yaml`
> (Charon, Aoede, Zephyr, Puck, Enceladus). Descriptors for the others
> come from Google's published documentation and should be re-auditioned
> with `preview_voice.py` before production use.

---

## 1. Pair recommendations by use case

### Dual-voice

| Use case | Speaker A | Speaker B | Why |
|---|---|---|---|
| **Pedagogical podcast** (senior ↔ junior) | Charon (informative, ♂) | Puck (upbeat, ♂) | Calm-vs-curious contrast; Puck lands as an engaged listener |
| **Warm podcast / conversation** | Charon | Aoede (breezy, ♀) | Default `podcast-chill` preset — mixed-gender, balanced |
| **Serious interview** | Charon | Kore (firm, ♀) | Authority on the guest side — good for tech / business |
| **Storytelling / dialogued audiobook** | Enceladus (breathy, ♂) | Aoede | Low + airy, strong narrative immersion |
| **Energetic discussion** | Fenrir (excitable, ♂) | Laomedeia (upbeat, ♀) | Dynamic, high-energy content |
| **Tutorial / approachable explainer** | Puck (friendly, ♂) | Sulafat (warm, ♀) | Accessible, non-intimidating |
| **Meditation / calm content** | Schedar (even, ♂) | Vindemiatrix (gentle, ♀) | Slow pacing, grounded tone |

### Mono (single narrator)

| Use case | Voice | Why |
|---|---|---|
| Documentary / vulgarization | Rasalgethi (informative, ♂) or Gacrux (mature, ♀) | Authoritative and clear |
| Audiobook fiction | Despina (smooth, ♀) or Algieba (smooth, ♂) | Flowing delivery, comfortable for long form |
| Announcements / ads | Zephyr (bright, ♀) or Alnilam (firm, ♂) | Attention-grabbing, concise |

---

## 2. Model choice: Pro vs. Flash

| Criterion | Flash | Pro |
|---|---|---|
| Prosody & nuance | Good | **Much better** — subtle emotion lands cleanly |
| Pacing fidelity | Good | Superior; handles pauses and emphasis naturally |
| Tag interpretation | Adequate | **Interprets `[tag]` directives more reliably** |
| Cost (per 1M output tokens) | $10 | $20 |
| Typical API latency | ~40% faster than Pro | Slower |
| When to use | Prototyping, A/B-ing voices, short assets | Final podcast, audiobook, hero content |

**Rule of thumb**: prototype with `--model flash`, then re-generate the
shipped version with `--model pro` once the script and voices are locked.

---

## 3. Inline tags — what actually works

Tags in square brackets are **directives, not spoken text**. They shift
tone, pacing, or insert vocalizations. Three modes:

1. **Silent modifiers** — `[slowly]`, `[measured]`, `[with emphasis]`,
   `[thoughtful]`, `[warm]`. Modify delivery; not vocalized.
2. **Non-speech vocalizations** — `[sigh]`, `[laugh]`, `[gasp]`,
   `[breathes]`, `[clears throat]`. Replaced with an audible sound.
3. **Emotion adjectives** — `[happy]`, `[sad]`, `[angry]`. ⚠️ Sometimes
   spoken aloud as words. Prefer action-oriented directives
   (`[thoughtful]`, `[enthusiastic]`) or combine as a single group.

### Formatting rules

- Always wrap in `[...]`: `[pause]`, not `(pause)` or `*pause*`.
- Separate a tag from surrounding text with whitespace or punctuation:
  ✅ `[pause] Puis on parle du DNS.`  
  ❌ `pause.Puis` (parser-hostile).
- **Never adjacent tags**: `[happy] [excited]` → combine: `[happy, excited]`.
- One tag per tonal shift is enough. Over-tagging sounds jerky.

### Useful tag vocabulary

- **Tone**: `[warm]`, `[curious]`, `[thoughtful]`, `[enthusiastic]`,
  `[serious]`, `[amused]`, `[surprised]`, `[triumphant]`, `[impressed]`.
- **Pacing**: `[slowly]`, `[measured]`, `[quickly]`, `[pause]`.
- **Texture**: `[whispers]`, `[gravelly]`, `[breathy]`, `[quiet]`.
- **Non-verbal**: `[laugh]`, `[sigh]`, `[gasp]`.
- **Delivery**: `[gently]`, `[forcefully]`, `[hesitantly]`.

---

## 4. Director's Notes — the three-part structure

Place at the top of the script, before `## Transcript`. The parser lifts
them into the model via the inline-sentinel path (`system_instruction` is
currently disabled — see `api_notes.md`).

1. **Profile** — who the characters are.
   > *Two French-speaking hosts: a senior developer patiently explaining
   > a concept, and a curious junior asking clarifying questions.*
2. **Scene** — where and when.
   > *Relaxed studio podcast, afternoon, conversational intimacy.*
3. **Direction** — the performance contract.
   > *Measured French pacing, natural pauses at punctuation, no lecture
   > tone. Warm, like talking to a colleague.*

Give enough detail to anchor the character, but leave room for the model
to fill in. Over-specification tends to flatten delivery.

---

## 5. Authoring rules for natural-sounding audio

- **Short sentences**. Long, nested clauses produce robotic intonation.
  Break on natural breathing points.
- **Match the text to the direction**. If the notes say "enthusiastic",
  don't write in a neutral register — the voice will fight the text.
- **Alternate rhythm between speakers**. A measured host + a quicker
  guest creates the cadence of a real conversation.
- **Use `[pause]` at speaker handoffs** for breathing room, especially
  in long chunks where energy can flatten.
- **Punctuation is a directive too**. Commas, em-dashes, ellipses, and
  question marks all shape delivery. Use them generously.
- **Avoid mid-sentence tag conflicts** with the overall direction —
  the model will average the cues and lose clarity.

---

## 6. Anti-patterns that force a regen

| Symptom | Likely cause | Fix |
|---|---|---|
| Voices sound flat / monotone | Flash model, or no Director's Notes | Switch to `--model pro`, add a 3-part directors note |
| Speakers read `[ton: warm]` aloud | Non-standard tag format | Use `[warm]` not `[ton: warm]` — the parser only strips recognized bracketed directives |
| Pacing too fast / no breaths | Long run-on sentences | Split into shorter phrases, insert `[pause]` between topics |
| One voice dominates energy | Both voices in the same tonal band | Pair a "calm" descriptor with an "upbeat" one (see §1) |
| Boundary click at chunk transitions | Normal for dual-voice chunks | Acceptable trade-off; document in output notes or rework script to fit in one chunk (<480s audio) |

---

## 7. Quick recipes

### Podcast dual-voice, Pro, 5–9 min

```bash
python scripts/generate_tts.py \
  --script my-podcast.md \
  --voice1 Charon --voice2 Puck \
  --model pro --format mp3 \
  --approved-cost-usd 0.50 \
  --progress --yes
```

### Prototype on Flash first (cheaper A/B)

```bash
python scripts/generate_tts.py \
  --script my-podcast.md \
  --preset podcast-chill \
  --model flash --format mp3 \
  --approved-cost-usd 0.20 --yes
```

### 30-second voice audition

```bash
python scripts/preview_voice.py Puck --seconds 30 --model pro --play
```

---

## 8. Sources

- Gemini TTS official documentation:
  [ai.google.dev/gemini-api/docs/speech-generation](https://ai.google.dev/gemini-api/docs/speech-generation)
- Gemini 2.5 TTS launch blog:
  [blog.google/technology/developers/gemini-2-5-text-to-speech](https://blog.google/innovation-and-ai/technology/developers-tools/gemini-2-5-text-to-speech/)
- Google Cloud TTS reference:
  [docs.cloud.google.com/text-to-speech/docs/gemini-tts](https://docs.cloud.google.com/text-to-speech/docs/gemini-tts)
