# Docker Compose Best Practices

Modern guide for creating efficient, scalable, and maintainable Docker Compose configurations.

## Deprecated: version Field

**DON'T use the `version:` field** in docker-compose.yml files.

```yaml
# ❌ OUTDATED - Don't do this
version: '3.8'
services:
  app:
    image: myapp:latest
```

```yaml
# ✅ MODERN - Do this instead
services:
  app:
    image: myapp:latest
```

### Why?

- The `version:` field is deprecated since Compose V2
- Compose now uses the Compose Specification (no versioning)
- Files without `version:` are forward-compatible
- Official docs no longer recommend it

### Reference

[Compose Specification](https://docs.docker.com/compose/compose-file/)

## Never Use container_name

**NEVER use `container_name:`** in service definitions.

```yaml
# ❌ BAD - Don't use container_name
services:
  app:
    image: myapp:latest
    container_name: my-app-container
```

```yaml
# ✅ GOOD - Let Compose generate names
services:
  app:
    image: myapp:latest
```

### Why?

- Prevents running multiple instances (`docker compose up --scale app=3`)
- Breaks horizontal scaling
- Creates naming conflicts in multi-environment setups
- Prevents parallel testing environments
- Compose generates predictable names: `{project}_{service}_{replica}`

Use project names to differentiate environments instead:

```bash
# Development
docker compose -p myapp-dev up

# Testing
docker compose -p myapp-test up

# Each creates isolated containers with predictable names
```

## Additional Compose Best Practices

### Use Specific Image Tags

```yaml
# ❌ BAD
services:
  app:
    image: myapp:latest

# ✅ GOOD
services:
  app:
    image: myapp:1.2.3
```

**Why:** `:latest` is unpredictable and changes without warning.

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

```yaml
# ✅ BEST - Use .env file
services:
  app:
    image: myapp:1.2.3
    env_file:
      - .env

# ✅ OK - Explicit env vars
services:
  app:
    image: myapp:1.2.3
    environment:
      - NODE_ENV=production
      - API_URL=https://api.example.com

# ❌ BAD - Secrets in environment
services:
  app:
    environment:
      - DATABASE_PASSWORD=secret123  # Don't do this
```

**Important:** Add `.env` to `.gitignore`!

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

**Never:**

- Commit secrets to git
- Use environment variables for secrets
- Hardcode passwords in compose files

## Complete Example: Modern Compose File

```yaml
# No version field

services:
  frontend:
    image: myapp-frontend:1.2.3
    build:
      context: ./frontend
      dockerfile: Dockerfile
    # No container_name
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
    # No container_name - allows scaling
    expose:
      - "8000"
    env_file:
      - .env
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
- [ ] No `container_name:` (never use it)
- [ ] Specific image tags (not `:latest`)
- [ ] Health checks defined for critical services
- [ ] Resource limits set
- [ ] Restart policies configured
- [ ] Secrets via files/secrets, not env vars
- [ ] Named volumes for persistence
- [ ] Networks for service isolation
- [ ] `.env` file in `.gitignore`
- [ ] `depends_on` with `condition: service_healthy` for ordered startup

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

# Only works if no container_name is set!
```

### Override Files

**Base (docker-compose.yml):**

```yaml
services:
  app:
    image: myapp:latest
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
      image: myapp:latest
```

### Remove container_name (always)

```diff
  services:
    app:
      image: myapp:latest
-     container_name: myapp-container
```

Use project names instead for environment isolation:

```bash
docker compose -p myapp-dev up
docker compose -p myapp-prod up
```

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

1. **No `version:` field** - Use Compose Specification
2. **Never use `container_name:`** - Allow scaling and parallel environments
3. **Specific tags** - Not `:latest`
4. **Health checks** - For dependencies
5. **Resource limits** - Prevent exhaustion
6. **Secrets management** - Never in git
7. **Networks** - Isolate services
8. **Named volumes** - For persistence
9. **Environment files** - Keep config separate
10. **Restart policies** - Handle failures

## References

- [Compose Specification](https://docs.docker.com/compose/compose-file/)
- [Compose CLI Reference](https://docs.docker.com/compose/reference/)
- [Docker Secrets](https://docs.docker.com/engine/swarm/secrets/)
- [Health Checks](https://docs.docker.com/engine/reference/builder/#healthcheck)
