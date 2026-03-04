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
    useradd -r -u 10001 -g app app

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
    useradd -r -u 10001 -g app app

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
