# Self-critique loop

Mandatory between writing a proposal and running the dry-run. The goal
is to hit `claude auto-mode critique` with a proposal it has nothing
left to say about, instead of discovering its objections one commit at
a time and ping-ponging with the user.

## The loop

1. **Stop.** The proposal is written. Do not run anything yet.
2. **Become the critic.** Re-read every rule as the reviewer who wants
   to reject it: `claude auto-mode critique` (flags rules that are
   ambiguous, redundant, or likely to cause false positives), the
   semantic lint (AM001-AM004), and a teammate reading the block cold.
   Think hard; this is the step that saves round-trips.
3. **Write the objections down.** One line each: rule, objection,
   severity (`major` blocks the proposal, `minor` is worth fixing,
   `nit` is optional). An unlisted objection does not count as
   considered.
4. **Rewrite.** Fix every `major` and every `minor` you agree with. For
   one you reject, keep a one-line reason: that is your answer when
   the real critique raises it.
5. **Repeat from 2** on the rewritten proposal, from scratch, not as a
   diff review: a rewrite can introduce a new overlap or ambiguity.
6. **Exit** when a full pass yields no new `major` or `minor`. Cap at
   three passes; if the third still produces majors, the problem is
   the user's intent, not the wording: stop and ask.

Then run the dry-run. Its lint output is the deterministic half of the
critique: any finding means the loop missed something, so fix it and
run one more pass before asking for the hash approval.

## What the critic checks

Per rule:

- **Ambiguous target.** "the repo", "prod", "the database": which one?
  Name the concrete repo, branch glob, namespace, bucket, domain, or
  CLI path.
- **Ambiguous action.** "touch", "mess with", "handle": say push,
  force-push, deploy, migrate, delete, send.
- **Too broad (false positives).** Would the rule block, or allow,
  something routine the project does daily? Check it against
  CLAUDE.md, AGENTS.md, CI configs, and scripts (AM003 catches only the
  literal case).
- **Too narrow (false negatives).** Does an obvious sibling escape it
  (`main` but not `master`, `push` but not `push --force-with-lease`,
  one remote but not the others)?
- **Condition in `hard_deny`** (AM001). "unless", "without", "except
  when": the condition never applies. Move the rule to `soft_deny` or
  drop the condition.
- **`allow` swallowing a `soft_deny`** (AM002, and the bare-noun case
  the lint misses). If an `allow` opens the target, the `soft_deny`
  condition is dead text.
- **Pattern syntax** (AM004). `Bash(...)`, `Read(...)`: belongs in
  `permissions`, never here.
- **Wrong section.** Trust signal written as an `allow`, preference
  written as a `hard_deny`, unconditional boundary left in `soft_deny`.
- **Rationale.** A rule with a surprising scope needs its reason in a
  trailing clause, or the next reader "fixes" it.

Across the block:

- **Redundant.** Two rules saying the same thing, or a rule restating
  what `"$defaults"` already covers in that section.
- **Contradictory.** Two rules pulling opposite ways on one target
  without an explicit precedence.
- **`"$defaults"` dropped.** Every section that lacks it loses the
  curated baseline; is that deliberate and confirmed?
- **Coverage.** Does the block say everything the project docs imply,
  and nothing they do not?

## Output

Keep the loop's working notes out of the user-facing diff. Report only:

- the number of passes run;
- the objections you rejected, with their one-line reason, so the user
  can overrule you before approving the hash.
