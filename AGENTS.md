# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Overview: Claude Agent Skills Stack

This repository implements a decentralized "Claude Agent Skills" architecture. Each skill is self-contained and provides tools, references, and validation scripts for agents.

## Execution Environment

- **Python Scripts**: Use `uv` for dependency management whenever possible. Scripts should be executable via `python <script_path>`.
- **Mandatory Requirements**:
  - All `SKILL.md` files MUST contain a YAML front-matter with `name`, `description`, and `tools`.
  - POSIX compliance: All text files must end with a newline (`\n`) and use LF line endings.

## Key Paths

- `skills/<skill-name>/SKILL.md`: Main entry point for a skill.
- `skills/<skill-name>/scripts/`: Validation and analysis scripts.
- `skills/<skill-name>/assets/`: Templates and static resources.
- `skills/<skill-name>/references/`: Documentation and best practices.
