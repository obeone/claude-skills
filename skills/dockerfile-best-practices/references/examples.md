# Dockerfile Optimization Examples

Real-world examples of Dockerfile optimizations using BuildKit.

## 🧪 1. APT with BuildKit cache mount

**Input:**

```dockerfile
FROM debian:bookworm
RUN apt-get update && apt-get install -y curl
```

**Optimized Output:**

```dockerfile
# syntax=docker/dockerfile:1

FROM debian:bookworm

# Configure APT to keep downloaded packages for cache
RUN rm -f /etc/apt/apt.conf.d/docker-clean; \
    echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache

# Use BuildKit cache mounts for APT metadata and package archives
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y curl
```

**Why it's better:**

- BuildKit cache avoids re-downloading on every build
- APT configured to keep packages in cache directories
- No need for manual cleanup (cache is external to image layers)
- Faster, cleaner builds with persistent mount

---

## 🔐 2. Secrets securely mounted (no ARG/ENV)

**Input (⚠️ INSECURE):**

```dockerfile
FROM alpine:3.19
ARG TOKEN
RUN curl -H "Authorization: Bearer $TOKEN" https://api.example.com
```

**Optimized Output:**

```dockerfile
# syntax=docker/dockerfile:1

FROM alpine:3.19

# Secure secret access without ARG/ENV – avoids leakage
RUN --mount=type=secret,id=api_token \
    curl -H "Authorization: Bearer $(cat /run/secrets/api_token)" https://api.example.com
```

**Build command:**

```bash
docker buildx build --secret id=api_token,src=./token.txt .
```

**Why it's better:**

- ARG exposes secrets in build history; secret mount does not
- Secret exists only at build time, never written to image
- Fully compliant with secure Dockerfile practices

---

## ⚙️ 3. Multi-stage Go build (runtime from scratch)

**Input:**

```dockerfile
# Anti-pattern: single stage ships the Go toolchain and source in the runtime
FROM golang:1.21
WORKDIR /app
COPY . .
RUN go build -o app
CMD ["./app"]
```

**Optimized Output:**

```dockerfile
# syntax=docker/dockerfile:1

# --- Build stage ---
FROM golang:1.21-alpine AS builder
WORKDIR /app

COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

COPY . .
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /app/main

# --- Final stage ---
FROM scratch
COPY --from=builder /app/main /main

# scratch has no /etc/passwd, so there is no name to create or resolve.
# A numeric UID:GID is the only form that works here, and it is enough:
# the kernel only needs the number to run the process as a non-root user.
USER 10001:10001

ENTRYPOINT ["/main"]
```

**Why it's better:**

- Final image is minimal (scratch) and secure
- Builder stage uses Go caching effectively
- No unnecessary tools shipped in runtime
- Runs as a non-root UID even though there is no user database to create one in

---

## 🧩 4. COPY --link for efficient reuse

**Input:**

```dockerfile
FROM node:20-alpine
COPY . /app
```

**Optimized Output:**

```dockerfile
# syntax=docker/dockerfile:1

FROM node:20-alpine

# Use link-based copy for better rebase/cache reuse
COPY --link . /app
```

**Why it's better:**

- Prevents duplication of content in cache
- Useful for multi-stage builds or rebasing
- Improves build performance on minor changes

---

## 📦 5. Yarn install with BuildKit mount

**Input:**

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package.json yarn.lock ./
RUN yarn install
COPY . .
```

**Optimized Output:**

```dockerfile
# syntax=docker/dockerfile:1

FROM node:20-alpine
WORKDIR /app

# Install dependencies using persistent BuildKit cache
COPY package.json yarn.lock ./
RUN --mount=type=cache,target=/root/.yarn \
    yarn install --frozen-lockfile

COPY . .
```

**Why it's better:**

- Saves time on repeated builds
- `--frozen-lockfile` ensures deterministic install
- Keeps yarn cache out of image layers

---

## 🔒 6. Secure non-root runtime (Python)

**Input:**

```dockerfile
# Anti-pattern: full python image, no dependency cache, and the app runs as root
FROM python:3.11
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
CMD ["python", "main.py"]
```

**Optimized Output:**

```dockerfile
# syntax=docker/dockerfile:1

FROM python:3.11-slim

# Create the user first, with explicit IDs. --system alone would let the base
# image pick a free low UID (it lands on 100 here), which collides with host
# users once the container mounts a volume. See example 11.
RUN groupadd -r -g 10001 app && \
    useradd -r -u 10001 -g app app

WORKDIR /app

# Install deps as root, using the pip cache
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY --chown=app:app . .

USER app

CMD ["python", "main.py"]
```

**Why it's better:**

- Smaller image with `python:slim`
- BuildKit cache for pip = faster builds
- Non-root runtime enhances container security
- Explicit UID/GID, so the identity is the same on every host

---

## 🐘 7. PHP with Composer cache

**Input:**

```dockerfile
FROM php:8.2-fpm
WORKDIR /app
COPY composer.json composer.lock ./
RUN composer install --no-dev
COPY . .
```

**Optimized Output:**

```dockerfile
# syntax=docker/dockerfile:1

FROM php:8.2-fpm-alpine
WORKDIR /app

# Install Composer. Pin the tag: ":latest" would silently change the Composer
# major version under you, and this skill rejects it everywhere else.
COPY --from=composer:2.8 /usr/bin/composer /usr/bin/composer

# Use Composer cache mount
COPY composer.json composer.lock ./
RUN --mount=type=cache,target=/tmp/cache \
    composer install --no-dev --optimize-autoloader

COPY . .
```

**Why it's better:**

- Faster dependency resolution with cache
- Alpine base = smaller image
- Optimized autoloader for production

---

## 🚀 8. CI/CD cache with registry

**Command Before:**

```bash
docker buildx build -t myimage .
```

**Optimized CI Command:**

```bash
docker buildx build \
  --cache-from=type=registry,ref=myregistry.com/myapp:cache \
  --cache-to=type=registry,ref=myregistry.com/myapp:cache,mode=max \
  --push \
  -t myregistry.com/myapp:1.4.2 .
```

**Why it's better:**

- Reuses shared cache layers across CI runners
- Saves time in install/compile steps
- Keeps your CI clean and fast
- Publishes a tag that says what it is; pushing `:latest` is what forces the
  next person to build `FROM myapp:latest` and guess

---

## 📄 9. COPY from external image

**Input:**

```dockerfile
FROM alpine:3.19
COPY nginx.conf /etc/nginx/nginx.conf
```

**Optimized Output:**

```dockerfile
# syntax=docker/dockerfile:1

FROM alpine:3.19

# Reuse config directly from nginx base image
COPY --from=nginx:1.27-alpine /etc/nginx/nginx.conf /etc/nginx/nginx.conf
```

**Why it's better:**

- No need to store config locally
- Keeps the Dockerfile DRY: the config tracks the nginx image it came from
- Reduces context size and maintenance

`nginx:1.27-alpine` is a tag, not a fixed artifact: the config you copy is
whatever that tag points at on the day you build. That is fine here, but do not
mistake it for reproducibility. See `optimization_guide.md` for what actually
buys you that.

---

## 🧱 10. Maven build with cache

**Input:**

```dockerfile
FROM maven:3.9-eclipse-temurin-17
WORKDIR /app
COPY pom.xml .
RUN mvn dependency:go-offline
COPY src ./src
RUN mvn package -DskipTests
```

**Optimized Output:**

```dockerfile
# syntax=docker/dockerfile:1

FROM maven:3.9-eclipse-temurin-17-alpine AS builder
WORKDIR /app

COPY pom.xml .
RUN --mount=type=cache,target=/root/.m2 \
    mvn dependency:go-offline -B

COPY src ./src
RUN --mount=type=cache,target=/root/.m2 \
    mvn package -B -DskipTests

FROM eclipse-temurin:17-jre-alpine
WORKDIR /app

# Create the runtime user before COPY --chown can name it
RUN addgroup -g 10001 app && adduser -u 10001 -G app -S app

COPY --from=builder --chown=app:app /app/target/*.jar ./app.jar

USER app
ENTRYPOINT ["java", "-jar", "app.jar"]
```

**Why it's better:**

- Maven cache persists across builds
- Multi-stage: only JRE in final image
- Alpine = minimal size
- The jar is owned by the non-root user that runs it, in a single layer

---

## 🔐 11. Secure non-root user with explicit UID/GID

**Input:**

```dockerfile
# Anti-pattern: useradd with no explicit UID takes whatever the base image has free
FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install -r requirements.txt

# Auto-assigned UID (could be < 1000, conflicts with host)
RUN useradd -r app
USER app

CMD ["python", "app.py"]
```

**Optimized Output:**

```dockerfile
# syntax=docker/dockerfile:1

FROM python:3.12-slim

# Create non-root user with UID/GID >10000 (safe range)
RUN groupadd -r -g 10001 app && \
    useradd -r -u 10001 -g app app

WORKDIR /app

# Install deps as root (needed for system packages)
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Copy app and set ownership in one layer. The user was created above, so
# --chown can resolve "app" against this stage's /etc/passwd.
COPY --chown=app:app . .

# Switch to non-root user last, after everything is installed
USER app

CMD ["python", "app.py"]
```

**Why it's better:**

- UID/GID >10000 avoids conflicts with host system users
- Explicit ownership of /app, set as the files are copied rather than after
- Cache mount for faster pip installs
- Clear separation: install as root, run as user

---

## 🌐 12. Multi-architecture build (AMD64 + ARM64)

**Input:**

```dockerfile
# Anti-pattern: no cache mount, and the app runs as root
FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install -r requirements.txt

CMD ["python", "app.py"]
```

**Optimized Output:**

```dockerfile
# syntax=docker/dockerfile:1

# No --platform flag here, deliberately. buildx runs this file once per entry
# in --platform, and each run already targets its own architecture.
FROM python:3.12-slim

# Create the runtime user first so COPY --chown can resolve it by name
RUN groupadd -r -g 10001 app && \
    useradd -r -u 10001 -g app app

WORKDIR /app

# Give each architecture its own pip cache. Cache mounts are keyed by target
# path, so without an arch-specific id both builds would share one directory
# and thrash it with wheels the other cannot use.
ARG TARGETARCH
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip,id=pip-$TARGETARCH,sharing=locked \
    pip install -r requirements.txt

COPY --chown=app:app . .

USER app

CMD ["python", "app.py"]
```

**Build command:**

```bash
# Build for multiple architectures
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t myapp:1.0.0 \
  --push .
```

**Why it's better:**

- Runs on Apple Silicon (M1/M2/M3)
- Runs on AWS Graviton (ARM instances)
- Runs on traditional AMD64
- Single Dockerfile for all platforms
- Each architecture gets the interpreter and the wheels that match it

### Why there is no `--platform=$BUILDPLATFORM` here

This is the trap. `--platform=$BUILDPLATFORM` pins a stage to the machine doing
the building rather than the machine that will run the image. It exists for one
reason: to escape QEMU.

Without it, BuildKit builds each non-native target under QEMU emulation, and
emulated builds are roughly an order of magnitude slower than native ones. That
cost is what the pattern buys you out of, and it is a real cost: it is why a
naive `--platform linux/amd64,linux/arm64` build feels like it has hung.

The escape only works when there is something to cross-compile. A Go or Rust
toolchain can run natively on the builder and still emit a binary for another
architecture, so you pin the *builder* stage to `$BUILDPLATFORM`, pass
`$TARGETOS`/`$TARGETARCH` to the compiler, and copy the result into a final
stage that is left unpinned:

```dockerfile
# syntax=docker/dockerfile:1

# Builder runs natively on the build machine: no QEMU, no emulation penalty.
FROM --platform=$BUILDPLATFORM golang:1.21-alpine AS builder
WORKDIR /src

ARG TARGETOS
ARG TARGETARCH

COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

COPY . .
# Cross-compile: the toolchain is native, the output is not.
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH \
    go build -ldflags="-w -s" -o /out/main

# No --platform: this stage resolves to the target, which is what ships.
FROM gcr.io/distroless/static-debian13:nonroot
COPY --from=builder /out/main /main
USER nonroot
ENTRYPOINT ["/main"]
```

Python has no such step. There is no cross-compiler, and nothing gets emitted
for another architecture: `pip` resolves wheels for the interpreter it is
running under, and that interpreter comes from the base image. Pin the stage to
`$BUILDPLATFORM` and every native wheel (`cryptography`, `numpy`, `pydantic-core`)
plus the interpreter itself is built for the *build* machine. Because only the
manifest entry says `linux/amd64` while the filesystem is arm64, the result is
worse than a slow build: it is a broken image that passes CI on an M-series
laptop and dies with an exec format error on the first amd64 host that pulls it.

The rule: `--platform=$BUILDPLATFORM` belongs on builder stages that
cross-compile, never on the stage you actually ship, and never on a
single-stage interpreted-language image. For Python the honest answer is that a
multi-arch build is slow, and you fix that with native builders (`docker buildx
create --append`, or an ARM CI runner), not by lying about the architecture.
See `optimization_guide.md` for the QEMU-versus-native-builder tradeoff.

---

## 🛡️ 13. Distroless final stage for maximum security

**Input:**

```dockerfile
# Anti-pattern: ships pip, the build toolchain and a shell in the runtime
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
CMD ["python", "app.py"]
```

**Optimized Output:**

```dockerfile
# syntax=docker/dockerfile:1

# Build stage. The Python minor version MUST match the runtime's: this image
# ships 3.13, and distroless/python3-debian13 runs /usr/bin/python3.13.
# Pair a 3.12 builder with it and every compiled wheel is built for the wrong
# ABI, so imports fail at runtime with no shell to debug them.
FROM python:3.13-slim AS builder

WORKDIR /app

# Install into a self-contained directory rather than --user: the runtime's
# nonroot user (UID 65532) cannot read /root.
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --target=/deps -r requirements.txt

COPY . .

# Runtime stage - Distroless (no shell, no package manager)
FROM gcr.io/distroless/python3-debian13:nonroot

# Copy installed packages and app
COPY --from=builder /deps /deps
COPY --from=builder /app /app

WORKDIR /app
ENV PYTHONPATH=/deps

# The ":nonroot" tag ships a UID 65532 account, so declare it rather than
# create it: a distroless image has no shell and no groupadd to create one with.
USER nonroot

# The image's ENTRYPOINT is already /usr/bin/python3.13, so CMD carries only args.
CMD ["app.py"]
```

Use the explicit `-debian13` repo rather than `gcr.io/distroless/python3`. The
unversioned name is deprecated upstream and silently rolls forward to the next
Debian release, which would move the interpreter out from under the builder you
just matched it to.

**Why it's better:**

- **Minimal attack surface** - No shell, no apt, no unnecessary tools
- **Smaller image** - Only Python runtime + dependencies
- **Better security** - Fewer CVEs to patch
- **Production-ready** - Google uses distroless in production
- **Non-root by default** - The `:nonroot` tag supplies UID 65532

**The two traps this example exists to avoid.** Both are silent: the image
builds successfully and only fails when the app first imports something.

1. **Interpreter mismatch.** Dependencies installed under one Python minor
   version are not on the next one's search path, and compiled wheels are built
   against a specific ABI. Match the builder to the runtime.
1. **`PATH` is not `PYTHONPATH`.** Copying packages in and adding them to `PATH`
   does nothing for `import`: `PATH` locates executables, `PYTHONPATH` locates
   modules. If the app cannot import its dependencies, this is usually why.

**Trade-off:** Harder to debug (no shell). Use the `:debug` tag for development:

```dockerfile
FROM gcr.io/distroless/python3-debian13:debug  # Includes busybox shell
```

---

## 🦀 14. Rust with cargo cache and distroless

**Input:**

```dockerfile
# Anti-pattern: ships the Rust toolchain and rebuilds all deps on each change
FROM rust:1
WORKDIR /app
COPY . .
RUN cargo build --release
CMD ["./target/release/myapp"]
```

**Optimized Output:**

```dockerfile
# syntax=docker/dockerfile:1

# Build stage
FROM rust:1-slim AS builder
WORKDIR /app

# Cache dependencies: create dummy project, build deps, then replace with real source
COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo "fn main() {}" > src/main.rs
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/app/target \
    cargo build --release

# Build real project.
# touch is load-bearing: cargo decides what to rebuild from mtimes, and COPY
# restores the source's mtime from the build context, which is OLDER than the
# dummy binary just built from it. Without the touch, cargo considers the
# dummy fresh, skips the rebuild, and the cp below ships the "fn main() {}"
# stub. The build still exits 0 and the container still starts, doing nothing.
COPY . .
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/app/target \
    touch src/main.rs && \
    cargo build --release && \
    cp target/release/myapp /usr/local/bin/

# Runtime stage: distroless/cc carries glibc, which a default (non-musl)
# Rust build links against. Use the explicit -debian13 repo: the unversioned
# gcr.io/distroless/cc is deprecated upstream and rolls forward on its own.
FROM gcr.io/distroless/cc-debian13:nonroot
COPY --from=builder /usr/local/bin/myapp /myapp

# ":nonroot" ships UID 65532; declare it rather than create it, since a
# distroless image has no shell and no useradd.
USER nonroot

ENTRYPOINT ["/myapp"]
```

**Why it's better:**

- Dependency caching via dummy project trick (only rebuilds deps when Cargo.toml changes)
- The `touch` keeps that trick honest: without it the trick silently wins by
  shipping the stub it was supposed to throw away
- Cache mounts for cargo registry and target directory
- Distroless runtime (minimal attack surface, no shell)
- Binary copied to fixed location for clean ENTRYPOINT
- Runs as a non-root UID that the base image already provides

---

## 📋 15. COPY --chown vs RUN chown

**Input:**

```dockerfile
# Anti-pattern: RUN chown -R after COPY duplicates every file into a new layer
FROM node:22-alpine
WORKDIR /app
COPY . .
RUN addgroup -g 10001 app && adduser -u 10001 -G app -S app
RUN chown -R app:app /app
USER app
CMD ["node", "index.js"]
```

**Optimized Output:**

```dockerfile
# syntax=docker/dockerfile:1

FROM node:22-alpine
WORKDIR /app

# Create the user FIRST. --chown resolves names against this stage's own
# /etc/passwd, so the account has to exist before any COPY names it.
# Alpine is busybox: addgroup/adduser. groupadd/useradd do not exist here.
RUN addgroup -g 10001 app && adduser -u 10001 -G app -S app

# Use --chown directly (single layer, no duplication)
COPY --chown=app:app . .

# Switch last, once everything is in place
USER app
CMD ["node", "index.js"]
```

**Why it's better:**

- `COPY --chown` sets ownership in a single layer
- `RUN chown -R` creates a new layer that duplicates all file data
- Can save hundreds of MB on large applications

### The ordering rule, and why it bites

This is the reference pattern for user creation: **create the user, then
`COPY --chown`, then `USER` last.** Install dependencies as root before the
switch.

Get the order wrong and nothing tells you. Reversing the first two lines here
does not fail the build: BuildKit cannot resolve `app`, silently falls back to
`0:0`, and exits 0. You get an image whose files are owned by root while the
process runs as `app`, so it dies on the first write to its own directory, in
production, long after the build that caused it went green.

Two consequences worth internalising:

- A passing build proves nothing about ownership. Check it (`stat`) if it matters.
- Name the user before you use the name. `--chown=10001:10001` sidesteps the
  problem entirely and is the only option on `scratch`, which has no
  `/etc/passwd` to resolve against (see example 3).
