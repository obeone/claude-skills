<p align="center">
  <img src="https://img.shields.io/badge/Helm-v3-0F1689?style=for-the-badge&logo=helm&logoColor=white" alt="Helm v3"/>
  <img src="https://img.shields.io/badge/bjw--s-v4+-326CE5?style=for-the-badge&logo=kubernetes&logoColor=white" alt="bjw-s v4+"/>
  <img src="https://img.shields.io/badge/Kubernetes-Ready-326CE5?style=for-the-badge&logo=kubernetes&logoColor=white" alt="Kubernetes"/>
</p>

<h1 align="center">⎈ Helm Chart Generator</h1>

<p align="center">
  <strong>Generate production-ready Helm charts using bjw-s common library</strong><br/>
  <em>app-template v4+ • Sidecars • Init containers • Ingress patterns</em>
</p>

<p align="center">
  <a href="#-installation">Installation</a> •
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-features">Features</a> •
  <a href="#-chart-structure">Structure</a> •
  <a href="#-patterns">Patterns</a>
</p>

---

## 📦 Installation

### Claude Code (CLI)

```bash
# Install to personal skills directory
curl -L https://github.com/obeone/claude-skill/releases/latest/download/helm-chart-generator.skill \
  | tar -xz -C ~/.claude/skills/

# Or install to current project only
curl -L https://github.com/obeone/claude-skill/releases/latest/download/helm-chart-generator.skill \
  | tar -xz -C .claude/skills/
```

### Claude.ai (Web)

1. Download [`helm-chart-generator.skill`](https://github.com/obeone/claude-skill/releases/latest/download/helm-chart-generator.skill)
2. Go to **Settings** → **Skills** → **Upload skill**

### From Source

```bash
git clone https://github.com/obeone/claude-skill.git
cp -r claude-skill/skills/helm-chart-generator/helm-chart-generator ~/.claude/skills/
```

> Skills are packaged using [Skill Pack](https://github.com/marketplace/actions/skill-pack) on every release.

---

## 🚀 Quick Start

### 1. Copy Templates

```bash
cp -r assets/templates/ ./my-app/
```

### 2. Customize values.yaml

```yaml
controllers:
  main:
    containers:
      main:
        image:
          repository: myapp
          tag: "1.0.0"

service:
  main:
    controller: main
    ports:
      http:
        port: 8080
```

### 3. Validate

```bash
python scripts/validate_chart.py ./my-app/
helm lint ./my-app/
helm template ./my-app/ --debug
```

## ✨ Features

### 📦 Complete Chart Generation

| Component | Description |
|-----------|-------------|
| **Chart.yaml** | Metadata with bjw-s dependency pre-configured |
| **values.yaml** | Structured configuration template |
| **common.yaml** | Single-line library include |
| **NOTES.txt** | Post-install instructions template |

### 🔧 bjw-s Common Library v4+

The [bjw-s common library](https://github.com/bjw-s/helm-charts) provides:

- Standardized controller patterns
- Service/Ingress abstraction
- Persistence management
- ConfigMap/Secret generation
- Init container support
- Sidecar patterns

### ✅ Chart Validator

```bash
python scripts/validate_chart.py ./my-chart/
```

**Validates:**
- Chart structure and required files
- Chart.yaml schema and dependencies
- values.yaml structure and patterns
- Template syntax and includes

## 📁 Chart Structure

Every generated chart follows this structure:

```
my-app/
├── Chart.yaml              # Metadata and dependencies
│   ├── apiVersion: v2
│   ├── name, description, version, appVersion
│   └── dependencies:
│       └── common → bjw-s-labs/helm-charts
│
├── values.yaml             # Configuration
│   ├── defaultPodOptions   # Pod-level settings
│   ├── controllers         # Deployment/StatefulSet
│   ├── service             # Service definitions
│   ├── ingress             # Ingress rules
│   ├── persistence         # PVC/Volume mounts
│   └── configMaps/secrets  # Generated resources
│
└── templates/
    ├── common.yaml         # {{ include "bjw-s.common.loader.all" . }}
    └── NOTES.txt           # Post-install message
```

## 🎨 Patterns

### Single Container Application

```yaml
controllers:
  main:
    containers:
      main:
        image:
          repository: nginx
          tag: alpine
        probes:
          liveness:
            enabled: true
          readiness:
            enabled: true

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
          repository: fluentd
          tag: latest
        env:
          LOG_PATH: /var/log/app
```

### VPN Sidecar (Gluetun)

```yaml
controllers:
  main:
    containers:
      main:
        image:
          repository: qbittorrent
          tag: latest

      gluetun:
        image:
          repository: qmcgaw/gluetun
          tag: latest
        securityContext:
          capabilities:
            add: ["NET_ADMIN"]
        env:
          VPN_SERVICE_PROVIDER: mullvad
          VPN_TYPE: wireguard
```

### Init Container

```yaml
controllers:
  main:
    initContainers:
      init-db:
        image:
          repository: busybox
          tag: latest
        command: ["sh", "-c", "until nc -z db 5432; do sleep 1; done"]

    containers:
      main:
        image:
          repository: myapp
          tag: latest
```

> 📁 More patterns in [references/patterns.md](./references/patterns.md)

## 📋 values.yaml Reference

### Controllers

```yaml
controllers:
  <name>:
    type: Deployment | StatefulSet | DaemonSet  # default: Deployment
    replicas: 1
    strategy: RollingUpdate | Recreate

    containers:
      <name>:
        image:
          repository: string
          tag: string
          pullPolicy: IfNotPresent | Always | Never

        env:
          KEY: value
          KEY_FROM_SECRET:
            valueFrom:
              secretKeyRef:
                name: secret-name
                key: key-name

        probes:
          liveness:
            enabled: true
            type: HTTP | TCP | exec
            path: /health
          readiness:
            enabled: true
          startup:
            enabled: false

        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            memory: 256Mi
```

### Service

```yaml
service:
  <name>:
    controller: <controller-name>  # Required: links to controller
    type: ClusterIP | LoadBalancer | NodePort
    ports:
      <port-name>:
        port: 80
        targetPort: 8080  # optional
        protocol: TCP | UDP
```

### Ingress

```yaml
ingress:
  <name>:
    className: nginx | traefik | ""
    annotations: {}
    hosts:
      - host: app.example.com
        paths:
          - path: /
            service:
              identifier: main  # Service identifier (not name!)
              port: http
    tls:
      - secretName: app-tls
        hosts:
          - app.example.com
```

### Persistence

```yaml
persistence:
  <name>:
    type: persistentVolumeClaim | emptyDir | configMap | secret | nfs | hostPath

    # For PVC
    accessMode: ReadWriteOnce | ReadOnlyMany | ReadWriteMany
    size: 1Gi
    storageClass: ""
    existingClaim: ""  # Use existing PVC

    # Mounting
    globalMounts:          # Simple: all containers
      - path: /data
        readOnly: false

    advancedMounts:        # Complex: per-controller/container
      main:                # controller name
        main:              # container name
          - path: /data
```

> 📁 Complete schema in [references/values-schema.md](./references/values-schema.md)

## ✅ Best Practices

### Always Do

- [ ] Use specific image tags, never `:latest`
- [ ] Set resource requests and limits
- [ ] Configure health probes (liveness, readiness)
- [ ] Use non-root security contexts
- [ ] Reference services by `identifier`, not `name`

### Naming Conventions

| Resource | Convention | Example |
|----------|------------|---------|
| Controllers | Descriptive, lowercase | `main`, `worker`, `api` |
| Containers | Match purpose | `app`, `sidecar`, `proxy` |
| Services | Match controller or port | `main`, `http`, `metrics` |
| Persistence | Match content | `config`, `data`, `cache` |

### Security Context

```yaml
defaultPodOptions:
  securityContext:
    runAsUser: 1000
    runAsGroup: 1000
    fsGroup: 1000
    runAsNonRoot: true
    seccompProfile:
      type: RuntimeDefault

controllers:
  main:
    containers:
      main:
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop: ["ALL"]
```

## 🔍 Validation

```bash
# Structure and content validation
python scripts/validate_chart.py ./my-chart/

# Helm native validation
helm lint ./my-chart/

# Template rendering (debug)
helm template ./my-chart/ --debug

# Dry-run installation
helm install --dry-run --debug my-release ./my-chart/

# Dependency update
helm dependency update ./my-chart/
```

## 📚 References

| Document | Description |
|----------|-------------|
| [patterns.md](./references/patterns.md) | Common deployment patterns and examples |
| [best-practices.md](./references/best-practices.md) | Kubernetes/Helm best practices |
| [values-schema.md](./references/values-schema.md) | Complete values.yaml reference |

## 📁 Skill Structure

```
helm-chart-generator/
├── SKILL.md                    # Main entry point
├── README.md                   # This file
├── scripts/
│   ├── validate_chart.py       # Chart structure validator
│   └── requirements.txt        # pyyaml
├── assets/
│   └── templates/
│       ├── Chart.yaml          # Pre-configured with bjw-s
│       ├── values.yaml         # Structured template
│       └── templates/
│           ├── common.yaml     # Library include
│           └── NOTES.txt       # Post-install template
└── references/
    ├── best-practices.md       # Kubernetes/Helm guidelines
    ├── patterns.md             # Deployment patterns
    └── values-schema.md        # values.yaml reference
```

## 🔄 Migration from v3.x

Key changes in bjw-s common library v4:

| v3.x | v4.x |
|------|------|
| Default objects auto-created | Must explicitly name all resources |
| Service `name` in ingress | Service `identifier` in ingress |
| Single `default` ServiceAccount | Multiple named ServiceAccounts |

---

<p align="center">
  <sub>Part of the <a href="../../../">Claude Agent Skills Stack</a></sub>
</p>
