# Dockerfile Optimization: Complete Guide

Complete guide covering modern optimization techniques with BuildKit, historical context, and structured best practices.

## Table of Contents

1. [BuildKit and Modern Syntax](#buildkit-and-modern-syntax)
2. [Fundamental Optimization Principles](#fundamental-optimization-principles)
3. [Advanced Caching with BuildKit](#advanced-caching-with-buildkit)
4. [Multi-Stage Builds](#multi-stage-builds)
5. [Instruction-Specific Optimizations](#instruction-specific-optimizations)
6. [Structured Techniques Summary](#structured-techniques-summary)

---

## BuildKit and Modern Syntax

### Why BuildKit?

BuildKit became the default build engine in Docker Engine 23.0. It provides:

- **Performance:** Parallel execution of independent build steps
- **Better caching:** Content-addressable storage and DAG-based analysis
- **Storage optimization:** Automatic garbage collection
- **Extensibility:** Frontend-based architecture with LLB format

### The `# syntax` directive

**Critical:** Always start Dockerfiles with:

```dockerfile
# syntax=docker/dockerfile:1
```

**Benefits:**
1. **Decoupling:** Use latest syntax features without updating Docker Engine
2. **Consistency:** Same parser across all environments (dev, CI/CD)
3. **Access to features:** Cache mounts, heredocs, COPY --link, etc.

**Best practice:**
```dockerfile
# syntax=docker/dockerfile:1  # Latest stable v1
# or for specific version:
# syntax=docker/dockerfile:1.4
```

**Without this directive:** You may use an older embedded parser, missing optimizations and bug fixes.

### Available Frontend Channels

- **Stable** (recommended): `docker/dockerfile:1` - Gets automatic minor updates
- **Labs** (experimental): `docker/dockerfile:labs` - Test new features

---

## Fundamental Optimization Principles

### 1. Layer Minimization

Each `RUN`, `COPY`, or `ADD` creates a new layer. Chain related commands:

```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends package1 package2 && \
    rm -rf /var/lib/apt/lists/*
```

**Critical:** Cleanup in the SAME instruction:
- ❌ Wrong: `RUN install` then `RUN cleanup` → files persist in first layer
- ✅ Right: `RUN install && cleanup` → single layer, no waste

### 2. Build Context Management (.dockerignore)

The build context is all files sent to Docker daemon. Reduce it with `.dockerignore`:

```dockerignore
# Logs
*.log
logs/

# Dependencies
node_modules
__pycache__/

# Source control
.git
.gitignore

# Local configs
.env
*.local
```

**Benefits:**
- Faster context upload
- Better cache efficiency
- Prevents secret leaks

### 3. Base Image Selection

| Image Type       | Size    | Libc  | Use Case                    |
|-----------------|---------|-------|-----------------------------|
| Ubuntu/Debian   | 30-100MB| glibc | Full environment, max compat|
| Debian Slim     | 25-70MB | glibc | Good size/compat balance    |
| Alpine          | 5-15MB  | musl  | Minimal, Node/Python/Nginx  |
| Distroless      | 2-100MB | glibc | Max security, no shell      |
| Scratch         | 0MB     | none  | Static binaries only        |

**Pin versions for reproducibility:**

```dockerfile
# Good: Specific version
FROM alpine:3.19
```

**Note:** While SHA256 pinning offers maximum reproducibility, it can complicate updates and security patches. Use specific version tags that balance stability with maintainability.

---

## Advanced Caching with BuildKit

### Cache Mechanics

BuildKit uses:
- **DAG-based analysis:** Identifies independent steps for parallel execution
- **Content-addressable storage:** Cache based on actual content, not just instruction sequence
- **Fine-grained invalidation:** Smarter detection of what needs rebuilding

### Instruction Ordering for Cache Hits

Place less-frequently-changing instructions first:

```dockerfile
# 1. Copy dependency manifests (rarely change)
COPY package.json yarn.lock ./

# 2. Install dependencies (cached if manifests unchanged)
RUN yarn install --frozen-lockfile

# 3. Copy source code (changes frequently)
COPY . .
```

### Cache Mounts (`RUN --mount=type=cache`)

**Game changer:** Persistent cache directory across builds, not stored in image layers.

#### Examples by Package Manager

**APT:**
```dockerfile
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y curl
```

**pip:**
```dockerfile
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
```

**npm/yarn:**
```dockerfile
RUN --mount=type=cache,target=/root/.npm \
    npm ci --prefer-offline
```

**Maven:**
```dockerfile
RUN --mount=type=cache,target=/root/.m2 \
    mvn package -DskipTests
```

**Go:**
```dockerfile
RUN --mount=type=cache,target=/go/pkg/mod \
    go build -o app
```

**Cargo:**
```dockerfile
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    cargo build --release
```

**Composer:**
```dockerfile
RUN --mount=type=cache,target=/tmp/cache \
    composer install --no-dev
```

**Benefits:**
- Dramatically faster dependency installation
- No manual cleanup needed
- Cache persists across builds

### Remote Cache Backends

Share cache across machines/CI runners:

```bash
docker buildx build \
  --cache-from=type=registry,ref=myregistry.com/myapp:cache \
  --cache-to=type=registry,ref=myregistry.com/myapp:cache,mode=max \
  --push \
  -t myregistry.com/myapp:latest .
```

**Options:**
- `type=registry` - Store in Docker registry
- `type=local` - Local filesystem
- `type=gha` - GitHub Actions cache
- `type=s3` - S3 bucket (experimental)

---

## Multi-Stage Builds

### Concept

Separate build environment from runtime environment.

**Problem:** SDK, compilers, dev tools bloat final image.

**Solution:** Build in one stage, copy artifacts to minimal runtime stage.

### Pattern

```dockerfile
# Build stage: full toolchain
FROM golang:1.21-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-w -s" -o main

# Runtime stage: minimal
FROM scratch
COPY --from=builder /app/main /main
ENTRYPOINT ["/main"]
```

### Benefits

- **Massive size reduction:** Final image contains only runtime artifacts
- **Security:** No build tools, compilers, dev dependencies in production
- **Clear separation:** Build vs runtime concerns
- **BuildKit optimization:** Only builds stages needed for target

### Advanced Usage

**Named stages:**
```dockerfile
FROM node:20 AS builder
# ...

FROM nginx:alpine AS runtime
COPY --from=builder /app/dist /usr/share/nginx/html
```

**Copy from external images:**
```dockerfile
COPY --from=nginx:latest /etc/nginx/nginx.conf /etc/nginx/
```

**Target specific stage:**
```bash
docker build --target builder -t myapp:builder .
```

---

## Instruction-Specific Optimizations

### RUN

**Chain commands:**
```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl git && \
    rm -rf /var/lib/apt/lists/*
```

**Use heredocs for complex scripts:**
```dockerfile
RUN <<EOF
set -e
apk add curl
curl -fsSL https://example.com/setup.sh | sh
apk del curl
EOF
```

### COPY vs ADD

| Instruction | Local | URL | Auto-extract | Recommendation |
|------------|-------|-----|--------------|----------------|
| COPY       | ✅    | ❌  | ❌           | **Preferred**  |
| ADD        | ✅    | ✅  | ✅           | Avoid          |

**Always use COPY** unless you specifically need URL download or tar extraction.

**COPY --link (BuildKit):**
```dockerfile
COPY --link . /app
```
- Better cache reuse in multi-stage builds
- Prevents duplication in cache

### ARG vs ENV

| Feature | ARG | ENV |
|---------|-----|-----|
| Build-time | ✅ | ✅ |
| Runtime | ❌ | ✅ |
| In history | ⚠️ Yes | ⚠️ Yes |
| For secrets | ❌ Never | ❌ Never |

**Pattern: ARG → ENV:**
```dockerfile
ARG APP_VERSION=1.0
ENV APP_VERSION=$APP_VERSION

ARG NODE_ENV=production
ENV NODE_ENV=$NODE_ENV
```

**⚠️ NEVER for secrets:**
```dockerfile
# ❌ WRONG - Secrets exposed in history
ARG SECRET_KEY
ENV API_TOKEN=$SECRET_KEY

# ✅ RIGHT - Use secret mounts
RUN --mount=type=secret,id=api_key \
    curl -H "Authorization: Bearer $(cat /run/secrets/api_key)" https://api.example.com
```

### Secret Management

**BuildKit secret mounts:**
```dockerfile
# syntax=docker/dockerfile:1

RUN --mount=type=secret,id=api_token \
    export TOKEN=$(cat /run/secrets/api_token) && \
    curl -H "Authorization: Bearer $TOKEN" https://api.example.com
```

**Build command:**
```bash
docker buildx build --secret id=api_token,src=./token.txt .
# or from env:
docker buildx build --secret id=api_token,env=API_TOKEN .
```

**Benefits:**
- Secret never written to image layer
- Not in build history
- Temporary mount only during RUN

---

## Structured Techniques Summary

### Quick Reference Checklist

1. **Syntax directive:**
   - Use `# syntax=docker/dockerfile:1`

2. **Base image:**
   - Choose minimal: alpine, slim, distroless
   - Pin with SHA256: `FROM alpine:3.19@sha256:...`

3. **Build context:**
   - Create comprehensive `.dockerignore`

4. **Layer optimization:**
   - Order: manifests → deps → code
   - Chain RUN commands with `&&`
   - Cleanup in same instruction

5. **Cache mounts:**
   - `RUN --mount=type=cache,target=<cache_dir>`
   - For all package managers

6. **Multi-stage builds:**
   - Build stage: full toolchain
   - Runtime stage: minimal image + artifacts only

7. **Security:**
   - Never use ARG/ENV for secrets
   - Use `RUN --mount=type=secret`
   - Create non-root user
   - Add HEALTHCHECK

8. **Instructions:**
   - Prefer COPY over ADD
   - Use COPY --link when appropriate
   - Use heredocs for complex scripts

9. **Remote cache (CI/CD):**
   - `--cache-from` / `--cache-to` with registry

### Impact Matrix

| Technique | Size Impact | Speed Impact | Security Impact |
|-----------|-------------|--------------|-----------------|
| Multi-stage | 🔥🔥🔥 | ⚡⚡ | 🛡️🛡️🛡️ |
| Cache mounts | - | 🔥🔥🔥 | - |
| Base image choice | 🔥🔥 | ⚡ | 🛡️🛡️ |
| .dockerignore | ⚡⚡ | ⚡⚡ | 🛡️ |
| Layer ordering | - | 🔥🔥 | - |
| Secret mounts | - | - | 🛡️🛡️🛡️ |
| Non-root user | - | - | 🛡️🛡️ |
| Remote cache | - | 🔥🔥🔥 | - |

Legend: 🔥 = Impact level (1-3)

---

## Complete Example (FastAPI + Python + uv)

```dockerfile
# syntax=docker/dockerfile:1

# --- Build stage ---
FROM python:3.12-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.9.10 /uv /uvx /bin/

WORKDIR /app

# Install dependencies (cached separately from code)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev --no-editable

# Copy and install project
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# --- Runtime stage ---
FROM python:3.12-slim-bookworm

WORKDIR /app

# Copy only venv from builder
COPY --from=builder /app/.venv /app/.venv

# Create non-root user
RUN groupadd -r app && useradd -r -g app app && \
    chown -R app:app /app
USER app

# Activate venv
ENV PATH="/app/.venv/bin:$PATH"

# Healthcheck
HEALTHCHECK --interval=30s --timeout=3s \
  CMD python -c "import requests; requests.get('http://localhost:8000/health')" || exit 1

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Features demonstrated:**
- ✅ BuildKit syntax directive
- ✅ Multi-stage build
- ✅ uv for fast dependency management
- ✅ Cache mounts for uv
- ✅ Intermediate layers (deps separate from code)
- ✅ Non-editable install in builder
- ✅ Slim base image
- ✅ Non-root user
- ✅ Healthcheck
- ✅ Copy only venv to runtime (not source code)

## Multi-Architecture Builds

Build images that run on multiple CPU architectures (AMD64, ARM64) from a single Dockerfile.

### Why Multi-Arch?

- **Apple Silicon** - ARM64 Macs (M1/M2/M3)
- **AWS Graviton** - ARM64 instances (better price/performance)
- **Raspberry Pi** - ARM devices
- **Cloud flexibility** - Run on any platform
- **Future-proof** - ARM adoption increasing

### Basic Pattern

```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t myapp:latest \
  --push .
```

### Setup (One-Time)

```bash
# Create builder instance
docker buildx create --name mybuilder --use

# Bootstrap builder
docker buildx inspect --bootstrap
```

### Platform-Specific Code

Use `TARGETARCH` and `TARGETOS` build arguments:

```dockerfile
# syntax=docker/dockerfile:1

FROM python:3.12-slim

# Automatic build args
ARG TARGETARCH
ARG TARGETOS

# Platform-specific dependencies
RUN if [ "$TARGETARCH" = "arm64" ]; then \
      echo "Installing ARM-specific packages"; \
      apt-get update && apt-get install -y libssl-dev; \
    fi

# Works on both platforms
COPY . /app
```

### Download Platform-Specific Binaries

```dockerfile
FROM alpine:3

ARG TARGETARCH

WORKDIR /app

# Download correct binary for architecture
RUN case "$TARGETARCH" in \
      "amd64") ARCH="x86_64" ;; \
      "arm64") ARCH="aarch64" ;; \
      *) echo "Unsupported arch: $TARGETARCH" && exit 1 ;; \
    esac && \
    wget https://example.com/tool-${ARCH}.tar.gz && \
    tar xzf tool-${ARCH}.tar.gz && \
    rm tool-${ARCH}.tar.gz

ENTRYPOINT ["/app/tool"]
```

### Complete Multi-Arch Example

```dockerfile
# syntax=docker/dockerfile:1

FROM --platform=$BUILDPLATFORM golang:1-alpine AS builder

ARG TARGETARCH
ARG TARGETOS

WORKDIR /src

# Dependencies (cached)
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

# Build for target platform
COPY . .
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} \
    go build -ldflags="-w -s" -o /app/server

# Runtime stage
FROM alpine:3

RUN addgroup -g 10001 app && \
    adduser -u 10001 -G app -S app

USER app
COPY --from=builder /app/server /app/server

ENTRYPOINT ["/app/server"]
```

### Build and Push Multi-Arch

```bash
# Build for multiple platforms and push
docker buildx build \
  --platform linux/amd64,linux/arm64,linux/arm/v7 \
  -t registry.com/myapp:1.0.0 \
  -t registry.com/myapp:latest \
  --push .

# View manifest
docker buildx imagetools inspect registry.com/myapp:latest
```

### Performance Tips

1. **Use native builds when possible:**
   ```bash
   # Build only for current architecture (faster)
   docker buildx build --platform linux/$(uname -m) .
   ```

2. **Cache BUILDPLATFORM layers:**
   ```dockerfile
   # Use build platform for tools (faster)
   FROM --platform=$BUILDPLATFORM node:20-alpine AS builder
   ```

3. **Separate arch-specific layers:**
   ```dockerfile
   # Common layer (shared)
   COPY package.json .
   RUN npm install

   # Arch-specific layer (separate)
   RUN if [ "$TARGETARCH" = "arm64" ]; then ...; fi
   ```

### CI/CD Integration

```yaml
# GitHub Actions example
- name: Build multi-arch image
  uses: docker/build-push-action@v5
  with:
    platforms: linux/amd64,linux/arm64
    push: true
    tags: myapp:latest
    cache-from: type=gha
    cache-to: type=gha,mode=max
```

## Distroless Images for Maximum Security

Distroless images contain only your application and runtime dependencies - no shell, package managers, or OS utilities.

### What is Distroless?

- **Minimal attack surface** - No shell, no package manager
- **Smaller size** - Only runtime dependencies
- **Better security** - Fewer vulnerabilities to patch
- **Production-ready** - Google uses in production

### Available Distroless Images

| Image | Use Case | Contains |
|-------|----------|----------|
| `gcr.io/distroless/static` | Static binaries (Go, Rust) | glibc, ca-certificates |
| `gcr.io/distroless/base` | Dynamically linked binaries | glibc, libssl, openssl |
| `gcr.io/distroless/python3` | Python apps | Python 3.x runtime |
| `gcr.io/distroless/nodejs20` | Node.js apps | Node.js 20.x runtime |
| `gcr.io/distroless/java17` | Java apps | Java 17 runtime |
| `gcr.io/distroless/cc` | C/C++ apps | glibc, libgcc, libstdc++ |

### Pattern: Multi-Stage with Distroless

```dockerfile
# syntax=docker/dockerfile:1

# Build stage
FROM python:3.12-slim AS builder

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Runtime stage (distroless)
FROM gcr.io/distroless/python3

# Copy dependencies and app
COPY --from=builder /root/.local /root/.local
COPY --from=builder /app /app

WORKDIR /app
ENV PATH=/root/.local/bin:$PATH

CMD ["app.py"]
```

### Go Example (Static Binary)

```dockerfile
# syntax=docker/dockerfile:1

FROM golang:1-alpine AS builder

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /app

# Distroless static (smallest)
FROM gcr.io/distroless/static

COPY --from=builder /app /app
ENTRYPOINT ["/app"]
```

### Node.js Example

```dockerfile
# syntax=docker/dockerfile:1

FROM node:20-alpine AS builder

WORKDIR /app
COPY package.json yarn.lock ./
RUN yarn install --frozen-lockfile --production

COPY . .

# Distroless Node.js
FROM gcr.io/distroless/nodejs20

COPY --from=builder /app /app
WORKDIR /app

CMD ["index.js"]
```

### Version Pinning with Distroless

```dockerfile
# ✅ GOOD - Pin language, not OS
FROM gcr.io/distroless/python3

# ❌ BAD - Pinning OS version
FROM gcr.io/distroless/python3-debian12

# ✅ BEST - Use digest for production
FROM gcr.io/distroless/python3@sha256:abc123...
```

### Debugging Distroless Images

Use debug variants during development:

```dockerfile
# Development - includes busybox shell
FROM gcr.io/distroless/python3:debug

# Production - no shell
FROM gcr.io/distroless/python3
```

**Debug container:**

```bash
# Shell into debug image
docker run -it --entrypoint /busybox/sh myapp:debug

# Exec into running container
docker exec -it container-id /busybox/sh
```

### Trade-offs

**Pros:**

- Minimal attack surface
- Smaller image size
- No unnecessary tools
- Google production-tested
- Auto-updated base layers

**Cons:**

- No shell (harder debugging)
- Must copy all dependencies
- Limited distros available
- Learning curve

### When to Use Distroless

**Use distroless when:**

- Production deployments
- Security is critical
- You don't need shell access
- Standard runtime (Python, Node, Java, Go)

**Don't use distroless when:**

- Development environment
- Need debugging tools
- Custom OS dependencies
- Learning Docker (use alpine/slim first)

## Build Performance Profiling

Identify and fix slow builds systematically.

### Enable Plain Progress

```bash
docker buildx build --progress=plain . 2>&1 | tee build.log
```

**Output shows:**

- Time per instruction
- Cache hits/misses
- Layer sizes
- Download progress

### Analyze Build Time

```bash
# Build with timing
time docker buildx build -t myapp .

# Find slow layers
docker buildx build --progress=plain . 2>&1 | grep -E "^\#[0-9]+"
```

### Common Bottlenecks

#### 1. Large Build Context

**Problem:**

```
#1 [internal] load build context
#1 transferring context: 500MB (15s)
```

**Solution:** Add to `.dockerignore`

```dockerignore
node_modules/
.git/
*.log
dist/
build/
.venv/
__pycache__/
```

#### 2. Package Installation

**Problem:**

```
#5 RUN pip install -r requirements.txt (120s)
```

**Solution:** Use cache mounts

```dockerfile
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
```

#### 3. Large Dependency Downloads

**Problem:**

```
#6 RUN apt-get update && apt-get install (90s)
```

**Solution:** Cache apt downloads

```dockerfile
RUN rm -f /etc/apt/apt.conf.d/docker-clean; \
    echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y curl
```

#### 4. Cache Invalidation

**Problem:**

```
#7 COPY . . (invalidates all subsequent layers)
```

**Solution:** Separate dependencies from code

```dockerfile
# Dependencies first (rarely change)
COPY package.json yarn.lock ./
RUN yarn install

# Code last (changes frequently)
COPY . .
```

### Measuring Improvements

**Before:**

```bash
$ time docker buildx build -t myapp .
real    5m23s
```

**After optimizations:**

```bash
$ time docker buildx build -t myapp .
real    0m15s  # 95% faster (cache hit)
```

### CI/CD Build Time Optimization

```bash
# Use remote cache
docker buildx build \
  --cache-from=type=registry,ref=registry.com/myapp:cache \
  --cache-to=type=registry,ref=registry.com/myapp:cache,mode=max \
  -t myapp:latest .
```

**mode=max** exports all layers for caching (slower push, faster builds).

### Profile Tools

**Docker BuildKit metrics:**

```bash
# Enable experimental features
export DOCKER_BUILDKIT=1
export BUILDKIT_PROGRESS=plain

docker buildx build --progress=plain . 2>&1 | \
  grep -E "^#[0-9]+ \[" | \
  awk '{print $NF, $0}'
```

**Build timing summary:**

```bash
docker buildx build --progress=plain . 2>&1 | \
  grep "done" | \
  grep -oP "\d+\.\d+s" | \
  awk '{s+=$1} END {print "Total: " s "s"}'
```

### Best Practices Summary

1. **Minimize build context** - Use `.dockerignore`
2. **Use cache mounts** - For all package managers
3. **Optimize layer order** - Deps before code
4. **Multi-stage builds** - Separate build/runtime
5. **Remote cache** - Share cache across CI jobs
6. **Measure regularly** - Profile before optimizing
7. **Parallelize** - Use concurrent builds when possible
