# Python + uv Docker Integration

Complete guide for using uv (the modern Python package manager) in Docker.

## Quick Start

### Recommended Pattern

```dockerfile
# syntax=docker/dockerfile:1

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.10 /uv /uvx /bin/

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

# Activate virtual environment
ENV PATH="/app/.venv/bin:$PATH"

CMD ["python", "-m", "myapp"]
```

## Installation Methods

### Method 1: Copy from distroless image (recommended)

```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.10 /uv /uvx /bin/
```

**Best practice:** Pin to specific version or SHA256

```dockerfile
# Pin to version
COPY --from=ghcr.io/astral-sh/uv:0.9.10 /uv /uvx /bin/

# Pin to SHA256 (most reproducible)
COPY --from=ghcr.io/astral-sh/uv@sha256:2381d6aa60c326b71fd40023f921a0a3b8f91b14d5db6b90402e65a635053709 /uv /uvx /bin/
```

### Method 2: Use pre-installed images

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
# uv is already installed
```

Available images:
- `ghcr.io/astral-sh/uv:python3.12-alpine`
- `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`
- `ghcr.io/astral-sh/uv:python3.12-bookworm`

### Method 3: Install via installer

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates
ADD https://astral.sh/uv/0.9.10/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.local/bin/:$PATH"
```

## Cache Optimization

### Enable uv cache mount (essential!)

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
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

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
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies
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

# Copy only the virtual environment (not source code)
COPY --from=builder --chown=app:app /app/.venv /app/.venv

# Create non-root user
RUN groupadd -r app && useradd -r -g app app
USER app

# Activate venv
ENV PATH="/app/.venv/bin:$PATH"

CMD ["/app/.venv/bin/myapp"]
```

**Benefits:**
- Source code not in final image
- Smaller final image
- Better security

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
RUN uv sync --locked
CMD ["myapp"]
```

## System Python vs Virtual Environment

### Use system Python (simpler)

```dockerfile
ENV UV_SYSTEM_PYTHON=1
RUN uv pip install --system ruff
```

### Use virtual environment (more isolated)

```dockerfile
RUN uv venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN uv pip install ruff
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

**Note:** Images `>= 0.8` set `UV_TOOL_BIN_DIR=/usr/local/bin` by default.

## Complete Example (FastAPI app)

```dockerfile
# syntax=docker/dockerfile:1

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.10 /uv /uvx /bin/

WORKDIR /app

# Install dependencies (separate layer for caching)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# Copy application
COPY . .

# Install project
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# Create non-root user
RUN groupadd -r app && useradd -r -g app app && \
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
- When you want speed (10-100x faster than pip)
- Projects with `pyproject.toml` + `uv.lock`

**Use pip for:**
- Legacy projects with `requirements.txt`
- When uv is not available in environment

### Temporary uv mount

If uv not needed in final image:

```dockerfile
RUN --mount=from=ghcr.io/astral-sh/uv,source=/uv,target=/bin/uv \
    uv sync --locked
```

## Common Patterns by Use Case

### CLI Tool

```dockerfile
FROM python:3.12-alpine
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked
ENV PATH="/app/.venv/bin:$PATH"
ENTRYPOINT ["mytool"]
```

### Web API

```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev
RUN groupadd -r app && useradd -r -g app app && chown -R app:app /app
USER app
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0"]
```

### Data Processing / ML

```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked
ENV PATH="/app/.venv/bin:$PATH"
CMD ["python", "-m", "myapp.process"]
```
