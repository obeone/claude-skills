#!/usr/bin/env python3
"""
Docker Compose analyzer - Detects common anti-patterns and suggests improvements.

Usage:
    python analyze_compose.py <path_to_compose_file>
    python analyze_compose.py <path_to_compose_file> --json
"""

import sys
import re
import json
from pathlib import Path
from typing import List

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Install with: pip install pyyaml")
    sys.exit(1)


class Issue:
    """Represents a detected issue in the Compose file."""

    def __init__(self, location: str, severity: str, rule: str, message: str, suggestion: str = ""):
        self.location = location
        self.severity = severity
        self.rule = rule
        self.message = message
        self.suggestion = suggestion

    def __str__(self):
        icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}[self.severity]
        result = f"{icon} {self.location} [{self.rule}]: {self.message}"
        if self.suggestion:
            result += f"\n   → {self.suggestion}"
        return result

    def to_dict(self):
        return {
            "location": self.location,
            "severity": self.severity,
            "rule": self.rule,
            "message": self.message,
            "suggestion": self.suggestion,
        }


def analyze_compose(compose_data: dict, filename: str) -> List[Issue]:
    """Analyze Compose file content and return list of issues."""
    issues = []

    if not isinstance(compose_data, dict):
        issues.append(Issue("Root", "error", "DC001", "Invalid Compose file structure"))
        return issues

    # Check for deprecated version field
    if "version" in compose_data:
        issues.append(Issue(
            "Root", "warning", "DC002",
            f'Deprecated "version: \'{compose_data["version"]}\'" field found',
            "Remove the version field - deprecated since Compose V2. Use Compose Specification."
        ))

    # Check services
    if "services" not in compose_data:
        issues.append(Issue(
            "Root", "error", "DC003",
            'No "services:" section found',
            "Compose file must have a services: section"
        ))
        return issues

    services = compose_data.get("services", {})
    if not isinstance(services, dict):
        issues.append(Issue("Root", "error", "DC003", "services: must be a mapping"))
        return issues

    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue
        loc = f"services.{service_name}"

        # --- CRITICAL: container_name ---
        if "container_name" in service_config:
            issues.append(Issue(
                loc, "error", "DC010",
                f'Using container_name: "{service_config["container_name"]}"',
                "NEVER use container_name - prevents scaling with --scale and breaks parallel environments. "
                "Use project names: docker compose -p myapp-dev up"
            ))

        # --- CRITICAL: links (deprecated) ---
        if "links" in service_config:
            issues.append(Issue(
                loc, "warning", "DC011",
                "Using deprecated 'links:' directive",
                "Remove links: and use networks instead. Services on the same network can reach each other by service name."
            ))

        # --- Image tag checks ---
        if "image" in service_config:
            image = service_config["image"]
            if isinstance(image, str):
                if ":latest" in image:
                    issues.append(Issue(
                        loc, "error", "DC012",
                        f'Using :latest tag: "{image}"',
                        "Pin to specific version (e.g., myapp:1.2.3)"
                    ))
                elif ":" not in image and "@" not in image:
                    issues.append(Issue(
                        loc, "warning", "DC013",
                        f'Untagged image: "{image}" (implies :latest)',
                        "Pin to specific version"
                    ))

        # --- Health check ---
        if "healthcheck" not in service_config:
            issues.append(Issue(
                loc, "info", "DC014",
                "No healthcheck defined",
                "Add healthcheck for service dependency management"
            ))

        # --- depends_on without condition ---
        if "depends_on" in service_config:
            deps = service_config["depends_on"]
            if isinstance(deps, list):
                issues.append(Issue(
                    loc, "warning", "DC015",
                    "depends_on without condition (bare list form)",
                    "Use depends_on with condition: service_healthy for reliable startup ordering"
                ))
            elif isinstance(deps, dict):
                for dep_name, dep_config in deps.items():
                    if isinstance(dep_config, dict) and "condition" not in dep_config:
                        issues.append(Issue(
                            f"{loc}.depends_on.{dep_name}", "warning", "DC015",
                            f"depends_on.{dep_name} without condition",
                            "Add condition: service_healthy"
                        ))

        # --- Restart policy ---
        if "restart" not in service_config:
            issues.append(Issue(
                loc, "info", "DC016",
                "No restart policy defined",
                "Add restart: unless-stopped (or appropriate policy)"
            ))

        # --- Secrets in environment ---
        if "environment" in service_config:
            env_vars = service_config["environment"]
            if isinstance(env_vars, dict):
                env_items = list(env_vars.items())
            elif isinstance(env_vars, list):
                env_items = []
                for item in env_vars:
                    if isinstance(item, str) and "=" in item:
                        key, _, value = item.partition("=")
                        env_items.append((key, value))
            else:
                env_items = []

            secret_words = {"PASSWORD", "SECRET", "TOKEN", "API_KEY", "CREDENTIAL", "PRIVATE_KEY"}
            for key, value in env_items:
                if any(sw in key.upper() for sw in secret_words):
                    if value and not str(value).startswith("$") and not str(value).endswith("_FILE"):
                        issues.append(Issue(
                            f"{loc}.environment.{key}", "error", "DC017",
                            f"Potential hardcoded secret: {key}",
                            "Use Docker secrets or env_file. Never commit secrets to version control."
                        ))

        # --- Resource limits ---
        deploy = service_config.get("deploy", {})
        if not isinstance(deploy, dict) or "resources" not in deploy:
            issues.append(Issue(
                loc, "info", "DC018",
                "No resource limits defined",
                "Add deploy.resources.limits to prevent resource exhaustion"
            ))

        # --- Privileged mode ---
        if service_config.get("privileged"):
            issues.append(Issue(
                loc, "warning", "DC019",
                "Service runs in privileged mode",
                "Avoid privileged mode; use specific capabilities with cap_add instead"
            ))

        # --- network_mode: host ---
        if service_config.get("network_mode") == "host":
            issues.append(Issue(
                loc, "warning", "DC020",
                "Using network_mode: host",
                "Prefer bridge networks for better isolation"
            ))

        # --- Build with no image tag ---
        if "build" in service_config and "image" not in service_config:
            issues.append(Issue(
                loc, "info", "DC021",
                "build: without image: tag",
                "Add image: with version tag so built image is properly tagged"
            ))

        # --- Bind mount without :ro ---
        if "volumes" in service_config:
            for vol in service_config["volumes"]:
                if isinstance(vol, str) and vol.startswith("./"):
                    if ":ro" not in vol and ":rw" not in vol:
                        issues.append(Issue(
                            f"{loc}.volumes", "info", "DC022",
                            f"Bind mount without explicit mode: {vol}",
                            "Consider adding :ro for read-only bind mounts in production"
                        ))

        # --- ports: using host port binding ---
        if "ports" in service_config:
            for port in service_config["ports"]:
                port_str = str(port)
                if ":" in port_str:
                    host_port = port_str.split(":")[0]
                    if host_port and not host_port.startswith("$"):
                        # Check for privileged ports
                        try:
                            if int(host_port) < 1024:
                                issues.append(Issue(
                                    f"{loc}.ports", "info", "DC023",
                                    f"Binding to privileged port {host_port}",
                                    "Consider using a non-privileged port (>1024) with a reverse proxy"
                                ))
                        except ValueError:
                            pass

    # --- Check for unused volumes ---
    if "volumes" in compose_data and isinstance(compose_data["volumes"], dict):
        defined_volumes = set(compose_data["volumes"].keys())
        used_volumes = set()

        for service_config in services.values():
            if not isinstance(service_config, dict):
                continue
            if "volumes" in service_config:
                for volume in service_config["volumes"]:
                    if isinstance(volume, str) and ":" in volume:
                        vol_name = volume.split(":")[0]
                        if not vol_name.startswith(".") and not vol_name.startswith("/"):
                            used_volumes.add(vol_name)
                    elif isinstance(volume, dict) and "source" in volume:
                        used_volumes.add(volume["source"])

        unused = defined_volumes - used_volumes
        if unused:
            issues.append(Issue(
                "volumes", "info", "DC030",
                f'Unused volumes defined: {", ".join(sorted(unused))}',
                "Remove unused volume definitions"
            ))

    # --- Check for unused networks ---
    if "networks" in compose_data and isinstance(compose_data["networks"], dict):
        defined_networks = set(compose_data["networks"].keys())
        used_networks = set()

        for service_config in services.values():
            if not isinstance(service_config, dict):
                continue
            if "networks" in service_config:
                nets = service_config["networks"]
                if isinstance(nets, list):
                    used_networks.update(nets)
                elif isinstance(nets, dict):
                    used_networks.update(nets.keys())

        unused = defined_networks - used_networks
        if unused:
            issues.append(Issue(
                "networks", "info", "DC031",
                f'Unused networks defined: {", ".join(sorted(unused))}',
                "Remove unused network definitions"
            ))

    return issues


def main():
    json_output = "--json" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--json"]

    if len(args) != 1:
        print("Usage: analyze_compose.py <path_to_compose_file> [--json]")
        sys.exit(1)

    compose_path = Path(args[0])

    if not compose_path.exists():
        print(f"Error: File not found: {compose_path}")
        sys.exit(1)

    try:
        with open(compose_path, "r") as f:
            compose_data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"Error: Invalid YAML in {compose_path}")
        print(f"  {e}")
        sys.exit(1)

    if compose_data is None:
        print(f"Error: Empty file: {compose_path}")
        sys.exit(1)

    issues = analyze_compose(compose_data, compose_path.name)

    if json_output:
        result = {
            "file": str(compose_path),
            "issues": [i.to_dict() for i in issues],
            "summary": {
                "errors": len([i for i in issues if i.severity == "error"]),
                "warnings": len([i for i in issues if i.severity == "warning"]),
                "info": len([i for i in issues if i.severity == "info"]),
            }
        }
        print(json.dumps(result, indent=2))
        sys.exit(1 if result["summary"]["errors"] else 0)

    if not issues:
        print("✅ No issues found! Compose file looks good.")
        return

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    infos = [i for i in issues if i.severity == "info"]

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

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
