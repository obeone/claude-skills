# automode-config

A Claude Code skill that authors, validates, and migrates project-level
`autoMode` permission blocks. The skill models the **four official
autoMode sections** — `environment`, `allow`, `soft_deny`, `hard_deny`,
all arrays of prose rules with `$defaults` per section — gates every
write behind `claude auto-mode critique`, and writes atomically under
per-file flock with a sha256 hash gate.

Primary target: `.claude/settings.local.json` (per-user-per-project,
gitignored, classifier-read). The skill **reads** the user baseline
(`~/.claude/settings.json`) and the shared project file
(`.claude/settings.json`) for adoption candidates, but never writes to
either silently.

> **Source of truth:** `references/automode_doc_bible.md` is the
> distilled reference this skill aligns with. When the docs and the
> skill code disagree, the bible wins; fix the code.

## Why

`autoMode` is the configuration for the classifier that gates tool
calls when the user is in `auto` permission mode. Hand-editing the
JSON is error-prone:

- It's easy to land a rule under a non-existent section like `ask` or
  the legacy `deny` (the official sections are `environment`, `allow`,
  `soft_deny`, `hard_deny`).
- The `$defaults` sentinel is per-section, and dropping it from any
  one section silently loses Anthropic's curated baseline for that
  section — including built-in `soft_deny` rules for force-push,
  `curl | bash`, and production deploys.
- It's tempting to write `Bash(...)` patterns: those are `permissions`
  syntax, **not** `autoMode`. autoMode rules are prose
  ("Pushing to feature branches is allowed: …").
- The shared file `.claude/settings.json` ignores `autoMode` for
  permission classification — but nothing warns you about the mismatch.
- The `claude auto-mode critique` invocation is the canonical
  validation gate, but its CLI has version-dependent quirks (no
  `--settings` on older builds, drifting section headers).

The skill folds all of that into a six-phase pipeline with reproducible
canonical bytes, so applying or migrating an `autoMode` block becomes a
single command instead of five careful manual steps.

## Requirements

- **Claude Code 2.1.83+** (auto mode itself; the docs do not currently
  pin a separate version for `hard_deny`).
- **`uv`** on `$PATH` ([install](https://astral.sh/uv/)). Each script
  declares its dependencies inline as a [PEP 723](https://peps.python.org/pep-0723/)
  header — no `pip install` step.
- A **`claude` binary** on `$PATH` (or `CLAUDE_CLI_BIN=/path/to/claude`)
  for the critique gate.

## Install

### From a release bundle

```bash
mkdir -p ~/.claude/skills
curl -L https://github.com/obeone/claude-skills/releases/latest/download/automode-config.skill \
  -o /tmp/automode.skill
rm -rf ~/.claude/skills/automode-config
unzip -q /tmp/automode.skill -d ~/.claude/skills/
rm /tmp/automode.skill
```

For a project-scoped install, drop `~/.claude/skills/` for `.claude/skills/`.

### From source

```bash
git clone https://github.com/obeone/claude-skills.git
cp -R claude-skills/skills/automode-config ~/.claude/skills/
```

### Verify

```bash
head -5 ~/.claude/skills/automode-config/SKILL.md
# expect: name: automode-config / metadata.version: 0.5.0 (or higher)
```

## Usage

The skill ships three Python entry points; `uv run` resolves their
inline dependencies on first invocation.

```bash
# Inspect what the three settings files currently say.
uv run skills/automode-config/scripts/inspect_automode.py

# Detect drift between local file and the approved cache (exit 6 on drift).
uv run skills/automode-config/scripts/inspect_automode.py --show-drift

# Scan the project for adoption candidates and trust signals.
uv run skills/automode-config/scripts/scan_project.py

# Dry-run a proposal. Prints canonical bytes + sha256 to use as the gate.
uv run skills/automode-config/scripts/apply_automode.py \
  --proposal proposal.json --mode fresh --dry-run

# Commit. The hash from --dry-run becomes the gate predicate.
uv run skills/automode-config/scripts/apply_automode.py \
  --proposal proposal.json --mode fresh \
  --approved-canonical-hash <sha256-from-dry-run>
```

A minimal proposal — note that all values are prose strings, not
`Tool(...)` patterns:

```json
{
  "autoMode": {
    "environment": [
      "$defaults",
      "Source control: github.com/acme-corp and all repos under it."
    ],
    "allow": ["$defaults"],
    "soft_deny": [
      "$defaults",
      "Never run database migrations outside the migrations CLI."
    ],
    "hard_deny": [
      "$defaults",
      "Never force-push to main or release/* branches."
    ]
  }
}
```

The agent-driven workflow is documented in `SKILL.md` (the calling agent
reads `CLAUDE.md` / `AGENTS.md`, applies judgment, then emits the
proposal JSON that flows through the same pipeline).

## What it gives you

- **Four-section schema enforcement.** Only `environment`, `allow`,
  `soft_deny`, `hard_deny` are accepted; legacy `deny` migrates to
  `soft_deny` and `ask` is dropped with a warning. `--migrate-strategy
  drop-all` resets all rule lists and preserves `["$defaults"]` in
  `environment`.
- **Atomic, gated writes.** Every commit goes through canonical bytes
  → sha256 → `--approved-canonical-hash` predicate → flock-protected
  `O_EXCL` → `os.replace`. Five rolling backups per file. Rollback line
  printed at end of Phase 3.
- **Critique as the validation gate.** `claude auto-mode critique` is
  invoked once per commit; exit code 0 is the contract. The raw output
  is archived to `.claude/.automode-history/critique-<UTC>.md` for audit.
- **Capability auto-detection.** When the CLI lacks `--settings`, the
  skill swaps `~/.claude/settings.json` transiently with signal-handler
  restore — no opt-in flag, no surprise prompt.
- **Stranded-state recovery.** `--repair` reclaims stale flocks and
  restores any orphaned `.preview-orig.<pid>` sentinels.

## Layout

```
skills/automode-config/
├── SKILL.md            # Agent-facing entry point (4-section model, six phases)
├── README.md           # This file (user-facing intro)
├── scripts/
│   ├── apply_automode.py     # Commit pipeline (Phase 0-4)
│   ├── inspect_automode.py   # Three-file inspection + drift gate
│   └── scan_project.py       # Adoption candidates + trust signals
├── assets/             # Heuristics YAML, fixtures, sample outputs
├── references/         # Bible, mental model, canonicalization, recovery, verification
└── tests/              # 200+ pytest cases — full pipeline + canonicalization
```

## Deeper documentation

- `references/automode_doc_bible.md` — **start here.** Distilled from
  the official Claude Code docs; the source of truth this skill aligns
  with.
- `SKILL.md` — agent-facing entry point with the full decision tree.
- `references/mental_model.md` — three files, four sections, six phases.
- `references/three_files.md` — per-file gotchas.
- `references/canonicalization.md` — byte contract and idempotency.
- `references/critique_workflow.md` — `--settings` probe, automatic
  swap-file, contract drift.
- `references/recovery.md` — backups, `--repair`, stranded state.
- `references/verification.md` — acceptance predicates with measurement
  commands.

## Status

`metadata.version: 0.5.0` (pre-1.0; see `SKILL.md` for the v1.0
roadmap).

## License

MIT — see the repository [LICENSE](../../LICENSE).
