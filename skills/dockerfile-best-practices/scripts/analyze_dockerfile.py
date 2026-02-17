#!/usr/bin/env python3
"""
Dockerfile analyzer - Detects common anti-patterns and suggests improvements.

Usage:
    python analyze_dockerfile.py <path_to_Dockerfile>
"""

import sys
import re
from pathlib import Path
from typing import List, Tuple


class Issue:
    """Represents a detected issue in the Dockerfile."""
    
    def __init__(self, line_num: int, severity: str, message: str, suggestion: str = ""):
        self.line_num = line_num
        self.severity = severity  # 'error', 'warning', 'info'
        self.message = message
        self.suggestion = suggestion
    
    def __str__(self):
        icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}[self.severity]
        result = f"{icon} Line {self.line_num}: {self.message}"
        if self.suggestion:
            result += f"\n   → {self.suggestion}"
        return result


def _join_continuation_lines(lines: List[str]) -> List[Tuple[int, str]]:
    """
    Join backslash-continued lines into logical instructions.

    Returns a list of (first_line_number, joined_content) tuples.
    Line numbers are 1-based to match editor display.
    """
    logical: List[Tuple[int, str]] = []
    current = ""
    start_line = 1
    for i, raw in enumerate(lines, 1):
        stripped = raw.rstrip()
        if not current:
            start_line = i
        if stripped.endswith("\\"):
            current += stripped[:-1] + " "
        else:
            current += stripped
            logical.append((start_line, current))
            current = ""
    if current:
        logical.append((start_line, current))
    return logical


def analyze_dockerfile(content: str) -> List[Issue]:
    """
    Analyze Dockerfile content and return list of issues.

    Parameters
    ----------
    content : str
        Raw Dockerfile content as a string.

    Returns
    -------
    List[Issue]
        List of detected issues sorted by line number.
    """
    issues = []
    lines = content.split('\n')
    logical_lines = _join_continuation_lines(lines)

    # Track SHELL instruction and counts
    has_pipefail = False
    cmd_count = 0
    entrypoint_count = 0

    # Check for syntax directive
    if not lines[0].strip().startswith('# syntax='):
        issues.append(Issue(
            1, 'warning',
            'Missing BuildKit syntax directive',
            'Add: # syntax=docker/dockerfile:1'
        ))

    for line_num, joined in logical_lines:
        stripped = joined.strip()

        # Skip comments and empty lines
        if not stripped or stripped.startswith('#'):
            continue

        # Track SHELL pipefail
        if stripped.startswith('SHELL ') and 'pipefail' in stripped:
            has_pipefail = True

        # --- MAINTAINER deprecated ---
        if stripped.startswith('MAINTAINER '):
            issues.append(Issue(
                line_num, 'warning',
                'MAINTAINER is deprecated',
                'Use: LABEL org.opencontainers.image.authors="name <email>"'
            ))

        # --- Check for ADD instead of COPY ---
        if stripped.startswith('ADD '):
            issues.append(Issue(
                line_num, 'warning',
                'Using ADD instead of COPY',
                'Use COPY unless you need URL download or tar extraction'
            ))

        # --- Check for latest tag ---
        if re.search(r'FROM\s+[\w./-]+:latest', stripped, re.IGNORECASE):
            issues.append(Issue(
                line_num, 'error',
                'Using :latest tag',
                'Pin to specific version (e.g., alpine:3 or python:3.12-slim)'
            ))

        # --- FROM checks ---
        if stripped.startswith('FROM '):
            # OS version pinning
            os_versions = r'(bookworm|bullseye|buster|jammy|focal|bionic|alpine:3\.\d+)'
            match = re.search(os_versions, stripped, re.IGNORECASE)
            if match:
                issues.append(Issue(
                    line_num, 'warning',
                    f'Base image pins OS version ({match.group(1)})',
                    'Consider using version tag without OS release (e.g., python:3.12-slim instead of python:3.12-slim-bookworm) for automatic security updates'
                ))

        # --- WORKDIR relative path ---
        workdir_match = re.match(r'WORKDIR\s+(\S+)', stripped)
        if workdir_match:
            wd_path = workdir_match.group(1)
            if not wd_path.startswith('/') and not wd_path.startswith('$'):
                issues.append(Issue(
                    line_num, 'warning',
                    f'Relative WORKDIR "{wd_path}"',
                    'Use absolute paths for WORKDIR to avoid confusion'
                ))

        # --- EXPOSE 22 (SSH anti-pattern) ---
        if re.match(r'EXPOSE\s+22\b', stripped):
            issues.append(Issue(
                line_num, 'warning',
                'Exposing port 22 (SSH) is a container anti-pattern',
                'Use docker exec or kubectl exec instead of SSH into containers'
            ))

        # --- Track CMD/ENTRYPOINT counts ---
        if re.match(r'CMD\s', stripped):
            cmd_count += 1
        if re.match(r'ENTRYPOINT\s', stripped):
            entrypoint_count += 1

        # --- Shell form ENTRYPOINT/CMD ---
        for instr in ('CMD', 'ENTRYPOINT'):
            pattern = rf'^{instr}\s+(?!\[)(.+)'
            match = re.match(pattern, stripped)
            if match:
                # Exclude common variable-only cases
                cmd_text = match.group(1).strip()
                if cmd_text and not cmd_text.startswith('['):
                    issues.append(Issue(
                        line_num, 'info',
                        f'{instr} uses shell form (no signal forwarding to PID 1)',
                        f'Use exec form: {instr} ["executable", "arg1", "arg2"]'
                    ))

        # --- apt-get checks ---
        if 'apt-get install' in stripped:
            # Missing cleanup
            if 'rm -rf /var/lib/apt/lists' not in stripped:
                if not any('rm -rf /var/lib/apt/lists' in lines[j]
                          for j in range(line_num, min(line_num + 10, len(lines)))):
                    issues.append(Issue(
                        line_num, 'warning',
                        'apt-get install without cleanup',
                        'Add: && rm -rf /var/lib/apt/lists/* in same RUN'
                    ))

            # Missing --no-install-recommends
            if '--no-install-recommends' not in stripped:
                issues.append(Issue(
                    line_num, 'info',
                    'apt-get install without --no-install-recommends',
                    'Add --no-install-recommends to avoid installing unnecessary packages'
                ))

        # --- apt-get upgrade/dist-upgrade ---
        if re.search(r'apt-get\s+(upgrade|dist-upgrade)', stripped):
            issues.append(Issue(
                line_num, 'warning',
                'apt-get upgrade/dist-upgrade in Dockerfile',
                'Use an up-to-date base image instead of upgrading inside the build'
            ))

        # --- apt (not apt-get) ---
        if re.search(r'\bapt\s+(install|update|remove|purge)\b', stripped):
            # Make sure it's not apt-get
            if 'apt-get' not in stripped:
                issues.append(Issue(
                    line_num, 'warning',
                    'Using "apt" instead of "apt-get"',
                    'apt CLI does not have a stable interface; use apt-get in Dockerfiles'
                ))

        # --- sudo in RUN ---
        if stripped.startswith('RUN ') and re.search(r'\bsudo\b', stripped):
            issues.append(Issue(
                line_num, 'warning',
                'Using sudo in RUN instruction',
                'Avoid sudo in Dockerfiles; run commands as root during build, then switch to non-root USER'
            ))

        # --- ARG/ENV with potential secrets ---
        if re.search(r'(ARG|ENV)\s+(.*?(PASSWORD|SECRET|TOKEN|KEY))', stripped, re.IGNORECASE):
            issues.append(Issue(
                line_num, 'error',
                'Potential secret in ARG/ENV',
                'Use: RUN --mount=type=secret,id=mysecret'
            ))

        # --- Missing cache mount on common package managers ---
        if stripped.startswith('RUN ') or '--mount' in stripped:
            run_content = stripped

            if 'pip install' in run_content and '--mount=type=cache' not in run_content:
                issues.append(Issue(
                    line_num, 'info',
                    'pip install without cache mount',
                    'Add: RUN --mount=type=cache,target=/root/.cache/pip'
                ))

            if ('npm install' in run_content or 'yarn install' in run_content) and '--mount=type=cache' not in run_content:
                issues.append(Issue(
                    line_num, 'info',
                    'npm/yarn install without cache mount',
                    'Add: RUN --mount=type=cache,target=/root/.npm'
                ))

            if 'apt-get' in run_content and '--mount=type=cache' not in run_content:
                issues.append(Issue(
                    line_num, 'info',
                    'apt-get without cache mount',
                    'Add: RUN --mount=type=cache,target=/var/cache/apt'
                ))

        # --- RUN cd instead of WORKDIR ---
        if stripped.startswith('RUN cd '):
            issues.append(Issue(
                line_num, 'warning',
                'Using RUN cd instead of WORKDIR',
                'Use: WORKDIR /path'
            ))

        # --- Pipes in RUN without pipefail ---
        if stripped.startswith('RUN ') and '|' in stripped and not has_pipefail:
            if 'set -o pipefail' not in stripped and 'pipefail' not in stripped:
                issues.append(Issue(
                    line_num, 'info',
                    'RUN with pipe but no pipefail set',
                    'Add SHELL ["/bin/bash", "-o", "pipefail", "-c"] or inline set -o pipefail'
                ))

        # --- Non-APT package managers without cleanup ---
        if stripped.startswith('RUN '):
            # yum/dnf without clean
            if re.search(r'\b(yum|dnf)\s+install\b', stripped):
                if 'clean all' not in stripped and 'clean all' not in ' '.join(
                    lines[line_num - 1:min(line_num + 5, len(lines))]
                ):
                    issues.append(Issue(
                        line_num, 'warning',
                        'yum/dnf install without cleanup',
                        'Add: && yum clean all (or dnf clean all) && rm -rf /var/cache/yum'
                    ))

            # apk without --no-cache
            if re.search(r'\bapk\s+add\b', stripped) and '--no-cache' not in stripped:
                issues.append(Issue(
                    line_num, 'warning',
                    'apk add without --no-cache',
                    'Add: apk add --no-cache to avoid storing the package index'
                ))

        # --- useradd without -l when UID >10000 ---
        if 'useradd' in stripped:
            uid_match = re.search(r'-u\s+(\d+)', stripped)
            if uid_match and int(uid_match.group(1)) > 10000 and ' -l' not in stripped:
                issues.append(Issue(
                    line_num, 'warning',
                    'useradd with high UID but without -l flag',
                    'Add -l to avoid creating a sparse lastlog file (can be several GB)'
                ))

        # --- Low UID/GID checks ---
        uid_pattern = r'(useradd|adduser).*?-u\s+(\d+)'
        gid_pattern = r'(groupadd|addgroup).*?-g\s+(\d+)'

        uid_match = re.search(uid_pattern, stripped)
        if uid_match:
            uid = int(uid_match.group(2))
            if uid < 10000:
                issues.append(Issue(
                    line_num, 'warning',
                    f'User created with UID {uid} (< 10000)',
                    'Consider using UID >10000 to avoid conflicts with host system users'
                ))

        gid_match = re.search(gid_pattern, stripped)
        if gid_match:
            gid = int(gid_match.group(2))
            if gid < 10000:
                issues.append(Issue(
                    line_num, 'warning',
                    f'Group created with GID {gid} (< 10000)',
                    'Consider using GID >10000 to avoid conflicts with host system users'
                ))

        # --- User creation without explicit UID/GID ---
        if re.search(r'(useradd|adduser|groupadd|addgroup)', stripped):
            if not re.search(r'-[ug]\s+\d+', stripped):
                issues.append(Issue(
                    line_num, 'info',
                    'User/group created without explicit UID/GID',
                    'Consider explicit UID/GID >10000 if consistent permissions across environments are needed'
                ))

        # --- USER root ---
        if stripped.startswith('USER root'):
            issues.append(Issue(
                line_num, 'warning',
                'Running as root user',
                'Create and use non-root user for security'
            ))

    # --- Multiple CMD/ENTRYPOINT ---
    if cmd_count > 1:
        issues.append(Issue(
            len(lines), 'warning',
            f'Multiple CMD instructions ({cmd_count}) — only the last one takes effect',
            'Keep only one CMD instruction'
        ))
    if entrypoint_count > 1:
        issues.append(Issue(
            len(lines), 'warning',
            f'Multiple ENTRYPOINT instructions ({entrypoint_count}) — only the last one takes effect',
            'Keep only one ENTRYPOINT instruction'
        ))

    # --- Check if USER is never set ---
    if not any(line.strip().startswith('USER ') and 'root' not in line.lower()
              for line in lines):
        issues.append(Issue(
            len(lines), 'warning',
            'No non-root USER defined',
            'Add: RUN adduser -D appuser && USER appuser'
        ))

    return issues


def main():
    if len(sys.argv) != 2:
        print("Usage: analyze_dockerfile.py <path_to_Dockerfile>")
        sys.exit(1)
    
    dockerfile_path = Path(sys.argv[1])
    
    if not dockerfile_path.exists():
        print(f"Error: File not found: {dockerfile_path}")
        sys.exit(1)
    
    content = dockerfile_path.read_text()
    issues = analyze_dockerfile(content)
    
    if not issues:
        print("✅ No issues found! Dockerfile looks good.")
        return
    
    # Group by severity
    errors = [i for i in issues if i.severity == 'error']
    warnings = [i for i in issues if i.severity == 'warning']
    infos = [i for i in issues if i.severity == 'info']
    
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
    
    # Exit with error code if errors found
    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
