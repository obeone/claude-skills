# Docker Compose → bjw-s `values.yaml` Mapping

Practical reference for converting a `docker-compose.yaml` stack into
bjw-s app-template v5 `values.yaml`, instead of re-deriving the mapping
each time.

Core mental shift: a compose **service** is one container on one host.
A bjw-s **controller** is a Kubernetes workload resource
(Deployment/StatefulSet/DaemonSet/CronJob/Job) managing a pod template
that can hold *multiple* containers. Compose's flat `services:` map
splits across two bjw-s levels: `controllers.<id>` for the workload,
`containers.<id>` inside it for each process.

## Table of Contents

- [Quick Mapping Table](#quick-mapping-table)
- [Worked Example](#worked-example)
- [Service → Controller + Container](#service--controller--container)
- [image → containers.<name>.image](#image--containersnameimage)
- [ports → service.<id>.ports](#ports--serviceidports)
- [volumes → persistence](#volumes--persistence)
- [environment / env_file → env / envFrom](#environment--env_file--env--envfrom)
- [depends_on → dependsOn / initContainers](#depends_on--dependson--initcontainers)
- [restart / deploy.replicas → controller type / replicas](#restart--deployreplicas--controller-type--replicas)
- [command / entrypoint → command / args](#command--entrypoint--command--args)
- [healthcheck → probes](#healthcheck--probes)
- [What Doesn't Map Cleanly](#what-doesnt-map-cleanly)

## Quick Mapping Table

| Compose                  | bjw-s `values.yaml`                          | Notes                                          |
| :------------------------ | :--------------------------------------------- | :------------------------------------------------ |
| `services.<name>`         | `controllers.<name>` + `containers.<name>`     | One controller per service unless containers share a pod |
| `image: repo:tag`         | `containers.<name>.image.repository` / `.tag`  | Never keep `:latest` — pin an explicit tag        |
| `ports:`                  | `service.<id>.ports.<port-name>`               | Container port is the Service's `targetPort`, not a separate field |
| `volumes:`                | `persistence.<id>`                             | Type depends on the volume kind (see below)       |
| `environment:`            | `containers.<name>.env`                        | Map form, not list form                           |
| `env_file:`               | `envFrom` (`configMapRef`/`secretRef`)         | Compose loads a file; k8s loads an object          |
| `depends_on:`             | `containers.<name>.dependsOn` (same pod only)  | Doesn't order separate controllers — caveat below  |
| `restart: unless-stopped` | Controller `type` + k8s restart semantics      | No direct field — behavior follows the workload kind |
| `deploy.replicas:`        | `controllers.<name>.replicas`                  | Must be `null` if an HPA manages this controller  |
| `command:` / `entrypoint:`| `containers.<name>.args` / `.command`          | Naming is reversed — see below                    |
| `healthcheck:`            | `containers.<name>.probes`                     | Exec healthchecks require `custom: true`          |

## Worked Example

Compose:

```yaml
services:
  app:
    image: ghcr.io/example/app:1.4.2
    ports:
      - "8080:8080"
    environment:
      LOG_LEVEL: info
    env_file:
      - app.env
    volumes:
      - app-data:/data
    depends_on:
      - db

volumes:
  app-data:
```

Equivalent `values.yaml` (`depends_on: [db]` is dropped — `db` maps to
its own `controllers.db`, and `dependsOn` doesn't reach across
controllers; see [the caveat below](#depends_on--dependson--initcontainers)):

```yaml
controllers:
  app:
    containers:
      app:
        image:
          repository: ghcr.io/example/app
          tag: "1.4.2"
        env:
          LOG_LEVEL: info
        envFrom:
          - secretRef:
              identifier: app-env    # replaces env_file: app.env

service:
  app:
    controller: app
    ports:
      http:
        port: 8080

persistence:
  app-data:
    type: persistentVolumeClaim
    accessMode: ReadWriteOnce
    size: 5Gi
    globalMounts:
      - path: /data
```

## Service → Controller + Container

Each compose `services.<name>:` becomes at minimum a
`controllers.<name>.containers.<name>` pair. Only fold two compose
services into containers under the *same* controller if they must
share a pod's network namespace and lifecycle (app + sidecar proxy).
Otherwise keep one controller per compose service — closer semantics,
independent scaling and restarts.

```yaml
controllers:
  app:
    type: deployment    # deployment | statefulset | daemonset | cronjob | job
    containers:
      app: {}           # image, env, probes, etc.
```

## `image` → `containers.<name>.image`

```yaml
containers:
  app:
    image:
      repository: ghcr.io/example/app
      tag: "1.4.2"        # never "latest" — pin a real tag or digest
      pullPolicy: IfNotPresent
```

Split `repository` and `tag` — compose keeps them as one string. Prefer
`digest:` over `tag:` for supply-chain-sensitive images.

## `ports` → `service.<id>.ports`

Compose `"8080:9000"` (host:container) has no equivalent shape: a
Kubernetes Service exposes a `port` (what clients hit) mapped to a
`targetPort` (the container's real listening port) — traffic reaches
the pod through the Service, not a host bind.

```yaml
service:
  app:
    controller: app
    ports:
      http:
        port: 8080
        targetPort: 9000   # omit to default to `port`
```

`NodePort`/`LoadBalancer` replace host-port publishing when the service
must be reachable from outside the cluster; `ClusterIP` (the default)
suffices for in-cluster-only traffic.

## `volumes` → `persistence`

Match by what the volume actually is:

| Compose volume                            | `persistence.<id>.type`              |
| :------------------------------------------ | :-------------------------------------- |
| Named volume (`app-data:/data`)             | `persistentVolumeClaim` (default)       |
| Bind mount from host (`./cfg:/config`)      | `hostPath`                              |
| `tmpfs:` mount                              | `emptyDir` with `medium: Memory`        |
| Anonymous/scratch volume                    | `emptyDir` or `ephemeral` (5.x only)    |
| NFS share mounted on the host                | `nfs`                                   |

```yaml
persistence:
  data:
    type: persistentVolumeClaim
    accessMode: ReadWriteOnce
    size: 5Gi
    globalMounts:
      - path: /data
```

Use `globalMounts` when one volume mounts at the same path in every
container; use `advancedMounts` when containers need it at different
paths, or only some should see it at all — see
[`references/best-practices.md`](best-practices.md).

## `environment` / `env_file` → `env` / `envFrom`

```yaml
containers:
  app:
    env:
      LOG_LEVEL: info      # compose: environment: { LOG_LEVEL: info }
```

`environment:` is a map in both formats — copy as-is. `env_file:` has no
direct analog because there's no "file" at deploy time: create a
ConfigMap (non-secret values) or Secret (credentials) from that file's
contents ahead of time, then reference it:

```yaml
envFrom:
  - configMapRef:
      identifier: app-config
  - secretRef:
      identifier: app-secrets
```

## `depends_on` → `dependsOn` / `initContainers`

Compose's `depends_on` waits for a container to start (or, with
`condition: service_healthy`, to pass its healthcheck); both keep
running afterward. **This does not map 1:1 to Kubernetes.** bjw-s only
orders containers *within a single pod*, via `dependsOn` — it does
**not** order two `controllers.*` entries:

```yaml
containers:
  app: { image: { repository: myapp, tag: "1.0.0" } }
  sidecar:
    dependsOn: app        # starts after app is ready
    image: { repository: sidecar, tag: "1.0.0" }
```

For two compose services mapped to two **separate controllers** (the
common case, e.g. `app` depends on `db`), there is no declarative
"controller B waits for controller A" field. Options, in preference
order:

- Make the dependent app retry its connection on startup — the
  Kubernetes-native pattern; apps are expected to tolerate a dependency
  not being ready yet.
- Add an `initContainers` entry on the dependent controller that polls
  the dependency (e.g. a `wait-for-db` check) before the main container
  starts — this blocks pod startup, unlike cross-controller `dependsOn`.
- For genuinely ordered rollouts (rare), handle it operationally (Helm
  hooks, a separate apply step) instead of expecting the chart to
  enforce it.

## `restart` / `deploy.replicas` → controller type / replicas

`restart: unless-stopped` (or `always`) has no field to port —
Kubernetes restarts failed containers per the workload kind's own
semantics (a Deployment's pods restart per `pod.restartPolicy`, default
`Always`), regardless of any compose-style flag. Pick the controller
`type` matching the workload's real shape (`deployment` for stateless,
`statefulset` for ordered/stable-identity, `cronjob`/`job` for
`restart: "no"` one-shot tasks) instead of translating the value.

```yaml
controllers:
  app:
    replicas: 3            # compose: deploy.replicas: 3
```

**HPA caveat**: if `horizontalPodAutoscaler` targets this controller
(5.x only), set `replicas: null` instead of a fixed number — the HPA
owns replica count and a static value fights it on every reconcile.

## `command` / `entrypoint` → `command` / `args`

Field names are swapped from what intuition suggests:

| Compose       | bjw-s                          | Meaning                       |
| :------------- | :------------------------------- | :------------------------------- |
| `entrypoint:`  | `containers.<name>.command`      | Overrides the image's `ENTRYPOINT` |
| `command:`     | `containers.<name>.args`         | Overrides the image's `CMD`      |

```yaml
containers:
  app:
    command: ["/bin/sh"]   # compose: entrypoint: ["/bin/sh"]
    args: ["-c", "run.sh"] # compose: command: ["-c", "run.sh"]
```

## `healthcheck` → `probes`

Compose has one `healthcheck:` block; bjw-s has three independent
probes (`liveness`, `readiness`, `startup`). A compose `healthcheck:`
usually becomes `liveness` at minimum, plus `readiness` if the service
should drop from load balancing while unhealthy.

Compose's `test: ["CMD", ...]` is exec-style — not one of the built-in
`type:` values, it requires `custom: true` with a raw pod-probe spec:

```yaml
probes:
  liveness:
    enabled: true
    custom: true
    spec:
      exec:
        command: ["curl", "-f", "http://localhost:8080/healthz"]
```

For a plain HTTP GET check, prefer the native `type: HTTP` probe over
`custom` — cheaper (no extra process spawn) and easier to read:

```yaml
probes:
  liveness:
    enabled: true
    type: HTTP
    path: /healthz
    port: http
```

## What Doesn't Map Cleanly

- **`networks:`** — Compose networks are per-project bridge networks
  with DNS aliasing by service name. Kubernetes has one flat pod network
  per cluster; no `values.yaml` field recreates that isolation.
  `networkpolicies` (5.x only) restricts traffic between controllers,
  but isn't an equivalent to multiple named compose networks.
- **`build:`** — Helm charts deploy pre-built images; they don't build
  them. Build in CI and reference the resulting `repository`/`tag`.
- **`profiles:`** — Compose profiles conditionally include/exclude
  services per invocation. The closest bjw-s equivalent is each
  section's own `enabled:` flag (`controllers.<id>.enabled`,
  `service.<id>.enabled`, …) toggled per environment — there's no
  single switch gating a whole group at once, toggle each one.
