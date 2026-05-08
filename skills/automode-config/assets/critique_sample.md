# Critique of Custom Rules

This is a hand-crafted v0.1.0 fixture demonstrating the section
structure the skill enforces via Path (b) contract drift. The two
required headers are `## Major issues` and `## Smaller issues`. The
prose between them is informational only; severity counts come from
the `### N.` walker (with `**N.**` fallback) and feed nothing but the
informational printout.

A v0.2.0 follow-up will replace this fixture with output captured from
the real `claude auto-mode critique` binary.

## Major issues

### 1. `Bash(*)` allow rule is silently dropped

The classifier rejects unbounded shell rules at load time. This rule
appears in `autoMode.allow` and is removed before any session runs;
the user sees no warning unless this skill surfaces it. Replace with
explicit command-prefix rules such as `Bash(git status:*)`.

### 2. `autoMode` block written to shared `.claude/settings.json`

The classifier ignores the `autoMode` key when it is read from the
shared (committed) settings file. Teammates who clone the repo will
not get the rules listed there. Move the block to
`.claude/settings.local.json` (per-user-per-project, gitignored) or
`~/.claude/settings.json` (per-user-global) to take effect.

### 3. `Read(~/.ssh/*)` allow rule

Reading SSH private keys is never auto-approved. The classifier drops
this rule on entry; even if it were honoured, exposing private keys
to an autonomous agent is not a configuration this skill will
canonicalize. Remove the rule.

## Smaller issues

### 1. Missing `$defaults` sentinel in `autoMode.environment`

The `environment` array does not include `"$defaults"`. The classifier
substitutes Anthropic-curated built-in trust signals only when the
sentinel is present. Without it, the user gets only their explicit
signals and loses the curated baseline.

### 2. Duplicate rule `Bash(git status:*)` in allow list

The allow list contains the same prefix twice. Not a hard error, but
the duplicate inflates the diff and obscures intent. Deduplicate.

### 3. `Network(loopback)` lacks port scope

The classifier requires `Network(loopback)` rules to declare a port or
port range. The bare form is dropped on entry. Replace with
`Network(loopback:8080)` or a range such as `Network(loopback:3000-3999)`.
