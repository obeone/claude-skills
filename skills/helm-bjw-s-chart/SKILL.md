---
name: helm-bjw-s-chart
description: "Generate production-ready Helm charts on the bjw-s-labs common library (app-template v5, v4 legacy). Use for new charts, Compose-to-Helm conversion, sidecars, init containers, services, ingress, persistence, StatefulSets, HPAs, Service/PodMonitors, and NetworkPolicies."
metadata:
  version: "5.3.0"
---

# Helm bjw-s Chart Generator

> Published as `helm-chart-generator` until v2.x. Update anything still
> pointing at the old name.

## Library version matrix

| common  | Kubernetes | Helm      | Status                                              |
| :------ | :--------- | :-------- | :-------------------------------------------------- |
| `5.1.0` | `>= 1.31`  | `>= 3.18` | **Default** — latest stable, all examples target it |
| `4.6.2` | `>= 1.25`  | `>= 3.14` | Legacy — pin when the cluster can't meet 5.x reqs   |

Everything documented here works on **common 5.x** by default. When a
pattern is **not available on 4.x** it's tagged **`(5.x only)`** so
agents pinned to the legacy track can skip it. See
[`references/migration-4-to-5.md`](references/migration-4-to-5.md) for
the full 4 → 5 upgrade procedure.

## New in common 5.1.0

Drop-in over 5.0.x — no values change is required to upgrade. Four
additions, each with a worked example in
[`references/patterns.md`](references/patterns.md):

1. **DaemonSets accept `strategy` / `rollingUpdate`** and render a real
   `updateStrategy`. On 5.0.x both keys were silently ignored for this
   controller type.
2. **`serviceAccount.<id>.automountServiceAccountToken`** sets the field
   on the ServiceAccount object itself. It does not replace the pod-level
   key: the library always writes `automountServiceAccountToken` into the
   pod spec (default `false`), and the pod spec wins. Set both.
3. **`route.<id>.namespaceOverride`** deploys a Route into another
   namespace, and the library then emits the matching `ReferenceGrant`
   automatically. Turn that off with
   `route.<id>.referenceGrant.enabled: false`.
4. **`rollingUpdate` takes the upstream key names** — `maxSurge` and
   `maxUnavailable`. The old `surge` / `unavailable` shorthands still
   work but are deprecated and disappear in 6.0. StatefulSets gained
   `rollingUpdate.maxUnavailable`, which the cluster only honours with the
   `MaxUnavailableStatefulSet` feature gate — alpha and off by default up
   to Kubernetes 1.34, beta from 1.35 with the default varying by patch
   release.

One behavioral change: an invalid `strategy` is now rejected by the values
schema instead of a template `fail`, so `helm lint` reports it earlier and
the message names the valid values per controller type.

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

1. **Understand the app.** Image, ports, environment, storage (config,
   data, logs), ingress, and whether sidecars or init containers apply.
2. **Generate the base** from `assets/templates/`: `Chart.yaml`,
   `values.yaml`, `templates/common.yaml`, `templates/NOTES.txt`.
3. **Build `values.yaml` in order**: controllers and containers, then
   services, ingress, persistence, secrets and configMaps.
4. **Validate**: `helm dependency update` (writes `Chart.lock`), then
   `validate_chart.py`, then `helm lint` and `helm template`.

## Core Structure

```text
my-app/
├── Chart.yaml           # Metadata and dependencies
├── values.yaml          # Configuration
└── templates/
    ├── common.yaml      # Includes the bjw-s library
    └── NOTES.txt        # Post-install instructions
```

`templates/common.yaml` is always exactly one line:
`{{- include "bjw-s.common.loader.all" . }}`. `NOTES.txt` covers how to
reach the app, default credentials if any, and the next configuration
step.

### Chart.yaml

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
    version: 5.1.0  # Default. Pin to 4.6.2 for legacy clusters (K8s < 1.31 / Helm < 3.18).
```

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

The baseline, a single container with a service and a PVC:

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

A sidecar is one more entry under `containers:` with
`dependsOn: <container>` to order startup.

See [`references/patterns.md`](references/patterns.md) for worked examples:

- Multi-controller setups
- Init containers
- VPN sidecars (gluetun)
- Code-server sidecars
- Shared volumes between containers
- Private registries with `imagePullSecrets`
- StatefulSets with headless service

Plus one section per 5.x-only key listed below.

## Version-gated features

These are ignored or rejected below the version in the `Since` column.
Each has a worked example in
[`references/patterns.md`](references/patterns.md):

| Key | Since | What it buys you |
| :-------------------------- | :------ | :--------------------------------------- |
| `horizontalPodAutoscaler`   | `5.0.0` | Autoscaling bound to a controller identifier |
| `podMonitor`                | `5.0.0` | Prometheus scraping without a Service     |
| `persistence.*.type: ephemeral` | `5.0.0` | Per-pod PVC, deleted with the pod     |
| `resizePolicy` (pod + container) | `5.0.0` | In-place CPU/memory resize, no pod recreation |
| `networkpolicies`           | `5.0.0` | Auto-targets the only controller when it is unambiguous |
| `strategy` on a DaemonSet   | `5.1.0` | Real `updateStrategy` instead of a silently dropped key |
| `serviceAccount.*.automountServiceAccountToken` | `5.1.0` | Declares the token policy on the SA itself, for consumers outside the chart |
| `route.*.namespaceOverride` | `5.1.0` | Cross-namespace Route with an auto-generated `ReferenceGrant` |
| `rollingUpdate.maxSurge` / `.maxUnavailable` | `5.1.0` | Upstream key names; `surge` / `unavailable` are deprecated |

## Best Practices

These shape every generated chart. The reasoning, and the long form, are
in [`references/best-practices.md`](references/best-practices.md).

- Pin image tags, never `:latest`. Requests and limits on every
  container. Liveness and readiness probes at minimum.
- Non-root `securityContext`. Secrets for sensitive data,
  `imagePullSecrets` for private registries.
- Reference services by identifier, not by name.
- Name controllers and containers for what they do, not `main`; name
  services after their controller or their purpose.
- Keep `automountServiceAccountToken: false` (the 5.x default). When the
  workload genuinely calls the K8s API, pair it with an explicit
  ServiceAccount and RBAC rather than the auto-created default.
- `globalMounts` for simple cases, `advancedMounts` for multi-container,
  `existingClaim` for pre-created PVCs, `type: ephemeral` for scratch
  space tied to the pod (5.x only).

## Validation

After generating a chart:

```bash
# 1. Fetch dependencies (required before helm commands)
cd /path/to/chart
helm dependency update

# 2. Validate structure (uv reads the script's PEP 723 header)
uv run scripts/validate_chart.py /path/to/chart
# Or with JSON output for CI:
uv run scripts/validate_chart.py --json /path/to/chart

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

A published chart must be self-contained: both `Chart.lock` and a
populated `charts/` have to be present before `helm package` runs, or
offline consumers cannot resolve the common library. Run
`helm dependency update` first, then package. Either commit `charts/` to
git, or gitignore it and run `helm dependency build` in the pipeline.

Full rationale and the two strategies:
[`references/best-practices.md`](references/best-practices.md), section
"Publishing and Dependency Vendoring".

## Common Issues

**Services not found**: Use `identifier` not `name` in ingress paths
**Mounts not working**: Check `globalMounts` vs `advancedMounts` usage
**Names too long**: Use `nameOverride` or `fullnameOverride` in global settings
**Controller not starting**: Check `dependsOn` order for init/sidecar containers
**Unexpected ServiceAccount appears (5.x)**: Set `global.createDefaultServiceAccount: false` or define your own SA
**Pod can't talk to the K8s API (5.x)**: Set `automountServiceAccountToken: true` on the pod AND grant RBAC
**`strategy` rejected by `helm lint` (5.1+)**: It is a string, never a map, and the valid values depend on the controller type
**Cross-namespace Route can't reach the Service**: The `ReferenceGrant` is only emitted from `namespaceOverride`, not from a hand-written `backendRefs.namespace`

## References

- [`references/migration-4-to-5.md`](references/migration-4-to-5.md) - Full 4 → 5 upgrade procedure
- [`references/patterns.md`](references/patterns.md) - Common deployment patterns
- [`references/best-practices.md`](references/best-practices.md) - Kubernetes/Helm best practices
- [`references/values-schema.md`](references/values-schema.md) - Complete values.yaml reference
- [`assets/templates/`](assets/templates/) - Base templates for quick start
