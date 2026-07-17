---
name: dockerfile-best-practices
description: "Create and optimize Dockerfiles with BuildKit, multi-stage builds, advanced caching, and security. Use this skill whenever you need to create, modify, or optimize a Dockerfile or a Docker Compose file. Also trigger when the user discusses container images, build performance, or Docker security — even if they don't explicitly mention 'Dockerfile'."
metadata:
  version: "3.0.0"
---

# Dockerfile Best Practices

Comprehensive guide for creating optimized, secure, and fast Docker images using modern BuildKit features.

## Workflow

1. **Identify language/framework** → Pick a template from [Language Templates](#language-templates)
2. **Apply essential rules** → Every Dockerfile must follow [Essential Rules](#essential-rules-always-apply)
3. **Security hardening** → Non-root user, secret mounts, provenance and SBOM attestations (see [references/supply_chain.md](references/supply_chain.md))
4. **Optimize for cache** → Separate deps from code, use cache mounts
5. **Multi-stage if needed** → Compiled languages or distroless runtime
6. **Add metadata** → OCI labels, HEALTHCHECK, STOPSIGNAL (see [PID 1 and Signals](#pid-1-and-signals))
7. **Review** → Run [scripts/analyze_dockerfile.py](scripts/analyze_dockerfile.py), then `docker build --check` (see [references/build_checks.md](references/build_checks.md))

## Essential Rules (Always Apply)

### 1. BuildKit syntax directive (first line, always)

```dockerfile
# syntax=docker/dockerfile:1
```

### 2. Pin a readable tag you are willing to maintain

"Receives security patches" and "reproducible" are properties of a **process**, not of a tag string. A floating tag patches nothing by itself: it patches when someone rebuilds.

- **Pin a tag as specific as you are willing to maintain.** `python:3.12-slim` is fine. `python:3.12-slim-bookworm` is equally fine: pinning the OS is a legitimate stability choice, not a mistake.
- **`:latest` and untagged images stay rejected.** Not because mutability is uniquely evil there, but because they carry zero information about what you are actually running.
- **Every tag is mutable, and security updates come from rebuilding regularly.** Rebuild in six months and you may get different bytes. A tag is documentation and a rough contract, not a reproducibility mechanism. Name the process, not the string.
- **Reproducibility comes from a process**: digest pinning backed by Renovate or Dependabot, or recording the resolved digest in build metadata, which is what provenance attestations already do ([references/supply_chain.md](references/supply_chain.md)).
- **Digests are an option, not the default.** Strongest guarantee available, but without renewal automation a digest is just a tag that rots silently while you ship known CVEs feeling safe. Most teams lack that automation. Adopt digests only with the tooling that renews them.

Full argument and the digest tradeoff: [references/best_practices.md](references/best_practices.md).

### 3. Cache mounts for all package managers

```dockerfile
# pip
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt
# npm
RUN --mount=type=cache,target=/root/.npm npm ci --omit=dev
# yarn (Yarn 2+; --frozen-lockfile is the retired Yarn 1 spelling)
RUN --mount=type=cache,target=/root/.yarn yarn install --immutable
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

Above 10000 keeps the container user from colliding with a real host account once a volume is bind-mounted. Some images ship a non-root user below that line (`node` is UID 1000); prefer your own unless the image hard-codes ownership of paths you need.

Distroless is the exception: it has no `groupadd`, so use a `:nonroot` tag and name the user **numerically** (`USER 65532:65532`). Kubernetes `runAsNonRoot` cannot verify a username.

### 7. COPY for local files, ADD --checksum for remote artifacts

- **`COPY`** for anything coming from the build context.
- **`ADD --checksum=sha256:<hash> <url> <dest>`** for a remote artifact. BuildKit verifies the digest before writing, which is strictly better than `RUN curl | tar`: that pipes an unverified download straight into a shell.
- **Never `ADD` a local archive you did not build.** Auto-extraction is implicit and can write outside the destination you named.

### 8. Create the user before any `--chown` that names it

`--chown=app:app` resolves `app` against **this stage's** `/etc/passwd`. If the `RUN` that creates `app` has not run yet, the modern BuildKit frontend does not fail: it silently drops the `--chown` and copies the files as root. The build stays green, `docker build --check` sees nothing, and you ship an image where the app runs as `app` while its own files are owned by root: it works until the first write, which fails at runtime, maybe in production, maybe never. Order every stage:

1. Create the user.
1. Install dependencies as **root**, so the app cannot rewrite its own deps at runtime.
1. `COPY --chown=app:app` the application source.
1. Hand over the workdir itself (`chown app:app /app`), not the dependency tree.
1. `USER app` **last**.

Use `COPY --chown=app:app . .` rather than `COPY` plus `RUN chown -R`: the latter copies every file into a second layer, doubling its weight in the image.

### 9. OCI labels for metadata

```dockerfile
LABEL org.opencontainers.image.source="https://github.com/org/repo" \
      org.opencontainers.image.description="My application" \
      org.opencontainers.image.version="1.0.0"
```

### 10. HEALTHCHECK: call a binary the image actually ships

**Kubernetes ignores Docker's `HEALTHCHECK` entirely** and runs its own probes. This rule matters for Compose, plain `docker run`, and Swarm. On a cluster, write probes instead.

Two ways to get it wrong:

- **Calling a binary that is not there.** `wget` is not in `python:3.12-slim`, or any Debian slim image. It exists on Alpine only because busybox provides it. Use the runtime the image already has.
- **Passing on a non-2xx response.** A check that fails only on connection refused reports a 500-ing app as healthy. `requests.get()` does not raise on HTTP 500 (`raise_for_status()` does); `fetch()` resolves on 500 too.

```dockerfile
# Python: urlopen raises HTTPError on non-2xx, so no explicit status check needed.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8000/health').read()" || exit 1

# Node: fetch resolves on 500, so check r.ok explicitly.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD node -e "fetch('http://localhost:3000/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

# Distroless/scratch: no shell, no interpreter. Ship a subcommand, exec form.
HEALTHCHECK CMD ["/app", "healthcheck"]
```

If the image genuinely cannot check itself (php-fpm speaks FastCGI and ships no FastCGI client), omit the `HEALTHCHECK` rather than installing a whole HTTP client to satisfy it.

### 11. Create .dockerignore

Use the template in [assets/dockerignore-template](assets/dockerignore-template). Critical for build context size and security.

## PID 1 and Signals

PID 1 is special: the kernel installs **no default signal handlers** for it. An app that registers no `SIGTERM` handler does not die on `docker stop`, it ignores it. Docker waits out the full grace period (10s by default), then `SIGKILL`s: no clean shutdown, no connection draining, ten seconds burned per deploy. PID 1 must also reap orphaned children, which most runtimes never do, so zombies accumulate.

In preference order:

1. **Handle `SIGTERM` in the application.** Nothing else shuts down cleanly.
1. **`docker run --init`** (Compose: `init: true`) injects a minimal init as PID 1 that forwards signals and reaps.
1. **`ENTRYPOINT ["/sbin/tini", "--"]`**, or `dumb-init`, when it must be baked into the image.

Always use the **exec form** of `CMD`/`ENTRYPOINT`: shell form wraps the command in `/bin/sh -c`, and that shell becomes PID 1 and forwards nothing. Set `STOPSIGNAL` when the app listens for something else (nginx and php-fpm want `SIGQUIT` to drain gracefully):

```dockerfile
STOPSIGNAL SIGQUIT
```

Depth: [references/best_practices.md](references/best_practices.md).

## Language Templates

### Python (with uv - Recommended)

For detailed uv patterns, see [references/uv_integration.md](references/uv_integration.md).

```dockerfile
# syntax=docker/dockerfile:1

FROM python:3.12-slim

# uv is pinned like any other dependency; :latest would break rule 2.
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /uvx /bin/

WORKDIR /app

# Create the user first: the --chown below resolves "app" against this stage's
# /etc/passwd; an unknown name is silently ignored, not a build failure (rule 8).
RUN groupadd -r -g 10001 app && useradd -r -u 10001 -g app app

# Deps as root in their own cached layer. /app/.venv stays root-owned on
# purpose: the app executes it but cannot rewrite it at runtime.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

# Still root here: uv sync writes /app/.venv, which USER app could not do.
COPY --chown=app:app . .
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked

# Hand over the workdir itself, not the venv, then drop privileges last.
RUN chown app:app /app
USER app

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8000/health').read()" || exit 1
CMD ["python", "-m", "myapp"]
```

### Node.js

npm is the default here. For pnpm, enable Corepack (`RUN corepack enable && corepack prepare pnpm@<version> --activate`) and swap the install line for `pnpm install --frozen-lockfile --prod` with a cache mount on `/root/.local/share/pnpm/store`.

```dockerfile
# syntax=docker/dockerfile:1

FROM node:22-alpine
WORKDIR /app

# node:22 ships a "node" user, but at UID 1000, which collides with the first
# real host account once a volume is bind-mounted. Rule 6 wins: our own, >10000.
RUN addgroup -g 10001 app && adduser -u 10001 -G app -S app

COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --omit=dev

COPY --chown=app:app . .

# WORKDIR created /app as root, so the app could not write to its own workdir.
# Hand over the directory; node_modules stays root-owned and read-only to it.
RUN chown app:app /app
USER app

EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD node -e "fetch('http://localhost:3000/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
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

# -debian13 is explicit: the unversioned distroless/static repo is deprecated
# upstream and rolls to the next Debian release on its own. :nonroot ships the
# non-root user, the only way to get one here (distroless has no groupadd).
FROM gcr.io/distroless/static-debian13:nonroot
COPY --from=builder /app/main /main
# Numeric, not "nonroot": Kubernetes runAsNonRoot cannot verify a username.
USER 65532:65532
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

# touch is load-bearing: COPY restores the context's older mtime, so without it
# cargo calls the dummy build fresh, skips the rebuild, and ships the
# "fn main() {}" stub.
COPY . .
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/app/target \
    touch src/main.rs && cargo build --release && cp target/release/myapp /usr/local/bin/

# cc-debian13 rather than the deprecated unversioned cc repo; :nonroot for the
# same reason as the Go template.
FROM gcr.io/distroless/cc-debian13:nonroot
COPY --from=builder /usr/local/bin/myapp /myapp
USER 65532:65532
ENTRYPOINT ["/myapp"]
```

### PHP (with Composer)

```dockerfile
# syntax=docker/dockerfile:1

FROM php:8-fpm-alpine
WORKDIR /app

COPY --from=composer:2 /usr/bin/composer /usr/bin/composer

# Before the first --chown that names "app" (rule 8).
RUN addgroup -g 10001 app && adduser -u 10001 -G app -S app

COPY composer.json composer.lock ./
RUN --mount=type=cache,target=/tmp/cache \
    composer install --no-dev --optimize-autoloader --no-scripts

COPY --chown=app:app . .
RUN composer dump-autoload --optimize

RUN chown app:app /app
USER app

EXPOSE 9000
# No HEALTHCHECK: php-fpm speaks FastCGI and this image ships no FastCGI
# client. Probe it from the web server in front of it instead (rule 10).
STOPSIGNAL SIGQUIT
CMD ["php-fpm"]
```

### Debian-based (with APT cache)

```dockerfile
# syntax=docker/dockerfile:1

FROM debian:13-slim

RUN rm -f /etc/apt/apt.conf.d/docker-clean; \
    echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache

WORKDIR /app

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends curl ca-certificates

# Before the COPY --chown below, not after it (rule 8).
RUN groupadd -r -g 10001 app && useradd -r -u 10001 -g app app

COPY --chown=app:app . .

RUN chown app:app /app
USER app

CMD ["./app"]
```

## Docker Compose Rules

1. **No `version:`**: a Compose V1 leftover, deprecated since V2.
1. **`container_name:` only where you have a reason**: it blocks `--scale` on
   that service. A single-instance service you address by name from scripts is
   a legitimate reason; habit is not.
1. **`depends_on` with `condition: service_healthy`**: bare `depends_on` waits
   for the container to start, not for the service to become usable.

Health checks, networks, volumes, secrets, runtime hardening, dev vs prod,
scaling, and the full `container_name` tradeoff:
[references/compose_best_practices.md](references/compose_best_practices.md).

## Commands Reference

```bash
# Review before building: this skill's linter, then BuildKit's own checks.
# uv run resolves each script's PEP 723 dependencies; plain python will not.
uv run scripts/analyze_dockerfile.py ./Dockerfile
uv run scripts/analyze_compose.py ./compose.yaml
docker buildx build --check .

# Build: with a secret mount (rule 5), and multi-platform
docker buildx build --secret id=api_key,src=./key.txt -t myapp:1.0.0 .
docker buildx build --platform linux/amd64,linux/arm64 -t myapp:1.0.0 --push .
```

Remote cache (`--cache-from` / `--cache-to`) and the rest of the buildx surface:
[references/optimization_guide.md](references/optimization_guide.md).

## Reference Documentation

| Reference | Content |
| --------- | ------- |
| [optimization_guide.md](references/optimization_guide.md) | BuildKit internals, caching strategies, multi-stage patterns, distroless, profiling |
| [best_practices.md](references/best_practices.md) | Complete checklist with impact levels, pinning doctrine and the digest tradeoff, UID/GID strategy, PID 1 and signal handling |
| [build_checks.md](references/build_checks.md) | `docker build --check`: the built-in rule set, wiring it into CI |
| [supply_chain.md](references/supply_chain.md) | Provenance attestations, SBOMs, signing, digest renewal tooling |
| [examples.md](references/examples.md) | Real-world before/after optimization examples (15 scenarios) |
| [uv_integration.md](references/uv_integration.md) | Python with uv: installation methods, workspaces, multi-stage, all patterns |
| [compose_best_practices.md](references/compose_best_practices.md) | Complete Compose guide: networks, volumes, secrets, dev vs prod, scaling |
