<p align="center">
  <img src="https://img.shields.io/badge/Claude-Skills-5A67D8?style=for-the-badge&logo=anthropic&logoColor=white" alt="Claude Skills"/>
  <img src="https://img.shields.io/badge/Docker-Best_Practices-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker"/>
  <img src="https://img.shields.io/badge/Helm-Charts-0F1689?style=for-the-badge&logo=helm&logoColor=white" alt="Helm"/>
</p>

<h1 align="center">🤖 Claude Agent Skills Stack</h1>

<p align="center">
  <strong>Self-contained skills for autonomous AI agents</strong><br/>
  <em>Production-ready tools, templates, and validators for Docker and Kubernetes</em>
</p>

<p align="center">
  <a href="#-installation">Installation</a> •
  <a href="#-available-skills">Skills</a> •
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-architecture">Architecture</a> •
  <a href="#-development">Development</a>
</p>

---

## 📦 Installation

### Claude Code (CLI)

```bash
# Personal skills (available in all projects)
mkdir -p ~/.claude/skills
curl -L https://github.com/obeone/claude-skills/releases/latest/download/dockerfile-best-practices.skill \
  -o /tmp/skill.zip && unzip -o /tmp/skill.zip -d ~/.claude/skills/

# Or project-specific skills
mkdir -p .claude/skills
curl -L https://github.com/obeone/claude-skills/releases/latest/download/dockerfile-best-practices.skill \
  -o /tmp/skill.zip && unzip -o /tmp/skill.zip -d .claude/skills/
```

### Claude.ai (Web)

1. Download the `.skill` bundle from [Releases](../../releases)
2. Go to **Settings** → **Skills**
3. Click **Upload skill** and select the `.skill` file

### From Source

Clone the repository to use skills directly:

```bash
git clone https://github.com/obeone/claude-skills.git

# Copy to your skills directory
cp -r claude-skills/skills/dockerfile-best-practices ~/.claude/skills/
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
# Analyze a Dockerfile
python skills/dockerfile-best-practices/scripts/analyze_dockerfile.py ./Dockerfile

# Analyze a Docker Compose file
python skills/dockerfile-best-practices/scripts/analyze_compose.py ./compose.yaml

# Validate a Helm chart
python skills/helm-chart-generator/helm-chart-generator/scripts/validate_chart.py ./my-chart/
```

## 🎯 Available Skills

| Skill | Description | Key Features |
|-------|-------------|--------------|
| [**dockerfile-best-practices**](./skills/dockerfile-best-practices/) | Create and optimize Dockerfiles with BuildKit, multi-stage builds, and security hardening | BuildKit syntax, cache mounts, non-root users, Python/uv integration |
| [**helm-chart-generator**](./skills/helm-chart-generator/helm-chart-generator/) | Generate production-ready Helm charts using bjw-s common library | app-template v4+, sidecars, init containers, ingress patterns |

## 🏗️ Architecture

```
skills/<skill-name>/
├── SKILL.md              # Entry point with YAML front-matter
│                         # Contains: name, description, tools list
│
├── scripts/              # Python validation tools
│   ├── analyze_*.py      # Static analyzers
│   ├── validate_*.py     # Structure validators
│   └── requirements.txt  # Dependencies (uv compatible)
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

All scripts use `uv` for dependency management:

```bash
# Install uv if needed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Run a script (dependencies auto-installed)
uv run python skills/dockerfile-best-practices/scripts/analyze_dockerfile.py ./Dockerfile
```

## 🔍 Key Features by Skill

### dockerfile-best-practices

- **Language templates**: Python/uv, Node.js, Go, PHP, Debian
- **Security patterns**: Non-root users (UID/GID >10000), secret mounts, version pinning
- **Performance optimization**: Cache mounts, multi-stage builds, layer ordering
- **Static analyzer**: Detects 15+ anti-patterns automatically
- **Compose support**: Modern V2 practices (no `version:`, no `container_name:`)

### helm-chart-generator

- **bjw-s common library**: app-template v4+ patterns
- **Complete chart structure**: Chart.yaml, values.yaml, common.yaml, NOTES.txt
- **Deployment patterns**: Single container, sidecars, init containers, multi-controller
- **Best practices**: Resource limits, security contexts, health probes
- **Chart validator**: Verifies structure and bjw-s compatibility

## 🛠️ Development

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
    └── helm-chart-generator/
```

### Mandatory Requirements

1. **SKILL.md YAML front-matter**: Every skill must have `name`, `description`, and `tools` fields
2. **POSIX compliance**: All files must end with newline (`\n`) and use LF line endings
3. **Python via uv**: Use `uv` for dependency management

### Adding a New Skill

1. Create `skills/<skill-name>/SKILL.md` with required front-matter
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

<p align="center">
  <sub>Built with 🤖 by autonomous agents, for autonomous agents</sub>
</p>
