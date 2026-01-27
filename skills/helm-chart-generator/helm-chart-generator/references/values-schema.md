# Values Schema Quick Reference

Quick reference for common values.yaml configuration options in bjw-s common library v4+.

## Controllers

```yaml
controllers:
  <identifier>:
    enabled: true                    # Enable/disable controller
    type: deployment                 # deployment, statefulset, daemonset, cronjob, job
    annotations: {}                  # Annotations on controller resource
    labels: {}                       # Labels on controller resource
    replicas: 1                      # Number of replicas (null for HPA)
    strategy: RollingUpdate          # Update strategy
    revisionHistoryLimit: 3          # History to keep
    
    # Pod-level options
    pod:
      securityContext: {}
      annotations: {}
      labels: {}
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
        
        probes:
          liveness:
            enabled: true
            type: TCP              # TCP, HTTP, EXEC
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

# Reference in controller
controllers:
  main:
    serviceAccount:
      identifier: <serviceaccount-id>
      # OR
      name: <serviceaccount-name>
```

## Default Pod Options

```yaml
defaultPodOptions:
  # Applied to all controllers
  automountServiceAccountToken: true
  enableServiceLinks: false
  
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

```yaml
serviceMonitor:
  <identifier>:
    enabled: true
    annotations: {}
    labels: {}
    serviceName: '{{ include "bjw-s.common.lib.chart.names.fullname" $ }}'
    
    endpoints:
      - port: metrics
        path: /metrics
        interval: 30s
        scrapeTimeout: 10s
```

## Routes (Gateway API)

```yaml
route:
  <identifier>:
    enabled: true
    kind: HTTPRoute                  # HTTPRoute, TCPRoute, TLSRoute, UDPRoute, GRPCRoute
    
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

```yaml
env:
  KEY1: value1
  KEY2: value2
  
  # OR list format
  - name: KEY1
    value: value1
```

### From ConfigMap

```yaml
env:
  CONFIG_KEY:
    valueFrom:
      configMapKeyRef:
        identifier: <configmap-id>   # From configMaps section
        key: key-name
        # OR
        name: external-configmap     # External ConfigMap
        key: key-name
```

### From Secret

```yaml
env:
  SECRET_KEY:
    valueFrom:
      secretKeyRef:
        identifier: <secret-id>      # From secrets section
        key: key-name
        # OR
        name: external-secret        # External Secret
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

### HTTP Probe

```yaml
probes:
  liveness:
    enabled: true
    type: HTTP
    spec:
      httpGet:
        path: /healthz
        port: http
        scheme: HTTP
        httpHeaders: []
      initialDelaySeconds: 0
      periodSeconds: 10
      timeoutSeconds: 1
      successThreshold: 1
      failureThreshold: 3
```

### TCP Probe

```yaml
probes:
  liveness:
    type: TCP
    spec:
      tcpSocket:
        port: 8080
```

### Exec Probe

```yaml
probes:
  liveness:
    type: EXEC
    spec:
      exec:
        command:
          - cat
          - /tmp/healthy
```

### Custom Probe

```yaml
probes:
  liveness:
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

## Network Policies

```yaml
networkpolicies:
  <identifier>:
    enabled: true
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
