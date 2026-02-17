# Dockerfile Best Practices Checklist

## Version Pinning Philosophy

### What to Pin

- **Runtime/language versions** (e.g., `python:3.12`, `node:20`, `golang:1`)
  - Controls application behavior
  - Prevents breaking changes from language updates
  - Reproducible builds across environments

### What NOT to Pin

- **OS release versions** (e.g., `bookworm`, `bullseye`, `alpine:3.19`)
  - Allow automatic security patches
  - Reduce maintenance burden
  - Stay current with base image updates

### Recommended Patterns

| Instead of | Use | Why |
|------------|-----|-----|
| `python:3.12-slim-bookworm` | `python:3.12-slim` | Auto security updates |
| `alpine:3.19` | `alpine:3` or `alpine:latest` | Latest stable |
| `debian:bookworm-slim` | `debian:stable-slim` | Rolling stable |
| `node:20-alpine3.19` | `node:20-alpine` | Latest alpine for Node 20 |
| `golang:1.21-alpine` | `golang:1-alpine` | Latest Go 1.x with latest alpine |

### Exceptions

Pin OS versions when:

- Absolute reproducibility required (regulated industries)
- CI/CD caching strategy depends on exact image
- Known compatibility issues with newer OS versions
- Need to freeze entire stack for extended periods

### Verification in Production

Use image digests for maximum reproducibility:

```dockerfile
FROM python:3.12-slim@sha256:abc123...
```

But let CI rebuild and update digest regularly to get security patches.

## User Creation: UID/GID Strategy

### Default Approach (Simple)

Let the system auto-assign UID/GID:

```dockerfile
# Debian/Ubuntu
RUN groupadd -r app && useradd -r -g app app

# Alpine
RUN addgroup -S app && adduser -S -G app app
```

### Explicit UID/GID (Consistency)

When you need consistent permissions across environments:

```dockerfile
# Debian/Ubuntu - Use UID/GID >10000
RUN groupadd -r -g 10001 app && \
    useradd -r -l -u 10001 -g app app

# Alpine
RUN addgroup -g 10001 app && \
    adduser -u 10001 -G app -S app
```

### Why >10000?

- Avoids conflicts with system users (typically <1000)
- Avoids conflicts with regular host users (typically 1000-9999)
- Safe range for containerized applications
- Kubernetes and orchestrators often enforce similar ranges

### When to Use Explicit UID/GID

- Volume mounts need specific file ownership
- Multi-container setups requiring shared file access
- Security policies mandate specific UID ranges
- Kubernetes SecurityContext with `runAsUser`
- NFS or shared storage with strict permission requirements

### Complete Pattern

```dockerfile
FROM python:3.12-slim

# Create non-root user with explicit UID/GID
RUN groupadd -r -g 10001 app && \
    useradd -r -l -u 10001 -g app app

WORKDIR /app
RUN chown app:app /app

USER app

# Rest of Dockerfile...
```

## Essential Rules

### 1. Always use `COPY` instead of `ADD`

**Why:** `ADD` has implicit behaviors (archive extraction, URL downloads) that create non-deterministic builds.

**Risk with ADD:**
- Unexpected cache invalidation
- Downloaded content cannot be verified
- Misleading behavior (auto-extraction)

**Best practice:**
```dockerfile
COPY ./mydir /app/mydir
```

### 2. Minimize layers and group RUN instructions

**Why:** Each `RUN`, `COPY`, or `ADD` creates a new layer. Combining related commands avoids bloat.

**Best practice:**
```dockerfile
RUN apt-get update && \
    apt-get install -y curl git && \
    rm -rf /var/lib/apt/lists/*
```

### 3. Use multi-stage builds

**Why:**
- Prevents unnecessary tools in final image
- Reduces size and improves security
- Separates build and runtime concerns

**Best practice:**
```dockerfile
FROM golang:1.21 AS builder
WORKDIR /src
COPY . .
RUN go build -o app

FROM scratch
COPY --from=builder /src/app /app
ENTRYPOINT ["/app"]
```

### 4. Handle secrets securely with BuildKit

**Critical:** Never expose secrets with `ARG` or `ENV` - they're stored in image history.

**Best practice:**
```dockerfile
# syntax=docker/dockerfile:1

RUN --mount=type=secret,id=api_key \
    curl -H "Authorization: Bearer $(cat /run/secrets/api_key)" https://api.example.com
```

### 5. Reuse cache with `--mount=type=cache`

**Why:** Speeds up builds by caching install/download steps

**Best practice:**
```dockerfile
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
```

### 5a. Configure APT for cache mounts (Debian-based images)

**Critical step:** Before using cache mounts with APT, configure it to keep downloaded packages:

```dockerfile
RUN rm -f /etc/apt/apt.conf.d/docker-clean; \
    echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache
```

**Then use cache mounts:**
```dockerfile
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y curl
```

### 6. Always use a `.dockerignore`

**Why:**
- Reduces build context size
- Prevents copying secrets or junk files

**Example entries:**
```dockerignore
.git
node_modules
.env
*.log
dist/
```

### 7. Use heredocs for inline scripts

**Best practice:**
```dockerfile
RUN <<EOF
apk add curl
curl -fsSL https://example.com/setup.sh | sh
EOF
```

## Security Best Practices

### Set USER to non-root

```dockerfile
RUN addgroup --system app && adduser --system --ingroup app appuser
USER appuser
```

### Set explicit base image versions

```dockerfile
FROM alpine:3.19
```

**Note:** While SHA256 pinning provides maximum reproducibility, it can complicate dependency updates and security patches. Use version tags that balance stability with maintainability.

### Use HEALTHCHECK

```dockerfile
HEALTHCHECK --interval=30s --timeout=3s \
  CMD curl -f http://localhost/ || exit 1
```

## PID 1 Signal Handling

Containers rely on the process at PID 1 to handle signals (SIGTERM, SIGINT) correctly for graceful shutdown.

### The Problem

Shell form (`CMD myapp`) runs the app as a child of `/bin/sh`. The shell does not forward signals, so the app never receives SIGTERM and Docker must SIGKILL it after the timeout (default 10s).

### Solutions

**1. Use exec form (always):**

```dockerfile
# ✅ App runs as PID 1, receives signals directly
CMD ["python", "-m", "myapp"]
ENTRYPOINT ["node", "server.js"]

# ❌ App runs as child of /bin/sh, signals lost
CMD python -m myapp
ENTRYPOINT node server.js
```

**2. Use `tini` or `dumb-init` for proper init:**

```dockerfile
# Install tini (Alpine)
RUN apk add --no-cache tini
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["python", "-m", "myapp"]

# Install tini (Debian/Ubuntu)
RUN apt-get update && apt-get install -y --no-install-recommends tini
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "myapp"]
```

**Benefits of tini/dumb-init:**

- Forwards signals to child processes
- Reaps zombie processes (PID 1 responsibility)
- Lightweight (~30KB)
- Docker has `--init` flag as runtime alternative

**3. Use `exec` in shell entrypoint scripts:**

```bash
#!/bin/sh
# Setup tasks...
export CONFIG_LOADED=true
# exec replaces shell with app process (becomes PID 1)
exec python -m myapp "$@"
```

**4. Set STOPSIGNAL if app expects non-SIGTERM:**

```dockerfile
# Nginx expects SIGQUIT for graceful shutdown
STOPSIGNAL SIGQUIT
```

## SHELL Pipefail

By default, `RUN` commands use `/bin/sh -c`, which only checks the exit code of the **last** command in a pipeline. A failing command before a pipe is silently ignored.

### The Problem

```dockerfile
# If curl fails, wc still runs and the RUN succeeds!
RUN curl -fsSL https://example.com/list | wc -l
```

### Solution

```dockerfile
# Set pipefail so any failure in a pipeline fails the RUN
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN curl -fsSL https://example.com/list | wc -l
```

**When to use:** Any `RUN` instruction that uses pipes (`|`).

**When NOT to use:** Alpine images use `ash` by default (no bash). Either install bash or use inline `set -o pipefail`:

```dockerfile
RUN set -o pipefail && curl -fsSL https://example.com/list | wc -l
```

## COPY --chmod

### The Problem

OverlayFS stores files with their original permissions. If you `COPY` then `RUN chmod`, the file exists in **two layers** (original + modified), doubling its size on disk.

### Solution

```dockerfile
# ✅ Single layer, correct permissions
COPY --chmod=755 entrypoint.sh /entrypoint.sh
COPY --chmod=644 config.yaml /app/config.yaml

# ❌ Two layers, file stored twice
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh
```

**Requirements:** BuildKit (`# syntax=docker/dockerfile:1`)

**Also works with `--chown`:**

```dockerfile
COPY --chown=app:app --chmod=755 entrypoint.sh /entrypoint.sh
```

## Alpine/musl vs glibc

Alpine Linux uses musl libc instead of glibc. While Alpine images are much smaller, musl has important behavioral differences.

### Known Issues

| Area | musl (Alpine) | glibc (Debian/Ubuntu) |
|------|---------------|----------------------|
| DNS resolution | Uses different resolver, no mDNS | Full resolver with NSS support |
| Python C extensions | May fail to compile or crash | Full compatibility |
| Locale support | Minimal (no full locale) | Full locale support |
| Stack size default | 80KB (can cause segfaults) | 8MB |
| Performance | Slower for some workloads | Generally faster for compute |
| Binary compat | Only musl-linked binaries | Most Linux binaries work |

### When to Use Alpine

- **Good:** Go static binaries, Node.js, Nginx, simple tools
- **Avoid:** Python with C extensions (numpy, pandas, scipy), Java (use `-slim`), apps needing full locale

### Alternatives for Small + glibc

- **Debian slim** variants (`python:3.12-slim`) — good balance
- **Distroless** images — minimal glibc-based
- **Chainguard/Wolfi** images — small, glibc-based, security-focused

## OCI Labels and Annotations

Use standardized OCI labels for image traceability and metadata.

### Standard Keys

```dockerfile
LABEL org.opencontainers.image.title="My App" \
      org.opencontainers.image.description="Short description" \
      org.opencontainers.image.version="1.2.3" \
      org.opencontainers.image.authors="team@example.com" \
      org.opencontainers.image.url="https://github.com/org/repo" \
      org.opencontainers.image.source="https://github.com/org/repo" \
      org.opencontainers.image.licenses="MIT"
```

### Dynamic Labels with Build Args

```dockerfile
ARG BUILD_DATE
ARG VCS_REF
ARG VERSION

LABEL org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${VERSION}"
```

```bash
docker buildx build \
  --build-arg BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --build-arg VCS_REF=$(git rev-parse --short HEAD) \
  --build-arg VERSION=1.2.3 \
  -t myapp:1.2.3 .
```

## HEALTHCHECK Advanced Tuning

### Parameters

```dockerfile
HEALTHCHECK \
  --interval=30s \
  --timeout=3s \
  --start-period=30s \
  --start-interval=5s \
  --retries=3 \
  CMD <check command>
```

- **`start-period`**: Grace period during startup (health failures don't count)
- **`start-interval`** (Docker 25+): Check frequency during start period (faster detection)

### Check Commands by Image Type

| Image type | Check command |
|-----------|---------------|
| Has curl | `curl -f http://localhost:PORT/health \|\| exit 1` |
| Has wget | `wget -qO- http://localhost:PORT/health \|\| exit 1` |
| Minimal/distroless | Use app-native check or compiled binary |
| Database | `pg_isready`, `mysqladmin ping`, `redis-cli ping` |

### Complete Pattern

```dockerfile
# Web application
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Without curl (Python)
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1
```

## Docker Build Checks

Docker BuildKit includes a built-in linter (since Docker Desktop 4.33+ / Buildx 0.15+).

### Usage

```bash
# One-time check (doesn't build)
docker buildx build --check .
```

### Embed in Dockerfile

```dockerfile
# syntax=docker/dockerfile:1
# check=error=true

FROM python:3.12-slim
# ... build checks will fail the build on warnings
```

### Skip Specific Checks

```dockerfile
# check=skip=SecretsUsedInArgOrEnv
```

### Compose Integration

```yaml
services:
  app:
    build:
      context: .
      additional_contexts:
        check: "true"
```

## Build Parallelization

### Parallel Make Jobs

Speed up compilation inside `RUN` with parallel jobs:

```dockerfile
# Use all available CPUs for make
RUN make -j$(nproc)
```

### Independent Build Stages

BuildKit automatically parallelizes independent stages:

```dockerfile
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/ .
RUN npm ci && npm run build

FROM python:3.12-slim AS backend
WORKDIR /app/backend
COPY backend/ .
RUN pip install -r requirements.txt

FROM python:3.12-slim
COPY --from=frontend /app/frontend/dist /app/static
COPY --from=backend /app/backend /app
```

Both `frontend` and `backend` stages build in parallel automatically.

## Optimization Checklist

| ✅ Best Practice                              | 📌 Reason                              |
| --------------------------------------------- | -------------------------------------- |
| Use `COPY` instead of `ADD`                   | Predictable and safe                   |
| Use `COPY --link`                             | Faster and more secure                 |
| Implement multi-stage builds                  | Produces small, secure images          |
| Use `--mount=type=cache` for caching          | Speeds up install and download steps   |
| Use `--mount=type=secret` for secrets         | Prevents secret leaks                  |
| Include a `.dockerignore` file                | Keeps build context clean              |
| Set `USER` to non-root user                   | Runs containers more securely          |
| Pin explicit base image versions              | Ensures reproducible builds            |
| Remove unnecessary files to reduce image size | Creates smaller, more efficient images |
| Use `HEALTHCHECK` to monitor container health | Ensures reliable container operation   |
| Avoid installing unnecessary packages         | Keeps images smaller and secure        |
| Prefer `COPY --chown=user:group`              | Sets correct file ownership            |
| Use `COPY --chmod` instead of `RUN chmod`     | Avoids extra layer and size bloat      |
| Use exec form CMD/ENTRYPOINT                  | Enables proper signal handling (PID 1) |
| Set `SHELL` with pipefail for piped commands  | Catches failures in pipe chains        |
| Add OCI labels for traceability               | Standard metadata for images           |
| Use non-root users with limited permissions   | Enhances runtime security              |

## Quick Wins by Impact

### 🔥 High Impact (do these first)
1. Use multi-stage builds
2. Add `.dockerignore`
3. Use `--mount=type=cache` for dependencies
4. Pin base image versions

### ⚡ Medium Impact
1. Minimize layers (chain RUN commands)
2. Use slim/alpine base images
3. Order instructions for cache efficiency
4. Clean up in same RUN instruction

### 🎯 Low Impact (polish)
1. Use heredocs for complex scripts
2. Add HEALTHCHECK
3. Use COPY --link
4. Add labels and metadata
