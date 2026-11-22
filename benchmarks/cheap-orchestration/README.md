# Cheap Orchestration Bench

**Is handing code to cheaper models worth it? Less than half the price, a
little less polish.**

The benchmark behind the
[cheap-orchestration](../../skills/cheap-orchestration/) skill: 313 Claude
Code sessions, 607.50 $ of API usage, 18 configurations compared on cost,
judged quality, pass rate, context and wall time. Everything is published
here: the interactive report and the per-run dataset.

---

## 🎯 Headline results

Long three-part session (T4), Opus 5.5 main loop:

| Setup | Cost | vs no delegation | Quality (of 5) |
|---|---|---|---|
| No delegation | 3.22 $ | baseline | 4.31 |
| Sonnet worker | 1.15 $ | -64% | 3.83 |
| Sonnet worker, final Opus review | 1.36 $ | -58% | 4.04 |

Most of the saving comes from context isolation: each subagent starts from a
small fresh context instead of dragging the whole session along. Delegation
costs about 0.3 of a point of judged quality, and a final review on a long
session recovers about half of that gap. On a short task the review adds 49%
to the cost and no quality.

---

## 👀 View the report

The report is three interactive pages that load `data/runs.json`. Browsers
block that when a page is opened straight from disk, so serve the folder:

```bash
cd benchmarks/cheap-orchestration && python3 -m http.server 8000
```

Then open <http://localhost:8000/>.

| Page | File | Content |
|---|---|---|
| Lab | `Main.dc.html` | The findings, a duel between any two configurations, cost and context leaderboards |
| Explorer | `Explorer.dc.html` | Every run, by task, bench and metric |
| Critique | `Critique.dc.html` | Limits of the benchmark, what the critique found, the first bench |

The pages are in French and English (switch at the top right). They are the
export of the original report, unchanged except for the path of the dataset.

---

## 🧪 Method

- **Tasks**: T4 is a long session in three ordered parts, T5 a shorter
  three-part task. T1 to T3 are small tasks from the first bench only.
- **Benches**: each bench compares a few configurations against a control
  run in the same conditions.
- **Quality**: mean of up to three blind judge ratings out of 5 (`judge3`).
  The first bench has a single rating (`judge`).
- **Pass**: the task's own acceptance check. T4 was re-scored with a stricter
  check (`passed2`), used when present.
- **Models**: Opus 5.5 main loop, Sonnet 5.5 and Haiku (4.5 in the first
  bench, 5.5 afterwards) as subagents.

| Bench | Runs | Configurations | Conditions |
|---|---|---|---|
| `orig` | 145 | A to I | First bench, run in the author's real environment |
| `clean` | 48 | V, X, Z | Pristine installs |
| `ideal` | 32 | W, Y | Pinned crew against its control |
| `guarded` | 32 | W, Y, Q | Pinned crew with and without the three guard rules |
| `opuscrew` | 20 | W, O | Worker on Opus instead of Sonnet |
| `v2` | 36 | W, S, R | The v2 rule, with and without the final reviewer |

---

## 🧩 Configurations

| | Name | What it is |
|---|---|---|
| A | Full Stack | The author's real setup: everything on, OMC hooks included |
| B | Soft Note | A soft delegation note, no hooks |
| C | Bare | No delegation guidance: the control of the first bench |
| D | Router | Soft note and a prompt router |
| E | Preload | Soft note and the skill preloaded at start |
| F | Rule Zero | Rule #0 (delegate before doing it yourself) and the preloaded skill |
| G | Gatekeeper | Preload and a gate denying any subagent without a model label |
| H | Nudger | Preload and mid-session delegation nudges |
| I | Zero Gate | Rule Zero and the label gate |
| V | Vanilla | Pristine Claude Code, nothing installed: the control |
| X | Clean Stack | Full cheap-orchestration v1 in a pristine install: skill, hooks and Rule #0 |
| Z | Clean Zero | Only the Rule #0 section and the SessionStart preload |
| W | Vanilla Twin | Second vanilla control, run in the time window of the later benches |
| Y | Pinned Crew | Rule #0 naming three agents with pinned models (scout and editor on Haiku, worker on Sonnet), built-in agents denied, no hooks |
| Q | Guarded Crew | Pinned Crew plus three rules: task order, one test per requirement, `path:line` re-check |
| O | Opus Crew | Guarded Crew with the worker pinned to Opus instead of Sonnet |
| S | Sized Crew | cheap-orchestration v2: agents pinned in their own definition, decision rule by size and stakes, binding order, guards, no hooks |
| R | Reviewed Crew | Sized Crew plus one final Opus reviewer pass |

---

## 📊 Results by configuration

Means over every run of the configuration, all benches together. Cost in
dollars, wall time in minutes.

### T4, long session

| | Configuration | Runs | Cost | Quality | Pass | Wall |
|---|---|---|---|---|---|---|
| A | Full Stack | 11 | 4.25 | 4.27 | 11/11 | 29.1 |
| B | Soft Note | 3 | 3.93 | 4.00 | 3/3 | 8.5 |
| C | Bare | 3 | 5.01 | 4.33 | 3/3 | 10.1 |
| D | Router | 3 | 4.63 | 4.00 | 3/3 | 27.3 |
| E | Preload | 11 | 4.14 | 4.18 | 11/11 | 32.6 |
| F | Rule Zero | 8 | 4.46 | 4.50 | 8/8 | 23.8 |
| G | Gatekeeper | 8 | 3.94 | 4.38 | 8/8 | 24.3 |
| H | Nudger | 8 | 4.80 | 4.38 | 8/8 | 31.7 |
| I | Zero Gate | 8 | 3.96 | 4.25 | 8/8 | 38.7 |
| V | Vanilla | 8 | 3.10 | 4.25 | 8/8 | 25.7 |
| X | Clean Stack | 8 | 1.89 | 3.88 | 8/8 | 31.6 |
| Z | Clean Zero | 8 | 1.92 | 3.83 | 8/8 | 32.4 |
| W | Vanilla Twin | 16 | 3.28 | 4.33 | 16/16 | 32.6 |
| Y | Pinned Crew | 12 | 1.21 | 3.86 | 12/12 | 18.7 |
| Q | Guarded Crew | 8 | 1.06 | 4.00 | 8/8 | 23.5 |
| O | Opus Crew | 8 | 1.51 | 4.00 | 8/8 | 27.9 |
| S | Sized Crew | 8 | 1.15 | 3.83 | 8/8 | 24.2 |
| R | Reviewed Crew | 8 | 1.36 | 4.04 | 7/8 | 34.1 |

### T5, short task

| | Configuration | Runs | Cost | Quality | Pass | Wall |
|---|---|---|---|---|---|---|
| A | Full Stack | 8 | 1.57 | 4.88 | 8/8 | 6.6 |
| B | Soft Note | 8 | 1.33 | 4.50 | 8/8 | 4.4 |
| C | Bare | 8 | 1.39 | 4.75 | 8/8 | 4.6 |
| E | Preload | 8 | 1.33 | 4.75 | 8/8 | 4.2 |
| F | Rule Zero | 8 | 1.45 | 4.75 | 8/8 | 4.7 |
| G | Gatekeeper | 8 | 1.49 | 4.62 | 8/8 | 4.7 |
| H | Nudger | 8 | 1.49 | 4.75 | 8/8 | 4.6 |
| I | Zero Gate | 8 | 1.48 | 4.50 | 8/8 | 7.9 |
| V | Vanilla | 8 | 0.89 | 4.58 | 8/8 | 3.2 |
| X | Clean Stack | 8 | 0.88 | 4.29 | 8/8 | 3.5 |
| Z | Clean Zero | 8 | 0.93 | 4.29 | 8/8 | 3.9 |
| W | Vanilla Twin | 16 | 0.87 | 4.46 | 16/16 | 3.3 |
| Y | Pinned Crew | 12 | 0.50 | 4.19 | 12/12 | 3.1 |
| Q | Guarded Crew | 8 | 0.52 | 4.21 | 8/8 | 10.1 |
| O | Opus Crew | 8 | 0.90 | 4.42 | 8/8 | 5.9 |
| S | Sized Crew | 8 | 0.50 | 4.12 | 8/8 | 2.4 |
| R | Reviewed Crew | 8 | 0.74 | 4.12 | 8/8 | 5.9 |

Configurations A to I ran in the first bench, in the author's real
environment with its hooks and plugins, so their costs do not compare with
the later ones. Compare a configuration with
the control of its own bench: the report does this for you.

---

## 🗂️ Dataset

[`data/runs.json`](./data/runs.json) is a JSON array with one object per
session.

| Field | Meaning |
|---|---|
| `id` | Run identifier, `<task>-<configuration>-r<repetition>` |
| `task`, `v`, `rep`, `bench` | Task, configuration letter, repetition, bench |
| `cost` | Total cost of the session in dollars |
| `m` | Per model family: input, output, cache read and cache write tokens, and cost |
| `hv` | Exact Haiku model identifiers seen in the run |
| `turns_all`, `sub` | Turns over the whole session, subagents launched |
| `mturns` | A second turn counter kept from the collector; the report does not use it |
| `ctx` | Peak context of the main loop, in tokens |
| `wall` | Wall time in seconds |
| `judges`, `judge3`, `judge` | Individual blind ratings, their mean, the single rating of the first bench |
| `passed`, `passed2`, `score2` | Acceptance check, stricter T4 re-check and its score |

`turns` is the legacy turn count of the last resumed segment only; use
`turns_all`.

---

## ⚠️ Limits

- One provider: every number was measured on Claude models. Nothing here is
  verified on GPT or Gemini.
- Two task shapes carry the conclusions, 8 to 16 runs per configuration.
- Quality is a judge rating, not a defect count.
- The harness that produced the runs is not published: its working directory
  no longer exists. What remains is this report and the dataset.

The Critique page goes through the limits in detail.

---

## 📄 License

MIT, see the repository [LICENSE](../../LICENSE).

Made by Grégoire Compagnon ([obeone](https://github.com/obeone))
