# Sample TTS Script

This file is the reference template for the `gemini-tts-script` skill.
The format has two sections: an optional `## Director's Notes` block at
the top, followed by the `## Transcript` section with speaker turns.
Inline directives such as `[ton: warm]` can be placed anywhere inside a
turn — the Gemini TTS model understands them natively, and the parser
records them in `ParsedScript.directives` for debugging.

## Director's Notes

Warm, conversational pace. Keep the energy friendly but not hyper.
Do not read these notes aloud; they are production guidance.

## Transcript

Speaker A: [ton: warm] Welcome back to the show. I'm glad you're here on a Thursday morning — it means you either love mornings or you're avoiding something harder. Either way, you picked the right episode.

Speaker B: [pace: measured] Thanks for having me. I spent the week reading about the history of standard time zones, which sounds dull until you realize railroads invented them to stop killing people.

Speaker A: That's a hook I was not expecting. Walk us through the short version?

Speaker B: [emphasis: mild] Short version: before 1883, every town set its own clock by solar noon. Trains from Boston and Chicago would arrive with contradictory times on the same platform. People missed connections. Occasionally, they collided.

Speaker A: [ton: curious] So standardization wasn't about tidiness — it was about not dying on the way to Cleveland.

Speaker B: Exactly. Coordination is usually invisible until its absence becomes violent.
