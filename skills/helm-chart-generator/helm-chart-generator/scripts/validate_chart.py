#!/usr/bin/env python3
"""
Helm Chart Validator for bjw-s common library charts.

Usage:
    python validate_chart.py <path-to-chart>
"""

import sys
import yaml
from pathlib import Path
from typing import List, Dict, Any


class Issue:
    """Represents a detected issue in the chart."""
    
    def __init__(self, location: str, severity: str, message: str, suggestion: str = ""):
        self.location = location
        self.severity = severity  # 'error', 'warning', 'info'
        self.message = message
        self.suggestion = suggestion
    
    def __str__(self):
        icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}[self.severity]
        result = f"{icon} {self.location}: {self.message}"
        if self.suggestion:
            result += f"\n   → {self.suggestion}"
        return result


def validate_chart_yaml(chart_path: Path) -> List[Issue]:
    """Validate Chart.yaml structure."""
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
    for field in required:
        if field not in chart:
            issues.append(Issue(
                'Chart.yaml',
                'error',
                f'Missing required field: {field}',
                f'Add {field} to Chart.yaml'
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
                break
        
        if not common_found:
            issues.append(Issue(
                'Chart.yaml',
                'error',
                'bjw-s common library not found in dependencies',
                'Add common library dependency'
            ))
    
    return issues


def validate_templates(chart_path: Path) -> List[Issue]:
    """Validate templates directory."""
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


def validate_values(chart_path: Path) -> List[Issue]:
    """Validate values.yaml structure."""
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
                elif image.get('tag') == 'latest':
                    issues.append(Issue(
                        f'{cont_location}.image',
                        'warning',
                        'Using :latest tag',
                        'Use specific version tag for reproducibility'
                    ))
            
            # Check probes
            if 'probes' in container_config:
                probes = container_config['probes']
                for probe_type in ['liveness', 'readiness', 'startup']:
                    if probe_type in probes:
                        probe = probes[probe_type]
                        if probe.get('enabled') and not probe.get('custom'):
                            if 'type' not in probe:
                                issues.append(Issue(
                                    f'{cont_location}.probes.{probe_type}',
                                    'info',
                                    'Probe type not specified',
                                    'Add type: HTTP, TCP, or EXEC'
                                ))
    
    # Check services
    if 'service' in values:
        services = values['service']
        for svc_name, svc_config in services.items():
            location = f'service.{svc_name}'
            
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
            
            # Validate service references
            for host in ing_config['hosts']:
                if 'paths' in host:
                    for path in host['paths']:
                        if 'service' in path:
                            svc = path['service']
                            if 'identifier' not in svc and 'name' not in svc:
                                issues.append(Issue(
                                    location,
                                    'error',
                                    'Service reference missing identifier or name',
                                    'Use identifier: <service-identifier> or name: <service-name>'
                                ))
    
    # Check persistence
    if 'persistence' in values:
        persistence = values['persistence']
        for vol_name, vol_config in persistence.items():
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
    
    return issues


def main():
    if len(sys.argv) != 2:
        print("Usage: validate_chart.py <path-to-chart>")
        sys.exit(1)
    
    chart_path = Path(sys.argv[1])
    
    if not chart_path.exists():
        print(f"Error: Path not found: {chart_path}")
        sys.exit(1)
    
    if not chart_path.is_dir():
        print(f"Error: Path is not a directory: {chart_path}")
        sys.exit(1)
    
    print(f"\n📋 Validating Helm chart at {chart_path}\n")
    
    # Collect all issues
    issues = []
    issues.extend(validate_chart_yaml(chart_path))
    issues.extend(validate_templates(chart_path))
    issues.extend(validate_values(chart_path))
    
    if not issues:
        print("✅ No issues found! Chart structure looks good.")
        return
    
    # Group by severity
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
    
    # Exit with error code if errors found
    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
