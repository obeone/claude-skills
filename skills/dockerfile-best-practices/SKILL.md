---
name: dockerfile-best-practices
description: "Create and optimize Dockerfiles with BuildKit, multi-stage builds, advanced caching, and security. Use this skill whenever you need to create, modify, or optimize a Dockerfile or a Docker Compose file. Also trigger when the user discusses container images, build performance, or Docker security — even if they don't explicitly mention 'Dockerfile'."
metadata:
  version: "2.0.0"
---

# Dockerfile Best Practices

Comprehensive guide for creating optimized, secure, and fast Docker images using modern BuildKit features.

## Workflow

1. **Identify language/framework** → Pick template from [Language Templates](#language-templates)
2. **Apply essential rules** → Every Dockerfile must follow [Essential Rules](#essential-rules)
3. **Security hardening** → Non-root user, pin versions, secrets management
4. **Optimize for cache** → Separate deps from code, use cache mounts
5. **Multi-stage if needed** → Compiled languages or distroless runtime
6. **Add metadata** → OCI labels, HEALTHCHECK, STOPSIGNAL
7. **Review** → Run `scripts/analyze_dockerfile.py` or `scripts/analyze_compose.py`

## Essential Rules (Always Apply)

### 1. BuildKit syntax directive (first line, always)

```dockerfile
# syntax=docker/dockerfile:1
```

### 2. Pin runtime versions, NOT OS versions

```dockerfile
# ✅ GOOD
FROM python:3.12-slim
FROM node:22-alpine
FROM golang:1-alpine

# ❌ BAD - pins OS, blocks security updates
FROM python:3.12-slim-bookworm
FROM node:22-alpine3.19
```

### 3. Cache mounts for all package managers

```dockerfile
# pip
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

# npm
RUN --mount=type=cache,target=/root/.npm npm ci

# yarn
RUN --mount=type=cache,target=/root/.yarn yarn install --frozen-lockfile

# go
RUN --mount=type=cache,target=/go/pkg/mod go mod download

# cargo
RUN --mount=type=cache,target=/usr/local/cargo/registry cargo build --release

# composer
RUN --mount=type=cache,target=/tmp/cache composer install --no-dev

# maven
RUN --mount=type=cache,target=/root/.m2 mvn package -DskipTests
```

### 4. APT cache setup (before any apt operation on Debian-based images)

```dockerfile
RUN rm -f /etc/apt/apt.conf.d/docker-clean; \
    echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends curl
```

### 5. Never use ARG/ENV for secrets

```dockerfile
# ✅ GOOD - secret mount
RUN --mount=type=secret,id=api_key \
    curl -H "Authorization: $(cat /run/secrets/api_key)" https://api.example.com

# ❌ BAD - exposed in image history
ARG API_KEY
```

### 6. Non-root user with UID/GID >10000

```dockerfile
# Debian/Ubuntu
RUN groupadd -r -g 10001 app && useradd -r -u 10001 -g app app

# Alpine
RUN addgroup -g 10001 app && adduser -u 10001 -G app -S app
```

### 7. Use COPY, never ADD

`ADD` has implicit behaviors (auto-extraction, URL downloads). Always use `COPY`.

### 8. Use COPY --chown instead of separate RUN chown

```dockerfile
# ✅ GOOD - single layer, no extra overhead
COPY --chown=app:app . .

# ❌ BAD - doubles layer size
COPY . .
RUN chown -R app:app /app
```

### 9. OCI labels for metadata

```dockerfile
LABEL org.opencontainers.image.source="https://github.com/org/repo" \
      org.opencontainers.image.description="My application" \
      org.opencontainers.image.version="1.0.0"
```

### 10. HEALTHCHECK for long-running services

```dockerfile
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD wget -qO- http://localhost:8000/health || exit 1
```

### 11. Create .dockerignore

Use template from `assets/dockerignore-template`. Critical for build context size and security.

## Language Templates

### Python (with uv - Recommended)

For detailed uv patterns, see `references/uv_integration.md`.

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

# Copy and install project
COPY --chown=app:app . .
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked

# Security
RUN groupadd -r -g 10001 app && useradd -r -u 10001 -g app app
USER app

ENV PATH="/app/.venv/bin:$PATH"
CMD ["python", "-m", "myapp"]
```

### Node.js

```dockerfile
# syntax=docker/dockerfile:1

FROM node:22-alpine
WORKDIR /app

COPY package.json yarn.lock ./
RUN --mount=type=cache,target=/root/.yarn \
    yarn install --frozen-lockfile --production

COPY --chown=app:app . .

RUN addgroup -g 10001 app && adduser -u 10001 -G app -S app
USER app

EXPOSE 3000
HEALTHCHECK --interval=30s CMD wget -qO- http://localhost:3000/health || exit 1
CMD ["node", "index.js"]
```

### Go (Multi-stage)

```dockerfile
# syntax=docker/dockerfile:1

FROM golang:1-alpine AS builder
WORKDIR /app

COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download

COPY . .
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o main

FROM gcr.io/distroless/static
COPY --from=builder /app/main /main
ENTRYPOINT ["/main"]
```

### Rust (Multi-stage)

```dockerfile
# syntax=docker/dockerfile:1

FROM rust:1-slim AS builder
WORKDIR /app

COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo "fn main() {}" > src/main.rs
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/app/target \
    cargo build --release

COPY . .
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/app/target \
    cargo build --release && cp target/release/myapp /usr/local/bin/

FROM gcr.io/distroless/cc
COPY --from=builder /usr/local/bin/myapp /myapp
ENTRYPOINT ["/myapp"]
```

### PHP (with Composer)

```dockerfile
# syntax=docker/dockerfile:1

FROM php:8-fpm-alpine
WORKDIR /app

COPY --from=composer:latest /usr/bin/composer /usr/bin/composer

COPY composer.json composer.lock ./
RUN --mount=type=cache,target=/tmp/cache \
    composer install --no-dev --optimize-autoloader --no-scripts

COPY --chown=app:app . .
RUN composer dump-autoload --optimize

RUN addgroup -g 10001 app && adduser -u 10001 -G app -S app
USER app

EXPOSE 9000
CMD ["php-fpm"]
```

### Debian-based (with APT cache)

```dockerfile
# syntax=docker/dockerfile:1

FROM debian:stable-slim

RUN rm -f /etc/apt/apt.conf.d/docker-clean; \
    echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache

WORKDIR /app

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends curl ca-certificates

COPY --chown=app:app . .

RUN groupadd -r -g 10001 app && useradd -r -u 10001 -g app app
USER app

CMD ["./app"]
```

## Docker Compose Rules

**Critical rules** (always enforce):

1. **Never use `version:`** — Deprecated since Compose V2
2. **Never use `container_name:`** — Prevents scaling and parallel environments
3. **Never use `links:`** — Deprecated, use networks instead
4. **Use specific image tags** — Never `:latest`
5. **Use `depends_on` with `condition: service_healthy`** — Not bare `depends_on`

For complete Compose guide with examples, see `references/compose_best_practices.md`.

## Build Commands Reference

```bash
# Basic build
docker buildx build -t myapp:1.0.0 .

# With remote cache (CI/CD)
docker buildx build \
  --cache-from=type=registry,ref=registry.com/myapp:cache \
  --cache-to=type=registry,ref=registry.com/myapp:cache,mode=max \
  -t myapp:1.0.0 .

# With secrets
docker buildx build --secret id=api_key,src=./key.txt -t myapp:1.0.0 .

# Multi-platform
docker buildx build --platform linux/amd64,linux/arm64 -t myapp:1.0.0 --push .
```

## Analysis Tools

```bash
# Analyze Dockerfile
python scripts/analyze_dockerfile.py ./Dockerfile

# Analyze docker-compose.yml
python scripts/analyze_compose.py ./docker-compose.yml
```

## Reference Documentation

For detailed information beyond what's covered here:

| Reference | Content |
|-----------|---------|
| `references/optimization_guide.md` | BuildKit internals, caching strategies, multi-stage patterns, distroless, profiling |
| `references/best_practices.md` | Complete checklist with impact levels, version pinning philosophy, UID/GID strategy |
| `references/examples.md` | Real-world before/after optimization examples (13+ scenarios) |
| `references/uv_integration.md` | Python with uv: installation methods, workspaces, multi-stage, all patterns |
| `references/compose_best_practices.md` | Complete Compose guide: networks, volumes, secrets, dev vs prod, scaling |
