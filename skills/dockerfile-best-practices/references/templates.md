# Language Templates

Six starting points, one per stack. Every template applies the essential
rules from `SKILL.md`; the inline comments explain the non-obvious lines
rather than restating the rule. Rule numbers below refer to that file.

All of these are extracted and linted in CI by
`scripts/extract_dockerfile_blocks.py`, so they are held to the same
doctrine the skill teaches.

| Template | What it demonstrates |
| :--- | :--- |
| [Python with uv](#python-with-uv) | Cache and bind mounts, deps installed as root, venv the app cannot rewrite |
| [Node.js](#nodejs) | Overriding an image's own sub-10000 user, npm cache mount |
| [Go](#go-multi-stage) | Multi-stage to distroless, numeric non-root user |
| [Rust](#rust-multi-stage) | Multi-stage to distroless-cc, the dummy-build cache trick |
| [PHP with Composer](#php-with-composer) | Composer from an external image, no HEALTHCHECK on purpose, STOPSIGNAL |
| [Debian base](#debian-based-with-apt-cache) | APT cache setup and the sharing=locked mounts |

## Python (with uv)

Recommended for Python. Detailed uv patterns: `references/uv_integration.md`.

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

## Node.js

npm is the default here. For pnpm, enable Corepack
(`RUN corepack enable && corepack prepare pnpm@<version> --activate`) and swap
the install line for `pnpm install --frozen-lockfile --prod` with a cache mount
on `/root/.local/share/pnpm/store`.

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

## Go (multi-stage)

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

## Rust (multi-stage)

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

## PHP (with Composer)

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

## Debian-based (with APT cache)

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
