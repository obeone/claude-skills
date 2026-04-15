# Voices Catalog

The Gemini TTS preview models advertise 30 prebuilt voices. Only five
are described in the public documentation; the remaining 25 ship with
a `(to verify)` descriptor and `tonal_hint: unknown` until an operator
auditions them (see the checklist below). The authoritative list lives
in `assets/voices.yaml` — this document mirrors it for human reference.

## Catalog (30 voices)

| # | Name | Descriptor | Tonal hint | Verified |
|---|------|------------|-----------:|---------:|
| 1 | Achernar | (to verify) | unknown | ❌ |
| 2 | Achird | (to verify) | unknown | ❌ |
| 3 | Algenib | (to verify) | unknown | ❌ |
| 4 | Algieba | (to verify) | unknown | ❌ |
| 5 | Alnilam | (to verify) | unknown | ❌ |
| 6 | Aoede | breezy | mid | ✅ |
| 7 | Autonoe | (to verify) | unknown | ❌ |
| 8 | Callirrhoe | (to verify) | unknown | ❌ |
| 9 | Charon | informative | low | ✅ |
| 10 | Despina | (to verify) | unknown | ❌ |
| 11 | Enceladus | breathy | low | ✅ |
| 12 | Erinome | (to verify) | unknown | ❌ |
| 13 | Fenrir | (to verify) | unknown | ❌ |
| 14 | Gacrux | (to verify) | unknown | ❌ |
| 15 | Iapetus | (to verify) | unknown | ❌ |
| 16 | Kore | (to verify) | unknown | ❌ |
| 17 | Laomedeia | (to verify) | unknown | ❌ |
| 18 | Leda | (to verify) | unknown | ❌ |
| 19 | Orus | (to verify) | unknown | ❌ |
| 20 | Puck | upbeat | high | ✅ |
| 21 | Pulcherrima | (to verify) | unknown | ❌ |
| 22 | Rasalgethi | (to verify) | unknown | ❌ |
| 23 | Sadachbia | (to verify) | unknown | ❌ |
| 24 | Sadaltager | (to verify) | unknown | ❌ |
| 25 | Schedar | (to verify) | unknown | ❌ |
| 26 | Sulafat | (to verify) | unknown | ❌ |
| 27 | Umbriel | (to verify) | unknown | ❌ |
| 28 | Vindemiatrix | (to verify) | unknown | ❌ |
| 29 | Zephyr | bright | high | ✅ |
| 30 | Zubenelgenubi | (to verify) | unknown | ❌ |

> 25 / 30 voices remain labelled `(to verify)`. They are usable — the
> SDK accepts the names — but the tonal descriptor has not been audited
> by a human yet.

## Pre-tag audition checklist

Every checkbox below must be ticked before cutting a stable release
that depends on the voice descriptor being accurate.

- [ ] `preview_voice.py Achernar --model flash`
- [ ] `preview_voice.py Achird --model flash`
- [ ] `preview_voice.py Algenib --model flash`
- [ ] `preview_voice.py Algieba --model flash`
- [ ] `preview_voice.py Alnilam --model flash`
- [ ] `preview_voice.py Aoede --model flash`
- [ ] `preview_voice.py Autonoe --model flash`
- [ ] `preview_voice.py Callirrhoe --model flash`
- [ ] `preview_voice.py Charon --model flash`
- [ ] `preview_voice.py Despina --model flash`
- [ ] `preview_voice.py Enceladus --model flash`
- [ ] `preview_voice.py Erinome --model flash`
- [ ] `preview_voice.py Fenrir --model flash`
- [ ] `preview_voice.py Gacrux --model flash`
- [ ] `preview_voice.py Iapetus --model flash`
- [ ] `preview_voice.py Kore --model flash`
- [ ] `preview_voice.py Laomedeia --model flash`
- [ ] `preview_voice.py Leda --model flash`
- [ ] `preview_voice.py Orus --model flash`
- [ ] `preview_voice.py Puck --model flash`
- [ ] `preview_voice.py Pulcherrima --model flash`
- [ ] `preview_voice.py Rasalgethi --model flash`
- [ ] `preview_voice.py Sadachbia --model flash`
- [ ] `preview_voice.py Sadaltager --model flash`
- [ ] `preview_voice.py Schedar --model flash`
- [ ] `preview_voice.py Sulafat --model flash`
- [ ] `preview_voice.py Umbriel --model flash`
- [ ] `preview_voice.py Vindemiatrix --model flash`
- [ ] `preview_voice.py Zephyr --model flash`
- [ ] `preview_voice.py Zubenelgenubi --model flash`
- [ ] `list_voices.py --validate` exits 0
