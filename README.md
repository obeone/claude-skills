# WORK IN PROGRESS



## Dockerfile Best Practices Skill

Comprehensive skill for creating and optimizing Dockerfiles with BuildKit, multi-stage builds, advanced caching, and security.

## Installation

1. Download the `dockerfile-best-practices.skill` file
2. In Claude.ai, go to Settings → Skills
3. Click "Upload Skill" and select the `.skill` file

## Contents

### 📄 SKILL.md (main guide)

- Quick decision workflow
- Language templates (Python/uv, Node.js, Go, PHP, Debian)
- Security and performance checklists
- Docker Compose best practices
- Build commands
- Common patterns (cache, secrets, multi-stage)

### 📚 Detailed References

- **optimization_guide.md** - Complete BuildKit, caching, multi-stage, multi-arch, distroless guide
- **best_practices.md** - Complete checklist with impact levels, version pinning philosophy, UID/GID strategy
- **examples.md** - Real before/after optimization examples (14 examples)
- **uv_integration.md** - Python integration with uv (recommended)
- **compose_best_practices.md** - Modern Docker Compose practices (no version:, no container_name:)

### 🛠️ Tools

- **scripts/analyze_dockerfile.py** - Analyzes and detects anti-patterns in Dockerfiles
- **scripts/analyze_compose.py** - Analyzes and detects anti-patterns in docker-compose.yml files
- **assets/dockerignore-template** - Complete .dockerignore template

## Usage

### Create a new Dockerfile

Ask Claude:

```text
Create a Dockerfile for a FastAPI API with uv
```

### Optimize an existing Dockerfile

```text
Analyze this Dockerfile and optimize it
[paste Dockerfile]
```

### Solve a problem

```text
My Docker build is very slow, how can I optimize it?
```

```text
How do I manage secrets in my Dockerfile?
```

## Automatic Triggering

The skill automatically triggers when you:

- Create a new Dockerfile
- Optimize an existing Dockerfile
- Work with docker-compose.yml files
- Ask questions about image size
- Request help with Docker security
- Use Python with uv
- Have cache or slow build issues
- Configure CI/CD builds

## Key Features

### Dockerfiles

✅ Optimized templates for Python (uv), Node.js, Go, PHP, Debian
✅ BuildKit with cache mounts
✅ Automatic multi-stage builds
✅ Secure secret management
✅ Non-root users with UID/GID >10000
✅ Smart version pinning (runtime yes, OS no)
✅ APT cache configuration for Debian-based images
✅ Multi-architecture build support
✅ Distroless image patterns
✅ Remote cache for CI/CD
✅ Integrated analyzer script (analyze_dockerfile.py)

### Docker Compose

✅ Modern Compose Specification (no version:)
✅ Scalable services (no container_name:)
✅ Health checks and dependencies
✅ Resource limits and restart policies
✅ Secrets management
✅ Network isolation patterns
✅ Integrated analyzer script (analyze_compose.py)  

## Important Notes

### APT Configuration

For Debian-based images, always configure APT before using cache mounts:

```dockerfile
RUN rm -f /etc/apt/apt.conf.d/docker-clean; \
    echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache
```

### Version Pinning Philosophy

**Pin runtime versions, NOT OS versions:**

```dockerfile
# ✅ GOOD - Pin runtime, let OS update
FROM python:3.12-slim

# ❌ BAD - Pins OS version (bookworm), prevents security updates
FROM python:3.12-slim-bookworm
```

**Why?** OS versions should update automatically for security patches. Runtime versions control application behavior and should be pinned for reproducibility.

### UID/GID Strategy

**Always use UID/GID >10000** for non-root users:

```dockerfile
# ✅ GOOD - UID/GID >10000 avoids conflicts
RUN groupadd -r -g 10001 app && \
    useradd -r -u 10001 -g app app
```

**Why?** Avoids conflicts with system users (<1000) and regular host users (1000-9999).

## Example Queries

**Dockerfiles:**

```text
"Create a Python Dockerfile with uv for a CLI tool"
"Optimize this Node.js Dockerfile to reduce size"
"How do I use cache mounts with Maven?"
"Create a multi-stage build for a Go app"
"How do I manage API secrets in Docker?"
"Analyze this Dockerfile and detect issues"
"Create a multi-architecture build for ARM and AMD64"
"How do I use distroless images for security?"
```

**Docker Compose:**

```text
"Create a docker-compose.yml for a web app with Postgres"
"Analyze this docker-compose.yml and detect issues"
"How do I scale services in Docker Compose?"
"Set up health checks and dependencies in Compose"
"Configure resource limits in docker-compose.yml"
```

## Package Structure

```text
dockerfile-best-practices.skill
├── SKILL.md                          # Main guide
├── references/
│   ├── optimization_guide.md         # Complete guide + multi-arch + distroless
│   ├── best_practices.md             # Checklist + version pinning + UID/GID
│   ├── examples.md                   # 14 real examples
│   ├── uv_integration.md             # Python + uv
│   └── compose_best_practices.md     # Docker Compose guide
├── scripts/
│   ├── analyze_dockerfile.py         # Dockerfile analyzer
│   ├── analyze_compose.py            # Docker Compose analyzer
│   └── requirements.txt              # Python dependencies
└── assets/
    └── dockerignore-template         # .dockerignore template
```

## Best Practices Summary

**Dockerfiles:**

- Always use BuildKit (`# syntax=docker/dockerfile:1`)
- Pin runtime versions (python:3.12), NOT OS versions (bookworm)
- Use UID/GID >10000 for non-root users
- Configure APT for cache on Debian-based images
- Separate dependencies from code for caching
- Multi-stage builds for compiled languages
- Never use ARG/ENV for secrets - use secret mounts
- Use cache mounts for package managers
- Consider multi-architecture builds (AMD64 + ARM64)
- Use distroless images for enhanced security

**Docker Compose:**

- No `version:` field (deprecated since Compose V2)
- Avoid `container_name:` (prevents scaling)
- Use specific image tags (not `:latest`)
- Define health checks for dependencies
- Set resource limits to prevent exhaustion
- Use secrets for sensitive data (not env vars)
- Implement network isolation with custom networks
- Configure restart policies

## What's New

### Version 2.0 (2024-12-14)

**Major updates:**

- **Smart Version Pinning**: Pin runtime versions, NOT OS versions (prevents outdated base images)
- **Secure UID/GID**: All examples now use UID/GID >10000 to avoid host conflicts
- **Docker Compose Support**: Complete guide for modern Compose (no version:, no container_name:)
- **Multi-Architecture Builds**: Support for AMD64 + ARM64 from single Dockerfile
- **Distroless Images**: Enhanced security patterns with minimal images
- **Enhanced Analyzers**: New detections for OS version pinning, UID/GID issues
- **Compose Analyzer**: New tool to analyze docker-compose.yml files

### Version 1.0 (2024-12-05)

Initial release with:

- BuildKit (default since Docker Engine 23.0)
- Cache mounts (`RUN --mount=type=cache`)
- Secret mounts (`RUN --mount=type=secret`)
- COPY --link
- Heredocs
- uv for Python (modern package manager)

---

**Last updated:** 2024-12-14
