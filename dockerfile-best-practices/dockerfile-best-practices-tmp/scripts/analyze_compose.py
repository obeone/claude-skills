#!/usr/bin/env python3
"""
Docker Compose analyzer - Detects common anti-patterns and suggests improvements.

Usage:
    python analyze_compose.py <path_to_compose_file>
"""

import sys
import re
from pathlib import Path
from typing import List
import yaml


class Issue:
    """Represents a detected issue in the Compose file."""

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


def analyze_compose(compose_data: dict, filename: str) -> List[Issue]:
    """Analyze Compose file content and return list of issues."""
    issues = []

    # Check for deprecated version field
    if 'version' in compose_data:
        issues.append(Issue(
            'Root',
            'warning',
            'Deprecated "version:" field found',
            'Remove "version:" field - it\'s deprecated since Compose V2. Use Compose Specification instead.'
        ))

    # Check services
    if 'services' not in compose_data:
        issues.append(Issue(
            'Root',
            'error',
            'No "services:" section found',
            'Compose file must have a "services:" section'
        ))
        return issues

    services = compose_data['services']

    for service_name, service_config in services.items():
        location = f'services.{service_name}'

        # Check for container_name
        if 'container_name' in service_config:
            issues.append(Issue(
                location,
                'warning',
                f'Using container_name: "{service_config["container_name"]}"',
                'Avoid container_name - it prevents scaling with --scale. Let Compose generate names automatically.'
            ))

        # Check for :latest tag
        if 'image' in service_config:
            image = service_config['image']
            if ':latest' in image or ':' not in image:
                issues.append(Issue(
                    location,
                    'error',
                    f'Using :latest or untagged image: "{image}"',
                    'Pin to specific version (e.g., myapp:1.2.3) for reproducible deployments'
                ))

        # Check for missing health check
        if 'healthcheck' not in service_config:
            # Only warn for long-running services (not one-off commands)
            if 'command' not in service_config or not any(word in str(service_config.get('command', ''))
                                                           for word in ['sleep', 'tail', 'watch']):
                issues.append(Issue(
                    location,
                    'info',
                    'No healthcheck defined',
                    'Add healthcheck for better service dependency management'
                ))

        # Check for missing restart policy
        if 'restart' not in service_config:
            issues.append(Issue(
                location,
                'info',
                'No restart policy defined',
                'Add "restart: unless-stopped" or appropriate policy'
            ))

        # Check for secrets in environment variables
        if 'environment' in service_config:
            env_vars = service_config['environment']
            if isinstance(env_vars, dict):
                env_items = env_vars.items()
            elif isinstance(env_vars, list):
                env_items = [(item.split('=')[0], item.split('=')[1] if '=' in item else '')
                             for item in env_vars]
            else:
                env_items = []

            for key, value in env_items:
                if any(secret_word in key.upper()
                       for secret_word in ['PASSWORD', 'SECRET', 'TOKEN', 'KEY', 'API_KEY']):
                    if value and not value.startswith('$'):  # Not an env var reference
                        issues.append(Issue(
                            f'{location}.environment.{key}',
                            'error',
                            f'Potential secret in environment variable: {key}',
                            'Use secrets or env_file instead. Never commit secrets to version control.'
                        ))

        # Check for missing resource limits
        if 'deploy' not in service_config or 'resources' not in service_config.get('deploy', {}):
            issues.append(Issue(
                location,
                'info',
                'No resource limits defined',
                'Add deploy.resources.limits to prevent resource exhaustion'
            ))

        # Check for privileged mode
        if service_config.get('privileged'):
            issues.append(Issue(
                location,
                'warning',
                'Service runs in privileged mode',
                'Avoid privileged mode unless absolutely necessary for security'
            ))

        # Check for network_mode: host
        if service_config.get('network_mode') == 'host':
            issues.append(Issue(
                location,
                'warning',
                'Using network_mode: host',
                'Prefer bridge networks for better isolation'
            ))

    # Check for unused volumes
    if 'volumes' in compose_data:
        defined_volumes = set(compose_data['volumes'].keys())
        used_volumes = set()

        for service_config in services.values():
            if 'volumes' in service_config:
                for volume in service_config['volumes']:
                    if isinstance(volume, str):
                        # Named volume format: "volume_name:/path"
                        if ':' in volume:
                            vol_name = volume.split(':')[0]
                            if not vol_name.startswith('.') and not vol_name.startswith('/'):
                                used_volumes.add(vol_name)
                    elif isinstance(volume, dict) and 'source' in volume:
                        used_volumes.add(volume['source'])

        unused = defined_volumes - used_volumes
        if unused:
            issues.append(Issue(
                'volumes',
                'info',
                f'Unused volumes defined: {", ".join(unused)}',
                'Remove unused volume definitions'
            ))

    return issues


def main():
    if len(sys.argv) != 2:
        print("Usage: analyze_compose.py <path_to_compose_file>")
        sys.exit(1)

    compose_path = Path(sys.argv[1])

    if not compose_path.exists():
        print(f"Error: File not found: {compose_path}")
        sys.exit(1)

    try:
        with open(compose_path, 'r') as f:
            compose_data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"Error: Invalid YAML in {compose_path}")
        print(f"  {e}")
        sys.exit(1)

    issues = analyze_compose(compose_data, compose_path.name)

    if not issues:
        print("✅ No issues found! Compose file looks good.")
        return

    # Group by severity
    errors = [i for i in issues if i.severity == 'error']
    warnings = [i for i in issues if i.severity == 'warning']
    infos = [i for i in issues if i.severity == 'info']

    print(f"\n📋 Analysis of {compose_path}\n")

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
