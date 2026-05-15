# Common Deployment Patterns

Proven patterns for common Kubernetes deployment scenarios using bjw-s common library.

> All patterns work on **common 4.x and 5.x** unless tagged
> **`(common ≥ 5.0)`**. See `SKILL.md` for the version matrix.

## Single Container App

Basic web application with persistence:

```yaml
controllers:
  app:
    containers:
      app:
        image:
          repository: nginx
          tag: "1.25-alpine"
        probes:
          liveness:
            enabled: true
          readiness:
            enabled: true

service:
  app:
    controller: app
    ports:
      http:
        port: 80

ingress:
  app:
    className: nginx
    hosts:
      - host: myapp.example.com
        paths:
          - path: /
            service:
              identifier: app
              port: http

persistence:
  data:
    type: persistentVolumeClaim
    accessMode: ReadWriteOnce
    size: 10Gi
    globalMounts:
      - path: /data
```

## App with Sidecar (Code-Server)

Application with development sidecar for editing configs:

```yaml
defaultPodOptions:
  securityContext:
    runAsUser: 568
    runAsGroup: 568
    fsGroup: 568

controllers:
  main:
    containers:
      app:
        image:
          repository: homeassistant/home-assistant
          tag: "2024.1"
      
      code:
        dependsOn: app
        image:
          repository: ghcr.io/coder/code-server
          tag: "4.19.0"
        args:
          - --auth=none
          - --user-data-dir=/config/.vscode
          - --port=8081
          - /config

service:
  app:
    controller: main
    ports:
      http:
        port: 8123
  
  code:
    controller: main
    ports:
      http:
        port: 8081

persistence:
  config:
    existingClaim: app-config
    globalMounts:
      - path: /config
```

## App with VPN Sidecar (Gluetun)

Route traffic through VPN (qBittorrent + Gluetun):

```yaml
defaultPodOptions:
  automountServiceAccountToken: false

controllers:
  main:
    pod:
      securityContext:
        fsGroup: 568

    containers:
      app:
        image:
          repository: ghcr.io/onedr0p/qbittorrent
          tag: "4.6.0"
        securityContext:
          runAsUser: 568
          runAsGroup: 568

      gluetun:
        dependsOn: app
        image:
          repository: ghcr.io/qdm12/gluetun
          tag: latest
        env:
          VPN_TYPE: wireguard
          VPN_INTERFACE: wg0
        securityContext:
          capabilities:
            add:
              - NET_ADMIN

      port-forward:
        dependsOn: gluetun
        image:
          repository: snoringdragon/gluetun-qbittorrent-port-manager
          tag: "1.0"
        env:
          QBITTORRENT_SERVER: localhost
          QBITTORRENT_PORT: "8080"
          PORT_FORWARDED: /tmp/gluetun/forwarded_port

service:
  app:
    controller: main
    ports:
      http:
        port: 8080

persistence:
  config:
    existingClaim: qbittorrent-config
    advancedMounts:
      main:
        app:
          - path: /config

  gluetun-data:
    type: emptyDir
    advancedMounts:
      main:
        gluetun:
          - path: /tmp/gluetun
        port-forward:
          - path: /tmp/gluetun
            readOnly: true
```

## Multi-Controller Setup

Separate frontend and backend controllers:

```yaml
controllers:
  frontend:
    containers:
      app:
        image:
          repository: myapp/frontend
          tag: "1.0.0"
  
  backend:
    containers:
      app:
        image:
          repository: myapp/backend
          tag: "1.0.0"

service:
  frontend:
    controller: frontend
    ports:
      http:
        port: 3000
  
  backend:
    controller: backend
    ports:
      http:
        port: 8000

ingress:
  main:
    className: nginx
    hosts:
      - host: myapp.example.com
        paths:
          - path: /
            service:
              identifier: frontend
              port: http
          - path: /api
            service:
              identifier: backend
              port: http
```

## StatefulSet with Init Container and Headless Service

Database with initialization and stable network identity (required for clustering):

```yaml
controllers:
  db:
    type: statefulset

    statefulset:
      podManagementPolicy: OrderedReady  # Ordered startup for clustered DBs

    initContainers:
      init-permissions:
        image:
          repository: busybox
          tag: "1.36"
        command:
          - sh
          - -c
          - chown -R 999:999 /data

    containers:
      postgres:
        image:
          repository: postgres
          tag: "16-alpine"
        env:
          POSTGRES_DB: mydb
          POSTGRES_USER: myuser
          POSTGRES_PASSWORD:
            valueFrom:
              secretKeyRef:
                name: postgres-secret
                key: password

        probes:
          liveness:
            enabled: true
            type: EXEC
            spec:
              command:
                - pg_isready
                - -U
                - myuser
              initialDelaySeconds: 30
              periodSeconds: 10

    statefulset:
      volumeClaimTemplates:
        - name: data
          accessMode: ReadWriteOnce
          size: 20Gi
          globalMounts:
            - path: /var/lib/postgresql/data

# Regular service for client connections
service:
  db:
    controller: db
    ports:
      postgres:
        port: 5432

  # Headless service for stable DNS per pod (pod-0.db-headless, pod-1.db-headless, ...)
  # Required for clustered databases and peer discovery
  db-headless:
    controller: db
    type: ClusterIP
    clusterIP: None  # Makes it headless
    ports:
      postgres:
        port: 5432
```

## CronJob Pattern

Periodic backup job:

```yaml
controllers:
  backup:
    type: cronjob
    
    cronjob:
      schedule: "0 2 * * *"  # 2 AM daily
      successfulJobsHistory: 3
      failedJobsHistory: 1
      concurrencyPolicy: Forbid

    containers:
      backup:
        image:
          repository: backup-tool
          tag: latest
        command:
          - /bin/backup.sh
        env:
          BACKUP_TARGET: /backups
          RETENTION_DAYS: "7"

persistence:
  backups:
    type: nfs
    server: nas.example.lan
    path: /volume/backups
    globalMounts:
      - path: /backups
```

## ConfigMap and Secrets Pattern

App with external configuration:

```yaml
configMaps:
  app-config:
    data:
      APP_MODE: production
      LOG_LEVEL: info
      API_URL: https://api.example.com

secrets:
  app-secrets:
    stringData:
      API_KEY: "your-api-key-here"
      DB_PASSWORD: "your-db-password"

controllers:
  app:
    containers:
      app:
        image:
          repository: myapp
          tag: "1.0.0"
        env:
          # Direct env vars
          APP_NAME: MyApp
          
          # From ConfigMap (individual)
          APP_MODE:
            valueFrom:
              configMapKeyRef:
                name: app-config
                key: APP_MODE
          
          # From Secret (individual)
          API_KEY:
            valueFrom:
              secretKeyRef:
                identifier: app-secrets
                key: API_KEY
        
        envFrom:
          # Load all ConfigMap keys
          - configMapRef:
              identifier: app-config
          # Load all Secret keys
          - secretRef:
              identifier: app-secrets
```

## Multiple Volumes Pattern

App with different storage types:

```yaml
persistence:
  # Config on PVC
  config:
    type: persistentVolumeClaim
    accessMode: ReadWriteOnce
    size: 1Gi
    globalMounts:
      - path: /config

  # Shared data on NFS
  media:
    type: nfs
    server: nas.example.lan
    path: /volume/media
    globalMounts:
      - path: /media
        readOnly: true

  # Temp storage
  cache:
    type: emptyDir
    medium: Memory
    sizeLimit: 1Gi
    globalMounts:
      - path: /cache

  # Config file from ConfigMap
  app-config:
    type: configMap
    identifier: app-config
    advancedMounts:
      main:
        app:
          - path: /app/config.yaml
            subPath: config.yaml
            readOnly: true
```

## WebSocket + HTTP Ingress

Application with both HTTP and WebSocket endpoints:

```yaml
service:
  app:
    controller: main
    ports:
      http:
        port: 80
      websocket:
        port: 3012

ingress:
  main:
    className: nginx
    annotations:
      nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
      nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
    hosts:
      - host: app.example.com
        paths:
          # Regular HTTP
          - path: /
            service:
              identifier: app
              port: http
          
          # WebSocket negotiate (still HTTP)
          - path: /ws/negotiate
            service:
              identifier: app
              port: http
          
          # WebSocket connection
          - path: /ws
            service:
              identifier: app
              port: websocket
```

## Resource Limits Pattern

Production-ready resource configuration:

```yaml
defaultPodOptions:
  securityContext:
    runAsNonRoot: true
    runAsUser: 10000
    fsGroup: 10000
    seccompProfile:
      type: RuntimeDefault

controllers:
  app:
    replicas: 2
    
    strategy:
      type: RollingUpdate
      rollingUpdate:
        maxSurge: 1
        maxUnavailable: 0

    containers:
      app:
        image:
          repository: myapp
          tag: "1.0.0"
        
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            memory: 512Mi
        
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop:
              - ALL

        probes:
          liveness:
            enabled: true
            type: HTTP
            spec:
              initialDelaySeconds: 30
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 3
          
          readiness:
            enabled: true
            type: HTTP
            spec:
              initialDelaySeconds: 5
              periodSeconds: 5
              timeoutSeconds: 3
              failureThreshold: 3
          
          startup:
            enabled: true
            type: HTTP
            spec:
              initialDelaySeconds: 0
              periodSeconds: 5
              timeoutSeconds: 3
              failureThreshold: 30
```

## Private Registry with imagePullSecrets

Pull images from a private container registry:

```yaml
# Step 1: Create the pull secret (outside the chart, or via secrets: below)
# kubectl create secret docker-registry registry-credentials \
#   --docker-server=registry.example.com \
#   --docker-username=myuser \
#   --docker-password=mytoken

# Step 2: Reference in defaultPodOptions (applies to all pods)
defaultPodOptions:
  imagePullSecrets:
    - name: registry-credentials

controllers:
  app:
    containers:
      app:
        image:
          repository: registry.example.com/myapp
          tag: "1.0.0"
          pullPolicy: IfNotPresent

# Alternative: Create the secret inline (stored in values.yaml — avoid for sensitive data)
secrets:
  registry-credentials:
    type: kubernetes.io/dockerconfigjson
    stringData:
      .dockerconfigjson: |
        {
          "auths": {
            "registry.example.com": {
              "auth": "<base64-encoded user:token>"
            }
          }
        }
```

> Use an external secret operator (e.g., External Secrets Operator, Sealed Secrets) to
> avoid committing credentials to version control.

## Advanced Mounts Pattern

Different mount points for different containers:

```yaml
persistence:
  shared-data:
    type: persistentVolumeClaim
    accessMode: ReadWriteOnce
    size: 10Gi
    advancedMounts:
      main:
        app:
          - path: /app/data
            subPath: app-data
        
        sidecar:
          - path: /sidecar/data
            subPath: sidecar-data
        
        backup:
          - path: /backup/source
            readOnly: true
  
  config:
    type: configMap
    identifier: app-config
    advancedMounts:
      main:
        app:
          - path: /app/config/main.yaml
            subPath: main.yaml
          - path: /app/config/feature.yaml
            subPath: feature.yaml
```

## HorizontalPodAutoscaler **(common ≥ 5.0)**

Autoscale a stateless workload on CPU + memory pressure. Leave
`replicas: null` on the controller so the HPA owns the replica count.

```yaml
controllers:
  web:
    replicas: null                   # Let the HPA decide
    containers:
      app:
        image:
          repository: myapp/web
          tag: "2.1.0"
        resources:
          requests:
            cpu: 100m
            memory: 256Mi
          limits:
            memory: 512Mi

horizontalPodAutoscaler:
  web:
    enabled: true
    controller: web
    minReplicas: 2
    maxReplicas: 20
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
    behavior:
      scaleDown:
        stabilizationWindowSeconds: 300
```

## PodMonitor (Prometheus, no Service required) **(common ≥ 5.0)**

When the workload exposes metrics but has no `Service` (e.g. CronJobs,
exporters that should be scraped per-pod):

```yaml
controllers:
  worker:
    containers:
      app:
        image:
          repository: myapp/worker
          tag: "1.4.0"
        # Container port name picked up by the PodMonitor
        # (declared inside the container spec, not the service)

podMonitor:
  worker:
    enabled: true
    controller: worker
    endpoints:
      - port: metrics
        path: /metrics
        interval: 30s
```

## Generic Ephemeral Volume **(common ≥ 5.0)**

A throwaway PVC scoped to the pod lifecycle — useful for scratch space
on dynamic provisioners without committing to a long-lived PVC:

```yaml
persistence:
  scratch:
    type: ephemeral
    accessMode: ReadWriteOnce
    size: 5Gi
    storageClass: fast-ssd
    globalMounts:
      - path: /scratch
```

## NetworkPolicy with single-controller auto-detection **(common ≥ 5.0)**

When the chart only defines one controller, the policy is auto-targeted —
no need to repeat `controller:` or `podSelector:`:

```yaml
controllers:
  main:
    containers:
      app:
        image:
          repository: myapp
          tag: "1.0.0"

networkpolicies:
  default-deny-egress:
    enabled: true
    # No controller / podSelector — auto-binds to `main`
    policyTypes:
      - Egress
    rules:
      egress:
        - to:
            - namespaceSelector:
                matchLabels:
                  kubernetes.io/metadata.name: kube-system
              podSelector:
                matchLabels:
                  k8s-app: kube-dns
          ports:
            - protocol: UDP
              port: 53
```
