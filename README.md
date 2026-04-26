![Claude Skills](https://img.shields.io/badge/Claude-Skills-5A67D8?style=for-the-badge&logo=anthropic&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Best_Practices-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![Helm](https://img.shields.io/badge/Helm-Charts-0F1689?style=for-the-badge&logo=helm&logoColor=white)

# 🤖 Claude Agent Skills Stack

**Self-contained skills for autonomous AI agents**
*Production-ready tools, templates, and validators for Docker and Kubernetes*

[Installation](#-installation) • [Skills](#-available-skills) • [Quick Start](#-quick-start) • [Architecture](#-architecture) • [Development](#-development)

---

## 🔄 Breaking Change — `helm-chart-generator` renamed to `helm-bjw-s-chart` (v3.0.0)

Starting with release **v3.0.0**, the skill formerly known as **`helm-chart-generator`** is now called **`helm-bjw-s-chart`** to make its scope explicit (it targets the `bjw-s` common library, not generic Helm charts).

**What changes for you:**

| Before (<= v2.x) | After (>= v3.0.0) |
|---|---|
| Skill directory: `skills/helm-chart-generator/` | `skills/helm-bjw-s-chart/` |
| Release asset: `helm-chart-generator.skill` | `helm-bjw-s-chart.skill` |
| Install path: `~/.claude/skills/helm-chart-generator/` | `~/.claude/skills/helm-bjw-s-chart/` |
| Agent/skill reference: `helm-chart-generator` | `helm-bjw-s-chart` |

**Migration:**

```bash
# 1. Remove the old skill
rm -rf ~/.claude/skills/helm-chart-generator

# 2. Install the new one (see Installation section below)
curl -L https://github.com/obeone/claude-skills/releases/latest/download/helm-bjw-s-chart.skill \
  -o /tmp/skill.zip && unzip -o /tmp/skill.zip -d ~/.claude/skills/
```

Any automation, doc, or agent still pointing to the old URL or name will break at the first install/refresh after v3.0.0 ships.

---

## 🔄 Breaking Change — `gemini-tts-script` renamed to `tts-duet` (v2.0.0)

Starting with release **v2.0.0**, the skill formerly known as **`gemini-tts-script`** is now called **`tts-duet`** to better reflect its dual-voice and MCP-based architecture.

**What changes for you:**

| Before (<= v1.x) | After (>= v2.0.0) |
|---|---|
| Skill directory: `skills/gemini-tts-script/` | `skills/tts-duet/` |
| Release asset: `gemini-tts-script.skill` | `tts-duet.skill` |
| Install path: `~/.claude/skills/gemini-tts-script/` | `~/.claude/skills/tts-duet/` |
| Agent/skill reference: `gemini-tts-script` | `tts-duet` |

**Migration:**

```bash
# 1. Remove the old skill
rm -rf ~/.claude/skills/gemini-tts-script

# 2. Install the new one (see Installation section below)
curl -L https://github.com/obeone/claude-skills/releases/latest/download/tts-duet.skill \
  -o /tmp/skill.zip && unzip -o /tmp/skill.zip -d ~/.claude/skills/
```

Any automation, doc, or agent still pointing to the old name will break at the first install/refresh after v2.0.0 ships.

---

## 📦 Installation

### Claude Code (CLI)

```bash
# Personal skills (available in all projects)
mkdir -p ~/.claude/skills

# Install dockerfile-best-practices
curl -L https://github.com/obeone/claude-skills/releases/latest/download/dockerfile-best-practices.skill \
  -o /tmp/skill.zip && unzip -o /tmp/skill.zip -d ~/.claude/skills/

# Install helm-bjw-s-chart
curl -L https://github.com/obeone/claude-skills/releases/latest/download/helm-bjw-s-chart.skill \
  -o /tmp/skill.zip && unzip -o /tmp/skill.zip -d ~/.claude/skills/
```

For project-specific skills, use `.claude/skills` instead of `~/.claude/skills`:

```bash
mkdir -p .claude/skills

curl -L https://github.com/obeone/claude-skills/releases/latest/download/dockerfile-best-practices.skill \
  -o /tmp/skill.zip && unzip -o /tmp/skill.zip -d .claude/skills/

curl -L https://github.com/obeone/claude-skills/releases/latest/download/helm-bjw-s-chart.skill \
  -o /tmp/skill.zip && unzip -o /tmp/skill.zip -d .claude/skills/
```

### Claude.ai (Web)

1. Download the `.skill` bundles from [Releases](../../releases)
2. Go to **Settings** → **Skills**
3. Click **Upload skill** and select each `.skill` file

### From Source

Clone the repository to use skills directly:

```bash
git clone https://github.com/obeone/claude-skills.git

# Copy all skills to your skills directory
cp -r claude-skills/skills/dockerfile-best-practices ~/.claude/skills/
cp -r claude-skills/skills/helm-bjw-s-chart ~/.claude/skills/
```

### Other Platforms

| Platform | Installation |
|----------|--------------|
| [Roo Code](https://roo.ai) | Add to `.roo/skills/` directory |
| [Cline](https://github.com/cline/cline) | Add to `.cline/skills/` directory |
| Generic | Extract `.skill` to your agent's skills directory |

> **How it works**: Skills are packaged using [Skill Pack](https://github.com/marketplace/actions/skill-pack) on every release. The action creates `.skill` bundles (ZIP archives) and uploads them to GitHub releases.

---

## 📖 Overview

This repository provides **modular skills** for Claude and other AI agents. Each skill is a self-contained bundle that includes:

- 📋 **SKILL.md** — Main entry point with decision trees and workflows
- 🔧 **Scripts** — Python validators and analyzers
- 📚 **References** — Deep-dive documentation and best practices
- 📦 **Assets** — Templates and boilerplate code

Skills are designed to be **installed once, used everywhere** — whether you're optimizing a Dockerfile, generating Helm charts, or setting up CI/CD pipelines.

## ⚡ Quick Start

### Using with Claude Code

Skills are automatically discovered when you run Claude Code in this repository. Simply ask:

```text
"Create a Dockerfile for my Python FastAPI application"
"Generate a Helm chart for this container image"
"Analyze my Dockerfile for best practices"
```

### Manual Usage

```bash
# Analyze a Dockerfile (uv reads PEP 723 metadata in the script header)
uv run skills/dockerfile-best-practices/scripts/analyze_dockerfile.py ./Dockerfile

# Analyze a Docker Compose file
uv run skills/dockerfile-best-practices/scripts/analyze_compose.py ./compose.yaml

# Validate a Helm chart
uv run skills/helm-bjw-s-chart/scripts/validate_chart.py ./my-chart/
```

## 🎯 Available Skills

| Skill | Description | Key Features |
|-------|-------------|--------------|
| [**dockerfile-best-practices**](./skills/dockerfile-best-practices/) | Create and optimize Dockerfiles with BuildKit, multi-stage builds, and security hardening | BuildKit syntax, cache mounts, non-root users, Python/uv integration |
| [**helm-bjw-s-chart**](./skills/helm-bjw-s-chart/) | Generate production-ready Helm charts using bjw-s common library | app-template v4+, sidecars, init containers, ingress patterns |
| [**tts-duet**](./skills/tts-duet/) | Author mono or dual-voice audio scripts and generate them with Gemini TTS | Adaptation pre-pass (agent or MCP), shape/language defaults, director enrichment, offline cost estimate, voice audition, background jobs |

## 🧩 Architecture

```
skills/<skill-name>/
├── SKILL.md              # Entry point with YAML front-matter
│                         # Contains: name, description
│
├── scripts/              # Python validation tools
│   ├── analyze_*.py      # Static analyzers — PEP 723 inline deps
│   └── validate_*.py     # Structure validators — PEP 723 inline deps
│
├── assets/               # Templates and static files
│   └── templates/        # Boilerplate code
│
└── references/           # Documentation and guides
    ├── best-practices.md # Comprehensive checklists
    ├── patterns.md       # Common patterns and examples
    └── *.md              # Topic-specific guides
```

### Design Principles

| Principle | Description |
|-----------|-------------|
| **Self-contained** | Each skill bundles everything needed — no external dependencies on other skills |
| **Progressive disclosure** | SKILL.md for quick start, references for deep dives |
| **Validation-first** | Every skill includes scripts to verify output quality |
| **Modern tooling** | BuildKit, Compose V2, Helm v3, bjw-s v4+, Python via `uv` |

## 📘 Usage

### Skill Installation

Skills can be packaged and distributed using the [Skill Pack](https://github.com/NimbleBrainInc/skill-pack) action:

```bash
# Skills are automatically packed on release
git tag v1.0.0
git push origin v1.0.0
```

### CI/CD Integration

This repository includes GitHub Actions workflows:

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `validate-skills.yml` | PRs, push to main | Validate SKILL.md frontmatter and structure |
| `publish-skills.yml` | Tag push (`v*`) | Pack skills, create release, upload to registry |

### Python Scripts

Every entry-point script declares its dependencies inline as a [PEP 723](https://peps.python.org/pep-0723/) header. `uv run path/to/script.py` resolves and caches them automatically — no `pip install` step.

```bash
# Install uv if needed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Run a script (uv reads the script's PEP 723 header and prepares the env)
uv run skills/dockerfile-best-practices/scripts/analyze_dockerfile.py ./Dockerfile
```

## 🔍 Key Features by Skill

### dockerfile-best-practices

- **Language templates**: Python/uv, Node.js, Go, PHP, Debian
- **Security patterns**: Non-root users (UID/GID >10000), secret mounts, version pinning
- **Performance optimization**: Cache mounts, multi-stage builds, layer ordering
- **Static analyzer**: Detects 15+ anti-patterns automatically
- **Compose support**: Modern V2 practices (no `version:`, no `container_name:`)

### helm-bjw-s-chart

- **bjw-s common library**: app-template v4+ patterns
- **Complete chart structure**: Chart.yaml, values.yaml, common.yaml, NOTES.txt
- **Deployment patterns**: Single container, sidecars, init containers, multi-controller
- **Best practices**: Resource limits, security contexts, health probes
- **Chart validator**: Verifies structure and bjw-s compatibility

## 🔨 Development

### Repository Structure

```
.
├── README.md             # This file
├── CLAUDE.md             # Claude Code configuration
├── AGENTS.md             # Agent guidelines
├── .github/
│   └── workflows/        # CI/CD automation
└── skills/
    ├── dockerfile-best-practices/
    ├── helm-bjw-s-chart/
    └── tts-duet/
```

### Mandatory Requirements

1. **SKILL.md YAML front-matter**: Every skill must have `name`, `description`, and `metadata.version`:
   ```yaml
   ---
   name: my-skill
   description: "Skill description"
   metadata:
     version: "1.0.0"
   ---
   ```
2. **POSIX compliance**: All files must end with newline (`\n`) and use LF line endings
3. **Python via uv**: Use `uv` for dependency management

### Adding a New Skill

1. Create `skills/<skill-name>/SKILL.md` with required front-matter (see format above)
2. Add `scripts/` with validators and analyzers
3. Add `references/` with deep-dive documentation
4. Add `assets/` with templates if needed
5. Submit a PR — the `validate-skills` workflow will verify structure

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

## 🙏 Credits

- [bjw-s common library](https://github.com/bjw-s/helm-charts) for Helm chart patterns
- [astral-sh/uv](https://github.com/astral-sh/uv) for Python package management
- [Docker BuildKit](https://docs.docker.com/build/buildkit/) for modern build features

---

*Built with 🤖 by autonomous agents, for autonomous agents*
