# CLI surface and exit codes

Every script also answers `--help`. This file exists so `SKILL.md` does
not have to carry the tables in context on every turn.

## `scan_project.py`

| Flag | Default | Purpose |
|---|---|---|
| `--project-root <path>` | cwd | Project root to scan. |
| `--json` | off | Machine-readable output. |
| `--include-shared` / `--no-include-shared` | on | Read `.claude/settings.json` `autoMode` for adoption candidates. |
| `--check-gitignore` | off | Warn if `.claude/settings.local.json` is not covered by `.gitignore`. |

## `inspect_automode.py`

| Flag | Default | Purpose |
|---|---|---|
| `--project-root <path>` | cwd | Project root to inspect. |
| `--show-drift` | off | Compare each file's canonical bytes against the approved cache; exit 6 on drift. |
| `--json` | off | Machine-readable output. |
| `--file {user,shared,local,all}` | all | Restrict to one file. |

## `apply_automode.py`

| Flag | Default | Purpose |
|---|---|---|
| `--project-root <path>` | cwd | Project root. |
| `--mode {auto,fresh,migrate}` | auto | Pipeline mode; `auto` derives from the local file. |
| `--proposal <path>` | required for non-interactive | JSON proposal to write. |
| `--dry-run` | off | Compute the hash, write nothing, preview the rollback line. |
| `--approved-canonical-hash <sha256>` | required for non-dry-run | Gate predicate. |
| `--lint-strict` | off | Promote semantic-lint warnings to blocking (see below). |
| `--no-lint` | off | Skip the semantic lint entirely. |
| `--migrate-strategy {keep-all,drop-all,fail,interactive}` | interactive | How existing rules are folded in. |
| `--show-drift` | off | Alias delegating to `inspect_automode.py`. |
| `--model <model>` | (CLI default) | Passed to `claude auto-mode critique`. |
| `--allow-empty-critique` | off | Accept a critique that says nothing (see below). |
| `--strict-critique-sections` | off | Also validate the critique's section headers against the hardcoded contract. |
| `--allow-unknown-critique-sections` | off | Forward-compat loosening of the section check. |
| `--write-shared` | off | Phase 4 opt-in: also write `.claude/settings.json`. |
| `--hoist <rule-id>` | off | Move a rule from local to user. |
| `--repair` | off | Restore orphans and reclaim locks; mutually exclusive with every other mode. |
| `--allow-swap-file-fallback` | off | DEPRECATED no-op; the swap-file path is automatic when `--settings` is missing. |

## The semantic lint (`_lint_rules.py`)

The critique is the only check that ever reads what a rule *says*, and
it is a network-dependent external binary that has been observed
failing in prose while exiting 0 (see below); the semantic lint is a
deterministic, local check over rule content that holds whether or
not the critique answers.

By default a lint error blocks with `EXIT_VALIDATION` (2); a lint
warning prints without blocking. `--lint-strict` promotes warnings to
blocking; `--no-lint` skips the lint entirely. The lint also runs
under `--dry-run`: when it blocks there, the canonical sha256 is not
printed, so a proposal with unresolved findings cannot be approved.

| Rule | Severity | Meaning |
|---|---|---|
| AM001 | error | A conditional connective (`unless`, `if`, `without`, …) inside a `hard_deny` rule; hard_deny is never lifted, so the condition is fiction. |
| AM002 | warn | An `allow` rule and a `soft_deny` rule name the same path, glob, quoted span, or tool name; confirm the allow does not swallow the soft_deny. Blind to a bare-noun target (see "Known limits"). |
| AM003 | warn | A `hard_deny` forbids a literal the project's own tracked files contain, which usually contradicts the real workflow. |
| AM004 | error | An entry shaped like a `permissions` pattern (e.g. `Bash(git push:*)`) pasted into an autoMode section. |

### Known limits

- AM002 only sees a shared path, glob, quoted span, or known tool name.
  A bare-noun target, e.g. `allow: "Deploying to staging is allowed"`
  next to `soft_deny: "Never deploy to staging without tests"`, produces
  no finding.
- AM002 suppresses the read/write idiom: when the `allow` side names
  only read-only subcommands (`get`, `describe`, `list`, `logs`, …) and
  the `soft_deny` side names none of them, the shared tool name is a
  collision, not a conflict, and no finding fires. The subcommand is
  read positionally, the token right after the tool name, including a
  slash-separated list (`kubectl get/describe`). A rule that describes
  its subcommands instead of naming them (`Run read-only kubectl
  commands against any context`) still fires: there is nothing
  positional to extract, by design, not by oversight.
- AM001 only matches a literal conditional connective. A condition
  phrased as a relative clause (`Never delete a namespace that is not
  labelled ephemeral`) or a participle (`Never force-push to a branch
  not marked as scratch`) is invisible to it.
- AM003 scans `git ls-files` inside a git repository and a filtered
  directory walk outside one; the file set it checks a `hard_deny`
  literal against differs between the two cases.

## The critique gate has two layers

**Mandatory, version-agnostic:** the critique must actually say
something. Exit code 0 is not sufficient. The binary has been observed
exiting 0 with nothing but:

```text
Analyzing your auto mode rules…

No critique was generated. Please try again.
```

That output means the proposal was never reviewed, so it must not open
the hash gate. `apply_automode.py` fails with `EXIT_CRITIQUE_FAILED`
when the output is empty, shorter than `MIN_CRITIQUE_CHARS` of
non-whitespace text, or matches `DEGENERATE_CRITIQUE_PATTERNS`. The raw
output is archived first, so the evidence survives the failure. Pass
`--allow-empty-critique` to accept it anyway.

**Opt-in, brittle:** `--strict-critique-sections` asserts the exact set
of `##` headers. The binary renames its sections across versions, so
this stays off by default.

Every invocation archives to `.claude/.automode-history/`. On the
swap-file fallback path (see `references/critique_workflow.md`), the
archived text can quote values from your real settings, because that
path's critique runs against a copy of them with the proposal merged
in. After archiving, the skill checks whether the history directory is
covered by a `.gitignore` rule and, if not, warns on stderr with the
exact line to add.

## Exit codes

| Code | Name | Meaning |
|---|---|---|
| 0 | EXIT_OK | Success. |
| 1 | EXIT_USAGE | Missing flag, unsupported combination. |
| 2 | EXIT_VALIDATION | Proposal fails the JSON schema, or the semantic lint reports a blocking finding. |
| 3 | EXIT_CRITIQUE_FAILED | Non-zero from `claude`, empty/degenerate critique, or contract drift. |
| 4 | EXIT_PERMISSION | Filesystem permission denied. |
| 5 | EXIT_CLAUDE_CLI_MISSING | `claude` is not on PATH. |
| 6 | EXIT_DRIFT | Canonical bytes differ from the approved cache. |
| 7 | EXIT_LOCK_HELD | A live writer holds the flock. |
| 8 | EXIT_HASH_MISMATCH | `--approved-canonical-hash` differs from the computed hash. |
| 9 | EXIT_STRANDED_STATE | `.preview-orig.<pid>` orphans found. |
| 10 | EXIT_OUT_OF_BAND | `claude` version outside the heuristics range. |
