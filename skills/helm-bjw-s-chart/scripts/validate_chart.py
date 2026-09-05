#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pyyaml>=6.0",
# ]
# ///
"""
Helm Chart Validator for bjw-s common library charts.

Usage:
    python validate_chart.py <path-to-chart>
    python validate_chart.py --json <path-to-chart>
"""

import argparse
import json
import re
import sys
import yaml
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class Issue:
    """Represents a detected issue in the chart."""

    location: str
    severity: str  # 'error', 'warning', 'info'
    message: str
    suggestion: str = ""

    def __str__(self) -> str:
        """
        Format the issue for human-readable output.

        Returns
        -------
        str
            Formatted string with icon, location, message, and optional suggestion.
        """
        icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}[self.severity]
        result = f"{icon} {self.location}: {self.message}"
        if self.suggestion:
            result += f"\n   → {self.suggestion}"
        return result


def _detect_common_majors(constraint: str) -> set:
    """
    Determine which common-library major versions a version constraint admits.

    This is a deliberately small heuristic, not a full SemVer range solver. It
    recognises 4.x legacy pins written as bare versions (``4.6.2``), tilde/caret
    ranges (``~4.6.0``, ``^4``), wildcard forms (``4.x``) and explicit bounded
    ranges (``>=4.0.0 <5.0.0``, ``>=4 <6``). Each version token is paired with
    the comparator that precedes it so an exclusive upper bound (``<5.0.0``,
    which admits up to 4.x) is not mistaken for admitting 5.x.

    Parameters
    ----------
    constraint : str
        Raw ``version`` string from the common dependency in Chart.yaml.

    Returns
    -------
    set
        The set of integer major versions the constraint admits. Empty when no
        numeric major can be parsed.
    """
    # Capture (comparator, version-token) pairs. The optional leading ``v`` on
    # a token (``v4.6.0``) is consumed so it never leaks into the major parse.
    tokens = re.findall(r'(>=|<=|>|<|\^|~|=)?\s*v?(\d+(?:\.[\dxX*]+)*)', constraint)
    lowers = []  # majors introduced by lower/exact/caret/tilde bounds
    uppers = []  # top admitted major implied by each upper bound
    for op, token in tokens:
        try:
            major = int(token.split('.')[0])
        except (ValueError, IndexError):
            continue
        if op == '<':
            # Exclusive upper bound: the highest admitted major is major - 1
            # (``<5.0.0`` / ``<5`` admits 4.x, never 5.x).
            uppers.append(major - 1)
        elif op == '<=':
            uppers.append(major)
        else:
            # >=, >, ^, ~, =, or no operator: this major is admitted.
            lowers.append(major)
    if not lowers and not uppers:
        return set()
    # Collapse to an inclusive [low, high] band. When only one side is present
    # the band degenerates to that side, so a bare pin admits just its major.
    low = min(lowers) if lowers else min(uppers)
    high = max(uppers) if uppers else max(lowers)
    if high < low:
        high = low
    return set(range(low, high + 1))


def _common_major_set(chart_path: Path) -> set:
    """
    Read Chart.yaml and return the common-library majors its version pin admits.

    Parameters
    ----------
    chart_path : Path
        Root directory of the Helm chart.

    Returns
    -------
    set
        Integer major versions admitted by the ``common`` dependency pin, or an
        empty set when Chart.yaml is missing/unparseable or has no common dep.
    """
    chart_yaml_path = chart_path / "Chart.yaml"
    if not chart_yaml_path.exists():
        return set()
    try:
        with open(chart_yaml_path) as cf:
            chart_meta = yaml.safe_load(cf) or {}
    except yaml.YAMLError:
        return set()
    for dep in (chart_meta.get('dependencies') or []):
        if isinstance(dep, dict) and dep.get('name') == 'common':
            return _detect_common_majors(str(dep.get('version', '')))
    return set()


def common_version(chart_path: Path) -> Optional[Tuple[int, int]]:
    """
    Read the pinned major/minor of the bjw-s common dependency.

    ``_common_major_set`` answers "which majors does this pin admit"; this
    answers "which exact minor is pinned", which the 5.0-vs-5.1 feature gates
    need and a set of majors cannot express.

    Parameters
    ----------
    chart_path : Path
        Root directory of the Helm chart.

    Returns
    -------
    Optional[Tuple[int, int]]
        ``(major, minor)`` of the ``common`` dependency pin, or ``None`` when
        Chart.yaml is missing, unparseable, has no ``common`` dependency, or
        the pin is not a plain ``X.Y[.Z]`` version. A leading comparator is
        stripped, so ``^5.1.0`` reads as ``(5, 1)``.
    """
    chart_yaml_path = chart_path / "Chart.yaml"
    if not chart_yaml_path.exists():
        return None
    try:
        with open(chart_yaml_path) as cf:
            chart_meta = yaml.safe_load(cf) or {}
    except (yaml.YAMLError, OSError):
        return None
    if not isinstance(chart_meta, dict):
        return None
    for dep in (chart_meta.get('dependencies') or []):
        if not isinstance(dep, dict) or dep.get('name') != 'common':
            continue
        parts = str(dep.get('version', '')).lstrip('^~=v ').split('.')
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            return int(parts[0]), int(parts[1])
        return None
    return None


def _collect_controllers(values: dict) -> dict:
    """
    Map declared controller ids to the set of container names each defines.

    Parameters
    ----------
    values : dict
        Parsed values.yaml.

    Returns
    -------
    dict
        ``{controller_id: set(container_names)}`` for every declared controller.
    """
    result = {}
    controllers = values.get('controllers')
    if not isinstance(controllers, dict):
        return result
    for cid, cfg in controllers.items():
        containers = set()
        if isinstance(cfg, dict) and isinstance(cfg.get('containers'), dict):
            containers = set(cfg['containers'].keys())
        result[cid] = containers
    return result


def _collect_services(values: dict) -> dict:
    """
    Map declared service ids to the set of port names each exposes.

    Parameters
    ----------
    values : dict
        Parsed values.yaml.

    Returns
    -------
    dict
        ``{service_id: set(port_names)}`` for every declared service.
    """
    result = {}
    services = values.get('service')
    if not isinstance(services, dict):
        return result
    for sid, cfg in services.items():
        ports = set()
        if isinstance(cfg, dict) and isinstance(cfg.get('ports'), dict):
            ports = set(cfg['ports'].keys())
        result[sid] = ports
    return result


def _check_service_controller_refs(values: dict, controller_ids: set) -> List[Issue]:
    """
    Verify each ``service.<id>.controller`` points at a declared controller.

    Parameters
    ----------
    values : dict
        Parsed values.yaml.
    controller_ids : set
        Declared controller identifiers.

    Returns
    -------
    List[Issue]
        One error per dangling controller reference. Empty when nothing can be
        resolved (no services or no controllers) to stay conservative.
    """
    issues: List[Issue] = []
    services = values.get('service')
    if not isinstance(services, dict) or not controller_ids:
        return issues
    for sid, cfg in services.items():
        if not isinstance(cfg, dict) or cfg.get('enabled') is False:
            continue
        ref = cfg.get('controller')
        # Only resolve explicit string references; a missing controller may be
        # auto-targeted by bjw-s when a single controller exists.
        if isinstance(ref, str) and ref not in controller_ids:
            issues.append(Issue(
                f'service.{sid}.controller',
                'error',
                f'References controller "{ref}" which is not defined under controllers',
                f'Point controller: at one of: {", ".join(sorted(controller_ids))}'
            ))
    return issues


def _check_ingress_service_refs(values: dict, services: dict) -> List[Issue]:
    """
    Verify ingress path references resolve to a declared service and port.

    Only in-chart ``identifier`` references are resolved; a ``name`` reference
    targets an external Service and is left alone. A numeric ``port`` is passed
    through untouched by bjw-s, so only string port names are checked.

    Parameters
    ----------
    values : dict
        Parsed values.yaml.
    services : dict
        ``{service_id: set(port_names)}`` from :func:`_collect_services`.

    Returns
    -------
    List[Issue]
        Errors for dangling service identifiers or unknown port names.
    """
    issues: List[Issue] = []
    ingresses = values.get('ingress')
    if not isinstance(ingresses, dict) or not services:
        return issues
    for iid, cfg in ingresses.items():
        if not isinstance(cfg, dict) or cfg.get('enabled', True) is False:
            continue
        hosts = cfg.get('hosts')
        if not isinstance(hosts, list):
            continue
        for host in hosts:
            if not isinstance(host, dict):
                continue
            paths = host.get('paths')
            if not isinstance(paths, list):
                continue
            for path in paths:
                if not isinstance(path, dict):
                    continue
                svc = path.get('service')
                if not isinstance(svc, dict):
                    continue
                identifier = svc.get('identifier')
                # 'name' targets an external Service; skip it. Only 'identifier'
                # resolves against chart-declared services.
                if not isinstance(identifier, str):
                    continue
                if identifier not in services:
                    issues.append(Issue(
                        f'ingress.{iid}',
                        'error',
                        f'Path references service identifier "{identifier}" which is not defined under service',
                        f'Use one of: {", ".join(sorted(services))}'
                    ))
                    continue
                port = svc.get('port')
                port_names = services[identifier]
                # Resolve named ports only; a bare integer is a literal port.
                if isinstance(port, str) and port_names and port not in port_names:
                    issues.append(Issue(
                        f'ingress.{iid}',
                        'error',
                        f'Path references port "{port}" not defined on service "{identifier}"',
                        f'Use one of: {", ".join(sorted(port_names))}'
                    ))
    return issues


def _check_persistence_mount_refs(values: dict, controllers: dict) -> List[Issue]:
    """
    Verify ``persistence.<id>.advancedMounts.<controller>.<container>`` targets.

    Parameters
    ----------
    values : dict
        Parsed values.yaml.
    controllers : dict
        ``{controller_id: set(container_names)}`` from
        :func:`_collect_controllers`.

    Returns
    -------
    List[Issue]
        Errors for advancedMounts pointing at unknown controllers or containers.
    """
    issues: List[Issue] = []
    persistence = values.get('persistence')
    if not isinstance(persistence, dict) or not controllers:
        return issues
    for pid, cfg in persistence.items():
        if not isinstance(cfg, dict) or cfg.get('enabled', True) is False:
            continue
        adv = cfg.get('advancedMounts')
        if not isinstance(adv, dict):
            continue
        # advancedMounts nests as {controllerKey: {containerKey: [mounts]}}.
        for ctrl_key, containers in adv.items():
            if ctrl_key not in controllers:
                issues.append(Issue(
                    f'persistence.{pid}.advancedMounts.{ctrl_key}',
                    'error',
                    f'advancedMounts targets controller "{ctrl_key}" which is not defined',
                    f'Use one of: {", ".join(sorted(controllers))}'
                ))
                continue
            if not isinstance(containers, dict):
                continue
            valid_containers = controllers[ctrl_key]
            for cont_key in containers.keys():
                # Only flag when the controller actually declares containers;
                # an empty set means we could not enumerate them safely.
                if valid_containers and cont_key not in valid_containers:
                    issues.append(Issue(
                        f'persistence.{pid}.advancedMounts.{ctrl_key}.{cont_key}',
                        'error',
                        f'advancedMounts targets container "{cont_key}" not defined in controller "{ctrl_key}"',
                        f'Use one of: {", ".join(sorted(valid_containers))}'
                    ))
    return issues


def _check_controller_ref_block(values: dict, block_key: str, controller_ids: set) -> List[Issue]:
    """
    Verify each ``<block>.<id>.controller`` points at a declared controller.

    Generic resolver for top-level blocks that reference a controller through
    a bare-string ``controller:`` key. Only ``networkpolicies`` uses this exact
    shape in common 5.x — ``horizontalPodAutoscaler`` has no top-level block
    (it nests under ``controllers.<id>``, see
    :func:`_check_controller_hpa_replicas_null` and
    :func:`_check_top_level_hpa_key`) and ``podMonitor.<id>.controller`` is an
    object, not a bare string (see :func:`_check_podmonitor_refs`).

    Parameters
    ----------
    values : dict
        Parsed values.yaml.
    block_key : str
        Top-level block name to inspect (e.g. ``networkpolicies``).
    controller_ids : set
        Declared controller identifiers.

    Returns
    -------
    List[Issue]
        One error per dangling controller reference.
    """
    issues: List[Issue] = []
    block = values.get(block_key)
    if not isinstance(block, dict) or not controller_ids:
        return issues
    for bid, cfg in block.items():
        if not isinstance(cfg, dict) or cfg.get('enabled', True) is False:
            continue
        ref = cfg.get('controller')
        # controller is optional (auto-targeted when a single controller
        # exists); resolve only explicit string references.
        if isinstance(ref, str) and ref not in controller_ids:
            issues.append(Issue(
                f'{block_key}.{bid}.controller',
                'error',
                f'References controller "{ref}" which is not defined under controllers',
                f'Use one of: {", ".join(sorted(controller_ids))}'
            ))
    return issues


def _check_top_level_hpa_key(values: dict) -> List[Issue]:
    """
    Detect a top-level ``horizontalPodAutoscaler:`` block (invalid in v5).

    In bjw-s common 5.x the HorizontalPodAutoscaler is declared per-controller
    under ``controllers.<id>.horizontalPodAutoscaler``; there is no top-level
    ``horizontalPodAutoscaler:`` key in the v5 schema. A chart that still uses
    the pre-v5 top-level shape renders zero HPA resources with no error from
    Helm itself — a silent no-op that is easy to miss in review.

    Parameters
    ----------
    values : dict
        Parsed values.yaml.

    Returns
    -------
    List[Issue]
        One error per entry found under a stray top-level
        ``horizontalPodAutoscaler`` block.
    """
    issues: List[Issue] = []
    block = values.get('horizontalPodAutoscaler')
    if not isinstance(block, dict) or not block:
        return issues
    for hid in block:
        issues.append(Issue(
            f'horizontalPodAutoscaler.{hid}',
            'error',
            'In common 5.x, HPA is defined per-controller under '
            'controllers.<id>.horizontalPodAutoscaler, not as a top-level block; '
            'a top-level horizontalPodAutoscaler renders no resource',
            'Move this HPA definition under controllers.<controller-id>.horizontalPodAutoscaler'
        ))
    return issues


def _check_controller_hpa_replicas_null(values: dict) -> List[Issue]:
    """
    Warn when a controller with a per-controller HPA pins concrete replicas.

    In common 5.x the HorizontalPodAutoscaler nests under
    ``controllers.<id>.horizontalPodAutoscaler`` (deployment/statefulset only).
    The bjw-s docs stress leaving that controller's ``replicas: null`` so the
    HPA owns the replica count; a fixed value fights the autoscaler on every
    Helm upgrade. Absent ``replicas`` is left alone to avoid false positives.

    Parameters
    ----------
    values : dict
        Parsed values.yaml.

    Returns
    -------
    List[Issue]
        Warnings for controllers with an enabled per-controller HPA that still
        pin replicas to a concrete value.
    """
    issues: List[Issue] = []
    controllers = values.get('controllers')
    if not isinstance(controllers, dict):
        return issues
    for ctrl_id, ctrl_cfg in controllers.items():
        if not isinstance(ctrl_cfg, dict):
            continue
        hpa = ctrl_cfg.get('horizontalPodAutoscaler')
        if not isinstance(hpa, dict) or not hpa or hpa.get('enabled', True) is False:
            continue
        # A present, non-null replicas value overrides the autoscaler on every
        # Helm upgrade. Only warn on an explicit value; None (null) is correct.
        if 'replicas' in ctrl_cfg and ctrl_cfg['replicas'] is not None:
            issues.append(Issue(
                f'controllers.{ctrl_id}.replicas',
                'warning',
                f'controllers.{ctrl_id} defines a horizontalPodAutoscaler but replicas is set to {ctrl_cfg["replicas"]!r}',
                'Set replicas: null so the HorizontalPodAutoscaler owns the replica count'
            ))
    return issues


def _check_podmonitor_refs(values: dict, controller_ids: set) -> List[Issue]:
    """
    Validate the podMonitor controller shape/reference and endpoints key.

    In common 5.x, ``podMonitor.<id>.controller`` must be an object
    ``{identifier: <controller-id>}``; a bare string crashes ``helm template``.
    The metrics-endpoint key is ``podMetricsEndpoints:`` — the Prometheus
    Operator ``ServiceMonitor`` spelling ``endpoints:`` parses as valid YAML
    but is not part of the schema, so it is silently dropped, producing a
    PodMonitor with no endpoints.

    Parameters
    ----------
    values : dict
        Parsed values.yaml.
    controller_ids : set
        Declared controller identifiers.

    Returns
    -------
    List[Issue]
        Errors for a bare-string controller, a dangling controller identifier,
        and a misspelled ``endpoints`` key.
    """
    issues: List[Issue] = []
    pod_monitors = values.get('podMonitor')
    if not isinstance(pod_monitors, dict):
        return issues
    for pid, cfg in pod_monitors.items():
        if not isinstance(cfg, dict) or cfg.get('enabled', True) is False:
            continue
        location = f'podMonitor.{pid}'
        ref = cfg.get('controller')
        if isinstance(ref, str):
            # The v5 schema requires the object form; a bare string here
            # crashes `helm template` rather than merely failing to resolve.
            issues.append(Issue(
                f'{location}.controller',
                'error',
                'podMonitor.<id>.controller must be an object {identifier: <controller-id>}; '
                'a bare string crashes helm template',
                f'Use controller: {{identifier: {ref}}}'
            ))
        elif isinstance(ref, dict) and controller_ids:
            identifier = ref.get('identifier')
            if isinstance(identifier, str) and identifier not in controller_ids:
                issues.append(Issue(
                    f'{location}.controller.identifier',
                    'error',
                    f'References controller "{identifier}" which is not defined under controllers',
                    f'Use one of: {", ".join(sorted(controller_ids))}'
                ))
        if 'endpoints' in cfg:
            issues.append(Issue(
                f'{location}.endpoints',
                'error',
                'podMonitor uses `podMetricsEndpoints:`, not `endpoints:`',
                'Rename the key to podMetricsEndpoints'
            ))
    return issues


def _check_servicemonitor_refs(values: dict, services: dict) -> List[Issue]:
    """
    Validate serviceMonitor service references and flag the invalid controller key.

    ``serviceMonitor.<id>`` targets a Service via ``service: {identifier: <id>}``
    (chart-managed) or ``service: {name: <ext>}`` (external) — never via
    ``controller:``. A stray ``controller:`` key is silently ignored by the
    schema and breaks once a controller exposes more than one Service.

    Parameters
    ----------
    values : dict
        Parsed values.yaml.
    services : dict
        ``{service_id: set(port_names)}`` from :func:`_collect_services`.

    Returns
    -------
    List[Issue]
        Errors for a stray ``controller:`` key and for a dangling service
        identifier.
    """
    issues: List[Issue] = []
    service_monitors = values.get('serviceMonitor')
    if not isinstance(service_monitors, dict):
        return issues
    for sid, cfg in service_monitors.items():
        if not isinstance(cfg, dict) or cfg.get('enabled', True) is False:
            continue
        location = f'serviceMonitor.{sid}'
        if 'controller' in cfg:
            issues.append(Issue(
                f'{location}.controller',
                'error',
                'serviceMonitor targets a Service via service: {identifier: <id>} (or {name:}), not controller:; '
                'the controller key is ignored and breaks with 2+ services',
                'Remove controller: and add service: {identifier: <service-id>}'
            ))
        svc = cfg.get('service')
        if isinstance(svc, dict) and services:
            identifier = svc.get('identifier')
            # 'name' targets an external Service; skip it, same treatment as
            # the ingress service-reference check.
            if isinstance(identifier, str) and identifier not in services:
                issues.append(Issue(
                    f'{location}.service.identifier',
                    'error',
                    f'References service identifier "{identifier}" which is not defined under service',
                    f'Use one of: {", ".join(sorted(services))}'
                ))
    return issues


def _check_env_valuefrom_identifier(values: dict) -> List[Issue]:
    """
    Flag ``identifier`` used inside a per-variable ``env`` ``valueFrom`` ref.

    The bjw-s common-5.1.0 schema (``schemas/envVars.json``) resolves both
    ``configMapKeyRef`` and ``secretKeyRef`` under a per-variable ``valueFrom``
    to ``$defs/objectKeySelector``, which is ``additionalProperties: false``
    with only ``name`` and ``key`` allowed. ``identifier`` there is schema
    -invalid and Helm rejects the chart. ``identifier`` only resolves
    chart-managed objects in ``envFrom`` and in persistence refs — never in a
    per-variable ``valueFrom``, which always needs the rendered object name.

    Handles both accepted ``env`` shapes: the mapping form
    (``env: {VAR: {valueFrom: {...}}}``) and the list form
    (``env: [{name: VAR, valueFrom: {...}}]``).

    Parameters
    ----------
    values : dict
        Parsed values.yaml.

    Returns
    -------
    List[Issue]
        One error per ``configMapKeyRef``/``secretKeyRef`` that uses
        ``identifier`` instead of ``name``.
    """
    issues: List[Issue] = []
    controllers = values.get('controllers')
    if not isinstance(controllers, dict):
        return issues

    def _check_value_from(value_from, location):
        """Inspect a single valueFrom block for a schema-invalid identifier key."""
        if not isinstance(value_from, dict):
            return
        for ref_key in ('configMapKeyRef', 'secretKeyRef'):
            ref = value_from.get(ref_key)
            if isinstance(ref, dict) and 'identifier' in ref:
                issues.append(Issue(
                    f'{location}.valueFrom.{ref_key}',
                    'error',
                    f'"identifier" is not valid inside a per-variable valueFrom.{ref_key} '
                    '(schema only allows name + key)',
                    'Use "name: <rendered-object-name>" instead — identifier only '
                    'works in envFrom and persistence refs'
                ))

    for ctrl_id, ctrl_cfg in controllers.items():
        if not isinstance(ctrl_cfg, dict):
            continue
        containers = ctrl_cfg.get('containers')
        if not isinstance(containers, dict):
            continue
        for cont_name, cont_cfg in containers.items():
            if not isinstance(cont_cfg, dict):
                continue
            env = cont_cfg.get('env')
            base_location = f'controllers.{ctrl_id}.containers.{cont_name}.env'
            if isinstance(env, dict):
                # Mapping form: env.<VAR>.valueFrom...
                for var_name, var_cfg in env.items():
                    if isinstance(var_cfg, dict):
                        _check_value_from(var_cfg.get('valueFrom'), f'{base_location}.{var_name}')
            elif isinstance(env, list):
                # List form: env: [{name: VAR, valueFrom: {...}}]
                for entry in env:
                    if isinstance(entry, dict):
                        var_name = entry.get('name', '?')
                        _check_value_from(entry.get('valueFrom'), f'{base_location}.{var_name}')
    return issues


def validate_chart_yaml(chart_path: Path) -> List[Issue]:
    """
    Validate Chart.yaml structure.

    Parameters
    ----------
    chart_path : Path
        Root directory of the Helm chart.

    Returns
    -------
    List[Issue]
        Issues found in Chart.yaml.
    """
    issues = []
    chart_yaml = chart_path / "Chart.yaml"

    if not chart_yaml.exists():
        issues.append(Issue(
            'Chart.yaml',
            'error',
            'Chart.yaml not found',
            'Create Chart.yaml with apiVersion, name, version, and dependencies'
        ))
        return issues

    try:
        with open(chart_yaml) as f:
            chart = yaml.safe_load(f)
    except yaml.YAMLError as e:
        issues.append(Issue(
            'Chart.yaml',
            'error',
            f'Invalid YAML: {e}',
            'Fix YAML syntax errors'
        ))
        return issues

    # Check required fields
    required = ['apiVersion', 'name', 'version', 'type']
    for field_name in required:
        if field_name not in chart:
            issues.append(Issue(
                'Chart.yaml',
                'error',
                f'Missing required field: {field_name}',
                f'Add {field_name} to Chart.yaml'
            ))

    # Check dependencies
    if 'dependencies' not in chart:
        issues.append(Issue(
            'Chart.yaml',
            'error',
            'No dependencies defined',
            'Add bjw-s common library as dependency'
        ))
    else:
        deps = chart['dependencies']
        common_found = False
        for dep in deps:
            if dep.get('name') == 'common':
                common_found = True
                if dep.get('repository') != 'https://bjw-s-labs.github.io/helm-charts':
                    issues.append(Issue(
                        'Chart.yaml',
                        'warning',
                        'Common library repository URL may be incorrect',
                        'Use: https://bjw-s-labs.github.io/helm-charts'
                    ))
                # Surface major-version info so callers know which
                # feature set is in scope. 5.x is the default; 4.x is
                # treated as a legacy track and 5.x-only features are
                # not validated against 4.x.
                raw_version = str(dep.get('version', '')).strip()
                # Robustly detect the major(s) a constraint admits so ranges
                # like ">=4.0.0 <5.0.0", "~4.6.0" or "4.x" still surface the
                # legacy-4.x warning (a naive first-segment parse misses them).
                majors = _detect_common_majors(raw_version)
                if not raw_version:
                    issues.append(Issue(
                        'Chart.yaml',
                        'warning',
                        'common library has no version pin',
                        'Pin a version (current default: 5.1.0)'
                    ))
                elif majors:
                    min_major = min(majors)
                    max_major = max(majors)
                    if min_major < 4:
                        issues.append(Issue(
                            'Chart.yaml',
                            'error',
                            f'common library version {raw_version} admits a release older than v4',
                            'Upgrade to 5.x (or 4.6.2 for legacy clusters) — pre-v4 is unsupported'
                        ))
                    if 4 in majors and max_major >= 5:
                        # The range straddles a major boundary (e.g. ">=4 <6"),
                        # so which feature set applies is ambiguous.
                        issues.append(Issue(
                            'Chart.yaml',
                            'warning',
                            f'common library constraint {raw_version} spans majors 4.x and 5.x',
                            'Tighten the pin to a single major (e.g. 5.1.0) — a range across majors is ambiguous'
                        ))
                    elif 4 in majors:
                        issues.append(Issue(
                            'Chart.yaml',
                            'warning',
                            f'common library pinned to {raw_version} (legacy 4.x track)',
                            'Migrate to 5.1.0 when K8s ≥ 1.31 / Helm ≥ 3.18 — see references/migration-4-to-5.md'
                        ))
                    elif min_major >= 5:
                        issues.append(Issue(
                            'Chart.yaml',
                            'info',
                            f'common library pinned to {raw_version} (5.x, current default)',
                            ''
                        ))
                break

        if not common_found:
            issues.append(Issue(
                'Chart.yaml',
                'error',
                'bjw-s common library not found in dependencies',
                'Add common library dependency'
            ))

    # Check Chart.lock (generated by helm dependency update)
    chart_lock = chart_path / "Chart.lock"
    if not chart_lock.exists():
        issues.append(Issue(
            'Chart.lock',
            'warning',
            'Chart.lock not found — dependencies not fetched',
            'Run: helm dependency update'
        ))

    # Check vendored dependency tarballs under charts/. A published chart
    # must be self-contained: `helm dependency update` (or `helm dependency
    # build` from Chart.lock) materializes every dependency as
    # charts/<name>-<resolved-version>.tgz. Without them, a consumer must
    # have each dependency repo pre-added to resolve the chart at install
    # time, which breaks offline / air-gapped installs.
    declared_deps = chart.get('dependencies') or []
    if declared_deps:
        charts_dir = chart_path / "charts"
        if not charts_dir.is_dir():
            issues.append(Issue(
                'charts/',
                'warning',
                'charts/ directory missing — dependencies not vendored',
                'Run `helm dependency update`, then publish charts/ alongside '
                'Chart.lock so the packaged chart is self-contained'
            ))
        else:
            # The Chart.yaml version may be a range, so the resolved tarball
            # version is unknown here. Match on "<name>-<digit>" to avoid a
            # sibling dependency (e.g. common-extra) satisfying "common".
            vendored = [p.name for p in charts_dir.glob('*.tgz')]
            for dep in declared_deps:
                if not isinstance(dep, dict):
                    continue
                dep_name = dep.get('name')
                if not dep_name:
                    continue
                prefix = f'{dep_name}-'
                if not any(
                    name.startswith(prefix) and name[len(prefix):][:1].isdigit()
                    for name in vendored
                ):
                    issues.append(Issue(
                        'charts/',
                        'warning',
                        f'Dependency "{dep_name}" has no vendored tarball under charts/',
                        f'Run `helm dependency update` (or `helm dependency build`) '
                        f'to fetch {dep_name}-<version>.tgz before publishing'
                    ))

    return issues


def validate_templates(chart_path: Path) -> List[Issue]:
    """
    Validate templates directory.

    Parameters
    ----------
    chart_path : Path
        Root directory of the Helm chart.

    Returns
    -------
    List[Issue]
        Issues found in the templates directory.
    """
    issues = []
    templates_dir = chart_path / "templates"

    if not templates_dir.exists():
        issues.append(Issue(
            'templates/',
            'error',
            'templates directory not found',
            'Create templates/ directory'
        ))
        return issues

    # Check common.yaml
    common_yaml = templates_dir / "common.yaml"
    if not common_yaml.exists():
        issues.append(Issue(
            'templates/common.yaml',
            'error',
            'common.yaml not found',
            'Create templates/common.yaml with: {{- include "bjw-s.common.loader.all" . }}'
        ))
    else:
        content = common_yaml.read_text()
        if 'bjw-s.common.loader.all' not in content:
            issues.append(Issue(
                'templates/common.yaml',
                'error',
                'Missing bjw-s.common.loader.all include',
                'Add: {{- include "bjw-s.common.loader.all" . }}'
            ))

    # Check NOTES.txt
    notes_txt = templates_dir / "NOTES.txt"
    if not notes_txt.exists():
        issues.append(Issue(
            'templates/NOTES.txt',
            'info',
            'NOTES.txt not found',
            'Consider adding NOTES.txt for post-install instructions'
        ))

    return issues


# Valid `strategy` values and the default the library applies when the key
# is absent, per controller type. Job/CronJob have no update strategy.
_STRATEGIES = {
    'deployment': ({'Recreate', 'RollingUpdate'}, 'Recreate'),
    'statefulset': ({'OnDelete', 'RollingUpdate'}, 'RollingUpdate'),
    # DaemonSet gained a rendered updateStrategy in common 5.1.0; before
    # that the key was accepted and dropped. No library-side default.
    'daemonset': ({'OnDelete', 'RollingUpdate'}, None),
}

# rollingUpdate keys the library renders, per controller type. The
# `surge` / `unavailable` spellings are the pre-5.1 shorthands.
_ROLLING_KEYS = {
    'deployment': {'maxSurge', 'maxUnavailable', 'surge', 'unavailable'},
    'daemonset': {'maxSurge', 'maxUnavailable', 'surge', 'unavailable'},
    'statefulset': {'partition', 'maxUnavailable'},
}

_DEPRECATED_ROLLING_KEYS = {'surge': 'maxSurge', 'unavailable': 'maxUnavailable'}


def _validate_strategy(
    location: str,
    ctrl_config: dict,
    common_ver: Optional[Tuple[int, int]],
) -> List[Issue]:
    """Check a controller's ``strategy`` and ``rollingUpdate`` keys.

    From common 5.1.0 an invalid ``strategy`` is rejected by the values
    schema rather than a template failure, and the valid set depends on
    the controller type. This reproduces that check locally, plus the
    version gates and deprecations that the schema does not express.

    Parameters
    ----------
    location : str
        Dotted path of the controller, used as the issue location.
    ctrl_config : dict
        The controller's values block.
    common_ver : Optional[Tuple[int, int]]
        ``(major, minor)`` of the pinned common library, or ``None`` when
        it could not be determined. Version-gated checks are skipped in
        that case rather than guessed at.

    Returns
    -------
    List[Issue]
        Issues found, empty when the controller has neither key set or
        both are well-formed.
    """
    issues: List[Issue] = []
    ctype = ctrl_config.get('type', 'deployment')
    strategy = ctrl_config.get('strategy')
    rolling = ctrl_config.get('rollingUpdate')

    if strategy is None and rolling is None:
        return issues

    # Job and CronJob have no update strategy; the keys are inert there.
    if ctype not in _STRATEGIES:
        if strategy is not None or rolling is not None:
            issues.append(Issue(
                location,
                'warning',
                f'`strategy` / `rollingUpdate` set on a {ctype} controller',
                'Neither key is rendered for this controller type — remove them'
            ))
        return issues

    valid, default = _STRATEGIES[ctype]
    effective = default

    if strategy is not None:
        if not isinstance(strategy, str):
            issues.append(Issue(
                f'{location}.strategy',
                'error',
                '`strategy` is a string, not a mapping',
                f'Use `strategy: RollingUpdate` with a sibling `rollingUpdate:` block — one of {sorted(valid)}'
            ))
            effective = None
        elif strategy not in valid:
            issues.append(Issue(
                f'{location}.strategy',
                'error',
                f'invalid strategy `{strategy}` for a {ctype} controller',
                f'Use one of {sorted(valid)}'
            ))
            effective = None
        else:
            effective = strategy
            if ctype == 'daemonset' and common_ver and common_ver < (5, 1):
                issues.append(Issue(
                    f'{location}.strategy',
                    'warning',
                    'DaemonSet `strategy` is dropped by common < 5.1.0',
                    'Pin common 5.1.0 or later for the key to render an updateStrategy'
                ))

    if rolling is None:
        return issues

    if not isinstance(rolling, dict):
        issues.append(Issue(
            f'{location}.rollingUpdate',
            'error',
            '`rollingUpdate` must be a mapping',
            'Use a block with maxSurge / maxUnavailable (or partition on a StatefulSet)'
        ))
        return issues

    # `rollingUpdate` is only read when the effective strategy is
    # RollingUpdate — which a Deployment does not get by default.
    if effective is not None and effective != 'RollingUpdate':
        hint = (
            'Set `strategy: RollingUpdate` explicitly — the library default is Recreate'
            if strategy is None
            else f'`rollingUpdate` is ignored with `strategy: {effective}`'
        )
        issues.append(Issue(
            f'{location}.rollingUpdate',
            'warning',
            f'`rollingUpdate` is ignored: effective strategy is {effective}',
            hint
        ))

    allowed = _ROLLING_KEYS[ctype]
    for key in rolling:
        if key not in allowed:
            issues.append(Issue(
                f'{location}.rollingUpdate.{key}',
                'error',
                f'`{key}` is not a rollingUpdate key for a {ctype} controller',
                f'Valid keys: {sorted(allowed)}'
            ))
            continue
        if key in _DEPRECATED_ROLLING_KEYS:
            issues.append(Issue(
                f'{location}.rollingUpdate.{key}',
                'warning',
                f'`{key}` is deprecated as of common 5.1.0',
                f'Rename to `{_DEPRECATED_ROLLING_KEYS[key]}` — the shorthand is removed in 6.0'
            ))

    if (
        ctype == 'statefulset'
        and 'maxUnavailable' in rolling
        and common_ver
        and common_ver < (5, 1)
    ):
        issues.append(Issue(
            f'{location}.rollingUpdate.maxUnavailable',
            'warning',
            'StatefulSet `maxUnavailable` is dropped by common < 5.1.0',
            'Pin common 5.1.0 or later; the cluster also needs the MaxUnavailableStatefulSet feature gate'
        ))

    return issues


def validate_values(chart_path: Path) -> List[Issue]:
    """
    Validate values.yaml structure.

    Parameters
    ----------
    chart_path : Path
        Root directory of the Helm chart.

    Returns
    -------
    List[Issue]
        Issues found in values.yaml.
    """
    issues = []
    values_yaml = chart_path / "values.yaml"

    if not values_yaml.exists():
        issues.append(Issue(
            'values.yaml',
            'error',
            'values.yaml not found',
            'Create values.yaml with chart configuration'
        ))
        return issues

    try:
        with open(values_yaml) as f:
            values = yaml.safe_load(f)
    except yaml.YAMLError as e:
        issues.append(Issue(
            'values.yaml',
            'error',
            f'Invalid YAML: {e}',
            'Fix YAML syntax errors'
        ))
        return issues

    if not values:
        issues.append(Issue(
            'values.yaml',
            'error',
            'values.yaml is empty',
            'Add controller configuration'
        ))
        return issues

    common_ver = common_version(chart_path)

    # Check controllers
    if 'controllers' not in values:
        issues.append(Issue(
            'values.yaml',
            'error',
            'No controllers defined',
            'Add at least one controller'
        ))
        return issues

    controllers = values['controllers']
    if not controllers:
        issues.append(Issue(
            'values.yaml',
            'error',
            'Controllers section is empty',
            'Add at least one controller'
        ))
        return issues

    # Validate each controller
    for ctrl_name, ctrl_config in controllers.items():
        location = f'controllers.{ctrl_name}'

        if not ctrl_config:
            issues.append(Issue(
                location,
                'error',
                'Controller configuration is empty',
                'Add container definitions'
            ))
            continue

        issues.extend(_validate_strategy(location, ctrl_config, common_ver))

        # Check containers
        if 'containers' not in ctrl_config:
            issues.append(Issue(
                location,
                'error',
                'No containers defined',
                'Add at least one container'
            ))
            continue

        containers = ctrl_config['containers']
        if not containers:
            issues.append(Issue(
                location,
                'error',
                'Containers section is empty',
                'Add at least one container'
            ))
            continue

        # Validate containers
        for container_name, container_config in containers.items():
            cont_location = f'{location}.containers.{container_name}'

            if not container_config:
                issues.append(Issue(
                    cont_location,
                    'error',
                    'Container configuration is empty',
                    'Add image configuration'
                ))
                continue

            # Check image
            if 'image' not in container_config:
                issues.append(Issue(
                    cont_location,
                    'error',
                    'No image defined',
                    'Add image.repository and image.tag'
                ))
            else:
                image = container_config['image']
                # A present-but-null image (`image:` with no children) parses
                # to None and is not subscriptable — guard before indexing.
                if not isinstance(image, dict) or not image:
                    issues.append(Issue(
                        f'{cont_location}.image',
                        'error',
                        'image block is empty/null',
                        'Define image.repository and image.tag'
                    ))
                else:
                    if 'repository' not in image:
                        issues.append(Issue(
                            f'{cont_location}.image',
                            'error',
                            'Missing image repository',
                            'Add image.repository'
                        ))
                    if 'tag' not in image:
                        issues.append(Issue(
                            f'{cont_location}.image',
                            'warning',
                            'Missing image tag',
                            'Add explicit image.tag (avoid :latest)'
                        ))
                    else:
                        raw_tag = image.get('tag')
                        # An unquoted numeric tag is reinterpreted by YAML:
                        # `tag: 1.10` -> float 1.1, `tag: 16` -> int 16, both
                        # silently losing the intended string. bool is a subclass
                        # of int, so it is covered by the same check.
                        if isinstance(raw_tag, (bool, int, float)):
                            issues.append(Issue(
                                f'{cont_location}.image',
                                'warning',
                                f'Image tag {raw_tag!r} is not a string — YAML reinterpreted an unquoted numeric/boolean tag',
                                'Quote the tag (e.g. tag: "1.10") so YAML preserves it verbatim'
                            ))
                        elif str(raw_tag).lower() == 'latest':
                            issues.append(Issue(
                                f'{cont_location}.image',
                                'warning',
                                'Using :latest tag',
                                'Use specific version tag for reproducibility'
                            ))

            # Check resource requests/limits
            resources = container_config.get('resources', {})
            if not resources:
                issues.append(Issue(
                    f'{cont_location}.resources',
                    'warning',
                    'No resource requests or limits defined',
                    'Add resources.requests (cpu, memory) and resources.limits.memory'
                ))
            else:
                requests = resources.get('requests', {})
                limits = resources.get('limits', {})
                if not requests.get('memory'):
                    issues.append(Issue(
                        f'{cont_location}.resources',
                        'warning',
                        'No memory request defined',
                        'Add resources.requests.memory (e.g. 128Mi)'
                    ))
                if not limits.get('memory'):
                    issues.append(Issue(
                        f'{cont_location}.resources',
                        'warning',
                        'No memory limit defined',
                        'Add resources.limits.memory to prevent OOM kills'
                    ))

            # Check probes
            probes = container_config.get('probes', {})
            replicas = ctrl_config.get('replicas', 1)
            if replicas and int(replicas) > 1:
                readiness = probes.get('readiness', {})
                if not readiness.get('enabled'):
                    issues.append(Issue(
                        f'{cont_location}.probes.readiness',
                        'warning',
                        f'No readiness probe with replicas={replicas} — RollingUpdate may route traffic to unready pods',
                        'Enable readiness probe to ensure zero-downtime deployments'
                    ))
            if probes:
                for probe_type in ['liveness', 'readiness', 'startup']:
                    if probe_type in probes:
                        probe = probes[probe_type]
                        if probe.get('enabled') and not probe.get('custom'):
                            if 'type' not in probe:
                                issues.append(Issue(
                                    f'{cont_location}.probes.{probe_type}',
                                    'info',
                                    'Probe type not specified',
                                    'Add type: TCP, HTTP, HTTPS, GRPC, or AUTO. '
                                    'For exec/command probes set custom: true with a raw spec.exec instead of a type'
                                ))

    # Check services
    if 'service' in values:
        services = values['service']
        for svc_name, svc_config in services.items():
            location = f'service.{svc_name}'

            if not svc_config:
                continue

            # A disabled service renders nothing — do not validate its inner
            # fields (default is enabled, so only skip on an explicit False).
            if svc_config.get('enabled') is False:
                continue

            if 'controller' not in svc_config:
                issues.append(Issue(
                    location,
                    'error',
                    'Service does not reference a controller',
                    'Add controller: <controller-name>'
                ))

            if 'ports' not in svc_config or not svc_config['ports']:
                issues.append(Issue(
                    location,
                    'error',
                    'Service has no ports defined',
                    'Add at least one port'
                ))

    # Check ingress
    if 'ingress' in values:
        ingresses = values['ingress']
        for ing_name, ing_config in ingresses.items():
            if not ing_config:
                continue
            if not ing_config.get('enabled', True):
                continue

            location = f'ingress.{ing_name}'

            if 'hosts' not in ing_config or not ing_config['hosts']:
                issues.append(Issue(
                    location,
                    'warning',
                    'Ingress has no hosts defined',
                    'Add hosts configuration'
                ))
                continue

            # Validate service references in paths
            for host in ing_config['hosts']:
                if 'paths' not in host:
                    continue
                for path in host['paths']:
                    if 'service' not in path:
                        continue
                    svc = path['service']
                    if 'name' in svc and 'identifier' not in svc:
                        # Using 'name' instead of 'identifier' is the most common mistake
                        issues.append(Issue(
                            location,
                            'error',
                            f'Service path uses "name: {svc["name"]}" — this references an external service',
                            'Use "identifier: <service-identifier>" to reference a chart-managed service'
                        ))
                    elif 'identifier' not in svc and 'name' not in svc:
                        issues.append(Issue(
                            location,
                            'error',
                            'Service reference missing identifier or name',
                            'Add identifier: <service-identifier>'
                        ))

    # Detect which common major(s) the chart targets. Reused to gate both the
    # legacy rawResources shape and the 5.x-only ServiceAccount hint. Re-read
    # Chart.yaml — validate_values runs independently of validate_chart_yaml.
    common_majors = _common_major_set(chart_path)
    # An empty set means the pin is unknown/unparseable; default to 5.x (the
    # current track) so 5.x-only checks still fire on well-formed modern charts.
    targets_v5 = (not common_majors) or (5 in common_majors)
    # Purely-4.x means 4 is admitted and 5 is not — legacy shapes are valid then.
    legacy_4x_only = bool(common_majors) and 4 in common_majors and 5 not in common_majors

    # Check rawResources for legacy 4.x shape
    raw_resources = values.get('rawResources') or {}
    for rr_name, rr_config in raw_resources.items():
        if not isinstance(rr_config, dict):
            continue
        location = f'rawResources.{rr_name}'
        if 'manifest' in rr_config:
            continue
        # Legacy 4.x shape: manifest fields live at the top level,
        # optionally under a 'spec:' key.
        legacy_keys = {'apiVersion', 'kind', 'spec', 'labels', 'annotations'}
        if legacy_keys & set(rr_config.keys()):
            if legacy_4x_only:
                # The skill advertises 4.x legacy support; on a 4.x pin the
                # top-level shape is the correct one, so this is informational.
                issues.append(Issue(
                    location,
                    'info',
                    'rawResources uses the legacy 4.x top-level shape (valid for common 4.x)',
                    'On 5.x this must be wrapped under a `manifest:` key — see references/migration-4-to-5.md'
                ))
            else:
                issues.append(Issue(
                    location,
                    'error',
                    'rawResources uses the legacy 4.x shape (no `manifest:` wrapper)',
                    'Wrap the K8s manifest under a `manifest:` key and move labels/annotations under `metadata:` — see references/migration-4-to-5.md'
                ))

    # ServiceAccount opt-out hint: a chart that wires an external SA
    # without disabling the 5.x default will end up with two SAs in the
    # namespace. Only emit the hint when the common dep is 5.x.
    def _references_external_sa(ctrls):
        for cfg in (ctrls or {}).values():
            if not isinstance(cfg, dict):
                continue
            sa = cfg.get('serviceAccount')
            if isinstance(sa, dict) and sa.get('name'):
                return True
        return False

    if 5 in common_majors:
        global_section = values.get('global') or {}
        if (
            _references_external_sa(values.get('controllers'))
            and not values.get('serviceAccount')
            and global_section.get('createDefaultServiceAccount') is not False
        ):
            issues.append(Issue(
                'global.createDefaultServiceAccount',
                'info',
                'Controllers reference an external ServiceAccount but the 5.x default SA is still being created',
                'Set `global.createDefaultServiceAccount: false` to suppress the auto-generated unprivileged SA'
            ))

    # Check persistence
    if 'persistence' in values:
        persistence = values['persistence']
        for vol_name, vol_config in persistence.items():
            if not vol_config:
                continue
            if not vol_config.get('enabled', True):
                continue

            location = f'persistence.{vol_name}'

            if 'type' not in vol_config:
                issues.append(Issue(
                    location,
                    'info',
                    'Persistence type not specified',
                    'Defaults to persistentVolumeClaim'
                ))

            vol_type = vol_config.get('type', 'persistentVolumeClaim')

            if vol_type == 'persistentVolumeClaim':
                if 'existingClaim' not in vol_config:
                    if 'size' not in vol_config:
                        issues.append(Issue(
                            location,
                            'error',
                            'PVC has no size specified',
                            'Add size: 1Gi (or use existingClaim)'
                        ))
                    if 'accessMode' not in vol_config:
                        issues.append(Issue(
                            location,
                            'info',
                            'PVC has no accessMode specified',
                            'Defaults to ReadWriteOnce'
                        ))

    # Cross-reference validation: resolve identifiers against declared objects.
    # These catch the dominant real-world failure — a typo'd identifier that
    # renders fine but wires to nothing. Every check is conservative: it only
    # errors on an explicit reference it can prove is dangling, and stays silent
    # on unfamiliar/optional shapes to avoid destroying trust with false alarms.
    controllers_map = _collect_controllers(values)      # {ctrl_id: {containers}}
    controller_ids = set(controllers_map)
    services_map = _collect_services(values)            # {svc_id: {port names}}
    issues.extend(_check_service_controller_refs(values, controller_ids))
    issues.extend(_check_ingress_service_refs(values, services_map))
    issues.extend(_check_persistence_mount_refs(values, controllers_map))
    # networkpolicies references a controller via a bare-string `controller:`
    # key. HPA and podMonitor use different shapes in v5 and are handled by
    # their own dedicated checks below.
    for block_key in ('networkpolicies',):
        issues.extend(_check_controller_ref_block(values, block_key, controller_ids))
    issues.extend(_check_top_level_hpa_key(values))
    issues.extend(_check_controller_hpa_replicas_null(values))
    issues.extend(_check_podmonitor_refs(values, controller_ids))
    issues.extend(_check_servicemonitor_refs(values, services_map))
    issues.extend(_check_env_valuefrom_identifier(values))

    return issues


def output_json(issues: List[Issue], chart_path: Path) -> None:
    """
    Print issues as a JSON report to stdout.

    Parameters
    ----------
    issues : List[Issue]
        All detected issues.
    chart_path : Path
        Chart directory that was validated.
    """
    errors = [i for i in issues if i.severity == 'error']
    warnings = [i for i in issues if i.severity == 'warning']
    infos = [i for i in issues if i.severity == 'info']

    report = {
        "chart": str(chart_path),
        "summary": {
            "errors": len(errors),
            "warnings": len(warnings),
            "suggestions": len(infos),
            "passed": len(errors) == 0,
        },
        "issues": [asdict(i) for i in issues],
    }
    print(json.dumps(report, indent=2))


def output_human(issues: List[Issue]) -> None:
    """
    Print issues in human-readable format to stdout.

    Parameters
    ----------
    issues : List[Issue]
        All detected issues.
    """
    if not issues:
        print("✅ No issues found! Chart structure looks good.")
        return

    errors = [i for i in issues if i.severity == 'error']
    warnings = [i for i in issues if i.severity == 'warning']
    infos = [i for i in issues if i.severity == 'info']

    if errors:
        print("🔴 Errors:")
        for issue in errors:
            print(f"  {issue}\n")

    if warnings:
        print("🟡 Warnings:")
        for issue in warnings:
            print(f"  {issue}\n")

    if infos:
        print("🔵 Suggestions:")
        for issue in infos:
            print(f"  {issue}\n")

    print(f"\nTotal: {len(errors)} errors, {len(warnings)} warnings, {len(infos)} suggestions")


def main() -> None:
    """Entry point — parse arguments and run validation."""
    parser = argparse.ArgumentParser(
        description='Validate a Helm chart using the bjw-s common library.'
    )
    parser.add_argument('chart_path', help='Path to the chart directory')
    parser.add_argument(
        '--json',
        action='store_true',
        dest='json_output',
        help='Output results as JSON (useful for CI pipelines)'
    )
    args = parser.parse_args()

    chart_path = Path(args.chart_path)

    if not chart_path.exists():
        print(f"Error: Path not found: {chart_path}", file=sys.stderr)
        sys.exit(1)

    if not chart_path.is_dir():
        print(f"Error: Path is not a directory: {chart_path}", file=sys.stderr)
        sys.exit(1)

    if not args.json_output:
        print(f"\n📋 Validating Helm chart at {chart_path}\n")

    # Collect all issues
    issues: List[Issue] = []
    issues.extend(validate_chart_yaml(chart_path))
    issues.extend(validate_templates(chart_path))
    issues.extend(validate_values(chart_path))

    if args.json_output:
        output_json(issues, chart_path)
    else:
        output_human(issues)

    errors = [i for i in issues if i.severity == 'error']
    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
