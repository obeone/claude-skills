# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is the **Claude Agent Skills Stack** - a collection of self-contained skills that provide tools, references, and validation scripts for autonomous agents. Each skill bundles everything needed to operate independently.

## Architecture

```text
skills/<skill-name>/
├── SKILL.md          # Entry point with YAML front-matter (name, description, tools)
├── scripts/          # Python validation and analysis tools
├── assets/           # Templates and static resources
└── references/       # Documentation and best practices
```

### Current Skills

| Skill                     | Entry Point                                                    | Validators                                    |
| :------------------------ | :------------------------------------------------------------- | :-------------------------------------------- |
| dockerfile-best-practices | `skills/dockerfile-best-practices/SKILL.md`                    | `analyze_dockerfile.py`, `analyze_compose.py` |
| helm-chart-generator      | `skills/helm-chart-generator/helm-chart-generator/SKILL.md`    | `validate_chart.py`                           |

## Commands

### Dockerfile Analysis

```bash
# Analyze a Dockerfile for anti-patterns
python skills/dockerfile-best-practices/scripts/analyze_dockerfile.py <path/to/Dockerfile>

# Analyze a Docker Compose file
python skills/dockerfile-best-practices/scripts/analyze_compose.py <path/to/compose.yaml>
```

### Helm Chart Validation

```bash
# Validate a bjw-s common library chart
python skills/helm-chart-generator/helm-chart-generator/scripts/validate_chart.py <path/to/chart/>
```

### Dependencies

Scripts use `uv` for Python execution. The `analyze_compose.py` and `validate_chart.py` scripts require `pyyaml`.

## Mandatory Requirements

1. **SKILL.md YAML front-matter**: Every skill must have `name`, `description`, and `tools` fields
2. **POSIX compliance**: All text files must end with newline (`\n`) and use LF line endings
3. **Python via uv**: Use `uv` for dependency management when possible

## Key Design Decisions

- **Runtime pinning over OS pinning**: Pin runtime versions (e.g., `python:3.12-slim`) not OS versions (e.g., `python:3.12-slim-bookworm`) to receive security updates
- **Non-root users with UID/GID >10000**: Avoid conflicts with host system users across orchestration platforms
- **BuildKit syntax directive**: Always start Dockerfiles with `# syntax=docker/dockerfile:1`
- **Compose V2**: No `version:` field, never use `container_name:` (prevents scaling)
- **bjw-s common library v4+**: Helm charts use `https://bjw-s-labs.github.io/helm-charts`
