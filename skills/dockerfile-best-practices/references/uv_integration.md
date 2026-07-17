# Python + uv Docker Integration

Complete guide for using uv (the modern Python package manager) in Docker.

## Quick Start

### Recommended Pattern

```dockerfile
# syntax=docker/dockerfile:1

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /uvx /bin/

WORKDIR /app

# Install dependencies (cached layer)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

# Copy application code
COPY . .

# Install project
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

# Create the runtime user, then hand it the tree uv wrote as root.
RUN groupadd -r -g 10001 app && useradd -r -u 10001 -g app app && \
    chown -R app:app /app
USER app

# Activate virtual environment
ENV PATH="/app/.venv/bin:$PATH"

CMD ["python", "-m", "myapp"]
```

Two ordering rules carry this file, and both are easy to get wrong:

1. **`uv sync` runs as root.** It needs to write both the venv (`/app/.venv`)
   and its cache (`/root/.cache/uv`, the mount target above). Switch to a
   non-root user before the sync and it dies on `Permission denied` at
   whichever of the two it reaches first.
1. **`USER` goes last**, after ownership of the workdir is settled.

The `--mount=type=bind` flags above mount `uv.lock` and `pyproject.toml` into
the build without copying them into a layer, so editing application code does
not invalidate the dependency layer. See `best_practices.md` for how bind
mounts differ from `COPY` and from cache mounts.

## Installation Methods

### Method 1: Copy from the uv image (recommended)

```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /uvx /bin/
```

This is Astral's own documented recommendation, and it is the cheapest correct
option: no network fetch at build time, no shell, no checksum to manage.

#### Pinning the uv image

Pin a readable version tag. `0.11.29` records exactly which uv you copied.
`:latest` records nothing, and this skill's own rule rejects it (DL002).

Be honest about what the tag buys you: it is documentation and a rough
contract, not a reproducibility mechanism. Tags are mutable. Rebuilding in six
months may resolve the same string to different bytes. What keeps uv current is
rebuilding regularly, not the string you typed.

If you need a hard guarantee, pinning the digest is the strongest one
available, but only when it is backed by renewal automation (Renovate,
Dependabot) or by recording the resolved digest in build metadata. Without that
automation a digest rots silently and you ship a known-vulnerable uv while
feeling safe. Most teams do not have the automation. See
`supply_chain.md` before choosing it.

### Method 2: Use a pre-installed uv image

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
# uv is already installed
```

Available images:

- `ghcr.io/astral-sh/uv:python3.12-alpine`
- `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`
- `ghcr.io/astral-sh/uv:python3.12-bookworm`

These tags name the OS (`bookworm`) as well as the Python version. That is a
legitimate stability choice: it pins you to a Debian release so a distro
upgrade cannot arrive unannounced in a rebuild. The tradeoff is that you move
to the next Debian yourself, on your own schedule.

### Method 3: Install via the installer script

Use this only when you cannot copy from an external registry (an air-gapped or
mirror-only build). Method 1 is better in every other case.

```dockerfile
# Fragment: the checksum is a placeholder; supply the real digest for your version
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*
ADD --checksum=sha256:<digest-of-install.sh> \
    https://astral.sh/uv/0.11.29/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.local/bin/:$PATH"
```

`--checksum` is what makes this method defensible: without it nothing verifies
the script you are about to execute as root, and a compromised or
man-in-the-middled endpoint owns your image. Fetch the real digest for the
version you pin and paste it in; do not copy the placeholder above.

## Cache Optimization

### Enable uv cache mount (essential)

```dockerfile
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked
```

**Alternative:** Set persistent cache location

```dockerfile
ENV UV_CACHE_DIR=/opt/uv-cache/
```

## Intermediate Layers Pattern

**Problem:** Installing dependencies on every code change is slow.

**Solution:** Separate dependency installation from project installation.

```dockerfile
# syntax=docker/dockerfile:1

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /uvx /bin/

WORKDIR /app

# Install dependencies ONLY (no project code yet)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

# Now copy and install project
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked
```

**Benefits:**

- Dependencies layer cached separately from code
- Only reinstalls deps when `uv.lock` or `pyproject.toml` change
- Massive speedup on code changes

## Multi-Stage Build with uv

```dockerfile
# syntax=docker/dockerfile:1

# --- Build stage ---
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /uvx /bin/

WORKDIR /app

# Install dependencies (root: uv writes /app/.venv here)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-editable

# Copy and install project (non-editable)
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

# --- Runtime stage ---
FROM python:3.12-slim

# Create the user BEFORE the --chown below: --chown resolves the name against
# THIS stage's /etc/passwd, and a new stage does not inherit the builder's user
# table. Get the order wrong and BuildKit does not stop you: it silently falls
# back to 0:0, the venv ends up root-owned, and the failure only surfaces at
# runtime when the app cannot write to it.
RUN groupadd -r -g 10001 app && useradd -r -u 10001 -g app app

# Copy only the virtual environment (not source code)
COPY --from=builder --chown=app:app /app/.venv /app/.venv

# Nothing writes to /app after this point, so the switch is safe here.
USER app

# Activate venv
ENV PATH="/app/.venv/bin:$PATH"

CMD ["/app/.venv/bin/myapp"]
```

**Benefits:**

- Source code not in final image
- Smaller final image
- Better security

Note that no `uv sync` runs in the runtime stage: the venv arrives prebuilt, so
switching to `app` immediately after the copy is safe. In a single-stage build
the same switch has to wait until after the last sync.

## Using the Environment

### Option 1: Activate venv via PATH (recommended)

```dockerfile
ENV PATH="/app/.venv/bin:$PATH"
CMD ["python", "-m", "myapp"]
```

### Option 2: Use uv run

```dockerfile
CMD ["uv", "run", "myapp"]
```

### Option 3: Install to system Python

```dockerfile
ENV UV_PROJECT_ENVIRONMENT=/usr/local
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked
CMD ["myapp"]
```

## System Python vs Virtual Environment

### Use system Python (simpler)

```dockerfile
ENV UV_SYSTEM_PYTHON=1
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system ruff
```

### Use virtual environment (more isolated)

```dockerfile
RUN uv venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install ruff
```

## Workspaces

For monorepos with multiple packages:

```dockerfile
# Install workspace dependencies (excludes all workspace members)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-workspace

# Copy and install specific package
COPY packages/api ./packages/api
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --package api
```

## Tools Installation

```dockerfile
ENV PATH=/root/.local/bin:$PATH
RUN uv tool install cowsay
RUN uv tool install ruff
```

**Note:** recent uv images set `UV_TOOL_BIN_DIR=/usr/local/bin` by default, so
tools land on `PATH` without the `ENV` above. Check the tag you actually pin
rather than assuming either behaviour.

## Complete Example (FastAPI app)

```dockerfile
# syntax=docker/dockerfile:1

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /uvx /bin/

WORKDIR /app

# Install dependencies (separate layer for caching)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# Copy application
COPY . .

# Install project (still root: uv writes /app/.venv)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# Create non-root user and hand over /app, then drop privileges
RUN groupadd -r -g 10001 app && useradd -r -u 10001 -g app app && \
    chown -R app:app /app
USER app

# Activate venv
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
CMD ["uvicorn", "myapp.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Important Notes

### .dockerignore

**Critical:** Add `.venv` to `.dockerignore`:

```dockerignore
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
```

The local venv is platform-specific and must be rebuilt in the container.

### uv vs pip

**Use uv for:**

- New projects
- When you want speed (Astral benchmarks uv at 10-100x faster than pip;
  the gap depends heavily on the workload and on cache state)
- Projects with `pyproject.toml` + `uv.lock`

**Use pip for:**

- Legacy projects with `requirements.txt`
- When uv is not available in environment

### Temporary uv mount

If uv is not needed in the final image, mount the binary for one `RUN` instead
of copying it into a layer:

```dockerfile
RUN --mount=from=ghcr.io/astral-sh/uv:0.11.29,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked
```

Pin this reference exactly as you would a `COPY --from`: an untagged image here
resolves to `:latest` and silently changes uv under you.

## Common Patterns by Use Case

### CLI Tool

```dockerfile
# syntax=docker/dockerfile:1

FROM python:3.12-alpine
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /bin/
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

# Alpine ships busybox adduser/addgroup, not the shadow groupadd/useradd.
RUN addgroup -g 10001 -S app && adduser -u 10001 -S app -G app && \
    chown -R app:app /app
USER app

ENV PATH="/app/.venv/bin:$PATH"
ENTRYPOINT ["mytool"]
```

### Web API

```dockerfile
# syntax=docker/dockerfile:1

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /bin/
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev
RUN groupadd -r -g 10001 app && useradd -r -u 10001 -g app app && \
    chown -R app:app /app
USER app
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0"]
```

### Data Processing / ML

```dockerfile
# syntax=docker/dockerfile:1

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /bin/
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked
RUN groupadd -r -g 10001 app && useradd -r -u 10001 -g app app && \
    chown -R app:app /app
USER app
ENV PATH="/app/.venv/bin:$PATH"
CMD ["python", "-m", "myapp.process"]
```
