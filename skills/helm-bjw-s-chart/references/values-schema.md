# Values Schema Quick Reference

Quick reference for common values.yaml configuration options in bjw-s common library v5.x (with v4.x legacy notes).

> Default target is **common 5.x**. Fields marked **`(5.x only)`** are
> unavailable on the legacy 4.x track. Everything else is shared by
> both branches. See `migration-4-to-5.md` for breaking changes.

## Controllers

```yaml
controllers:
  <identifier>:
    enabled: true                    # Enable/disable controller
    type: deployment                 # deployment, statefulset, daemonset, cronjob, job
    annotations: {}                  # Annotations on controller resource
    labels: {}                       # Labels on controller resource
    replicas: 1                      # Number of replicas (null for HPA)
    # Update strategy. A string, never a map. Valid values depend on
    # `type`: deployment → Recreate (default) | RollingUpdate;
    # statefulset → RollingUpdate (default) | OnDelete;
    # daemonset → RollingUpdate | OnDelete (5.1+; ignored before).
    # Rejected by the values schema from 5.1.0 on, by a template
    # failure before that.
    strategy: RollingUpdate
    # Only read when strategy is RollingUpdate.
    rollingUpdate:
      maxUnavailable: 0              # deployment, daemonset, statefulset (5.1+)
      maxSurge: 1                    # deployment, daemonset
      partition: 0                   # statefulset only
      # `unavailable` / `surge` are the pre-5.1 spellings: still
      # accepted, deprecated, removed in 6.0. maxUnavailable / maxSurge
      # win when both are set.
    revisionHistoryLimit: 3          # History to keep

    # Pod-level options
    pod:
      securityContext: {}
      annotations: {}
      labels: {}
      # resizePolicy — pod-level in-place vertical scaling
      # (5.x only, K8s ≥ 1.36)
      resizePolicy: PreferNoRestart        # PreferNoRestart | RestartContainer
      # ... other pod options

    # Container definitions
    containers:
      <identifier>:
        image:
          repository: ""
          tag: ""
          digest: ""
          pullPolicy: IfNotPresent

        command: []
        args: []
        workingDir: ""

        env: {}
        envFrom: []

        resources:
          requests:
            cpu: ""
            memory: ""
          limits:
            cpu: ""
            memory: ""

        securityContext: {}

        # resizePolicy — in-place vertical scaling (5.x only, K8s ≥ 1.35)
        resizePolicy:
          - resourceName: cpu
            restartPolicy: NotRequired      # NotRequired or RestartContainer
          - resourceName: memory
            restartPolicy: RestartContainer

        probes:
          liveness:
            enabled: true
            type: TCP              # TCP, HTTP, HTTPS, GRPC, AUTO (default TCP)
            custom: false
            spec:
              initialDelaySeconds: 0
              periodSeconds: 10
              timeoutSeconds: 1
              failureThreshold: 3
          readiness: {}            # Same structure
          startup: {}              # Same structure

    # Init containers
    initContainers: {}               # Same structure as containers

    # For StatefulSets
    statefulset:
      podManagementPolicy: OrderedReady  # OrderedReady or Parallel
      volumeClaimTemplates: []

    # For CronJobs
    cronjob:
      schedule: "*/20 * * * *"
      concurrencyPolicy: Forbid    # Allow, Forbid, Replace
      successfulJobsHistory: 1
      failedJobsHistory: 1
      startingDeadlineSeconds: 30
      ttlSecondsAfterFinished: null

    # For Jobs
    job:
      backoffLimit: 6
      ttlSecondsAfterFinished: null
      parallelism: null
```

## Services

```yaml
service:
  <identifier>:
    enabled: true
    controller: <controller-identifier>  # Which controller to target
    type: ClusterIP                      # ClusterIP, LoadBalancer, NodePort
    annotations: {}
    labels: {}

    ports:
      <port-name>:
        enabled: true
        primary: true                    # Mark as primary port
        port: 80
        targetPort: null                 # Defaults to port
        protocol: HTTP                   # HTTP, HTTPS, TCP, UDP
        nodePort: null                   # For NodePort services
        appProtocol: ""                  # Optional protocol hint
```

## Ingress

```yaml
ingress:
  <identifier>:
    enabled: true
    className: nginx
    annotations: {}
    labels: {}

    hosts:
      - host: example.com
        paths:
          - path: /
            pathType: Prefix           # Prefix, Exact, ImplementationSpecific
            service:
              identifier: <service-id> # Reference by identifier
              # OR
              name: <service-name>     # Reference by name
              port: http               # Port name or number

    tls:
      - secretName: example-tls
        hosts:
          - example.com
```

## Persistence

### PersistentVolumeClaim

```yaml
persistence:
  <identifier>:
    enabled: true
    type: persistentVolumeClaim

    # For new PVC
    accessMode: ReadWriteOnce        # ReadWriteOnce, ReadOnlyMany, ReadWriteMany
    size: 1Gi
    storageClass: ""                 # Empty for default
    retain: false                    # Keep PVC on uninstall

    # For existing PVC
    existingClaim: my-pvc-name

    # Mount configuration
    globalMounts:
      - path: /data
        readOnly: false
        subPath: ""

    # OR for complex scenarios
    advancedMounts:
      <controller-id>:
        <container-id>:
          - path: /data
            readOnly: false
            subPath: ""
```

### Ephemeral (generic ephemeral volume) — 5.x only

```yaml
persistence:
  <identifier>:
    type: ephemeral                  # (5.x only)
    accessMode: ReadWriteOnce
    size: 1Gi
    storageClass: ""                 # Empty for default
    globalMounts:
      - path: /scratch
```

Generic ephemeral volumes look like a PVC but are bound to the pod
lifecycle — they're created when the pod is scheduled and deleted when
it terminates, with no `PersistentVolumeClaim` left behind.

### EmptyDir

```yaml
persistence:
  <identifier>:
    type: emptyDir
    medium: ""                       # "" for disk, "Memory" for tmpfs
    sizeLimit: 1Gi                   # Optional size limit
```

### ConfigMap

```yaml
persistence:
  <identifier>:
    type: configMap
    identifier: <configmap-id>       # From configMaps section
    # OR
    name: my-configmap               # External ConfigMap
    defaultMode: 0644
    items: []                        # Specific keys to mount
```

### Secret

```yaml
persistence:
  <identifier>:
    type: secret
    identifier: <secret-id>          # From secrets section
    # OR
    name: my-secret                  # External Secret
    defaultMode: 0644
    items: []
```

### NFS

```yaml
persistence:
  <identifier>:
    type: nfs
    server: nas.example.lan
    path: /volume/data
```

### HostPath

```yaml
persistence:
  <identifier>:
    type: hostPath
    hostPath: /mnt/data
    hostPathType: Directory          # Directory, DirectoryOrCreate, File, etc.
```

## ConfigMaps

```yaml
configMaps:
  <identifier>:
    enabled: true
    annotations: {}
    labels: {}
    data:
      key1: value1
      key2: value2
      config.yaml: |
        key: value
```

## Secrets

```yaml
secrets:
  <identifier>:
    enabled: true
    annotations: {}
    labels: {}
    stringData:
      password: secret123
      api-key: key123
```

## ServiceAccounts

```yaml
serviceAccount:
  <identifier>:
    enabled: true
    annotations: {}
    labels: {}
    staticToken: false               # Create long-lived token
    # (5.1+) Set on the ServiceAccount object itself. The pod spec always
    # carries its own automountServiceAccountToken (default false) and
    # wins, so this does not govern this chart's pods — set
    # `controllers.<id>.pod.automountServiceAccountToken` for those.
    automountServiceAccountToken: false

# Reference in controller
controllers:
  main:
    serviceAccount:
      identifier: <serviceaccount-id>
      # OR
      name: <serviceaccount-name>
```

> **(5.x only)** — A default unprivileged ServiceAccount is created
> automatically. Disable when you bring your own:
>
> ```yaml
> global:
>   createDefaultServiceAccount: false
> ```

## Default Pod Options

```yaml
defaultPodOptions:
  # Applied to all controllers.
  # (common 4.x default: true | common 5.x default: false)
  # Set to true if your workload needs the SA token.
  automountServiceAccountToken: false
  enableServiceLinks: false

  imagePullSecrets:
    - name: registry-credentials      # Secret of type kubernetes.io/dockerconfigjson

  securityContext:
    runAsUser: 10001
    runAsGroup: 10001
    runAsNonRoot: true
    fsGroup: 10001
    fsGroupChangePolicy: OnRootMismatch

  annotations: {}
  labels: {}

  nodeSelector: {}
  tolerations: []
  affinity: {}

  topologySpreadConstraints: []

  dnsConfig: {}
  dnsPolicy: ClusterFirst

  hostNetwork: false
  hostIPC: false
  hostPID: false

  priorityClassName: ""
  runtimeClassName: ""
  schedulerName: ""

  terminationGracePeriodSeconds: 30
```

## ServiceMonitor (Prometheus)

ServiceMonitor targets a `Service` via `service:` (not `controller:`) and
uses `endpoints:`.

```yaml
serviceMonitor:
  <identifier>:
    enabled: true
    annotations: {}
    labels: {}
    service:
      identifier: <service-id>       # References service.<service-id>
      # OR
      name: <external-service-name>  # A Service not managed by this chart
    jobLabel: app.kubernetes.io/name # (5.x only default — was unset)

    endpoints:
      - port: metrics
        path: /metrics
        interval: 30s
        scrapeTimeout: 10s
```

## PodMonitor (Prometheus) — 5.x only

Scrape pods directly without needing a Service. PodMonitor targets a
controller via `controller: {identifier: ...}` (an object, not a bare
string) and uses `podMetricsEndpoints:` — not `endpoints:`. Don't
conflate this with ServiceMonitor above (`service:` + `endpoints:`).

```yaml
podMonitor:
  <identifier>:
    enabled: true
    controller:
      identifier: <controller-id>    # Object form; a bare string fails schema validation
    annotations: {}
    labels: {}
    jobLabel: app.kubernetes.io/name

    podMetricsEndpoints:              # Not `endpoints:` — that key is rejected by the schema
      - port: metrics
        path: /metrics
        interval: 30s
        scrapeTimeout: 10s
```

## HorizontalPodAutoscaler — 5.x only

There is no top-level `horizontalPodAutoscaler:` key. It nests under the
target controller, and has no `controller:` field — the parent
controller is implicitly the target.

```yaml
controllers:
  <controller-id>:
    replicas: null                   # HPA owns the replica count
    horizontalPodAutoscaler:
      enabled: true
      minReplicas: 1
      maxReplicas: 10
      metrics:
        - type: Resource
          resource:
            name: cpu
            target:
              type: Utilization
              averageUtilization: 70
        - type: Resource
          resource:
            name: memory
            target:
              type: Utilization
              averageUtilization: 80
      behavior: {}                   # Optional scale-up/down behavior
```

> Set `replicas: null` on the targeted controller so the HPA controls
> the replica count without Helm reverting it.

## Routes (Gateway API)

```yaml
route:
  <identifier>:
    enabled: true
    kind: HTTPRoute                  # HTTPRoute, TCPRoute, TLSRoute, UDPRoute, GRPCRoute

    # (5.1+) Deploy the Route somewhere other than the release namespace.
    namespaceOverride: ""
    # (5.1+) Only consulted when namespaceOverride differs from the
    # release namespace: a ReferenceGrant covering the backend Services
    # is generated unless disabled here.
    referenceGrant:
      enabled: true

    parentRefs:
      - group: gateway.networking.k8s.io
        kind: Gateway
        name: gateway-name
        namespace: gateway-namespace
        sectionName: ""

    hostnames:
      - example.com

    rules:
      - matches:
          - path:
              type: PathPrefix
              value: /
        backendRefs:
          - kind: Service
            name: <service-name>
            port: 80
```

## Environment Variables

### Simple Values

Map form (recommended):

```yaml
env:
  KEY1: value1
  KEY2: value2
```

A list form is also accepted:

```yaml
env:
  - name: KEY1
    value: value1
  - name: KEY2
    value: value2
```

### From ConfigMap

```yaml
env:
  CONFIG_KEY:
    valueFrom:
      configMapKeyRef:
        name: my-configmap           # Rendered ConfigMap name — `identifier` is NOT valid inside valueFrom
        key: key-name
```

### From Secret

```yaml
env:
  SECRET_KEY:
    valueFrom:
      secretKeyRef:
        name: my-secret              # Rendered Secret name — `identifier` is NOT valid inside valueFrom
        key: key-name
```

### Load All Keys

```yaml
envFrom:
  - configMapRef:
      identifier: <configmap-id>
  - secretRef:
      identifier: <secret-id>
```

## Probes

### HTTP Probe (standard)

Standard (non-custom) probe: `type`/`path`/`port` sit at probe level; `spec`
holds only timing tuning.

```yaml
probes:
  liveness:
    enabled: true
    type: HTTP
    path: /healthz
    port: http
    spec:
      initialDelaySeconds: 0
      periodSeconds: 10
      timeoutSeconds: 1
      successThreshold: 1
      failureThreshold: 3
```

### TCP Probe (standard)

```yaml
probes:
  liveness:
    enabled: true
    type: TCP
    port: 8080
    spec:
      initialDelaySeconds: 0
      periodSeconds: 10
```

### Exec Probe (custom)

There is no `EXEC` type. Exec/command probes require `custom: true` with a
raw pod-probe `spec` containing `exec.command`.

```yaml
probes:
  liveness:
    enabled: true
    custom: true
    spec:
      exec:
        command:
          - cat
          - /tmp/healthy
```

### Custom Probe (raw spec)

Set `custom: true` and provide a raw pod-probe `spec` (`httpGet`,
`tcpSocket`, or `exec`) for anything the standard fields can't express.

```yaml
probes:
  liveness:
    enabled: true
    custom: true
    spec:
      httpGet:
        path: /custom
        port: 9000
```

## Resource Naming

```yaml
# Override default naming
global:
  nameOverride: short-name           # Replaces chart name
  fullnameOverride: full-name        # Replaces entire name
  alwaysAppendIdentifierToResourceName: false

# Per-resource naming
service:
  main:
    forceRename: custom-service-name
    prefix: team
    suffix: svc
```

## Labels and Annotations

### Global

```yaml
global:
  labels:
    team: platform
    environment: production

  annotations:
    example.com/managed-by: automation

  propagateGlobalMetadataToPods: false
```

### Per-Resource

```yaml
service:
  main:
    labels:
      service-specific: label
    annotations:
      service-specific: annotation
```

## rawResources

Ship arbitrary Kubernetes manifests alongside the chart-managed
resources. **5.x requires the `manifest:` wrapper** — the legacy 4.x
top-level shape is not accepted.

```yaml
rawResources:
  <identifier>:
    enabled: true
    manifest:
      apiVersion: <group>/<version>
      kind: <Kind>
      metadata:
        labels: {}                   # Merged with chart-managed labels
        annotations: {}              # Merged with chart-managed annotations
        # metadata.name is ignored — library derives the name
      # Everything else from the K8s schema goes here:
      # - spec: ...                  # For kinds that have a spec
      # - data: ...                  # For ConfigMaps
      # - rules: ...                 # For webhook configs, RBAC, etc.
```

## Network Policies

```yaml
networkpolicies:
  <identifier>:
    enabled: true
    # (5.x only) If you omit both `controller` and `podSelector`
    # and exactly one controller exists, it is auto-targeted.
    controller: <controller-id>      # Which controller to target

    policyTypes:
      - Ingress
      - Egress

    rules:
      ingress:
        - from:
            - podSelector:
                matchLabels:
                  app: allowed-app
          ports:
            - protocol: TCP
              port: 8080

      egress:
        - to:
            - namespaceSelector:
                matchLabels:
                  name: allowed-namespace
          ports:
            - protocol: TCP
              port: 443
```
