# CLAUDE.md

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

To cut a release: pick the next micro for the current month (`v$(date +%Y.%m).N`, N starting at 0 and incrementing per release that month), confirm `main` matches `origin/main` and the tag is free, then push an annotated GPG-signed tag. The `Publish Skills` workflow triggers on `v*` and builds the `.skill` assets. Legacy SemVer repo tags (`v4.1.0` and earlier) are ignored when computing the next micro.

## Key Design Decisions

- **Pin runtimes, not the OS**: `python:3.12-slim`, not `python:3.12-slim-bookworm`, so security updates land.
- **Non-root users, UID/GID > 10000**: avoids clashes with host users across orchestration platforms.
- **BuildKit directive**: Dockerfiles start with `# syntax=docker/dockerfile:1`.
- **Compose V2**: no `version:` field, never `container_name:` (it blocks scaling).
- **bjw-s common library v4+**: charts use `https://bjw-s-labs.github.io/helm-charts`.
