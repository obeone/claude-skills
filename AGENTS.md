# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Overview: Claude Agent Skills Stack

This repository implements a decentralized "Claude Agent Skills" architecture. Each skill is self-contained and provides tools, references, and validation scripts for agents.

## Execution Environment

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

## Key Paths

- `skills/<skill-name>/SKILL.md`: Main entry point for a skill.
- `skills/<skill-name>/scripts/`: Validation and analysis scripts.
- `skills/<skill-name>/assets/`: Templates and static resources.
- `skills/<skill-name>/references/`: Documentation and best practices.

## Release & Versioning

Two **decoupled** version spaces — never align one to the other:

- **Per-skill version → SemVer.** Each skill carries its own
  `metadata.version` in `SKILL.md` (e.g. `4.0.0`), bumped major/minor/patch
  according to the change in *that skill*. Independent across skills.
- **Repo release tags → CalVer.** Git tags use `vYYYY.MM.MICRO`
  (e.g. `v2026.05.0`, then `v2026.05.1` for a second release the same
  month, `v2026.06.0` the next month). A tag means "a publish happened" —
  it is **not** the version of any skill.

Tagging procedure:

1. Next tag = `v$(date +%Y.%m).<micro>` where `<micro>` is the highest
   existing `vYEAR.MONTH.*` tag + 1, or `0` if none this month. Legacy
   SemVer tags (`v4.1.0` and earlier) are ignored for this calculation.
2. Pre-checks: `main == origin/main`, target commit pushed, and
   `git rev-parse -q --verify refs/tags/<tag>` shows the tag is free.
   The `Publish Skills` workflow (trigger `v*`) is destructive if a
   published tag is rewritten.
3. Annotated + GPG-signed tag, message `vYYYY.MM.MICRO - <summary>`.
4. The `Publish Skills` workflow needs no change: `v*` still matches, the
   tag is only used as the GitHub release name, and the `.skill` filename
   strip targets the skill's SemVer in the filename, not the tag.

Transition note: the last legacy SemVer repo tag is `v4.1.0`
(helm-bjw-s-chart common-5.x release). CalVer starts from the next release.
