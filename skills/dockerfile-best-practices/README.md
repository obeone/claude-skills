# dockerfile-best-practices

A Claude Code skill that creates and optimizes Dockerfiles with modern
BuildKit features — multi-stage builds, cache mounts, secret mounts,
non-root users — and analyzes existing Dockerfiles and Compose files
for anti-patterns.

The skill ships language templates (Python/uv, Node.js, Go, Rust, PHP,
Debian) and two static analyzers covering the most common Docker and
Compose mistakes.

## Why

Hand-writing production-grade Dockerfiles requires juggling a long
checklist: BuildKit syntax directive, runtime-only version pinning,
per-package-manager cache mounts, `--mount=type=secret` instead of
`ARG SECRET`, non-root UID/GID > 10000, `COPY --chown` instead of
separate `RUN chown`, OCI labels, healthchecks. Most images get one or
two of those right and silently leak the rest.

Compose V2 adds its own set of footguns: a stale `version:` field that
warns on every run, `container_name:` that blocks scaling, bare
`depends_on` that doesn't actually wait for the upstream to be healthy.

This skill folds the full ruleset into a single workflow with ready-to-
copy templates and analyzer scripts that flag anti-patterns before they
ship.

## Requirements

- **Claude Code** (or any agent that can read `SKILL.md`).
- **`uv`** on `$PATH` ([install](https://astral.sh/uv/)). Both analyzer
  scripts declare their dependencies inline as a
  [PEP 723](https://peps.python.org/pep-0723/) header — no `pip install`
  step.
- **Docker with BuildKit** (Docker 23+ enables it by default) if you
  want to actually build the generated Dockerfiles.

## Install

### Recommended — `skills` CLI

The [`skills`](https://skills.sh/) CLI resolves the repo and drops the
bundle into the right agent directory. Run via `npx` — no global Node
install required.

```bash
# User-global (works in every project)
npx skills add obeone/claude-skills -g --skill dockerfile-best-practices -y

# Project-scoped (./.claude/skills)
npx skills add obeone/claude-skills --skill dockerfile-best-practices -y
```

Update later with `npx skills update dockerfile-best-practices`, remove
with `npx skills remove dockerfile-best-practices`. Full options:
`npx skills -h`.

### From a release bundle (fallback)

```bash
mkdir -p ~/.claude/skills
curl -L https://github.com/obeone/claude-skills/releases/latest/download/dockerfile-best-practices.skill \
  -o /tmp/dockerfile.skill
rm -rf ~/.claude/skills/dockerfile-best-practices
unzip -q /tmp/dockerfile.skill -d ~/.claude/skills/
rm /tmp/dockerfile.skill
```

For a project-scoped install, drop `~/.claude/skills/` for
`.claude/skills/`.

### From source

```bash
git clone https://github.com/obeone/claude-skills.git
cp -R claude-skills/skills/dockerfile-best-practices ~/.claude/skills/
```

## Usage

Ask Claude to write or review a Dockerfile and the skill auto-triggers.
The two analyzer scripts can also be invoked directly:

```bash
# Analyze an existing Dockerfile for anti-patterns
uv run skills/dockerfile-best-practices/scripts/analyze_dockerfile.py ./Dockerfile

# Analyze a Compose file (V2 compliance + service-level rules)
uv run skills/dockerfile-best-practices/scripts/analyze_compose.py ./compose.yaml
```

Each analyzer reports findings with severity (error / warning / info)
and references the exact `SKILL.md` rule that was violated.

## What it gives you

- **Eleven essential rules.** BuildKit syntax directive, runtime-only
  version pinning, cache mounts per package manager (pip/npm/yarn/go/
  cargo/composer/maven), APT cache setup, `--mount=type=secret`,
  non-root UID/GID > 10000, `COPY` over `ADD`, `COPY --chown`, OCI
  labels, `HEALTHCHECK`, `.dockerignore`.
- **Six language templates.** Python (with `uv`), Node.js, Go
  (multi-stage to distroless), Rust (multi-stage to distroless), PHP
  with Composer, Debian-base with APT cache. Each template bundles the
  full ruleset.
- **Compose V2 ruleset.** No `version:`, no `container_name:`, no
  `links:`, specific image tags, `depends_on` with
  `condition: service_healthy`.
- **Static analyzers.** `analyze_dockerfile.py` flags 15+ anti-patterns;
  `analyze_compose.py` enforces V2 hygiene and service-level rules.

## Layout

```
skills/dockerfile-best-practices/
├── SKILL.md          # Agent-facing entry point with all rules + templates
├── README.md         # This file (user-facing intro)
├── scripts/
│   ├── analyze_dockerfile.py  # Static analyzer for Dockerfiles
│   └── analyze_compose.py     # Static analyzer for Compose files
├── assets/           # `.dockerignore` template, base snippets
└── references/
    ├── best_practices.md       # Complete checklist with impact levels
    ├── optimization_guide.md   # BuildKit internals, caching, multi-stage
    ├── examples.md             # Real-world before/after optimizations
    ├── uv_integration.md       # Python with uv: all patterns
    └── compose_best_practices.md  # Compose V2 deep dive
```

## Deeper documentation

- `SKILL.md` — agent-facing entry point with the full workflow,
  essential rules, and language templates.
- `references/best_practices.md` — complete checklist with impact
  levels, version pinning philosophy, UID/GID strategy.
- `references/optimization_guide.md` — BuildKit internals, caching
  strategies, multi-stage patterns, distroless, profiling.
- `references/examples.md` — 13+ before/after optimization scenarios.
- `references/uv_integration.md` — Python with uv: installation
  methods, workspaces, multi-stage, all patterns.
- `references/compose_best_practices.md` — networks, volumes, secrets,
  dev vs prod, scaling.

## Status

`metadata.version: 2.0.0`.

## License

MIT — see the repository [LICENSE](../../LICENSE).
