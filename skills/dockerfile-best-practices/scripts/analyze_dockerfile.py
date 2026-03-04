#!/usr/bin/env python3
"""
Dockerfile analyzer - Detects common anti-patterns and suggests improvements.

Usage:
    python analyze_dockerfile.py <path_to_Dockerfile>
    python analyze_dockerfile.py <path_to_Dockerfile> --json
"""

import sys
import re
import json
from pathlib import Path
from typing import List


class Issue:
    """Represents a detected issue in the Dockerfile."""

    def __init__(self, line_num: int, severity: str, rule: str, message: str, suggestion: str = ""):
        self.line_num = line_num
        self.severity = severity  # 'error', 'warning', 'info'
        self.rule = rule
        self.message = message
        self.suggestion = suggestion

    def __str__(self):
        icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}[self.severity]
        result = f"{icon} Line {self.line_num} [{self.rule}]: {self.message}"
        if self.suggestion:
            result += f"\n   → {self.suggestion}"
        return result

    def to_dict(self):
        return {
            "line": self.line_num,
            "severity": self.severity,
            "rule": self.rule,
            "message": self.message,
            "suggestion": self.suggestion,
        }


def _join_continuations(lines: list[str]) -> list[tuple[int, str]]:
    """Join backslash-continued lines into logical instructions.
    Returns list of (first_line_number, joined_instruction)."""
    result = []
    current = ""
    start_line = 1

    for i, line in enumerate(lines, 1):
        stripped = line.rstrip()
        if not current:
            start_line = i

        if stripped.endswith("\\"):
            current += stripped[:-1] + " "
        else:
            current += stripped
            if current.strip():
                result.append((start_line, current))
            current = ""

    if current.strip():
        result.append((start_line, current))

    return result


def analyze_dockerfile(content: str) -> List[Issue]:
    """Analyze Dockerfile content and return list of issues."""
    issues = []
    lines = content.split("\n")
    logical_lines = _join_continuations(lines)

    has_user = False
    has_healthcheck = False
    has_label = False
    has_expose = False
    from_count = 0
    last_from_line = 0
    uses_apt = False
    has_apt_cache_config = False
    has_copy_chown_issue = False

    # Check for syntax directive
    first_non_empty = next((l for l in lines if l.strip()), "")
    if not first_non_empty.strip().startswith("# syntax="):
        issues.append(Issue(
            1, "warning", "DL001",
            "Missing BuildKit syntax directive",
            "Add as first line: # syntax=docker/dockerfile:1"
        ))

    for line_num, instruction in logical_lines:
        stripped = instruction.strip()

        # Skip comments and empty lines
        if not stripped or stripped.startswith("#"):
            continue

        upper = stripped.upper()

        # --- FROM checks ---
        if upper.startswith("FROM "):
            from_count += 1
            last_from_line = line_num

            # Check for :latest tag
            if re.search(r"FROM\s+[\w./-]+:latest", stripped, re.IGNORECASE):
                issues.append(Issue(
                    line_num, "error", "DL002",
                    "Using :latest tag on base image",
                    "Pin to specific version (e.g., python:3.12-slim)"
                ))

            # Check for untagged image (implies :latest)
            from_match = re.match(r"FROM\s+([\w./-]+)(\s|$)", stripped)
            if from_match:
                image = from_match.group(1)
                if ":" not in image and "@" not in image and image not in ("scratch",):
                    issues.append(Issue(
                        line_num, "warning", "DL003",
                        f"Untagged base image '{image}' (implies :latest)",
                        "Pin to specific version"
                    ))

            # Check for OS version pinning
            os_versions = r"(bookworm|bullseye|buster|jammy|focal|bionic|noble)"
            os_match = re.search(os_versions, stripped, re.IGNORECASE)
            if os_match:
                issues.append(Issue(
                    line_num, "warning", "DL004",
                    f"Base image pins OS version ({os_match.group(1)})",
                    "Use version without OS release (e.g., python:3.12-slim instead of python:3.12-slim-bookworm)"
                ))

            # Check for pinned alpine minor version
            alpine_pin = re.search(r"alpine:3\.\d+", stripped)
            if alpine_pin:
                issues.append(Issue(
                    line_num, "info", "DL005",
                    f"Base image pins Alpine minor version ({alpine_pin.group()})",
                    "Consider alpine:3 for automatic patch updates"
                ))

        # --- ADD checks ---
        if upper.startswith("ADD "):
            # Allow ADD for URLs and tar extraction explicitly
            if not re.search(r"ADD\s+(https?://|.*\.tar)", stripped):
                issues.append(Issue(
                    line_num, "warning", "DL006",
                    "Using ADD instead of COPY",
                    "Use COPY unless you specifically need URL download or tar extraction"
                ))

        # --- RUN checks ---
        if upper.startswith("RUN "):
            # apt-get tracking
            if "apt-get" in stripped:
                uses_apt = True

            # apt-get install without cleanup (only if no cache mount)
            if "apt-get install" in stripped and "--mount=type=cache" not in stripped:
                if "rm -rf /var/lib/apt/lists" not in stripped:
                    issues.append(Issue(
                        line_num, "warning", "DL007",
                        "apt-get install without cleanup or cache mount",
                        "Use --mount=type=cache or add && rm -rf /var/lib/apt/lists/*"
                    ))

            # Missing cache mounts for package managers
            pkg_managers = [
                ("pip install", "/root/.cache/pip", "DL008"),
                ("pip3 install", "/root/.cache/pip", "DL008"),
                ("npm install", "/root/.npm", "DL009"),
                ("npm ci", "/root/.npm", "DL009"),
                ("yarn install", "/root/.yarn", "DL010"),
                ("yarn add", "/root/.yarn", "DL010"),
                ("go mod download", "/go/pkg/mod", "DL011"),
                ("go build", "/root/.cache/go-build", "DL011"),
                ("cargo build", "/usr/local/cargo/registry", "DL012"),
                ("composer install", "/tmp/cache", "DL013"),
                ("mvn ", "/root/.m2", "DL014"),
                ("gradle ", "/root/.gradle", "DL015"),
            ]

            for cmd, cache_target, rule in pkg_managers:
                if cmd in stripped and "--mount=type=cache" not in stripped:
                    issues.append(Issue(
                        line_num, "info", rule,
                        f"{cmd} without cache mount",
                        f"Add: --mount=type=cache,target={cache_target}"
                    ))

            # RUN cd instead of WORKDIR
            if re.match(r"RUN\s+cd\s+", stripped):
                issues.append(Issue(
                    line_num, "warning", "DL016",
                    "Using RUN cd instead of WORKDIR",
                    "Use: WORKDIR /path"
                ))

            # curl | sh anti-pattern
            if re.search(r"curl.*\|\s*(ba)?sh", stripped):
                issues.append(Issue(
                    line_num, "warning", "DL017",
                    "Piping curl to shell (curl | sh)",
                    "Download first, verify checksum, then execute for security"
                ))

            # apt-get upgrade
            if "apt-get upgrade" in stripped or "apt-get dist-upgrade" in stripped:
                issues.append(Issue(
                    line_num, "warning", "DL018",
                    "Running apt-get upgrade in Dockerfile",
                    "Use a newer base image instead of upgrading inside the container"
                ))

            # apt-get without --no-install-recommends
            if "apt-get install" in stripped and "--no-install-recommends" not in stripped:
                issues.append(Issue(
                    line_num, "info", "DL019",
                    "apt-get install without --no-install-recommends",
                    "Add --no-install-recommends to reduce image size"
                ))

            # Check for apt cache config
            if "docker-clean" in stripped or "Keep-Downloaded-Packages" in stripped:
                has_apt_cache_config = True

        # --- ARG/ENV secret checks ---
        if re.search(r"(ARG|ENV)\s+(.*?(PASSWORD|SECRET|TOKEN|KEY|CREDENTIAL|API_KEY))", stripped, re.IGNORECASE):
            # Exclude common non-secret patterns
            if not re.search(r"(GPG_KEY|KEYRING|KEY_FILE|KEYBOARD|KEYMAP)", stripped, re.IGNORECASE):
                issues.append(Issue(
                    line_num, "error", "DL020",
                    "Potential secret in ARG/ENV",
                    "Use: RUN --mount=type=secret,id=mysecret"
                ))

        # --- USER checks ---
        if upper.startswith("USER "):
            if "root" in stripped.lower().split()[-1]:
                issues.append(Issue(
                    line_num, "warning", "DL021",
                    "Explicitly setting USER root",
                    "Create and use a non-root user for security"
                ))
            else:
                has_user = True

        # --- UID/GID checks ---
        uid_match = re.search(r"(useradd|adduser).*?-u\s+(\d+)", stripped)
        if uid_match:
            uid = int(uid_match.group(2))
            if uid < 10000:
                issues.append(Issue(
                    line_num, "warning", "DL022",
                    f"User created with UID {uid} (< 10000)",
                    "Use UID >10000 to avoid conflicts with host system users"
                ))

        gid_match = re.search(r"(groupadd|addgroup).*?-g\s+(\d+)", stripped)
        if gid_match:
            gid = int(gid_match.group(2))
            if gid < 10000:
                issues.append(Issue(
                    line_num, "warning", "DL023",
                    f"Group created with GID {gid} (< 10000)",
                    "Use GID >10000 to avoid conflicts with host system users"
                ))

        # --- COPY then chown anti-pattern ---
        if upper.startswith("COPY ") and "--chown" not in stripped:
            # Check if next logical instruction is RUN chown
            idx = next((j for j, (_, inst) in enumerate(logical_lines)
                        if inst.strip().startswith(f"RUN ") and "chown" in inst
                        and logical_lines[j-1][1].strip() == stripped), None)
            if idx is not None:
                has_copy_chown_issue = True

        # --- HEALTHCHECK ---
        if upper.startswith("HEALTHCHECK "):
            has_healthcheck = True

        # --- LABEL ---
        if upper.startswith("LABEL "):
            has_label = True

        # --- EXPOSE ---
        if upper.startswith("EXPOSE "):
            has_expose = True

        # --- WORKDIR without absolute path ---
        if upper.startswith("WORKDIR "):
            path = stripped.split(None, 1)[1] if len(stripped.split(None, 1)) > 1 else ""
            if path and not path.startswith("/") and not path.startswith("$"):
                issues.append(Issue(
                    line_num, "warning", "DL024",
                    f"WORKDIR uses relative path: {path}",
                    "Use absolute paths for WORKDIR"
                ))

        # --- ENTRYPOINT/CMD exec form check ---
        for directive in ("ENTRYPOINT", "CMD"):
            if upper.startswith(f"{directive} "):
                value = stripped[len(directive):].strip()
                if value and not value.startswith("["):
                    issues.append(Issue(
                        line_num, "info", "DL025",
                        f"{directive} uses shell form",
                        f"Prefer exec form: {directive} [\"executable\", \"arg1\"] for proper signal handling"
                    ))

    # --- Global checks ---

    # No non-root USER defined
    if not has_user:
        issues.append(Issue(
            len(lines), "warning", "DL030",
            "No non-root USER defined",
            "Add: RUN groupadd -r -g 10001 app && useradd -r -u 10001 -g app app && USER app"
        ))

    # No HEALTHCHECK (only if EXPOSE is present - likely a service)
    if not has_healthcheck and has_expose:
        issues.append(Issue(
            len(lines), "info", "DL031",
            "Service exposes ports but has no HEALTHCHECK",
            "Add HEALTHCHECK for container orchestration and monitoring"
        ))

    # No LABEL
    if not has_label:
        issues.append(Issue(
            len(lines), "info", "DL032",
            "No LABEL defined",
            "Add OCI labels: org.opencontainers.image.source, .description, .version"
        ))

    # Uses apt but no cache config
    if uses_apt and not has_apt_cache_config:
        # Check if cache mounts are used
        has_apt_cache_mount = any("--mount=type=cache" in inst and "apt" in inst
                                  for _, inst in logical_lines)
        if has_apt_cache_mount:
            issues.append(Issue(
                1, "warning", "DL033",
                "APT cache mount used without configuring APT to keep packages",
                "Add before apt operations: RUN rm -f /etc/apt/apt.conf.d/docker-clean; "
                "echo 'Binary::apt::APT::Keep-Downloaded-Packages \"true\";' > /etc/apt/apt.conf.d/keep-cache"
            ))

    # COPY then chown pattern
    if has_copy_chown_issue:
        issues.append(Issue(
            0, "info", "DL034",
            "COPY followed by RUN chown detected",
            "Use COPY --chown=user:group instead to avoid doubling the layer size"
        ))

    return issues


def main():
    json_output = "--json" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--json"]

    if len(args) != 1:
        print("Usage: analyze_dockerfile.py <path_to_Dockerfile> [--json]")
        sys.exit(1)

    dockerfile_path = Path(args[0])

    if not dockerfile_path.exists():
        print(f"Error: File not found: {dockerfile_path}")
        sys.exit(1)

    content = dockerfile_path.read_text()
    issues = analyze_dockerfile(content)

    if json_output:
        result = {
            "file": str(dockerfile_path),
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
        print("✅ No issues found! Dockerfile looks good.")
        return

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    infos = [i for i in issues if i.severity == "info"]

    print(f"\n📋 Analysis of {dockerfile_path}\n")

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
