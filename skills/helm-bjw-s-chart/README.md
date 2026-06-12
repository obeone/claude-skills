# helm-bjw-s-chart

A Claude Code skill that generates production-ready Helm charts on top
of the [`bjw-s-labs`](https://github.com/bjw-s-labs/helm-charts) common
library — `app-template v5` by default, with `v4` still supported as a
legacy track.

The skill bundles a chart validator, ready-to-fill templates, and
reference patterns covering single-container apps, sidecars, init
containers, StatefulSets, HPAs, NetworkPolicies, and the full 4 → 5
migration.

> **🆕 v5.0.0 — common 5.x is the default**. New charts target
> `common: 5.0.1` (released 2026-05-14). 4.x remains a legacy track for
> clusters that can't meet Kubernetes 1.31 / Helm 3.18.
>
> **🔄 Renamed in v3.0.0** — this skill was previously published as
> `helm-chart-generator`. Update any agent, automation, or doc still
> referencing the old name.

## Why

Bare Helm charts force you to re-implement the same dozen objects every
time: Deployment, Service, Ingress, PVCs, ConfigMaps, Secrets,
ServiceAccount, HPA, NetworkPolicy. The `bjw-s` common library replaces
all of that with a values-only DSL, but its surface is large and the
4 → 5 migration moves several defaults (`automountServiceAccountToken`,
auto-created ServiceAccounts, `rawResources` shape, `jobLabel`).

This skill folds the library into a single quick-start workflow with
templates, opinionated values-file ordering, and a validator that
catches the most common pitfalls (still pinning 4.x, legacy
`rawResources` `spec:` shape, external ServiceAccount without opting
out of the default).

## Requirements

- **Claude Code** (or any agent that can read `SKILL.md`).
- **`uv`** on `$PATH` ([install](https://astral.sh/uv/)) for the
  validator. The script declares its dependencies inline as a
  [PEP 723](https://peps.python.org/pep-0723/) header — no `pip install`
  step.
- **Helm** ≥ 3.18 and **Kubernetes** ≥ 1.31 to deploy 5.x charts. The
  4.x legacy track supports Helm ≥ 3.14 / Kubernetes ≥ 1.25.

## Install

### Recommended — `skills` CLI

The [`skills`](https://skills.sh/) CLI resolves the repo and drops the
bundle into the right agent directory. Run via `npx` — no global Node
install required.

```bash
# User-global (works in every project)
npx skills add obeone/claude-skills -g --skill helm-bjw-s-chart -y

# Project-scoped (./.claude/skills)
npx skills add obeone/claude-skills --skill helm-bjw-s-chart -y
```

Update later with `npx skills update helm-bjw-s-chart`, remove with
`npx skills remove helm-bjw-s-chart`. Full options: `npx skills -h`.

### From a release bundle (fallback)

```bash
mkdir -p ~/.claude/skills
curl -L https://github.com/obeone/claude-skills/releases/latest/download/helm-bjw-s-chart.skill \
  -o /tmp/helm.skill
rm -rf ~/.claude/skills/helm-bjw-s-chart
unzip -q /tmp/helm.skill -d ~/.claude/skills/
rm /tmp/helm.skill
```

For a project-scoped install, drop `~/.claude/skills/` for
`.claude/skills/`.

### From source

```bash
git clone https://github.com/obeone/claude-skills.git
cp -R claude-skills/skills/helm-bjw-s-chart ~/.claude/skills/
```

## Usage

Ask Claude to generate a chart and the skill auto-triggers. The
validator can also be invoked directly:

```bash
# Validate a chart against the bjw-s common library expectations
uv run skills/helm-bjw-s-chart/scripts/validate_chart.py ./my-chart/

# JSON output for CI pipelines
uv run skills/helm-bjw-s-chart/scripts/validate_chart.py --json ./my-chart/
```

The validator warns when the chart pins `common 4.x`, when
`rawResources` still uses the legacy `spec:` shape (removed in 5.x), or
when an external ServiceAccount is referenced without
`global.createDefaultServiceAccount: false`.

After generating a chart:

```bash
cd /path/to/chart
helm dependency update         # fetch common, write Chart.lock
helm lint .
helm template . --debug
helm install --dry-run --debug my-release .
```

## What it gives you

- **Library version matrix.** Default `common 5.0.1` for new charts
  (Kubernetes ≥ 1.31, Helm ≥ 3.18); pin `4.6.2` for legacy clusters.
- **Quick-start workflow.** Five steps from "understand the app" to
  `helm install --dry-run`.
- **Opinionated `values.yaml` ordering.** `defaultPodOptions` →
  `controllers` → `service` → `ingress` → `persistence` →
  `configMaps/secrets`.
- **Pattern library.** Single container, sidecars, init containers,
  multi-controller, StatefulSets, HPA, PodMonitor, ephemeral volumes,
  NetworkPolicies with single-controller auto-targeting (the last four
  are 5.x-only).
- **4 → 5 migration guide.** Five behavioral changes to know
  (`automountServiceAccountToken`, default SA, `rawResources` shape,
  `jobLabel`, version bumps) with a full upgrade procedure.
- **Static validator.** `validate_chart.py` flags missing dependencies,
  4.x → 5.x migration debt, and the most common structural mistakes.

## Layout

```
skills/helm-bjw-s-chart/
├── SKILL.md          # Agent-facing entry point: workflow, patterns, 5.x rules
├── README.md         # This file (user-facing intro)
├── scripts/
│   └── validate_chart.py       # Structure + bjw-s compatibility validator
├── assets/
│   └── templates/              # Chart.yaml, values.yaml, common.yaml starters
└── references/
    ├── migration-4-to-5.md     # Full 4 → 5 upgrade procedure
    ├── patterns.md             # Common deployment patterns
    ├── best-practices.md       # Kubernetes/Helm best practices
    └── values-schema.md        # Complete values.yaml reference
```

## Deeper documentation

- `SKILL.md` — agent-facing entry point with the full workflow,
  patterns, and 5.x-only features.
- `references/migration-4-to-5.md` — **start here if you have an
  existing 4.x chart.** Five behavioral changes + full upgrade
  procedure.
- `references/patterns.md` — common deployment patterns (single
  container, sidecars, init, multi-controller, StatefulSets, HPA,
  PodMonitor, ephemeral volumes, NetworkPolicies).
- `references/best-practices.md` — Kubernetes/Helm best practices for
  production charts.
- `references/values-schema.md` — complete `values.yaml` reference for
  every supported field.

## Status

`metadata.version: 5.0.0`.

## License

MIT — see the repository [LICENSE](../../LICENSE).
