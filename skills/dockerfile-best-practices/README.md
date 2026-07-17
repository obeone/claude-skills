# dockerfile-best-practices

A Claude Code skill that creates and optimizes Dockerfiles with modern
BuildKit features (multi-stage builds, cache mounts, secret mounts,
non-root users) and analyzes existing Dockerfiles and Compose files for
anti-patterns.

The skill ships language templates (Python/uv, Node.js, Go, Rust, PHP,
Debian) and two static analyzers covering the most common Docker and
Compose mistakes.

## Why

Hand-writing production-grade Dockerfiles means juggling a long
checklist: the BuildKit syntax directive, cache mounts per package
manager, `--mount=type=secret` instead of `ARG SECRET`, a non-root user
at UID/GID above 10000, creating that user *before* the first
`COPY --chown` that names it, a `HEALTHCHECK` that calls a binary the
image actually ships. Most images get one or two of those right and
quietly miss the rest.

It also means resisting advice that sounds right and isn't. "Receives
security patches" and "reproducible" are properties of a process, not of
a tag string: a floating tag patches nothing on its own, it patches when
someone rebuilds. So this skill tells you to pin a readable tag as
specific as you are willing to maintain, and says plainly that every tag
is mutable, rather than implying the tag protects you. Pinning the OS
(`python:3.12-slim-bookworm`, `alpine:3.19`) is a legitimate stability
choice and is not flagged. `:latest` and untagged images stay rejected,
because they carry zero information about what you are running. Digests
get one honest paragraph as an option with a real tradeoff: they are the
strongest guarantee available, and without renewal automation a digest is
just a tag that rots silently while you ship known CVEs feeling safe.

Compose V2 adds its own footguns: a stale `version:` field that warns on
every run, `container_name:` that blocks scaling, bare `depends_on` that
doesn't actually wait for the upstream to be healthy.

This skill folds the full ruleset into a single workflow with
ready-to-copy templates and analyzer scripts that flag anti-patterns
before they ship.

## Requirements

- **Claude Code** (or any agent that can read `SKILL.md`).
- **`uv`** on `$PATH` ([install](https://astral.sh/uv/)). The one script
  that needs a third-party dependency (`analyze_compose.py`, which parses
  YAML) declares it inline as a
  [PEP 723](https://peps.python.org/pep-0723/) header, so `uv run`
  resolves it with no `pip install` step. `analyze_dockerfile.py` is
  standard library only.
- **Docker with BuildKit** (Docker 23+ enables it by default) if you want
  to actually build the generated Dockerfiles.

## Install

### Recommended: `skills` CLI

The [`skills`](https://skills.sh/) CLI resolves the repo and drops the
bundle into the right agent directory. Run via `npx`, no global Node
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

Each analyzer reports findings with a severity (error / warning / info)
and a stable rule id, and references the `SKILL.md` rule that was
violated. Rule ids are never reused: a retired id stays retired, so an
id in an old report always means the same thing.

The analyzer is not a substitute for BuildKit's own linter. Run both:
`docker build --check` catches things this skill's rules deliberately
don't duplicate, and `references/build_checks.md` explains where the two
overlap.

## What it gives you

- **Eleven essential rules.** BuildKit syntax directive, a pinned
  readable tag, cache mounts per package manager (pip, npm, yarn, go,
  cargo, composer, maven), APT cache setup, `--mount=type=secret`,
  non-root UID/GID above 10000, `COPY` for local files with
  `ADD --checksum` for remote artifacts, user creation before the first
  `COPY --chown` that names it, OCI labels, `HEALTHCHECK`,
  `.dockerignore`.
- **Six language templates.** Python (with `uv`), Node.js, Go
  (multi-stage to distroless), Rust (multi-stage to distroless), PHP with
  Composer, Debian-base with APT cache. Each template bundles the full
  ruleset and is linted in CI against the skill's own analyzer.
- **Compose V2 ruleset.** No `version:`, no `container_name:`, no
  `links:`, pinned image tags, `depends_on` with
  `condition: service_healthy`, plus runtime hardening (`read_only`,
  `cap_drop`, `no-new-privileges`, `init`).
- **Static analyzers.** `analyze_dockerfile.py` runs 31 checks;
  `analyze_compose.py` runs 19 covering V2 hygiene and service-level
  rules.
- **PID 1 and signal handling.** Why shell-form `CMD` makes your
  container ignore `docker stop` for the full grace period, and the three
  ways out in preference order.

Some of these rules exist because no other tool can catch what they
catch. The worst bug this skill has shipped was a `COPY --chown` naming a
user created later in the same stage: the modern BuildKit frontend does
not fail on that, it silently drops the `--chown` and copies the files as
root. The build stays green, `docker build --check` sees nothing, and the
image only breaks on the first runtime write. A static rule is the only
possible net.

## Layout

```text
skills/dockerfile-best-practices/
├── SKILL.md          # Agent-facing entry point with all rules + templates
├── README.md         # This file (user-facing intro)
├── CHANGELOG.md      # Version history and breaking changes
├── assets/
│   └── dockerignore-template   # Blocklist template, with an allowlist variant
├── references/
│   ├── best_practices.md         # Complete checklist with impact levels
│   ├── build_checks.md           # BuildKit's native linter (docker build --check)
│   ├── compose_best_practices.md # Compose V2 deep dive
│   ├── examples.md               # Real-world before/after optimizations
│   ├── optimization_guide.md     # BuildKit internals, caching, multi-stage
│   ├── supply_chain.md           # SBOM, provenance, signing
│   └── uv_integration.md         # Python with uv: all patterns
└── scripts/
    ├── analyze_dockerfile.py       # Static analyzer for Dockerfiles
    ├── analyze_compose.py          # Static analyzer for Compose files
    ├── extract_dockerfile_blocks.py # Lints the skill's own examples in CI
    └── tests/                      # Test suite for the extractor
```

## Deeper documentation

- `SKILL.md`: agent-facing entry point with the full workflow, essential
  rules, and language templates.
- `references/best_practices.md`: complete checklist with impact levels,
  the pinning doctrine and the digest tradeoff, UID/GID strategy, PID 1
  and signal handling.
- `references/optimization_guide.md`: BuildKit internals, caching
  strategies, multi-stage patterns, distroless, profiling.
- `references/build_checks.md`: `docker build --check`, its 21 built-in
  rules, and wiring it into CI.
- `references/supply_chain.md`: provenance attestations, SBOMs, signing,
  and the tooling that renews a pinned digest.
- `references/examples.md`: 15 before/after optimization scenarios.
- `references/uv_integration.md`: Python with uv: installation methods,
  workspaces, multi-stage, all patterns.
- `references/compose_best_practices.md`: networks, volumes, secrets, dev
  vs prod, scaling.
- `CHANGELOG.md`: what changed and what breaks between versions.

## Status

`metadata.version: 3.0.0`.

v3.0.0 is a breaking release: it reverses the old "pin the runtime, never
the OS" doctrine, retires the two analyzer rules that enforced it, and
inverts a third. See `CHANGELOG.md` before upgrading if your CI asserts
on rule ids.

## License

MIT, see the repository [LICENSE](../../LICENSE).
