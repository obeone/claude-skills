# AGENTS.md

Canonical project instructions for coding agents. Maintain shared guidance here.

Guidance for Claude Code (claude.ai/code) when working in this repository.

## Repository Overview

The **Claude Agent Skills Stack**: a collection of self-contained skills, each bundling the tools, references, and validation scripts an autonomous agent needs to operate independently.

## Architecture

```text
skills/<skill-name>/
├── SKILL.md          # Entry point with YAML front-matter (name, description, metadata.version)
├── scripts/          # Python validation and analysis tools
├── assets/           # Templates and static resources
└── references/       # Documentation and best practices
```

### Current skills

| Skill                     | Entry point                                 | Validators                                                              |
| :------------------------ | :------------------------------------------ | :--------------------------------------------------------------------- |
| dockerfile-best-practices | `skills/dockerfile-best-practices/SKILL.md` | `analyze_dockerfile.py`, `analyze_compose.py`                          |
| helm-bjw-s-chart          | `skills/helm-bjw-s-chart/SKILL.md`          | `validate_chart.py`                                                    |
| automode-config           | `skills/automode-config/SKILL.md`           | `scan_project.py`, `inspect_automode.py`, `apply_automode.py --dry-run` |
| apple-shortcuts           | `skills/apple-shortcuts/SKILL.md`           | `validate-shortcut.py`, `inspect-shortcut.py`, `list-app-intents.py`   |

> Historical: the skill once named `helm-chart-generator` became `helm-bjw-s-chart` (renamed in v3.0.0). Update any lingering reference to the old name (directory, asset filename, or skill name).

## Commands

Every entry-point script runs via `uv run` and declares its dependencies inline as a [PEP 723](https://peps.python.org/pep-0723/) header (`# /// script` block), so `uv run <script>` resolves and caches them with no `requirements.txt` step.

```bash
# Dockerfile / Compose analysis
uv run skills/dockerfile-best-practices/scripts/analyze_dockerfile.py <path/to/Dockerfile>
uv run skills/dockerfile-best-practices/scripts/analyze_compose.py <path/to/compose.yaml>

# Helm bjw-s chart validation
uv run skills/helm-bjw-s-chart/scripts/validate_chart.py <path/to/chart/>

# autoMode: inspect the three settings files, scan for adoption candidates
uv run skills/automode-config/scripts/inspect_automode.py
uv run skills/automode-config/scripts/scan_project.py
```

autoMode proposals flow through a dry-run (which prints the canonical sha256) then a hash-gated commit:

```bash
uv run skills/automode-config/scripts/apply_automode.py --proposal proposal.json --mode auto --dry-run
uv run skills/automode-config/scripts/apply_automode.py --proposal proposal.json --mode auto --approved-canonical-hash <sha256>
```

Natural-language editing is the `/automode-edit` slash command (e.g. `add a hard_deny rule that forbids pushing to main`). Full contract: `skills/automode-config/commands/automode-edit.md`.

## Mandatory Requirements

1. **SKILL.md front-matter** needs `name`, `description`, and `metadata.version`:
   ```yaml
   ---
   name: my-skill
   description: "Skill description"
   metadata:
     version: "1.0.0"
   ---
   ```
2. **POSIX text**: every text file ends with a newline (`\n`) and uses LF line endings.
3. **Python via uv**: use `uv` for dependency management.

## Release and Versioning

Two version spaces, kept decoupled:

- **Per-skill `metadata.version` is SemVer**, bumped for changes to that one skill.
- **Repo release tags are CalVer** (`vYYYY.MM.MICRO`, e.g. `v2026.06.1`). A tag means "a publish happened", not a skill version.

To cut a release, run `uv run scripts/release.py` locally (`--dry-run` to preview). It tags `origin/main` with the next micro for the current month (`v$(date +%Y.%m).N`, N starting at 0; legacy SemVer tags such as `v4.1.0` are ignored), as an annotated GPG-signed tag, and pushes it. It does nothing when `skills/` is unchanged since the last tag (`--force` overrides), so it is safe to run on a schedule after Dependabot auto-merges. `scripts/release-agent.sh` wraps it for a weekly local launchd job: headless Claude follows `scripts/release-agent.md` to write the summary, watch `Publish Skills`, add release highlights, and notify over ntfy. The `Publish Skills` workflow triggers on `v*` and builds the `.skill` assets.

## Key Design Decisions

- **Pin runtimes, not the OS**: `python:3.12-slim`, not `python:3.12-slim-bookworm`, so security updates land.
- **Non-root users, UID/GID > 10000**: avoids clashes with host users across orchestration platforms.
- **BuildKit directive**: Dockerfiles start with `# syntax=docker/dockerfile:1`.
- **Compose V2**: no `version:` field, never `container_name:` (it blocks scaling).
- **bjw-s common library v4+**: charts use `https://bjw-s-labs.github.io/helm-charts`.

## Additional agent and contributor instructions

This file provides guidance to agents when working with code in this repository.

### Overview: Claude Agent Skills Stack

This repository implements a decentralized "Claude Agent Skills" architecture. Each skill is self-contained and provides tools, references, and validation scripts for agents.

### Execution Environment

- **Python Scripts**: Use `uv` for dependency management whenever possible. Scripts should be executable via `python <script_path>`.
- **Mandatory Requirements**:
  - All `SKILL.md` files MUST contain a YAML front-matter with `name`, `description`, and `tools` (as a YAML list).
  - POSIX compliance: All text files must end with a newline (`\n`) and use LF line endings.
  - Example front-matter:
    ```yaml
    ---
    name: my-skill
    description: "Skill description"
    tools:
      - Read
      - Write
    ---
    ```

### Key Paths

- `skills/<skill-name>/SKILL.md`: Main entry point for a skill.
- `skills/<skill-name>/scripts/`: Validation and analysis scripts.
- `skills/<skill-name>/assets/`: Templates and static resources.
- `skills/<skill-name>/references/`: Documentation and best practices.

### Release & Versioning

Two **decoupled** version spaces — never align one to the other:

- **Per-skill version → SemVer.** Each skill carries its own
  `metadata.version` in `SKILL.md` (e.g. `4.0.0`), bumped major/minor/patch
  according to the change in *that skill*. Independent across skills.
- **Repo release tags → CalVer.** Git tags use `vYYYY.MM.MICRO`
  (e.g. `v2026.05.0`, then `v2026.05.1` for a second release the same
  month, `v2026.06.0` the next month). A tag means "a publish happened" —
  it is **not** the version of any skill.

Tagging procedure, automated by `uv run scripts/release.py` (run locally so
the tag is GPG-signed; `--dry-run` previews, `--force` releases even when
`skills/` is unchanged since the last tag, otherwise it is a no-op):

1. Next tag = `v$(date +%Y.%m).<micro>` where `<micro>` is the highest
   existing `vYEAR.MONTH.*` tag + 1, or `0` if none this month. Legacy
   SemVer tags (`v4.1.0` and earlier) are ignored for this calculation.
2. Pre-checks: the tag targets the fetched `origin/main` commit (the local
   `main` is never used), and `git ls-remote --tags origin` shows the tag
   is free.
   The `Publish Skills` workflow (trigger `v*`) is destructive if a
   published tag is rewritten.
3. Annotated + GPG-signed tag, message `vYYYY.MM.MICRO - <summary>`.
4. The `Publish Skills` workflow needs no change: `v*` still matches, the
   tag is only used as the GitHub release name, and the `.skill` filename
   strip targets the skill's SemVer in the filename, not the tag.

Transition note: the last legacy SemVer repo tag is `v4.1.0`
(helm-bjw-s-chart common-5.x release). CalVer starts from the next release.
