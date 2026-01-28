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
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /app/main

# --- Final stage ---
FROM scratch
COPY --from=builder /app/main /main
ENTRYPOINT ["/main"]
```

**Why it's better:**

- Final image is minimal (scratch) and secure
- Builder stage uses Go caching effectively
- No unnecessary tools shipped in runtime

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
WORKDIR /app

# Use pip cache for dependency resolution
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY . .

# Create non-root user for runtime security
RUN addgroup --system app && adduser --system --ingroup app appuser
USER appuser

CMD ["python", "main.py"]
```

**Why it's better:**

- Smaller image with `python:slim`
- BuildKit cache for pip = faster builds
- Non-root runtime enhances container security

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

# Install Composer
COPY --from=composer:latest /usr/bin/composer /usr/bin/composer

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
  -t myregistry.com/myapp:latest .
```

**Why it's better:**

- Reuses shared cache layers across CI runners
- Saves time in install/compile steps
- Keeps your CI clean and fast

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
- Keeps Dockerfile DRY and reproducible
- Reduces context size and maintenance

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
COPY --from=builder /app/target/*.jar ./app.jar
ENTRYPOINT ["java", "-jar", "app.jar"]
```

**Why it's better:**

- Maven cache persists across builds
- Multi-stage: only JRE in final image
- Alpine = minimal size

---

## 🔐 11. Secure non-root user with explicit UID/GID

**Input:**

```dockerfile
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

# Copy app and set ownership
COPY . .
RUN chown -R app:app /app

# Switch to non-root user
USER app

CMD ["python", "app.py"]
```

**Why it's better:**

- UID/GID >10000 avoids conflicts with host system users
- Explicit ownership of /app directory
- Cache mount for faster pip installs
- Clear separation: install as root, run as user

---

## 🌐 12. Multi-architecture build (AMD64 + ARM64)

**Input:**

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install -r requirements.txt

CMD ["python", "app.py"]
```

**Optimized Output:**

```dockerfile
# syntax=docker/dockerfile:1

# Use build platform for faster dependency resolution
FROM --platform=$BUILDPLATFORM python:3.12-slim AS base

ARG TARGETARCH
ARG TARGETOS

WORKDIR /app

# Install dependencies (works on all platforms)
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Platform-specific adjustments (if needed)
RUN if [ "$TARGETARCH" = "arm64" ]; then \
      echo "ARM64-specific optimizations"; \
      pip install --no-cache-dir some-arm-optimized-package; \
    fi

# Copy application
COPY . .

# Create non-root user (same UID across platforms)
RUN groupadd -r -g 10001 app && \
    useradd -r -u 10001 -g app app && \
    chown -R app:app /app

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
- Platform-specific optimizations possible
- Single Dockerfile for all platforms

---

## 🛡️ 13. Distroless final stage for maximum security

**Input:**

```dockerfile
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

# Build stage
FROM python:3.12-slim AS builder

WORKDIR /app

# Install dependencies in user directory
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Runtime stage - Distroless (no shell, no package manager)
FROM gcr.io/distroless/python3

# Copy installed packages and app
COPY --from=builder /root/.local /root/.local
COPY --from=builder /app /app

WORKDIR /app
ENV PATH=/root/.local/bin:$PATH

CMD ["app.py"]
```

**Why it's better:**

- **Minimal attack surface** - No shell, no apt, no unnecessary tools
- **Smaller image** - Only Python runtime + dependencies
- **Better security** - Fewer CVEs to patch
- **Production-ready** - Google uses distroless in production
- **Still functional** - Application runs normally

**Trade-off:** Harder to debug (no shell). Use `:debug` tag for development:

```dockerfile
FROM gcr.io/distroless/python3:debug  # Includes busybox shell
```
