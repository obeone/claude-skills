---
name: helm-chart-generator
description: "[DEPRECATED — DO NOT USE] This skill has been renamed to `helm-bjw-s-chart` in v3.0.0. If you loaded this skill, install and trigger `helm-bjw-s-chart` instead. Do not invoke this package — it only contains a deprecation notice."
metadata:
  version: "3.0.0"
  deprecated: true
  superseded_by: "helm-bjw-s-chart"
---

# ⚠️ DEPRECATED — This skill has been renamed

**`helm-chart-generator` was renamed to [`helm-bjw-s-chart`](../helm-bjw-s-chart/) in v3.0.0.**

The new name makes the scope explicit: this skill targets the
[bjw-s common library](https://github.com/bjw-s-labs/helm-charts) (app-template
v4+), not generic Helm charts.

This package is kept only as a deprecation shim so that stale install URLs
and cloned paths land on a clear redirect instead of silently breaking.

## If you are a human

You probably got here because you followed a stale URL or cloned the old
directory path. Replace your installation:

```bash
# Remove the old skill
rm -rf ~/.claude/skills/helm-chart-generator
rm -rf .claude/skills/helm-chart-generator

# Install the renamed skill
curl -L https://github.com/obeone/claude-skills/releases/latest/download/helm-bjw-s-chart.skill \
  -o /tmp/skill.zip && unzip -o /tmp/skill.zip -d ~/.claude/skills/
```

Update every remaining reference:

| Old | New |
|---|---|
| Skill name `helm-chart-generator` | `helm-bjw-s-chart` |
| Asset `helm-chart-generator.skill` | `helm-bjw-s-chart.skill` |
| Directory `skills/helm-chart-generator/` | `skills/helm-bjw-s-chart/` |

Search for stragglers:

```bash
grep -r "helm-chart-generator" .
```

## If you are an AI agent

**Stop. Do not invoke this skill.** It has no scripts, no references, no
usable content — only this redirect notice.

If the user asked you to generate a Helm chart with the bjw-s common library,
trigger the `helm-bjw-s-chart` skill instead. If that skill is not available
in the current environment, tell the user to install it from
`https://github.com/obeone/claude-skills/releases/latest/download/helm-bjw-s-chart.skill`
and stop.

## Removal schedule

This deprecation shim will be removed in a future major release. If you are
maintaining automation that depends on the old name, migrate now.
