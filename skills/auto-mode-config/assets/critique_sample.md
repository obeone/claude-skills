# Critique of Custom Rules

## Major issues

### 1. `Bash(*)` in `allow` defeats the classifier

The rule `Bash(*)` in `permissions.allow` matches every shell command,
which means the auto-mode classifier never gets a chance to weigh in on
destructive operations such as `rm -rf`, `curl | sh`, or commands that
exfiltrate credentials. Auto mode silently drops this rule on entry,
but its presence here suggests the user expects it to apply, which can
mask the gap between intent and behaviour. Replace it with narrowly
scoped allow rules (for example `Bash(git status:*)`) or move it to
`autoMode.allow` if the intent is genuinely to opt out of classification
for shell commands.

### 2. Environment claim contradicts the project layout

The environment entry "I am the only user of this machine and any
command should be considered safe" is too broad to be actionable. The
classifier interprets environment lines as factual context about the
host and the project, and a blanket trust statement will lead it to
under-rate risk on commands that touch files outside the project tree
or send data over the network. Narrow the claim — for example, "Network
calls in this repo only go to 127.0.0.1" — so the model can apply it
selectively.

### 3. Missing `$defaults` sentinel in `soft_deny`

`autoMode.soft_deny` is set but does not contain `"$defaults"`, which
means the user has unintentionally opted out of the Anthropic-curated
soft-deny list. Operations like `WebFetch(*)` or `Bash(curl ... | sh)`
that would normally produce a soft-deny prompt will pass through
unchallenged. Add `"$defaults"` as the first entry to inherit the
shipped baseline and append project-specific extensions afterwards.

## Smaller issues

### 1. Duplicated allow patterns

`Bash(git status)` and `Bash(git status:*)` both appear in `allow`.
The colon-suffixed form already covers the bare command, so the
unsuffixed entry is redundant noise that makes the rule list harder to
audit. Drop the duplicate.

### 2. Wide-open `WebFetch(domain:*)` in allow

`WebFetch(domain:*)` allows fetches against any host, which the
classifier interprets as user-asserted trust in arbitrary URLs. Scope
it to the domains you actually use (for example `WebFetch(domain:
docs.python.org)`) or move it to `autoMode.allow` if the looseness is
intentional under auto mode only.

### 3. `Agent(*)` allow entry is silently ignored

`Agent(*)` in `allow` is in the auto-mode dropped-rules list and will
not take effect once auto mode is engaged. Either remove it (the
default `$defaults` already covers reasonable Agent usage) or replace
it with a specific Agent name such as `Agent(executor)`.
