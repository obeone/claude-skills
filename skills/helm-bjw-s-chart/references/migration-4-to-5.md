# Migrating from bjw-s common 4.x to 5.x

This guide captures every breaking change introduced by
`common-5.0.0` (2026-05-04) plus the `5.0.1` patches (2026-05-14), and
lists the values-side rewrites you have to perform.

Official sources:

- [Upgrade notes — 4.x → 5.x](https://bjw-s-labs.github.io/helm-charts/docs/app-template/upgrades/4-to-5/)
- [Release notes — common-5.0.0](https://github.com/bjw-s-labs/helm-charts/releases/tag/common-5.0.0)
- [Release notes — common-5.0.1](https://github.com/bjw-s-labs/helm-charts/releases/tag/common-5.0.1)

## Prerequisites

| Requirement | 4.x       | 5.x       |
| :---------- | :-------- | :-------- |
| Kubernetes  | `>= 1.25` | `>= 1.31` |
| Helm        | `>= 3.14` | `>= 3.18` |

If the cluster can't meet the 5.x prerequisites, **stay on 4.6.2**. The
skill keeps documenting both tracks; the validator only warns when a
chart still pins 4.x.

## Bump the dependency

```yaml
# Chart.yaml
dependencies:
  - name: common
    repository: https://bjw-s-labs.github.io/helm-charts
    version: 5.0.1   # was 4.6.x
```

Then:

```bash
helm dependency update
helm template . --debug | less     # spot-check the rendered output
```

Commit the refreshed `Chart.lock`.

## Pre-upgrade checklist

Run through these before the helm dep bump — they correspond to the
five breaking changes covered below:

- [ ] **Workloads that talk to the Kubernetes API** — identify which
      pods actually need the SA token mounted. Set
      `defaultPodOptions.automountServiceAccountToken: true` (or the
      per-controller equivalent) on **only** those pods.
- [ ] **External / pre-existing ServiceAccount** — if you reference a
      SA created outside the chart, add
      `global.createDefaultServiceAccount: false` so 5.x doesn't create
      a parallel unprivileged SA.
- [ ] **`rawResources`** — convert every entry to the new
      `manifest:` wrapper (see below). Anything still using the legacy
      `spec:` shape renders an invalid manifest in 5.x.
- [ ] **Prometheus rules** — grep for jobs filtered by the old
      `ServiceMonitor.metadata.name` value; either override `jobLabel`
      back to that name or update the recording/alerting rules.
- [ ] **NetworkPolicies** — find policies that set both `controller`
      and `podSelector`. Pick one (5.x rejects the combo).

## Breaking change 1 — `automountServiceAccountToken` defaults to `false`

In 4.x, every pod mounted the SA token by default. In 5.x, the default
is `false`. Apps that hit the Kubernetes API (operators, controllers,
sidecars using `kubectl`, in-cluster clients) suddenly lose their token.

```yaml
# Before (4.x — implicit)
defaultPodOptions: {}

# After (5.x — opt-in per pod that needs it)
defaultPodOptions:
  automountServiceAccountToken: true
```

**RBAC reminder**: 5.x ships an *unprivileged* default ServiceAccount.
Mounting the token alone won't grant API access — you also need an
explicit `Role`/`ClusterRole` and a `RoleBinding`/`ClusterRoleBinding`.

## Breaking change 2 — A default unprivileged ServiceAccount is created

When no SA is configured, 5.x creates a per-release SA named after the
Helm release. This improves isolation but surprises charts that wired
in an externally-managed SA.

```yaml
# Opt out when you bring your own SA
global:
  createDefaultServiceAccount: false

# Or define a chart-managed SA — the default isn't created in that case
serviceAccount:
  app:
    annotations:
      example.com/purpose: workload-api-access

controllers:
  main:
    serviceAccount:
      identifier: app
```

If you do nothing, you'll get a fresh `ServiceAccount/<release-name>`
in the namespace. That's harmless but clutters `kubectl get sa`.

## Breaking change 3 — `rawResources` restructured

The manifest wrapper is required. Labels and annotations move under
`metadata`, and the `spec:` indirection is dropped (anything that used
to live at the manifest root now lives directly under `manifest:`).

```yaml
# Before (4.x)
rawResources:
  validating-webhook:
    enabled: true
    apiVersion: admissionregistration.k8s.io/v1
    kind: ValidatingWebhookConfiguration
    name: my-webhook
    labels:
      app: my-app
    annotations:
      description: "My webhook"
    spec:
      rules:
        - apiGroups: [""]
          apiVersions: ["v1"]
          operations: ["CREATE"]
          resources: ["pods"]
          scope: "Namespaced"

# After (5.x)
rawResources:
  validating-webhook:
    enabled: true
    manifest:
      apiVersion: admissionregistration.k8s.io/v1
      kind: ValidatingWebhookConfiguration
      metadata:
        labels:
          app: my-app
        annotations:
          description: "My webhook"
      rules:
        - apiGroups: [""]
          apiVersions: ["v1"]
          operations: ["CREATE"]
          resources: ["pods"]
          scope: "Namespaced"
```

Notes:

- `metadata.labels` / `metadata.annotations` you provide are
  automatically merged with the chart-managed labels/annotations.
- `metadata.name` is ignored — the library always derives the resource
  name from its naming scheme.
- `spec:` is gone for resources whose schema doesn't have a `spec`
  (`ValidatingWebhookConfiguration`, `ConfigMap`, etc.). Resources that
  *do* have a `spec` field (`Deployment`, `Service`, …) keep it
  underneath `manifest:` as normal — the change is the wrapper, not
  the schema.

## Breaking change 4 — `ServiceMonitor` / `PodMonitor` `jobLabel`

Both default to `app.kubernetes.io/name` in 5.x. In 4.x they defaulted
to the value of `metadata.name` on the monitor object itself.

```yaml
# Restore the 4.x default explicitly if your Prom rules rely on it
serviceMonitor:
  main:
    jobLabel: ""    # empty string ⇒ falls back to monitor's metadata.name
```

Easier path: update the Prometheus recording/alerting rules to match
on `app.kubernetes.io/name` and forget about the legacy.

## Breaking change 5 — NetworkPolicy `controller` / `podSelector`

Mutually exclusive in 5.x. 4.x silently let you set both with surprising
results.

```yaml
# Pick one — not both
networkpolicies:
  allow-from-ingress:
    enabled: true
    # Option A: target a chart-managed controller's pods
    controller: web

  allow-from-monitoring:
    enabled: true
    # Option B: target an arbitrary pod selector (no controller hint)
    podSelector:
      matchLabels:
        role: side-channel
```

### Bonus quality-of-life — single-controller auto-targeting

When the chart defines exactly one controller and the policy doesn't
specify `controller` or `podSelector`, 5.x auto-targets that
controller. Drop the explicit `controller:` line in simple
single-controller charts.

## What's new in 5.x (non-breaking, opt-in)

These are not migration steps — just capabilities you can adopt once
you're on 5.x:

- **HorizontalPodAutoscaler** wired to a controller
  (`horizontalPodAutoscaler.<id>`). Set
  `controllers.<id>.replicas: null` so the HPA owns the replica count.
- **PodMonitor** alongside ServiceMonitor — scrape pods directly when
  no Service is exposed (CronJob exporters, etc.).
- **Generic ephemeral volumes** via `persistence.<id>.type: ephemeral`
  — looks like a PVC, lifecycle bound to the pod.
- **Container-level `resizePolicy`** (in-place vertical scaling, K8s
  ≥ 1.35) and **pod-level `resizePolicy`** (K8s ≥ 1.36).
- **NetworkPolicy single-controller auto-targeting** (see above).

See [`patterns.md`](patterns.md) for ready-to-paste examples.

## Validation after migration

```bash
# Refresh deps and verify the lock pins common 5.x
helm dependency update
grep -A1 'name: common' Chart.lock

# Lint + dry-run render
helm lint .
helm template . --debug > /tmp/rendered.yaml

# bjw-s-aware structural validator (warns on 4.x pin and legacy rawResources shape)
uv run scripts/validate_chart.py .

# Diff against the previously-rendered 4.x output to spot surprises
diff /tmp/rendered-4x.yaml /tmp/rendered.yaml | less
```

A clean diff should only show:

- The new `ServiceAccount` object (unless you opted out)
- `automountServiceAccountToken: false` propagated to PodSpecs
- Updated `jobLabel` on any `ServiceMonitor` / `PodMonitor`
- `rawResources` rendered under the new manifest shape

Anything else means the migration touched a value you didn't intend to
change — investigate before applying.

## Rollback plan

If something breaks in the cluster, the lockfile is the rollback lever:

```bash
# Pin back to 4.6.2 in Chart.yaml, then:
helm dependency update
helm upgrade <release> .
```

Helm's `helm rollback <release>` also works as long as the prior
revision was still on 4.x — the rendered manifests are restored
verbatim and the 5.x-only resources (default SA, etc.) are deleted by
the upgrade hook.
