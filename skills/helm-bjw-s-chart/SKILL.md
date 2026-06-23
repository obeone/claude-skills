---
name: helm-bjw-s-chart
description: "Generate production-ready Helm charts using the bjw-s-labs common library (app-template v5, with v4 legacy support). Use when creating a new Helm chart, converting Docker Compose to Helm, configuring controllers with sidecars or init containers, setting up services/ingress/persistence, HorizontalPodAutoscalers, ServiceMonitors/PodMonitors, NetworkPolicies, or handling StatefulSets and multi-controller deployments."
metadata:
  version: "5.1.0"
---

# Helm bjw-s Chart Generator

> **🆕 v5.0.0 — common 5.x is now the default** — The skill is rebased on
> `common: 5.0.1` (released 2026-05-14). New charts target 5.x out of the
> box, and the migration path from 4.x is captured in
> [`references/migration-4-to-5.md`](references/migration-4-to-5.md). 4.x
> remains supported as a legacy track for clusters that can't meet the
> Kubernetes 1.31 / Helm 3.18 prerequisites.
>
> **🔄 Renamed in v3.0.0** — This skill was previously published as
> `helm-chart-generator`. Update any agent, automation, or documentation
> that still references the old name.

Generate production-ready Helm charts using the bjw-s-labs common library
(app-template v5, with v4 legacy support).

## Library version matrix

| common  | Kubernetes | Helm      | Status                                              |
| :------ | :--------- | :-------- | :-------------------------------------------------- |
| `5.0.1` | `>= 1.31`  | `>= 3.18` | **Default** — latest stable, all examples target it |
| `4.6.2` | `>= 1.25`  | `>= 3.14` | Legacy — pin when the cluster can't meet 5.x reqs   |

Everything documented here works on **common 5.x** by default. When a
pattern is **not available on 4.x** it's tagged **`(5.x only)`** so
agents pinned to the legacy track can skip it. See
[`references/migration-4-to-5.md`](references/migration-4-to-5.md) for
the full 4 → 5 upgrade procedure.

## Migration 4.x → 5.x at a glance

Five things to know — full details in
[`references/migration-4-to-5.md`](references/migration-4-to-5.md):

1. **`automountServiceAccountToken: false`** is now the default. Flip it
   back to `true` per-pod if the workload needs to call the Kubernetes
   API.
2. **A default unprivileged ServiceAccount is created** for every release.
   Opt out with `global.createDefaultServiceAccount: false` when you
   reference an externally-managed SA.
3. **`rawResources` was restructured** — manifest content moved out of
   `spec:` into a `manifest:` wrapper, and labels/annotations now live
   under `metadata:`. Only relevant if you use `rawResources` (rare).
4. **ServiceMonitor / PodMonitor `jobLabel`** defaults to
   `app.kubernetes.io/name`. Override if your Prometheus rules depended on
   the old `metadata.name` default.
5. **Minimums bumped**: Kubernetes **≥ 1.31**, Helm **≥ 3.18**.

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
    version: 5.0.1  # Default. Pin to 4.6.2 for legacy clusters (K8s < 1.31 / Helm < 3.18).
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
  # 5.x default is false; set to true only if the pod calls the K8s API.
  automountServiceAccountToken: false
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
    # or: emptyDir, configMap, secret, nfs, hostPath, ephemeral

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
          tag: "1.0.0"

      sidecar:
        dependsOn: main
        image:
          repository: sidecar-image
          tag: "1.0.0"
```

See [`references/patterns.md`](references/patterns.md) for more examples:

- Multi-controller setups
- Init containers
- VPN sidecars (gluetun)
- Code-server sidecars
- Shared volumes between containers
- Private registries with `imagePullSecrets`
- StatefulSets with headless service
- HorizontalPodAutoscaler **(5.x only)**
- PodMonitor (scrape pods without a Service) **(5.x only)**
- Generic ephemeral volumes **(5.x only)**
- NetworkPolicy with single-controller auto-targeting **(5.x only)**

## 5.x-only features

The patterns below require `common >= 5.0.0`. They are silently ignored
or rejected on 4.x.

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
#    container resizePolicy: Kubernetes >= 1.35
#    pod resizePolicy:       Kubernetes >= 1.36
controllers:
  main:
    pod:
      resizePolicy: PreferNoRestart   # k8s >= 1.36
    containers:
      main:
        resizePolicy:                 # k8s >= 1.35
          - resourceName: cpu
            restartPolicy: NotRequired
          - resourceName: memory
            restartPolicy: RestartContainer

# 5. NetworkPolicy auto-targets the only controller when neither
#    `controller` nor `podSelector` is given. `controller` and
#    `podSelector` are now mutually exclusive.
networkpolicies:
  default-deny:
    enabled: true
    policyTypes:
      - Egress
```

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

- Keep `automountServiceAccountToken: false` (5.x default) unless the
  workload calls the K8s API — and even then, pair it with an explicit
  ServiceAccount + RBAC, not the auto-created default
- Configure proper `securityContext`
- Use secrets for sensitive data
- Use `imagePullSecrets` for private registries (see `references/patterns.md`)

**Persistence:**

- Use `globalMounts` for simple cases
- Use `advancedMounts` for complex multi-container scenarios
- Specify `existingClaim` for pre-created PVCs
- Use `type: ephemeral` for scratch space tied to the pod lifecycle (5.x only)

See [`references/best-practices.md`](references/best-practices.md) for
comprehensive guidelines.

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

The validator warns when the chart still pins `common 4.x`, when
`rawResources` uses the legacy `spec:` shape (removed in 5.x), when
an external ServiceAccount is referenced without
`global.createDefaultServiceAccount: false`, when `Chart.lock` is
missing, or when a declared dependency has no vendored tarball under
`charts/`.

## Pre-Deploy Checklist

Before deploying to a cluster, verify:

- [ ] All image tags are pinned (no `:latest`)
- [ ] Resources (requests + memory limits) are set on every container
- [ ] Health probes configured (liveness + readiness minimum)
- [ ] `securityContext` set: non-root, `readOnlyRootFilesystem`, drop ALL capabilities
- [ ] `automountServiceAccountToken: false` unless explicitly needed
- [ ] If using an external ServiceAccount, `global.createDefaultServiceAccount: false` is set
- [ ] If `rawResources` is in play, manifest uses the 5.x `manifest:` wrapper (not legacy `spec:`)
- [ ] Secrets reference external sources, not hardcoded values
- [ ] `helm dependency update` run, with `Chart.lock` **and** the populated `charts/` published (see [Publishing the Chart](#publishing-the-chart))
- [ ] `helm lint` passes with no errors

## Publishing the Chart

A published chart must be **self-contained**. Both of these have to ship
inside the packaged `.tgz` (and the committed chart):

- `Chart.lock` — pins the exact resolved dependency versions and digests.
- The full `charts/` directory — the vendored dependency tarballs
  (`common-<version>.tgz`, …) materialized by `helm dependency update`.

`helm package` bundles whatever is under `charts/` at package time, and the
default `.helmignore` excludes neither `Chart.lock` nor `charts/`. The rule
is therefore about making sure both are present *before* you package:

```bash
# Vendor dependencies into charts/ and (re)generate Chart.lock
helm dependency update

# ...then package — the .tgz now embeds charts/common-<version>.tgz
helm package .
```

Two equally valid ways to satisfy it:

- **Commit `charts/` to git** (vendoring): the checkout is already
  self-contained; the publish step is just `helm package`.
- **Gitignore `charts/`** but commit `Chart.lock`, then run
  `helm dependency build` in the publish pipeline before `helm package`.
  `helm dependency build` repopulates `charts/` from the locked versions
  without re-resolving them.

Never publish a chart whose `charts/` is empty while `Chart.yaml` declares
dependencies: consumers without the `bjw-s-labs.github.io/helm-charts` repo
pre-added (offline / air-gapped installs) cannot resolve the common library
at install time. `scripts/validate_chart.py` warns when `Chart.lock` is
missing or when a declared dependency has no matching tarball under
`charts/`.

## Common Issues

**Services not found**: Use `identifier` not `name` in ingress paths
**Mounts not working**: Check `globalMounts` vs `advancedMounts` usage
**Names too long**: Use `nameOverride` or `fullnameOverride` in global settings
**Controller not starting**: Check `dependsOn` order for init/sidecar containers
**Unexpected ServiceAccount appears (5.x)**: Set `global.createDefaultServiceAccount: false` or define your own SA
**Pod can't talk to the K8s API (5.x)**: Set `automountServiceAccountToken: true` on the pod AND grant RBAC

## References

- [`references/migration-4-to-5.md`](references/migration-4-to-5.md) - Full 4 → 5 upgrade procedure
- [`references/patterns.md`](references/patterns.md) - Common deployment patterns
- [`references/best-practices.md`](references/best-practices.md) - Kubernetes/Helm best practices
- [`references/values-schema.md`](references/values-schema.md) - Complete values.yaml reference
- [`assets/templates/`](assets/templates/) - Base templates for quick start
