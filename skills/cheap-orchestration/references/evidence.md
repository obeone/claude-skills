# Evidence

Every number below was measured on Claude models: Opus is the `large` tier,
Sonnet `medium`, Haiku `small`. The findings name the models that ran; the
rules they back are stated by tier.

From the cheap-orchestration benchmark (2026-10, pristine `CLAUDE_CONFIG_DIR`
installs, Opus 5.5 main loop, 277 runs on a long three-part session T4 and a
shorter three-part task T5, quality as the mean of 3 blind judge ratings out
of 5). The interactive report and the per-run dataset (313 sessions, the
first bench included) are published in the repository:
<https://github.com/obeone/claude-skills/tree/main/benchmarks/cheap-orchestration>.

| Finding | Number | Rule it backs |
|---|---|---|
| v1 routed to OMC agents (`executor`, `writer`, `test-engineer`) that do not exist without OMC; every launch fell back to `general-purpose`, which inherits Opus | 0 OMC types requested in X/Z runs | Name only agents pinned in their own file; never pass `model` |
| Hooks (label gate, router, nudges) | gate 0 denials; router no effect; nudges +0.16 $ and +10k context on T5 | No hooks; the rule text carries the effect |
| Rule #0 alone, long session | -38% cost | Delegate by default |
| All-Opus crew, long session | -53% | Savings are mostly context isolation |
| Sonnet worker, long session | about -65% | Pin the worker to the medium tier |
| Short task, Opus subagents | about 0% | Never a large-tier subagent on a short task |
| Short task, pinned cheaper agents | about -40% | Delegate short tasks too |
| Quality, any delegation | about -0.3 of 5, no 5/5 grades; same with an Opus worker | Stakes branch: write it yourself |
| Guard rules (order, tests, references) | cost about 0; test lines 154 vs 97 without; reference re-check 8/8 vs 2/4 | Keep the three guards |
| Order rule as first phrased | ignored in 3/8 runs | Phrased as "one per message, wait" |
| Haiku editors | 2.4x the output tokens per unit of Sonnet, under 3% of cost | Editor for mechanical work only |
| Scout | never used | Kept: cheap, harmless, useful outside the bench |
| v2 S (no reviewer), long session | 1.15 $ vs 3.22 $ (-64%), quality 3.83 vs 4.31 (-0.47, p=.0007) | Delegation still costs quality |
| v2 R (final Opus reviewer), long session | 1.36 $ (-58%), quality 4.04 (-0.26, p=.0035); vs S +0.21 (p=.06) for +0.20 $; first delegated 5/5 | Reviewer by default on long multi-part sessions |
| v2 R, short task | 0.74 $ vs S 0.50 $ (+49%), quality 4.12 = S | No reviewer on short tasks |
| t4-R-r3 failed the docstrings-only check | a Haiku editor's script turned `def arity(self) -> int: ...` into a docstring-only body (the `...` dropped); the reviewer had that line in its `git diff` and missed it | Reviewer checks restrictions first, restores, never touches code otherwise |

## Dropped from v1

- The SessionStart preload, the label gate, the delegation router and the
  `delegation-nudge.sh` / `[DELEGATION NOTICE]` nudges. The label itself
  (the model name in brackets at the start of each `description`) came back in 2.1.0 as
  rule text; only the hook that enforced it stays dropped (0 denials).
- The OMC routing matrix and the fan-out pseudo-calls naming OMC agents.
- Review and verification agents by default: they cost 0.2 to 1.3 $ each
  with no measured quality gain. Exception measured in v2: one final
  `reviewer` pass on long multi-part sessions (variant R).
- Models above the large tier: still no place in delegation.

## Built-in agents (Claude Code)

`general-purpose`, `Explore`, `Plan` and `claude` run with `model: inherit`,
so under an Opus session they bill Opus. The optional deny list in
`settings.json` (`Agent(general-purpose)`, `Agent(Explore)`, `Agent(Plan)`,
`Agent(claude)`) blocks those four targets and nothing else: any other
user-defined or plugin agent stays callable and can still inherit the session
model, so the list is not a cost boundary on its own. Trade-off: `Explore`
(fast read-only search) and `Plan` are gone, and any skill or plugin that
launches `general-purpose` stops working until the deny is lifted.
