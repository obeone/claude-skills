---
name: helm-bjw-s-chart
description: "Generate production-ready Helm charts using the bjw-s-labs common library (app-template v4 and v5). Use when creating a new Helm chart, converting Docker Compose to Helm, configuring controllers with sidecars or init containers, setting up services/ingress/persistence, HorizontalPodAutoscalers, ServiceMonitors/PodMonitors, NetworkPolicies, or handling StatefulSets and multi-controller deployments."
metadata:
  version: "4.0.0"
---

# Helm bjw-s Chart Generator

> **🆕 v4.0.0 — common 5.x support** — Default dependency is now `common: 5.0.1` (released 2026-05-14). Charts pinned to `4.x` continue to work; see "Library version compatibility" below for the migration matrix and breaking-change notes.
>
> **🔄 Renamed in v3.0.0** — This skill was previously published as `helm-chart-generator`. If an agent, automation, or documentation still references the old name (`helm-chart-generator`, `helm-chart-generator.skill`, `skills/helm-chart-generator/`), update it to `helm-bjw-s-chart`. The old asset URL will 404 from v3.0.0 onward.

Generate production-ready Helm charts using the bjw-s-labs common library (app-template v4 and v5).

## Library version compatibility

| common version | Kubernetes | Helm | Status                                  |
| :------------- | :--------- | :--- | :-------------------------------------- |
| `5.0.1`        | `>= 1.31`  | `>= 3.18` | **Default** — latest, recommended  |
| `4.6.0`        | `>= 1.25`  | `>= 3.14` | Supported — use on older clusters  |

The skill is **backward-compatible**: every pattern documented here works on
both `4.x` and `5.x`. New 5.x-only features (HorizontalPodAutoscaler,
PodMonitor, generic ephemeral volumes, container/pod `resizePolicy`,
NetworkPolicy single-controller auto-detection) are flagged with
**`(common ≥ 5.0)`** so agents targeting `4.x` can skip them.

### Breaking changes when migrating 4.x → 5.x

1. **`automountServiceAccountToken` now defaults to `false`** (was `true`).
   Set it back to `true` per-pod if your workload reads the token.
2. **A default unprivileged ServiceAccount is created**. Opt out with
   `global.createDefaultServiceAccount: false` if you reference an
   externally-managed ServiceAccount.
3. **ServiceMonitor / PodMonitor `jobLabel`** now defaults to
   `app.kubernetes.io/name`. Override if your Prometheus rules depend on
   the old default.
4. **`rawResources`** schema restructured — manifest content moved out of
   `spec:` into a manifest wrapper key. Only relevant if you used
   `rawResources` (rare).
5. **Minimum Kubernetes 1.31** and **Helm 3.18** required.

## Quick Start Workflow

1. **Understand the application**
   - Ask about the container image, ports, environment variables
   - Identify if sidecars/init containers are needed
   - Determine storage requirements (config, data, logs)
   - Check if ingress/networking is required

2. **Generate base structure**
   - Use templates from `assets/templates/`
   - Start with Chart.yaml and basic values.yaml
   - Add templates/common.yaml (minimal, just includes library)
   - Create templates/NOTES.txt for post-install instructions

3. **Build values.yaml progressively**
   - Controllers and containers (main app + sidecars if needed)
   - Services (one per controller or port)
   - Ingress if web-accessible
   - Persistence for stateful data
   - Secrets/ConfigMaps if needed

4. **Validate and refine**
   - Run `helm dependency update` to fetch dependencies (generates Chart.lock)
   - Use `scripts/validate_chart.py` to check structure
   - Review against `references/best-practices.md`
   - Test with `helm template` and `helm lint`

## Core Structure

Every chart consists of:

```text
my-app/
├── Chart.yaml           # Chart metadata and dependencies
├── values.yaml          # Configuration values
└── templates/
    ├── common.yaml      # Includes the bjw-s library
    └── NOTES.txt        # Post-install instructions
```

### Chart.yaml Template

```yaml
apiVersion: v2
name: <app-name>
description: <brief description>
type: application
version: 1.0.0
appVersion: "<app version>"
dependencies:
  - name: common
    repository: https://bjw-s-labs.github.io/helm-charts
    version: 5.0.1  # Latest stable (needs K8s >= 1.31 / Helm >= 3.18)
    # Pin to 4.6.0 for clusters that don't meet the 5.x prerequisites.
```

### templates/common.yaml (Always the same)

```yaml
{{- include "bjw-s.common.loader.all" . }}
```

### templates/NOTES.txt

Provide useful post-install information:

- How to access the application
- Default credentials if any
- Next steps for configuration

## values.yaml Structure

Follow this order for clarity:

```yaml
# 1. Default Pod options (optional)
defaultPodOptions:
  securityContext: {}
  annotations: {}

# 2. Controllers (required)
controllers:
  main:  # or custom name
    containers:
      main:  # or custom name
        image: {}
        env: {}
        probes: {}

# 3. Service (required if exposing)
service:
  main:
    controller: main
    ports: {}

# 4. Ingress (optional)
ingress:
  main:
    className: ""
    hosts: []

# 5. Persistence (optional)
persistence:
  config:
    type: persistentVolumeClaim
    # or: emptyDir, configMap, secret, nfs, hostPath

# 6. ConfigMaps/Secrets (optional)
configMaps: {}
secrets: {}
```

## Common Patterns

### Single Container Application

```yaml
controllers:
  main:
    containers:
      main:
        image:
          repository: nginx
          tag: "1.25-alpine"
          pullPolicy: IfNotPresent

service:
  main:
    controller: main
    ports:
      http:
        port: 80

persistence:
  config:
    type: persistentVolumeClaim
    accessMode: ReadWriteOnce
    size: 1Gi
    globalMounts:
      - path: /config
```

### Application with Sidecar

```yaml
controllers:
  main:
    containers:
      main:
        image:
          repository: myapp
          tag: latest
      
      sidecar:
        dependsOn: main
        image:
          repository: sidecar-image
          tag: "1.0.0"
```

See `references/patterns.md` for more examples:

- Multi-controller setups
- Init containers
- VPN sidecars (gluetun)
- Code-server sidecars
- Shared volumes between containers
- Private registries with `imagePullSecrets`
- StatefulSets with headless service
- HorizontalPodAutoscaler **(common ≥ 5.0)**
- PodMonitor (scrape pods without a Service) **(common ≥ 5.0)**
- Generic ephemeral volumes **(common ≥ 5.0)**

## What's new in common 5.x

These options are **only** available when the chart depends on
`common >= 5.0.0`. They are silently ignored by `4.x`.

```yaml
# 1. HorizontalPodAutoscaler tied to a controller
horizontalPodAutoscaler:
  main:
    enabled: true
    controller: main           # Target controller identifier
    minReplicas: 2
    maxReplicas: 10
    metrics:
      - type: Resource
        resource:
          name: cpu
          target:
            type: Utilization
            averageUtilization: 70

# 2. PodMonitor (alternative to ServiceMonitor — scrapes pods directly)
podMonitor:
  main:
    enabled: true
    controller: main
    endpoints:
      - port: metrics
        path: /metrics
        interval: 30s

# 3. Generic ephemeral volumes (per-pod PVC, deleted with the pod)
persistence:
  scratch:
    type: ephemeral
    accessMode: ReadWriteOnce
    size: 5Gi
    storageClass: fast-ssd
    globalMounts:
      - path: /scratch

# 4. Container / Pod resizePolicy (in-place vertical scaling)
#    container: Kubernetes >= 1.35   |   pod: Kubernetes >= 1.36
controllers:
  main:
    pod:
      resizePolicy: PreferNoRestart   # (k8s >= 1.36)
    containers:
      main:
        resizePolicy:                 # (k8s >= 1.35)
          - resourceName: cpu
            restartPolicy: NotRequired
          - resourceName: memory
            restartPolicy: RestartContainer
```

NetworkPolicies also gained an ergonomic improvement: when exactly one
controller is defined and you omit both `controller` and `podSelector`,
the policy automatically targets that controller.

## Best Practices

**Always:**

- Use specific image tags, never `:latest`
- Set resource limits and requests
- Configure health checks (liveness, readiness, startup)
- Use non-root security contexts when possible
- Reference services by identifier, not name

**Naming:**

- Controllers: Use descriptive names (not just "main")
- Containers: Use descriptive names (not just "main")
- Services: Match controller name or purpose

**Security:**

- Set `automountServiceAccountToken: false` unless needed
- Configure proper `securityContext`
- Use secrets for sensitive data
- Use `imagePullSecrets` for private registries (see `references/patterns.md`)

**Persistence:**

- Use `globalMounts` for simple cases
- Use `advancedMounts` for complex multi-container scenarios
- Specify `existingClaim` for pre-created PVCs

See `references/best-practices.md` for comprehensive guidelines.

## Validation

After generating a chart:

```bash
# 1. Fetch dependencies (required before helm commands)
cd /path/to/chart
helm dependency update

# 2. Validate structure
python scripts/validate_chart.py /path/to/chart
# Or with JSON output for CI:
python scripts/validate_chart.py --json /path/to/chart

# 3. Helm validation
helm lint .
helm template . --debug

# 4. Dry-run installation
helm install --dry-run --debug my-release .
```

## Pre-Deploy Checklist

Before deploying to a cluster, verify:

- [ ] All image tags are pinned (no `:latest`)
- [ ] Resources (requests + memory limits) are set on every container
- [ ] Health probes configured (liveness + readiness minimum)
- [ ] `securityContext` set: non-root, `readOnlyRootFilesystem`, drop ALL capabilities
- [ ] `automountServiceAccountToken: false` unless explicitly needed
- [ ] Secrets reference external sources, not hardcoded values
- [ ] `helm dependency update` run and `Chart.lock` committed
- [ ] `helm lint` passes with no errors

## Common Issues

**Services not found**: Use `identifier` not `name` in ingress paths
**Mounts not working**: Check `globalMounts` vs `advancedMounts` usage
**Names too long**: Use `nameOverride` or `fullnameOverride` in global settings
**Controller not starting**: Check `dependsOn` order for init/sidecar containers

## References

- `references/patterns.md` - Common deployment patterns
- `references/best-practices.md` - Kubernetes/Helm best practices
- `references/values-schema.md` - Complete values.yaml reference
- `assets/templates/` - Base templates for quick start
