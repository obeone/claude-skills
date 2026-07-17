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

### 1. Layer Content, Not Layer Count

"Minimize the number of layers" is a pre-BuildKit reflex. BuildKit builds a DAG,
caches layers by content, and pulls layers in parallel, so the layer *count* is
close to irrelevant to both image size and build speed. Chasing a lower count by
welding unrelated commands into one `RUN` actively hurts: it widens the cache
blast radius, so an unrelated change rebuilds the whole thing.

Layer **content** is what matters, for one reason:

> A layer records the bytes written while it ran. A later layer that deletes
> those bytes only adds a whiteout marker on top. The original bytes stay in the
> image, and you still ship and pull them.

That is a statement about deleted bytes, not about the number of `RUN` lines.
The rule it implies is narrow and concrete:

**Cleanup must happen in the same instruction that created the files.**

```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends package1 package2 && \
    rm -rf /var/lib/apt/lists/*
```

Split that into `RUN apt-get install ...` followed by a separate
`RUN rm -rf /var/lib/apt/lists/*` and the package lists stay in the first layer
forever: the image is exactly as large as if you had never cleaned up. Note what
the rule does *not* say. Two `RUN` instructions that each clean up after
themselves are fine. One `RUN` that installs and never cleans up is not. The
count was never the variable.

Corollary: an instruction that writes nothing you would want to delete does not
need to be merged with anything. Splitting `COPY` steps to improve cache hits
(see [Instruction Ordering for Cache Hits](#instruction-ordering-for-cache-hits))
is a win, not a layer-count sin.

**The two apt flags above are orthogonal.** They are easy to lump together and
they solve different problems:

- **`rm -rf /var/lib/apt/lists/*` is the one that has an alternative.** Its job
  is keeping the apt lists out of the layer. An apt cache mount (see
  [Cache Mounts](#cache-mounts-run---mounttypecache)) achieves the same thing by
  moving those paths out of the layer entirely. Pick one. Do **not** do both:
  with a cache mount on `/var/lib/apt`, the `rm -rf` purges the very cache you
  mounted it to keep, so you get the maintenance of a cache and none of the
  speed.
- **`--no-install-recommends` never has an alternative.** It controls what apt
  *installs into `/usr`*, which is to say what lands in the layer in the first
  place. A cache mount only relocates downloaded `.deb` files and lists; it does
  nothing about recommended packages being installed. Keep
  `--no-install-recommends` always, whichever choice you made above.

The analyzer encodes exactly this: DL007 accepts a cache mount *or* the `rm -rf`
and is satisfied by either, while DL019 asks for `--no-install-recommends`
independently of both.

See `references/best_practices.md`, which argues the same rule from the
image-size side.

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

Choose by what you are shipping, not by which row of a table looks smallest.

**The decision:**

- **A static binary** (Go with `CGO_ENABLED=0`, Rust against musl): `scratch` or
  `gcr.io/distroless/static-debian13:nonroot`. There is no libc question,
  because you are not linking one at runtime.
- **Anything with C extensions** (Python wheels, native Node modules, anything
  that loads glibc at runtime): **Debian slim** while you are building and
  debugging, **distroless** for the production runtime. Both are glibc, so the
  prebuilt wheels your ecosystem publishes actually apply to you.
- **Your organization counts CVEs**: a hardened base (Docker Hardened Images, or
  Chainguard/Wolfi). This is an organizational answer, not a technical one. You
  are buying a rebuild cadence and attestations, not a smaller image.
- **Alpine for a glibc-linked ecosystem**: only once you have measured the build
  cost and accepted it. See the musl note below.

**Reference sizes** (approximate, and they move):

| Image type | Size | libc | What it is for |
| --- | --- | --- | --- |
| Ubuntu / Debian | 30-100 MB | glibc | Full environment, maximum compatibility |
| Debian slim | 25-70 MB | glibc | Default for glibc-linked runtimes |
| Alpine | 5-15 MB | musl | Static binaries, or measured musl builds |
| Distroless | 2-100 MB | glibc | Production runtime, no shell |
| Hardened (DHI, Chainguard) | Varies | glibc or musl | CVE posture and attestations |
| `scratch` | 0 MB | None | Static binaries only |

#### Hardened base images

Two options exist if the driver is vulnerability posture rather than size.

**Docker Hardened Images (DHI)** launched commercially in May 2025. In
mid-December 2025 Docker made the whole 1,000-plus image catalogue free and open
source under Apache 2.0. Every image, including the free Community tier, ships an
SBOM, SLSA Build Level 3 provenance, a signature, and OpenVEX data. Docker
markets these as having up to 95 percent fewer vulnerabilities; treat that as a
vendor claim rather than a measurement, and check the numbers against your own
scanner. One thing that is not free: the 7-day critical-CVE remediation SLA is
exclusive to the paid tiers. If the SLA is the reason you are adopting DHI, you
are buying a subscription, not just pulling a free image.

**Chainguard Images**, built on the Wolfi undistro, are the other option in this
category, with a comparable low-to-zero-CVE and signed-attestation pitch.

For either one, the value is the vendor's rebuild cadence plus the attestations,
not the base itself. That is the same argument as
[Pinning](#4-pinning-a-tag-is-documentation-not-a-mechanism) below: what protects
you is a process that rebuilds, not a string in a `FROM` line.

#### The honest musl caveat

The folklore says "Alpine breaks DNS in Kubernetes". That mostly traces to musl's
stub resolver having no DNS-over-TCP fallback, so replies too large for a UDP
packet came back truncated. musl 1.2.4 (released 2023-05-01) added the TCP
fallback, and it first shipped in Alpine 3.18.0. On any current Alpine that
specific problem is fixed. Do not reject Alpine over it, and do not repeat the
claim.

What is still true, and is the real reason to think twice:

- **Build time and wheel availability for C extensions.** Python does publish
  musllinux wheels (PEP 656), but coverage is thinner than manylinux. When a
  wheel is missing, pip falls back to compiling from source, which means a
  toolchain in the build stage and an install that takes minutes instead of
  seconds. Native Node modules hit the same wall.
- musl and glibc are genuinely different implementations, with different
  allocators. Performance and edge-case behavior differ. Measure, do not assume.

### 4. Pinning: a tag is documentation, not a mechanism

The most common error in this area is treating "receives security patches" and
"reproducible" as properties of a tag string. They are properties of a
**process**.

1. **Pin a readable tag, as specific as you are willing to maintain.**
   `python:3.12-slim` is fine. `python:3.12-slim-bookworm` is equally fine: an
   OS-pinned tag is a legitimate stability choice, not a mistake.
1. **`:latest` and untagged images stay rejected** (DL002 error, DL003 warning).
   Not because mutability is uniquely evil there, but because they carry zero
   information about what you are actually running.
1. **Every tag is mutable.** `python:3.12-slim` today and `python:3.12-slim` in
   six months are different bytes. A tag is documentation and a rough contract,
   not a reproducibility mechanism. Implying otherwise is the actual hazard.
1. **Security updates come from rebuilding regularly**, not from your choice of
   tag. A floating tag patches nothing by itself: it patches when someone
   rebuilds. Name the process, not the string.
1. **Reproducibility, when you need it, comes from a process**: digest pinning
   backed by Renovate or Dependabot, or recording the resolved digest in build
   metadata. Provenance attestations do exactly the latter, so see
   `references/supply_chain.md` rather than rebuilding the argument here.

**Digests, honestly.** A digest (`FROM python:3.12-slim@sha256:<digest>`) is the
strongest guarantee available: it names exact bytes. It also comes with a
maintenance bill. Without renewal automation, a digest is just a tag that rots
silently, and you ship known CVEs while feeling rigorous, which is worse than a
floating tag you rebuild every month. Most teams do not have that automation. Use
digests if you do; do not adopt them as a default because they look serious.

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
# syntax=docker/dockerfile:1

# Build stage: full toolchain
FROM golang:1-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-w -s" -o main

# Runtime stage: minimal
FROM scratch
COPY --from=builder --chown=10001:10001 /app/main /main
# Numeric: scratch has no /etc/passwd, so there is no name to resolve
USER 10001:10001
ENTRYPOINT ["/main"]
```

Both IDs are numeric on purpose, because `scratch` has no `/etc/passwd` and there
is no name to resolve. The two instructions fail differently, and neither failure
looks like you would expect:

- `COPY --chown=app:app` fails the **build**, with `invalid user index: -1`.
  There is no passwd file at all, so BuildKit cannot even attempt the lookup.
- `USER app` **builds fine, exit 0**, and the image is broken. It only falls over
  at `docker run`, with `unable to find user app: no matching entries in passwd
  file`. Nothing in the build catches it.

Numeric IDs sidestep both: they need no lookup. Note that the kernel only ever
deals in numbers anyway, so `USER 10001:10001` is what `USER app` would have
resolved to. You are skipping a translation step, not losing anything.

### Benefits

- **Massive size reduction:** Final image contains only runtime artifacts
- **Security:** No build tools, compilers, dev dependencies in production
- **Clear separation:** Build vs runtime concerns
- **BuildKit optimization:** Only builds stages needed for target

### Advanced Usage

**Named stages:**

```dockerfile
FROM node:22-alpine AS builder
# ...

FROM nginx:1.29-alpine AS runtime
COPY --from=builder /app/dist /usr/share/nginx/html
```

**Copy from external images:**

```dockerfile
COPY --from=nginx:1.29-alpine /etc/nginx/nginx.conf /etc/nginx/
```

The tag rules apply to `COPY --from` exactly as they do to `FROM`: this pulls a
real image, so `--from=nginx:latest` would make the build depend on whatever
`latest` happens to be that day. The analyzer only inspects `FROM` lines, so it
will not catch a `:latest` hiding here. You have to.

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
| --- | --- | --- | --- | --- |
| COPY | ✅ | ❌ | ❌ | **Preferred** |
| ADD | ✅ | ✅ | ✅ | Avoid |

**Always use COPY** unless you specifically need URL download or tar extraction.

**COPY --link (BuildKit):**

```dockerfile
COPY --link . /app
```

- Better cache reuse in multi-stage builds
- Prevents duplication in cache

### ARG vs ENV

| Feature | ARG | ENV |
| --- | --- | --- |
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
   - Choose by what you ship: static binary, C extensions, or CVE posture
   - Pin a readable tag as specific as you will maintain (`python:3.12-slim`)
   - Never `:latest`, never untagged
   - Rebuild on a schedule: that, not the tag, is what patches you

3. **Build context:**
   - Create comprehensive `.dockerignore`

4. **Layer optimization:**
   - Order: manifests → deps → code
   - Cleanup in the same instruction that created the files
   - Optimize layer content, not layer count

5. **Cache mounts:**
   - `RUN --mount=type=cache,target=<cache_dir>`
   - For all package managers

6. **Multi-stage builds:**
   - Build stage: full toolchain
   - Runtime stage: minimal image + artifacts only

7. **Security:**
   - Never use ARG/ENV for secrets
   - Use `RUN --mount=type=secret`
   - Create the non-root user before any `--chown` naming it; put `USER` last
   - Add a HEALTHCHECK that uses a shipped binary and fails on non-2xx
     (and remember Kubernetes ignores it, see the complete example above)

8. **Instructions:**
   - Prefer COPY over ADD
   - Use COPY --link when appropriate
   - Use heredocs for complex scripts

9. **Remote cache (CI/CD):**
   - `--cache-from` / `--cache-to` with registry

### Impact Matrix

| Technique | Size Impact | Speed Impact | Security Impact |
| --- | --- | --- | --- |
| Multi-stage | 🔥🔥🔥 | ⚡⚡ | 🛡️🛡️🛡️ |
| Cache mounts | --- | 🔥🔥🔥 | --- |
| Base image choice | 🔥🔥 | ⚡ | 🛡️🛡️ |
| .dockerignore | ⚡⚡ | ⚡⚡ | 🛡️ |
| Layer ordering | --- | 🔥🔥 | --- |
| Secret mounts | --- | --- | 🛡️🛡️🛡️ |
| Non-root user | --- | --- | 🛡️🛡️ |
| Remote cache | --- | 🔥🔥🔥 | --- |

Legend: 🔥 = Impact level (1-3)

---

## Complete Example (FastAPI + Python + uv)

```dockerfile
# syntax=docker/dockerfile:1

# --- Build stage ---
FROM python:3.12-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /uvx /bin/

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

# Create the user BEFORE anything names it, then switch. USER goes last.
RUN groupadd -r -g 10001 app && useradd -r -u 10001 -g app app && \
    chown -R app:app /app
USER app

# Activate venv
ENV PATH="/app/.venv/bin:$PATH"

# Healthcheck: stdlib only, and urlopen raises on non-2xx
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Features demonstrated:**

- BuildKit syntax directive
- Multi-stage build
- uv for fast dependency management
- Cache mounts for uv
- Intermediate layers (deps separate from code)
- Non-editable install in builder
- Slim base image
- Non-root user created before the `chown` that names it
- Healthcheck that actually fails on a broken service
- Copy only venv to runtime (not source code)

**The user ordering is load-bearing.** The `RUN` that creates `app` comes before
anything that refers to `app` by name, and `USER app` comes last, after every
step that needed root. Get that backwards, by putting a `COPY --chown=app:app`
above the `useradd`, and the build does **not** fail: it exits 0 and quietly
drops the `--chown`, leaving the files owned by root. The container then starts
happily and dies the first time it tries to write. There is no build-time check
for this, which is exactly why it survives code review.

**Two things worth reading closely in that healthcheck**, because the obvious
version of it is wrong:

- **It uses only what the image ships.** `python:3.12-slim` has Python, so a
  stdlib one-liner always runs. The tempting `import requests` does not: nothing
  installs `requests` into the runtime stage unless your project depends on it,
  and a healthcheck that crashes on `ImportError` reports unhealthy for a reason
  that has nothing to do with your service. `wget` is not an option here either,
  since Debian slim does not ship it (Alpine does, via busybox).
- **It fails on a non-2xx, not merely on connection refused.**
  `urllib.request.urlopen` raises `HTTPError` on 4xx and 5xx, so a service
  returning 500 is correctly marked unhealthy. `requests.get()` does **not**
  raise on 500: it returns a response object and exits 0, so the classic
  `python -c "import requests; requests.get(...)"` check reports *healthy* for a
  service that is failing every request. That is worse than having no healthcheck
  at all, because it looks like coverage.

**Also: Kubernetes ignores `HEALTHCHECK` entirely.** It never reads the
instruction and runs its own `livenessProbe` / `readinessProbe` / `startupProbe`
instead. `HEALTHCHECK` is useful for plain `docker run`, Compose (`depends_on`
with `condition: service_healthy`), and Swarm. If Kubernetes is your only target,
the instruction is documentation, and the probes in your manifests are the thing
that has to be correct.

## Multi-Architecture Builds

Build images that run on multiple CPU architectures (AMD64, ARM64) from a single Dockerfile.

### Why Multi-Arch?

- **Apple Silicon** - ARM64 Macs (M1/M2/M3)
- **AWS Graviton** - ARM64 instances (better price/performance)
- **Raspberry Pi** - ARM devices
- **Cloud flexibility** - Run on any platform
- **Future-proof** - ARM adoption increasing

### The one thing that makes multi-arch builds fast: `$BUILDPLATFORM`

This is the whole game, and it is the part most multi-arch guides leave out.

When you ask for `--platform linux/amd64,linux/arm64`, BuildKit runs each
target's build. A plain `FROM golang:1-alpine` means "give me the *target*
platform's image", so for the arm64 target on an amd64 runner, every `RUN` in
that stage executes under **QEMU emulation**: an emulated compiler, running an
emulated linker, doing emulated I/O. Emulated compilation is routinely an order
of magnitude slower than native. A Go build that takes 40 seconds natively can
sit there for 10 minutes, and CI bills you for all of it.

`FROM --platform=$BUILDPLATFORM` pins the *build* stage to the architecture of
the machine doing the building, so the toolchain always runs natively. You then
cross-compile to the target using the `TARGETOS` / `TARGETARCH` args BuildKit
provides for free:

```dockerfile
FROM --platform=$BUILDPLATFORM golang:1-alpine AS builder
ARG TARGETOS
ARG TARGETARCH
RUN CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} go build -o /out/server
```

The compiler runs native; only the *output* is foreign. Both target images get
built by one native toolchain, and the emulator never starts. This works for any
toolchain with real cross-compilation (Go, Rust, .NET). It does not rescue a
build whose slow step is genuinely target-native, such as compiling C extensions
against the target's libc, and QEMU remains the fallback there.

Two BuildKit build checks guard this area, and both are worth knowing because
they catch the two ways people get the pattern wrong. See
`references/build_checks.md` for the full rule list and how to run
`docker build --check`:

- **`FromPlatformFlagConstDisallowed`** fires when you hardcode a constant, as in
  `FROM --platform=linux/amd64`. That defeats the point: it nails the stage to
  one architecture, so the arm64 build silently produces an amd64 image or falls
  back to emulation. Use the `$BUILDPLATFORM` variable, never a literal.
- **`RedundantTargetPlatform`** fires on `FROM --platform=$TARGETPLATFORM`, which
  is already the default. It is harmless but noise, and it suggests the author
  thought it was doing something.

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
# syntax=docker/dockerfile:1

FROM alpine:3

ARG TARGETARCH

WORKDIR /app

# Download correct binary for architecture. Still root here: the download and
# extraction need to write into /app before ownership is settled.
RUN case "$TARGETARCH" in \
      "amd64") ARCH="x86_64" ;; \
      "arm64") ARCH="aarch64" ;; \
      *) echo "Unsupported arch: $TARGETARCH" && exit 1 ;; \
    esac && \
    wget https://example.com/tool-${ARCH}.tar.gz && \
    tar xzf tool-${ARCH}.tar.gz && \
    rm tool-${ARCH}.tar.gz

# Create the user, then switch. USER goes last, after everything root had to do.
RUN addgroup -g 10001 app && \
    adduser -u 10001 -G app -S app && \
    chown -R app:app /app
USER app

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

1. **Run the toolchain on the build platform:**

   ```dockerfile
   # Native toolchain, no QEMU. See the $BUILDPLATFORM section above.
   FROM --platform=$BUILDPLATFORM node:22-alpine AS builder
   ```

1. **Separate arch-specific layers:**

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

Name the Debian release explicitly. The unversioned aliases (`distroless/static`,
`distroless/python3`, and friends) are deprecated upstream: they still resolve,
but they roll forward to the next Debian release on their own, which is a base
image change you did not ask for and did not review. The `-debian13` repos are
the ones Google publishes and updates.

| Image | Use Case | Contains |
| --- | --- | --- |
| `gcr.io/distroless/static-debian13` | Static binaries (Go, Rust) | ca-certificates, tzdata, `/tmp`, a root `/etc/passwd` entry. **No libc** |
| `gcr.io/distroless/base-nossl-debian13` | Needs libc, not libssl | `static` plus glibc |
| `gcr.io/distroless/base-debian13` | Dynamically linked binaries | `static` plus glibc and libssl |
| `gcr.io/distroless/cc-debian13` | C/C++, cgo | `base` plus libgcc, libstdc++ |
| `gcr.io/distroless/python3-debian13` | Python apps | Python 3 runtime |
| `gcr.io/distroless/nodejs22-debian13` | Node.js apps | Node.js 22 runtime |
| `gcr.io/distroless/java21-debian13` | Java apps | Java 21 runtime |

Each of those carries four tags: `latest`, `nonroot`, `debug`, and
`debug-nonroot`. Node also ships `nodejs24` and `nodejs26`, and Java ships
`java17` and `java25`, on the same pattern. Anything outside the published set,
including `nodejs20-debian13`, still resolves but is deprecated and no longer
updated, which for a security-motivated base image defeats the entire purpose.

**Prefer `:nonroot` over writing your own `USER`.** There is no `groupadd` in a
distroless image, so the usual "create a user" `RUN` cannot work: there is no
shell to run it and no package to provide it. The `:nonroot` tag ships a
non-root user (UID 65532) already in `/etc/passwd`, so you declare
`USER nonroot:nonroot` and you are done.

### Pattern: Multi-Stage with Distroless

```dockerfile
# syntax=docker/dockerfile:1

# Build stage. The Python minor MUST match the runtime's: see below.
FROM python:3.13-slim AS builder

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Runtime stage (distroless)
FROM gcr.io/distroless/python3-debian13:nonroot

# Copy dependencies and app, handing them to the user that will run them
COPY --from=builder --chown=nonroot:nonroot /root/.local /home/nonroot/.local
COPY --from=builder --chown=nonroot:nonroot /app /app

WORKDIR /app
ENV PYTHONPATH=/home/nonroot/.local/lib/python3.13/site-packages

USER nonroot:nonroot

CMD ["app.py"]
```

This example is a minefield, and the obvious version of it fails at runtime with
`ModuleNotFoundError` while building perfectly. Three separate traps:

- **The Python minor versions must match.** `pip install --user` writes to
  `/root/.local/lib/python3.13/site-packages`, a path with the minor version
  baked into it. `gcr.io/distroless/python3-debian13` currently ships Python
  3.13, so a `python:3.12-slim` builder produces a `python3.12` directory that
  the 3.13 runtime never looks in. The dependencies are present in the image and
  invisible to the interpreter. Check the runtime's version rather than assuming
  it (`docker run --rm --entrypoint /usr/bin/python3
  gcr.io/distroless/python3-debian13:debug-nonroot -V`), and pin the builder to
  it. Note the coupling this creates: distroless bumps its Python minor on its
  own schedule, and when it does, this Dockerfile breaks. The
  [complete example](#complete-example-fastapi--python--uv) above avoids the
  whole problem by shipping a venv, which carries its own interpreter path.
- **`PATH` is not the right variable.** `PATH` finds executables; it has nothing
  to do with module imports. `PYTHONPATH` is what puts `site-packages` on
  `sys.path`.
- **`--user` installs are relative to a home directory that distroless does not
  advertise.** The image sets no `HOME`, so Python cannot resolve the per-user
  site directory on its own, which is why `PYTHONPATH` is spelled out explicitly
  rather than relying on `~/.local` being discovered. Copying to `/root/.local`
  and running as `nonroot`, as the older version of this example did, fails for
  the same family of reasons.

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
FROM gcr.io/distroless/static-debian13:nonroot

COPY --from=builder --chown=nonroot:nonroot /app /app
USER nonroot:nonroot
ENTRYPOINT ["/app"]
```

`CGO_ENABLED=0` is what earns `static-debian13`: the binary links no libc, and
`static` ships none. Drop that flag, or pull in a cgo-dependent package, and the
binary will need glibc at runtime and die with a loader error on `static`. That
is the case for `base-debian13` (glibc) or `cc-debian13` (glibc plus libstdc++).

### Node.js Example

```dockerfile
# syntax=docker/dockerfile:1

FROM node:22-alpine AS builder

WORKDIR /app
COPY package.json yarn.lock ./
RUN --mount=type=cache,target=/root/.yarn \
    yarn install --frozen-lockfile --production

COPY . .

# Distroless Node.js: major version matches the builder
FROM gcr.io/distroless/nodejs22-debian13:nonroot

COPY --from=builder --chown=nonroot:nonroot /app /app
WORKDIR /app
USER nonroot:nonroot

CMD ["index.js"]
```

Keep the builder's Node major and the runtime's Node major in step. Native
modules compiled by `yarn install` under Node 22 are built against that ABI, and
handing them to a different runtime major is how you get a `NODE_MODULE_VERSION`
mismatch at startup, long after the build went green.

### Version Pinning with Distroless

Earlier versions of this guide taught the opposite of what follows: they called
`distroless/python3` good and `distroless/python3-debian12` bad, on the theory
that naming the OS over-pins. That was wrong, and upstream has since settled the
question in the other direction.

```dockerfile
# Name the Debian release. This is the form Google publishes and updates.
FROM gcr.io/distroless/python3-debian13:nonroot
```

The unversioned `distroless/python3` is not "pinning the language and leaving the
OS free to be patched". It is an alias that will silently become the *next*
Debian release when Google cuts one. Nothing about that is a patch: it is a
whole-OS upgrade, arriving unannounced, on a rebuild you did for an unrelated
reason. Meanwhile `-debian13` gets patched exactly the same, because Google
rebuilds the versioned repos too. You give up nothing and you learn when the base
OS changes, because you have to type it.

This is the same argument as
[Pinning](#4-pinning-a-tag-is-documentation-not-a-mechanism) above, and it lands
the same way: `-debian13` is a readable tag as specific as you are willing to
maintain, and it patches when you rebuild. Reach for a digest only if you have
Renovate or Dependabot renewing it. Without that automation a pinned distroless
digest rots exactly like any other, and a security-motivated base image that
never gets rebuilt is just a slower way to ship CVEs.

### Debugging Distroless Images

Use debug variants during development:

```dockerfile
# Development - includes a busybox shell
FROM gcr.io/distroless/python3-debian13:debug-nonroot

# Production - no shell
FROM gcr.io/distroless/python3-debian13:nonroot
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

```text
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

```text
#5 RUN pip install -r requirements.txt (120s)
```

**Solution:** Use cache mounts

```dockerfile
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
```

#### 3. Large Dependency Downloads

**Problem:**

```text
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

```text
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
