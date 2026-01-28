# Kubernetes and Helm Best Practices

Comprehensive guidelines for production-ready Helm charts with bjw-s common library.

## Image Management

### Version Pinning

**ALWAYS** use specific image tags:

```yaml
# ✅ GOOD - Specific version
image:
  repository: nginx
  tag: "1.25.3-alpine"
  pullPolicy: IfNotPresent

# ❌ BAD - latest is unpredictable
image:
  repository: nginx
  tag: latest
```

### Pull Policies

- `IfNotPresent`: Default, good for immutable tags
- `Always`: Use for mutable tags (dev environments)
- `Never`: Use only for local images

## Security

### Non-Root Users

**ALWAYS** run as non-root when possible:

```yaml
defaultPodOptions:
  securityContext:
    runAsNonRoot: true
    runAsUser: 10001
    runAsGroup: 10001
    fsGroup: 10001
    fsGroupChangePolicy: OnRootMismatch

controllers:
  main:
    containers:
      app:
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop:
              - ALL
```

### Service Account Tokens

Disable unless explicitly needed:

```yaml
defaultPodOptions:
  automountServiceAccountToken: false
```

### Secrets Management

**NEVER** hardcode secrets in values.yaml:

```yaml
# ❌ BAD - Secret in plain text
env:
  DATABASE_PASSWORD: "my-secret-password"

# ✅ GOOD - Reference external secret
env:
  DATABASE_PASSWORD:
    valueFrom:
      secretKeyRef:
        name: db-credentials
        key: password

# ✅ GOOD - Use sealed secrets or external secret operators
secrets:
  db-credentials:
    stringData:
      password: "<sealed or templated>"
```

### Read-Only Root Filesystem

Enforce when possible:

```yaml
securityContext:
  readOnlyRootFilesystem: true

# Provide writable directories with emptyDir
persistence:
  tmp:
    type: emptyDir
    globalMounts:
      - path: /tmp
  
  cache:
    type: emptyDir
    globalMounts:
      - path: /var/cache
```

## Resource Management

### Resource Requests and Limits

**ALWAYS** set both:

```yaml
resources:
  requests:
    cpu: 100m      # Guaranteed minimum
    memory: 128Mi
  limits:
    cpu: 500m      # Maximum allowed (optional for CPU)
    memory: 512Mi  # REQUIRED - prevents OOM kills
```

**Guidelines:**
- Start conservative, measure actual usage
- Requests: What the app needs under normal load
- Limits: Peak usage (leave headroom for spikes)
- Memory limits: ALWAYS set to prevent node issues
- CPU limits: Optional (throttling can cause issues)

### Quality of Service Classes

Kubernetes assigns QoS based on resources:

```yaml
# Guaranteed (highest priority)
# requests == limits for all containers
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 100m
    memory: 128Mi

# Burstable (medium priority)
# requests < limits OR only requests set
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    memory: 512Mi

# BestEffort (lowest priority)
# No requests or limits set
# ❌ Avoid in production
```

## Health Checks

### Liveness Probes

Detect if app needs restart:

```yaml
probes:
  liveness:
    enabled: true
    type: HTTP
    spec:
      path: /healthz
      port: http
      initialDelaySeconds: 30  # Wait for app to start
      periodSeconds: 10
      timeoutSeconds: 5
      failureThreshold: 3      # 3 failures = restart
```

### Readiness Probes

Detect if app can receive traffic:

```yaml
probes:
  readiness:
    enabled: true
    type: HTTP
    spec:
      path: /ready
      port: http
      initialDelaySeconds: 5
      periodSeconds: 5
      timeoutSeconds: 3
      failureThreshold: 3
```

### Startup Probes

For slow-starting apps:

```yaml
probes:
  startup:
    enabled: true
    type: HTTP
    spec:
      path: /startup
      port: http
      initialDelaySeconds: 0
      periodSeconds: 5
      timeoutSeconds: 3
      failureThreshold: 30  # 30 * 5s = 150s max startup time
```

**Probe Types:**
- `HTTP`: Best for web services
- `TCP`: For non-HTTP services
- `EXEC`: For custom checks

## Persistence

### Storage Classes

```yaml
persistence:
  data:
    type: persistentVolumeClaim
    storageClass: fast-ssd  # Or leave empty for default
    accessMode: ReadWriteOnce
    size: 10Gi
```

**Access Modes:**
- `ReadWriteOnce` (RWO): Single node R/W (most common)
- `ReadOnlyMany` (ROX): Multi-node read-only
- `ReadWriteMany` (RWX): Multi-node R/W (expensive, limited support)

### Volume Retention

```yaml
persistence:
  data:
    type: persistentVolumeClaim
    size: 10Gi
    retain: true  # Keep PVC on helm uninstall
```

### Mount Strategies

**globalMounts** for simple cases:

```yaml
persistence:
  config:
    globalMounts:
      - path: /config
```

**advancedMounts** for complex scenarios:

```yaml
persistence:
  shared:
    advancedMounts:
      main:
        app:
          - path: /app/data
            subPath: app
        sidecar:
          - path: /sidecar/data
            subPath: sidecar
```

## Networking

### Service Types

```yaml
service:
  app:
    type: ClusterIP        # Internal only (default)
    # type: LoadBalancer   # External with cloud LB
    # type: NodePort       # External on node port
```

**Guidelines:**
- `ClusterIP`: Default, use with Ingress
- `LoadBalancer`: Cloud environments only
- `NodePort`: Dev/testing, avoid in production

### Ingress Configuration

```yaml
ingress:
  main:
    enabled: true
    className: nginx
    annotations:
      cert-manager.io/cluster-issuer: letsencrypt-prod
      nginx.ingress.kubernetes.io/rate-limit: "100"
    
    hosts:
      - host: app.example.com
        paths:
          - path: /
            pathType: Prefix
            service:
              identifier: app
              port: http
    
    tls:
      - secretName: app-tls
        hosts:
          - app.example.com
```

## Controller Configuration

### Deployment Strategy

```yaml
controllers:
  main:
    strategy: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0      # Always keep at least 1 running
      maxSurge: 1            # Max 1 extra pod during update
```

**Strategies:**
- `RollingUpdate`: Zero-downtime updates (default)
- `Recreate`: Terminate old before creating new (for RWO volumes)

### Replicas and Scaling

```yaml
controllers:
  main:
    replicas: 2  # Or null for HPA

# With HorizontalPodAutoscaler (external)
# Set replicas: null in controller
```

### Pod Disruption Budgets

Protect availability during maintenance:

```yaml
controllers:
  main:
    replicas: 3
    podDisruptionBudget:
      minAvailable: 2  # Or maxUnavailable: 1
```

## Configuration Management

### ConfigMaps vs Secrets

**ConfigMaps**: Non-sensitive configuration

```yaml
configMaps:
  app-config:
    data:
      APP_MODE: production
      LOG_LEVEL: info
```

**Secrets**: Sensitive data

```yaml
secrets:
  app-secrets:
    stringData:
      api-key: your-key-here
      db-password: your-password
```

### Environment Variables

```yaml
# Direct values
env:
  APP_NAME: MyApp
  LOG_LEVEL: info

# From ConfigMap
env:
  APP_MODE:
    valueFrom:
      configMapKeyRef:
        identifier: app-config
        key: APP_MODE

# From Secret
env:
  API_KEY:
    valueFrom:
      secretKeyRef:
        identifier: app-secrets
        key: api-key

# Load all from ConfigMap/Secret
envFrom:
  - configMapRef:
      identifier: app-config
  - secretRef:
      identifier: app-secrets
```

## Labels and Annotations

### Standard Labels

```yaml
global:
  labels:
    app.kubernetes.io/name: myapp
    app.kubernetes.io/instance: "{{ .Release.Name }}"
    app.kubernetes.io/version: "{{ .Chart.AppVersion }}"
    app.kubernetes.io/managed-by: Helm
```

### Useful Annotations

```yaml
defaultPodOptions:
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "9090"
    prometheus.io/path: /metrics
```

## Naming Conventions

### Resource Naming

```yaml
# ✅ GOOD - Descriptive names
controllers:
  frontend:
    containers:
      nginx:
        ...
      php-fpm:
        ...

service:
  frontend:
    controller: frontend
    ports:
      http:
        port: 80

# ❌ BAD - Generic names
controllers:
  main:
    containers:
      main:
        ...
```

### Identifier vs Name

**Use identifier** to reference app-template resources:

```yaml
ingress:
  main:
    hosts:
      - paths:
          - service:
              identifier: app  # References service.app
```

**Use name** for external resources:

```yaml
persistence:
  config:
    existingClaim: my-app-config  # External PVC
```

## Multi-Environment Support

### Values Structure

```yaml
# values.yaml (defaults)
image:
  repository: myapp
  tag: "1.0.0"

# values-dev.yaml
image:
  pullPolicy: Always
ingress:
  hosts:
    - host: dev.example.com

# values-prod.yaml
replicas: 3
resources:
  limits:
    memory: 1Gi
ingress:
  hosts:
    - host: prod.example.com
```

Deploy with:

```bash
helm install myapp . -f values-prod.yaml
```

## StatefulSets

When to use:

- Stable network identities required
- Ordered deployment/scaling needed
- Persistent storage per pod

```yaml
controllers:
  database:
    type: statefulset
    
    statefulset:
      podManagementPolicy: OrderedReady
      volumeClaimTemplates:
        - name: data
          accessMode: ReadWriteOnce
          size: 20Gi
          globalMounts:
            - path: /var/lib/postgresql/data
```

## Jobs and CronJobs

### Jobs (One-time Tasks)

```yaml
controllers:
  migration:
    type: job
    
    job:
      backoffLimit: 3
      ttlSecondsAfterFinished: 86400  # Clean up after 24h
    
    containers:
      migrate:
        command:
          - /bin/migrate-db.sh
```

### CronJobs (Scheduled Tasks)

```yaml
controllers:
  backup:
    type: cronjob
    
    cronjob:
      schedule: "0 2 * * *"  # 2 AM daily
      concurrencyPolicy: Forbid
      successfulJobsHistory: 3
      failedJobsHistory: 1
```

## Monitoring and Observability

### Prometheus Metrics

```yaml
service:
  app:
    controller: main
    ports:
      http:
        port: 8080
      metrics:
        port: 9090

serviceMonitor:
  app:
    enabled: true
    endpoints:
      - port: metrics
        path: /metrics
        interval: 30s
```

### Logging

```yaml
containers:
  app:
    env:
      LOG_FORMAT: json
      LOG_LEVEL: info
```

## Testing

### Template Validation

```bash
# Check for errors
helm template . --debug

# Validate against Kubernetes
helm template . | kubectl apply --dry-run=client -f -

# Lint chart
helm lint .
```

### Install Validation

```bash
# Dry-run install
helm install --dry-run --debug myapp .

# Install with timeout
helm install myapp . --timeout 5m --wait

# Check status
helm status myapp
kubectl get pods -l app.kubernetes.io/instance=myapp
```

## Common Pitfalls

### Services Not Found in Ingress

```yaml
# ❌ WRONG
ingress:
  main:
    hosts:
      - paths:
          - service:
              name: app  # ❌ Won't work

# ✅ CORRECT
ingress:
  main:
    hosts:
      - paths:
          - service:
              identifier: app  # ✅ References service.app
```

### Volume Mounts Not Working

```yaml
# For single container - use globalMounts
persistence:
  config:
    globalMounts:
      - path: /config

# For multiple containers - use advancedMounts
persistence:
  shared:
    advancedMounts:
      main:
        app:
          - path: /app/data
        sidecar:
          - path: /sidecar/data
```

### Container Dependency Order

```yaml
# ✅ CORRECT - Use dependsOn
containers:
  app:
    image: myapp
  
  sidecar:
    dependsOn: app  # Starts after app
    image: sidecar
```

### Resource Names Too Long

```yaml
# ✅ Use nameOverride
global:
  fullnameOverride: myapp  # Instead of myapp-myrelease-long-name
```
