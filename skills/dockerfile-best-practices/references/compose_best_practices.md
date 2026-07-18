# Docker Compose Best Practices

Modern guide for creating efficient, scalable, and maintainable Docker Compose configurations.

## Deprecated: version Field

Do not use the `version:` field in Compose files. It is a leftover from Compose
V1 that old tutorials still propagate, which is why it is worth naming.

```yaml
# Anti-pattern: the version field is obsolete and ignored
version: '3.8'
services:
  app:
    image: myapp:1.2.3
```

Write this instead:

```yaml
services:
  app:
    image: myapp:1.2.3
```

### Why?

- The `version:` field is deprecated since Compose V2
- Compose now uses the Compose Specification (no versioning)
- Files without `version:` are forward-compatible
- Official docs no longer recommend it

### Reference

[Compose Specification](https://docs.docker.com/compose/compose-file/)

## container_name: Know What It Costs

Avoid `container_name:` unless you have a specific reason for it, and know the
tradeoff you are accepting.

```yaml
services:
  app:
    image: myapp:1.2.3
    # No container_name: Compose derives the name from the project and service
```

The cost is exact and singular: **Compose refuses to scale a service beyond one
container when that service sets `container_name`, and `--scale` on it fails
with an error.** Running the same file twice under two project names also
collides, because the fixed name is global to the daemon rather than scoped to
the project.

That cost is real, and it is also irrelevant to plenty of deployments. A
single-instance service on a personal server, addressed by a stable name from
scripts or from `docker exec`, is a legitimate use. `--scale` is not a goal for
every service, and paying nothing for a capability you will never use is not a
defect. Set it deliberately, not by habit.

Where you do want scaling and parallel environments, leave the name to Compose
and separate environments by project name instead:

```bash
# Development
docker compose -p myapp-dev up

# Testing
docker compose -p myapp-test up

# Each project gets its own isolated set of containers
```

Compose also labels every container it creates with
`com.docker.compose.project` and `com.docker.compose.service`, so scripts can
find a container by service rather than by a hardcoded name:

```bash
docker ps --filter label=com.docker.compose.project=myapp-dev \
          --filter label=com.docker.compose.service=app
```

That covers most of what people actually reach for `container_name` to get.

## Additional Compose Best Practices

### Use Specific Image Tags

```yaml
services:
  app:
    image: myapp:1.2.3
```

Reject `:latest` and untagged images: they carry zero information about what you
are actually running, so nobody reading the file (or debugging the container at
3am) can tell what is deployed.

Be honest about what a specific tag does and does not buy you. `myapp:1.2.3`
documents intent and acts as a rough contract. It is **not** a reproducibility
mechanism: tags are mutable, and the same tag can resolve to different bytes
later. Compose makes this concrete via `pull_policy` (see below), which decides
when Compose goes back to the registry and possibly picks up new bytes under the
same tag. If you need true reproducibility, that comes from a process, not from
the tag string: pin a digest and back it with renewal automation, or record the
resolved digest in your deployment metadata. `image:` accepts the
`name@sha256:<digest>` form for that purpose.

### Health Checks

Define health checks for service dependencies:

```yaml
services:
  app:
    image: myapp:1.2.3
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    depends_on:
      database:
        condition: service_healthy
```

Two things the syntax will not tell you:

- **The binary must exist in the image.** The check runs inside the container,
  not on the host. `curl` is absent from many slim images and from every
  distroless one, and `wget` exists on Alpine (busybox) but not on Debian slim.
  Use something the image actually ships, or add the probe to the image
  deliberately. See `references/best_practices.md` for picking a probe per base
  image.
- **The check must fail on a bad response, not only on a refused connection.**
  `curl -f` is correct here because `-f` makes curl exit non-zero on HTTP 4xx and
  5xx. Naive checks that only prove the port is open report a wedged service as
  healthy.

Note that this is Compose's own health check and Compose's `depends_on` acts on
it. It is unrelated to Kubernetes probes, which ignore container-level
healthchecks entirely.

### Resource Limits

Prevent resource exhaustion:

```yaml
services:
  app:
    image: myapp:1.2.3
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 1G
        reservations:
          cpus: '1'
          memory: 512M
```

### Restart Policies

```yaml
services:
  app:
    image: myapp:1.2.3
    restart: unless-stopped  # or: no, always, on-failure
```

**Options:**

- `no`: Never restart (default)
- `always`: Always restart on stop
- `on-failure`: Only restart on non-zero exit
- `unless-stopped`: Always restart unless explicitly stopped

### Environment Variables

Keep config out of the file with `env_file`, so the same Compose file works
across environments:

```yaml
services:
  app:
    image: myapp:1.2.3
    env_file:
      - .env
```

Setting values inline is fine when they are genuinely fixed for every
deployment:

```yaml
services:
  app:
    image: myapp:1.2.3
    environment:
      - NODE_ENV=production
      - API_URL=https://api.example.com
```

Neither route is acceptable for secrets. `DATABASE_PASSWORD=secret123` in either
block is a leak; use the `secrets:` mechanism below instead.

**Important:** add `.env` to `.gitignore`.

### Volumes

```yaml
services:
  app:
    image: myapp:1.2.3
    volumes:
      # Named volume (managed by Docker)
      - app-data:/app/data

      # Bind mount (development)
      - ./src:/app/src:ro  # :ro = read-only

volumes:
  app-data:  # Declare named volumes
```

**Patterns:**

- **Named volumes** for persistence (databases, uploads)
- **Bind mounts** for development (live code reload)
- Use `:ro` (read-only) when container doesn't need write access

### Networks

```yaml
services:
  frontend:
    image: frontend:1.0.0
    networks:
      - public

  backend:
    image: backend:1.0.0
    networks:
      - public
      - private

  database:
    image: postgres:16-alpine
    networks:
      - private  # Not exposed to frontend

networks:
  public:
  private:
    internal: true  # No external access
```

**Benefits:**

- Service isolation
- Security (databases not exposed)
- Clear architecture

### Secrets Management

```yaml
services:
  app:
    image: myapp:1.2.3
    environment:
      - POSTGRES_DB=myapp
      - POSTGRES_USER=myapp
      - POSTGRES_PASSWORD_FILE=/run/secrets/db_password
    secrets:
      - db_password

secrets:
  db_password:
    file: ./secrets/db_password.txt
```

The pattern above is worth spelling out: the non-secret settings stay in
`environment:`, and the password arrives as a **file path** (`_FILE` suffix) that
the image reads at startup. Most official images (postgres, mysql, redis) support
this `_FILE` convention.

Avoid putting the secret value itself in `environment:`, because an environment
variable is far more exposed than it looks:

- It is visible to anyone who can run `docker inspect` on the container, and to
  `docker compose config`
- It is inherited by every child process, so it leaks into crash dumps, error
  trackers, and debug endpoints that dump the environment
- It ends up in your shell history and in CI job logs on the way in

A file under `/run/secrets/` is readable only inside the container and does not
propagate to child processes. Never commit the secret file itself: keep
`./secrets/` out of git.

## Runtime Hardening

Compose can lock a container down considerably, and none of it is on by default.
A service that only serves HTTP has no business being able to write to its own
filesystem or to gain new privileges.

```yaml
services:
  app:
    image: registry.example.com/app:1.0.0
    read_only: true
    tmpfs:
      - /tmp
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    user: "10001:10001"
    init: true
```

Line by line, because each one has a failure mode worth understanding:

- **`read_only: true`** mounts the container's root filesystem read-only. This is
  the highest-value line here and the one most likely to break your app on the
  first try: anything that writes to disk now fails. Common casualties are
  temporary files, framework caches, PID files, and any library that writes to
  the working directory. That breakage is the point (it tells you what the
  service actually writes), but you have to give the legitimate writes somewhere
  to go, which is the next line.
- **`tmpfs: [/tmp]`** mounts an in-memory filesystem at `/tmp`, restoring
  scratch space without giving up the read-only root. It is wiped on restart and
  never persisted, which is what you want for scratch. Add one entry per path the
  service genuinely needs to write (`/var/run`, a cache dir), and prefer a named
  volume for anything that must survive a restart. If you find yourself adding
  many, that is a signal about the app, not about the setting.
- **`cap_drop: [ALL]`** drops every Linux capability, then you add back only what
  the service actually needs via `cap_add`. Order matters conceptually: start at
  zero, justify each addition. Most application containers need none. The classic
  exception is binding to a port below 1024, which needs `NET_BIND_SERVICE`, and
  the better fix is usually to listen on a high port and map it (`ports: -
  "80:8080"`) rather than granting the capability.
- **`security_opt: [no-new-privileges:true]`** sets the kernel's
  `no_new_privs` bit, which prevents a process from **gaining** privileges it did
  not start with. Concretely it neuters setuid and setgid binaries: an attacker
  who lands code execution as your unprivileged user cannot execute a setuid-root
  binary in the image to become root. It does not remove privileges you already
  granted, so it complements `user:` and `cap_drop:` rather than replacing them.
- **`user: "10001:10001"`** runs the container as an unprivileged UID/GID rather
  than root. Numeric form is used here because it does not depend on a matching
  entry in the image's `/etc/passwd`. Prefer setting `USER` in the Dockerfile so
  the image is safe by default; use this when you need to override an image you
  do not control. High IDs (above 10000) avoid colliding with host users.
- **`init: true`** runs a small init process as PID 1 that forwards signals and
  reaps processes. Use it when your entrypoint is not itself a well-behaved
  PID 1 (the reasoning, and how to avoid needing it, is in
  `references/best_practices.md` under PID 1 and signal handling). Not re-argued
  here.

Roll these out one at a time against a real workload. `read_only: true` in
particular will surface writes you did not know about, and you want to see them
one by one rather than as a single opaque crash loop.

## Complete Example: Modern Compose File

```yaml
# No version field

services:
  frontend:
    image: myapp-frontend:1.2.3
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    environment:
      - NODE_ENV=production
      - API_URL=http://backend:8000
    depends_on:
      backend:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped
    networks:
      - frontend-network
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 512M

  backend:
    image: myapp-backend:1.2.3
    build:
      context: ./backend
      dockerfile: Dockerfile
    expose:
      - "8000"
    env_file:
      - .env
    # Runtime hardening: see the Runtime Hardening section for what each does
    read_only: true
    tmpfs:
      - /tmp
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    user: "10001:10001"
    init: true
    depends_on:
      database:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped
    networks:
      - frontend-network
      - backend-network
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 1G

  database:
    image: postgres:16-alpine
    environment:
      - POSTGRES_DB=myapp
      - POSTGRES_USER=myapp
      - POSTGRES_PASSWORD_FILE=/run/secrets/db_password
    secrets:
      - db_password
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "myapp"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped
    networks:
      - backend-network

  redis:
    image: redis:7-alpine
    volumes:
      - redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped
    networks:
      - backend-network

volumes:
  postgres-data:
  redis-data:

networks:
  frontend-network:
  backend-network:
    internal: true

secrets:
  db_password:
    file: ./secrets/db_password.txt
```

## Quick Checklist

Before deploying your Compose file:

- [ ] No `version:` field
- [ ] `container_name:` only where you meant it (it blocks `--scale`)
- [ ] Specific image tags (not `:latest`)
- [ ] Health checks defined for critical services, using a binary the image ships
- [ ] Resource limits set
- [ ] Restart policies configured
- [ ] Secrets via files/secrets, not env vars
- [ ] Named volumes for persistence
- [ ] Networks for service isolation
- [ ] `.env` file in `.gitignore`
- [ ] `depends_on` with `condition: service_healthy` for ordered startup
- [ ] `read_only: true` plus `tmpfs` for scratch paths
- [ ] `cap_drop: [ALL]`, adding back only what is needed
- [ ] `no-new-privileges:true` set
- [ ] Non-root `user:` (or `USER` in the Dockerfile)

## Common Patterns

### Development vs Production

**Development (docker-compose.yml):**

```yaml
services:
  app:
    build: .
    volumes:
      - ./src:/app/src  # Live reload
    environment:
      - DEBUG=true
```

**Production (docker-compose.prod.yml):**

```yaml
services:
  app:
    image: myapp:1.2.3
    # No volumes - use built image
    environment:
      - DEBUG=false
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '2'
          memory: 1G
```

**Usage:**

```bash
# Development
docker compose up

# Production
docker compose -f docker-compose.yml -f docker-compose.prod.yml up
```

### Scaling Services

```bash
# Scale backend to 3 instances
docker compose up --scale backend=3
```

This errors out for any service that sets `container_name` (see above).

### Controlling When Images Are Pulled

`pull_policy` decides when Compose goes back to the registry, which is what
actually determines whether you are running the bytes you think you are:

```yaml
services:
  app:
    image: registry.example.com/app:1.0.0
    pull_policy: always
```

The values:

- `missing`: pull only if the image is not in the local cache. This is the
  default when you are not using the Compose Build Specification.
  `if_not_present` is an alias kept for backward compatibility. Note that
  `:latest` is always pulled even under `missing`.
- `always`: always pull from the registry. The right choice for a deployment
  target, where a stale local cache silently serving last month's image is a
  real failure mode.
- `never`: never pull, rely on the local cache, and fail if there is nothing
  cached. Useful for air-gapped or offline runs.
- `build`: build the image, rebuilding even if it is already present.
- `daily` / `weekly` / `every_<duration>`: check the registry only if the last
  pull is older than that window. `every_12h`, `every_30m`, and so on.

The `daily`/`weekly` options exist because a tag is a moving target: they are a
crude renewal schedule for a mutable tag. If you pin a digest instead, the pull
policy stops mattering for correctness.

### Profiles: Optional Services

Profiles let one Compose file carry services that are not started by default,
instead of maintaining a separate file for the debug tooling:

```yaml
services:
  app:
    image: myapp:1.2.3

  # Only started when the "debug" profile is enabled
  adminer:
    image: adminer:4.8.1
    profiles:
      - debug
    ports:
      - "8080:8080"
```

A service with no `profiles:` key always starts. A service with one starts only
when that profile is enabled:

```bash
docker compose --profile debug up
COMPOSE_PROFILES=debug docker compose up

# Several at once
docker compose --profile debug --profile frontend up

# Everything
docker compose --profile "*" up
```

This is the cleanest way to keep seeders, admin UIs, and one-off tools in the
same file without inflicting them on everyone who runs `docker compose up`.

### Override Files

**Base (docker-compose.yml):**

```yaml
services:
  app:
    image: myapp:1.2.3
    ports:
      - "8000:8000"
```

**Override (docker-compose.override.yml):**

```yaml
services:
  app:
    volumes:
      - ./src:/app/src  # Development only
```

Compose automatically merges `docker-compose.override.yml` if present.

#### Removing a value in an override: !reset

Merging is additive, which is a problem when the override needs to take
something *away*. Setting the attribute to an empty value does not help, because
sequences merge rather than replace. The `!reset` YAML tag clears an attribute
that the base file set:

```yaml
# docker-compose.override.yml
services:
  app:
    ports: !reset []
    environment:
      FOO: !reset null
```

Against the base above, the merged result has no `ports` and no `FOO`. A value
must be present after the tag but it is ignored; write `!reset null` or
`!reset []` so a reader can see the attribute is being cleared rather than set.

The related `!override` tag replaces an attribute wholesale instead of merging
into it, which is what you want when the base declares ports you must drop while
declaring new ones:

```yaml
# docker-compose.override.yml
services:
  app:
    ports: !override
      - "8443:443"
```

`!override` requires Docker Compose 2.24.4 or later.

### Live Reload in Development: develop.watch

Bind-mounting source into a container is the traditional dev loop and it is a
poor one: it only works when the container's layout happens to match the host's,
and it silently does nothing for anything that needs a rebuild. The `develop`
section is the supported mechanism. It is optional in the Compose Specification
and available with Docker Compose 2.22.0 and later.

```yaml
services:
  frontend:
    image: myapp-frontend:1.2.3
    build: ./frontend
    develop:
      watch:
        # Copy changed static files into the running container
        - path: ./frontend/src
          action: sync
          target: /app/src
          ignore:
            - node_modules/

  backend:
    image: myapp-backend:1.2.3
    build: ./backend
    develop:
      watch:
        # Dependency changes need a real rebuild
        - path: ./backend/pyproject.toml
          action: rebuild
```

Run it with `docker compose watch`. The available actions:

- `sync`: copy changed files into the running container, no restart. For code
  that a hot reloader picks up on its own.
- `rebuild`: rebuild the image and recreate the service. For dependency
  manifests and anything baked in at build time.
- `sync+restart`: sync, then restart the container. For config a process only
  reads at startup. Available with Compose 2.23.0 and later.
- `restart`: restart the container without syncing. Available with Compose
  2.32.0 and later.
- `sync+exec`: sync, then run a command inside the container, e.g. a migration.
  Available with Compose 2.32.0 and later.

Set `ignore` on any `sync` rule that watches a directory containing installed
dependencies; syncing `node_modules/` from host to container is both slow and
usually wrong. The `initial_sync` attribute makes Compose reconcile files at the
start of a watch session for already-existing containers, so a container that
drifted while you were not watching does not start out stale.

### Splitting a Large Compose File: include

`include` composes a project out of other Compose files, each of which stays a
valid standalone project. This is different from `-f` merging: an included file
is parsed relative to its own directory, so a team can own their compose file
and its relative paths without knowing who includes it.

```yaml
include:
  - ../commons/compose.yaml
  - path: ../another/compose.yaml
    project_directory: ..
    env_file: ../another/.env

services:
  app:
    image: myapp:1.2.3
    depends_on:
      - database  # Defined in an included file
```

**Use Compose 2.40.2 or later if you use `include`.** Earlier versions carry
CVE-2025-62725 (CVSS 8.9): a path traversal in Compose's handling of OCI
artifact layer annotations lets a malicious remote Compose artifact write
outside the cache directory, and it triggers on read-only commands like
`docker compose config` and `docker compose ps`, so merely inspecting an
untrusted project is enough. Fixed 2025-10-27.

## Troubleshooting

### Service won't start

```bash
# Check logs
docker compose logs app

# Follow logs
docker compose logs -f app

# Check all services
docker compose ps
```

### Network issues

```bash
# Inspect networks
docker network ls
docker network inspect myproject_backend-network

# Test connectivity
docker compose exec app ping database
```

### Volume issues

```bash
# List volumes
docker volume ls

# Inspect volume
docker volume inspect myproject_postgres-data

# Remove all volumes (DANGER!)
docker compose down -v
```

## Migration from Old Compose Files

### Remove version field

```diff
- version: '3.8'
  services:
    app:
      image: myapp:1.2.3
```

### Reconsider container_name

Not a mechanical removal. Drop it where you want `--scale` or several
environments side by side:

```diff
  services:
    app:
      image: myapp:1.2.3
-     container_name: myapp-container
```

Then isolate environments by project name:

```bash
docker compose -p myapp-dev up
docker compose -p myapp-prod up
```

If the service is single-instance and something outside Compose addresses it by
that exact name, keep it and move on.

### Update image tags

```diff
  services:
    app:
-     image: myapp:latest
+     image: myapp:1.2.3
```

### Add health checks

```diff
  services:
    database:
      image: postgres:16-alpine
+     healthcheck:
+       test: ["CMD", "pg_isready", "-U", "myapp"]
+       interval: 10s
+       timeout: 5s
+       retries: 5
```

## Best Practices Summary

1. **No `version:` field**: use the Compose Specification
1. **`container_name:` deliberately, not by habit**: it blocks `--scale`
1. **Specific tags**: not `:latest`, and know that a tag is still mutable
1. **Health checks**: for dependencies, using a binary the image ships
1. **Resource limits**: prevent exhaustion
1. **Runtime hardening**: `read_only`, `cap_drop: [ALL]`, `no-new-privileges`,
   non-root `user`
1. **Secrets management**: files, not env vars, and never in git
1. **Networks**: isolate services
1. **Named volumes**: for persistence
1. **Environment files**: keep config separate
1. **Restart policies**: handle failures
1. **Profiles**: keep optional services out of the default `up`

## Linting

### Before any linter: docker compose config --quiet

`docker compose config --quiet` is the zero-install step and should run before
either linter below. It resolves the file (merging any override, expanding
`include`, substituting environment variables) and validates the result against
the Compose Specification schema. It reports on interpolation and schema
errors, not on the style or security rules the linters below cover, but a file
that fails it is not valid YAML-plus-Compose in the first place, so there is no
point running anything else against it yet.

### DCLint

[DCLint](https://github.com/zavoloklom/docker-compose-linter) is the
established third-party linter for Compose files. It ships as an npm package
(`dclint`, TypeScript) and as a Docker image, so it runs with or without
Node.js on the machine:

```bash
# npx, no install
npx dclint .
npx dclint compose.yaml

# Docker image, no Node.js required
docker pull zavoloklom/dclint
docker run -t --rm -v ${PWD}:/app zavoloklom/dclint .
```

It ships a `--fix` mode that auto-corrects most of its own findings; YAML
anchors are the one documented exception it will not touch.

### Overlap with this skill's analyzer

DCLint ships 15 rules. Two genuinely overlap with `scripts/analyze_compose.py`:

| DCLint rule | This skill's rule | Relationship |
| :--- | :--- | :--- |
| `no-version-field` | DC002 | Same check: the deprecated top-level `version:` field. |
| `service-image-require-explicit-tag` | DC012, DC013 | Same intent. DCLint covers both cases in one rule; the analyzer splits `:latest` (DC012) from a bare untagged image (DC013). |

The rest is disjoint. A meaningful chunk of DCLint's rule set is ordering and
formatting opinion rather than correctness, and can be turned off in its
config if it does not match your conventions:

- `no-quotes-in-volumes`, `require-quotes-in-ports`: quoting style.
- `service-container-name-regex`: enforces a naming convention, not a defect.
- `service-dependencies-alphabetical-order`, `service-keys-order`,
  `service-ports-alphabetical-order`, `services-alphabetical-order`,
  `top-level-properties-order`: pure ordering.

That leaves a real, disjoint set this skill's analyzer does not check at all:

- `no-build-and-image`: a service declaring both `build:` and `image:`.
- `no-duplicate-container-names`: two services (or a service and an unrelated
  container) sharing the same `container_name`. Different from this skill's
  DC010, which flags any use of `container_name:` regardless of collision.
- `no-duplicate-exported-ports`: the same host port published twice.
- `no-unbound-port-interfaces`: a port published with no explicit bind
  interface, which exposes the container on every host interface rather than
  just `127.0.0.1`.
- `require-project-name-field`: a missing top-level `name:` field.

Run both, in this order:

```bash
docker compose config --quiet
npx dclint compose.yaml
uv run scripts/analyze_compose.py compose.yaml
```

DCLint runs against a daemon-free parse of the file, same as this skill's
analyzer; neither needs Docker running. The skill's own analyzer still earns
its place: it is the only one of the two that flags secrets hardcoded into
`environment:`, missing health checks and restart policies, resource limits,
privileged mode, `network_mode: host`, and unused top-level `volumes:` or
`networks:` definitions, none of which DCLint's rule set touches.

## References

- [Compose Specification](https://docs.docker.com/compose/compose-file/)
- [Compose CLI Reference](https://docs.docker.com/compose/reference/)
- [Services top-level element](https://docs.docker.com/reference/compose-file/services/)
- [Merge Compose files](https://docs.docker.com/reference/compose-file/merge/)
- [Compose Develop Specification](https://docs.docker.com/reference/compose-file/develop/)
- [Use include to modularize Compose files](https://docs.docker.com/reference/compose-file/include/)
- [Using profiles with Compose](https://docs.docker.com/compose/how-tos/profiles/)
- [Docker Secrets](https://docs.docker.com/engine/swarm/secrets/)
- [DCLint (Docker Compose Linter)](https://github.com/zavoloklom/docker-compose-linter)
- [Health Checks](https://docs.docker.com/engine/reference/builder/#healthcheck)
- [CVE-2025-62725 advisory](https://github.com/docker/compose/security/advisories/GHSA-gv8h-7v7w-r22q)
