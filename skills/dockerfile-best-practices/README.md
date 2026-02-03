<p align="center">
  <img src="https://img.shields.io/badge/Docker-BuildKit-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker BuildKit"/>
  <img src="https://img.shields.io/badge/Python-uv-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python uv"/>
  <img src="https://img.shields.io/badge/Security-Hardened-10B981?style=for-the-badge&logo=shield&logoColor=white" alt="Security"/>
</p>

<h1 align="center">🐳 Dockerfile Best Practices</h1>

<p align="center">
  <strong>Create optimized, secure, and fast Docker images</strong><br/>
  <em>Modern BuildKit features • Multi-stage builds • Cache optimization</em>
</p>

<p align="center">
  <a href="#-installation">Installation</a> •
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-features">Features</a> •
  <a href="#-templates">Templates</a> •
  <a href="#-validation">Validation</a>
</p>

---

## 📦 Installation

### Claude Code (CLI)

```bash
# Install to personal skills directory
mkdir -p ~/.claude/skills
curl -L https://github.com/obeone/claude-skills/releases/latest/download/dockerfile-best-practices.skill \
  -o /tmp/skill.zip && unzip -o /tmp/skill.zip -d ~/.claude/skills/

# Or install to current project only
mkdir -p .claude/skills
curl -L https://github.com/obeone/claude-skills/releases/latest/download/dockerfile-best-practices.skill \
  -o /tmp/skill.zip && unzip -o /tmp/skill.zip -d .claude/skills/
```

### Claude.ai (Web)

1. Download [`dockerfile-best-practices.skill`](https://github.com/obeone/claude-skills/releases/latest/download/dockerfile-best-practices.skill)
2. Go to **Settings** → **Skills** → **Upload skill**

### From Source

```bash
git clone https://github.com/obeone/claude-skills.git
cp -r claude-skills/skills/dockerfile-best-practices ~/.claude/skills/
```

> Skills are packaged using [Skill Pack](https://github.com/marketplace/actions/skill-pack) on every release.

---

## 🚀 Quick Start

```bash
# Analyze your Dockerfile for anti-patterns
python scripts/analyze_dockerfile.py ./Dockerfile

# Analyze Docker Compose file
python scripts/analyze_compose.py ./compose.yaml

# Copy .dockerignore template
cp assets/dockerignore-template .dockerignore
```

## ✨ Features

### 🔧 Static Analyzers

| Analyzer | Purpose | Detects |
|----------|---------|---------|
| `analyze_dockerfile.py` | Dockerfile anti-patterns | 15+ issues including missing BuildKit syntax, :latest tags, secrets in ENV |
| `analyze_compose.py` | Compose anti-patterns | Deprecated `version:` field, `container_name:`, missing health checks |

### 📝 Language Templates

Ready-to-use templates for common stacks:

| Language | Features |
|----------|----------|
| **Python (uv)** | Cache mounts, locked dependencies, non-root user |
| **Node.js** | Yarn cache, frozen lockfile, alpine base |
| **Go** | Multi-stage, static binary, scratch/alpine runtime |
| **PHP** | Composer cache, FPM configuration |
| **Debian** | APT cache persistence, minimal packages |

### 🔐 Security Hardening

- Non-root users with UID/GID >10000
- BuildKit secret mounts (never in ENV/ARG)
- Version pinning for reproducibility
- Minimal base images (alpine, slim, distroless)

### ⚡ Performance Optimization

- BuildKit syntax directive
- Cache mounts for all package managers
- Layer ordering (dependencies before code)
- Multi-stage builds for compiled languages

## 📋 Essential Rules

Every Dockerfile should follow these core principles:

```dockerfile
# 1. Always start with BuildKit syntax
# syntax=docker/dockerfile:1

# 2. Pin runtime versions, not OS versions
FROM python:3.12-slim  # ✅ Good
# FROM python:3.12-slim-bookworm  # ❌ Prevents security updates

# 3. Use cache mounts for package managers
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# 4. Never expose secrets via ENV/ARG
RUN --mount=type=secret,id=api_key \
    curl -H "Authorization: $(cat /run/secrets/api_key)" https://api.example.com

# 5. Run as non-root user
RUN groupadd -r -g 10001 app && useradd -r -u 10001 -g app app
USER app
```

## 🎨 Templates

### Python with uv (Recommended)

```dockerfile
# syntax=docker/dockerfile:1

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies (cached layer)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked

RUN groupadd -r -g 10001 app && \
    useradd -r -u 10001 -g app app && \
    chown -R app:app /app
USER app

ENV PATH="/app/.venv/bin:$PATH"
CMD ["python", "-m", "myapp"]
```

### Go Multi-stage

```dockerfile
# syntax=docker/dockerfile:1

FROM golang:1-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -ldflags="-w -s" -o main

FROM alpine:3
RUN addgroup -g 10001 app && adduser -u 10001 -G app -S app
USER app
COPY --from=builder /app/main /main
ENTRYPOINT ["/main"]
```

> 📁 More templates in [SKILL.md](./SKILL.md#language-specific-templates)

## 🔍 Validation

### Dockerfile Analyzer

```bash
python scripts/analyze_dockerfile.py ./Dockerfile
```

**Detected Issues:**

| Category | Issues |
|----------|--------|
| **Syntax** | Missing BuildKit directive |
| **Security** | :latest tags, secrets in ENV/ARG, running as root |
| **Performance** | Missing cache mounts, wrong layer order |
| **Style** | ADD vs COPY, apt-get without cleanup |

### Compose Analyzer

```bash
python scripts/analyze_compose.py ./compose.yaml
```

**Detected Issues:**

| Category | Issues |
|----------|--------|
| **Deprecated** | `version:` field (Compose V2 doesn't need it) |
| **Anti-pattern** | `container_name:` (prevents scaling) |
| **Best Practice** | Missing health checks, resource limits |

## 📚 References

| Document | Description |
|----------|-------------|
| [best_practices.md](./references/best_practices.md) | Complete checklist with impact levels |
| [optimization_guide.md](./references/optimization_guide.md) | Deep-dive into BuildKit, caching, multi-arch |
| [examples.md](./references/examples.md) | 14 real-world before/after optimizations |
| [uv_integration.md](./references/uv_integration.md) | Python with uv package manager |
| [compose_best_practices.md](./references/compose_best_practices.md) | Modern Compose V2 patterns |

## 📁 Skill Structure

```
dockerfile-best-practices/
├── SKILL.md                 # Main entry point with workflows
├── README.md                # This file
├── scripts/
│   ├── analyze_dockerfile.py    # Dockerfile anti-pattern detector
│   ├── analyze_compose.py       # Compose anti-pattern detector
│   └── requirements.txt         # pyyaml
├── assets/
│   └── dockerignore-template    # .dockerignore template
└── references/
    ├── best_practices.md        # Complete checklist
    ├── compose_best_practices.md
    ├── examples.md              # Before/after examples
    ├── optimization_guide.md    # BuildKit deep-dive
    └── uv_integration.md        # Python + uv guide
```

## 🏃 Build Commands

```bash
# Basic build
docker buildx build -t myapp:latest .

# With registry cache (CI/CD)
docker buildx build \
  --cache-from=type=registry,ref=registry.com/myapp:cache \
  --cache-to=type=registry,ref=registry.com/myapp:cache,mode=max \
  -t myapp:latest .

# With secrets
docker buildx build --secret id=api_key,src=./key.txt -t myapp:latest .

# Multi-platform
docker buildx build --platform linux/amd64,linux/arm64 -t myapp:latest --push .
```

## ✅ Checklists

### Security

- [ ] Use specific version tags for base images
- [ ] Use minimal base image (alpine, slim, distroless)
- [ ] Create and use non-root user (UID/GID >10000)
- [ ] Never expose secrets via ARG/ENV
- [ ] Add HEALTHCHECK instruction
- [ ] Scan image for vulnerabilities

### Performance

- [ ] Add BuildKit syntax directive
- [ ] Create comprehensive `.dockerignore`
- [ ] Order instructions: manifests → deps → code
- [ ] Use `--mount=type=cache` for all package managers
- [ ] Implement multi-stage builds for compiled languages

---

<p align="center">
  <sub>Part of the <a href="../../">Claude Agent Skills Stack</a></sub>
</p>
