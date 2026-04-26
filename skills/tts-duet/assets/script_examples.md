# TTS Script Examples — one per shape

Documentation companion to `assets/script_template.md`. The template
itself is a single runnable `dialogue` script (the parser can only
consume one shape at a time, so this file stays purely illustrative).

Use these examples to see what each shape looks like in practice and
to copy-paste a starting point. Discard the sections that do not match
your `shape:` config (or `--shape` flag).

---

## Shape: dialogue

Two voices, lively turn-taking, ~1-3 sentences per turn. Default
shape and the most common one for podcasts.

### Director's Notes

Warm, conversational pace. Keep the energy friendly but not hyper.
Do not read these notes aloud; they are production guidance.

### Transcript

Speaker A: [ton: warm] Welcome back to the show. I'm glad you're here on a Thursday morning — it means you either love mornings or you're avoiding something harder. Either way, you picked the right episode.

Speaker B: [pace: measured] Thanks for having me. I spent the week reading about the history of standard time zones, which sounds dull until you realize railroads invented them to stop killing people.

Speaker A: That's a hook I was not expecting. Walk us through the short version?

Speaker B: [emphasis: mild] Short version: before 1883, every town set its own clock by solar noon. Trains from Boston and Chicago would arrive with contradictory times on the same platform. People missed connections. Occasionally, they collided.

Speaker A: [ton: curious] So standardization wasn't about tidiness — it was about not dying on the way to Cleveland.

Speaker B: Exactly. Coordination is usually invisible until its absence becomes violent.

---

## Shape: mono

Single narrator. Format every paragraph as `Mono:`. Use for
voice-overs, narrated essays, audiobook-style readings.

### Director's Notes

Calm, deliberate pace. Treat each paragraph as a beat — a small pause
between paragraphs is welcome. Lean into clarity over performance.

### Transcript

Mono: [ton: measured] Before eighteen eighty-three, every town in North America set its own clock by solar noon. Boston, Chicago, and Denver each kept their own time, and trains arriving on a single platform could disagree on the hour by a margin of forty minutes.

Mono: This was not a curiosity. It was a hazard. Conductors were issued thick books listing local time offsets for every stop on a route, and human error in those tables produced collisions, missed connections, and at least one inquest with a verdict of death by punctuation.

Mono: [emphasis: mild] So when American railroads adopted four standard time zones on November eighteenth, eighteen eighty-three, they were not optimizing for elegance. They were trying to stop killing their passengers.

Mono: Coordination is usually invisible until its absence becomes violent. Standard time was born of a quiet realization that the alternative was funerals.

---

## Shape: interview

Strict Q/A alternation. `Speaker A:` is always the interviewer,
`Speaker B:` always the interviewee. No narrator interjections, no
back-and-forth that breaks the role.

### Director's Notes

Interviewer is curious but unhurried; interviewee is precise and
slightly understated. Avoid overlapping cadences — let each turn
land.

### Transcript

Speaker A: You've been writing about pre-1883 American rail timekeeping. Why does that matter today?

Speaker B: [pace: measured] Because every town used to keep its own clock, and the railroads quietly invented standard time to stop killing people. It's the clearest historical example I know of coordination being a safety feature, not an aesthetic one.

Speaker A: How bad was it before standardization?

Speaker B: [emphasis: mild] Bad enough that conductors carried books of offsets — Boston is eight minutes ahead of New York, New York is twelve minutes ahead of Philadelphia. A typo in those tables had a body count.

Speaker A: [ton: curious] So when railroads imposed four time zones in November eighteen eighty-three, that was a public-safety act, not an act of tidiness.

Speaker B: Exactly. And the more interesting lesson is the general one: most coordination work looks invisible until you stop doing it. Then it looks like a derailment.
