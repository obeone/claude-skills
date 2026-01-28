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


def analyze_dockerfile(content: str) -> List[Issue]:
    """Analyze Dockerfile content and return list of issues."""
    issues = []
    lines = content.split('\n')
    
    # Check for syntax directive
    if not lines[0].strip().startswith('# syntax='):
        issues.append(Issue(
            1, 'warning',
            'Missing BuildKit syntax directive',
            'Add: # syntax=docker/dockerfile:1'
        ))
    
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        
        # Skip comments and empty lines
        if not stripped or stripped.startswith('#'):
            continue
        
        # Check for ADD instead of COPY
        if stripped.startswith('ADD '):
            issues.append(Issue(
                i, 'warning',
                'Using ADD instead of COPY',
                'Use COPY unless you need URL download or tar extraction'
            ))
        
        # Check for latest tag
        if re.search(r'FROM\s+[\w/-]+:latest', stripped, re.IGNORECASE):
            issues.append(Issue(
                i, 'error',
                'Using :latest tag',
                'Pin to specific version: alpine:3.19 or SHA256'
            ))
        
        # Check for apt-get without cleanup
        if 'apt-get install' in stripped and 'rm -rf /var/lib/apt/lists' not in stripped:
            # Check if cleanup is in same RUN
            if not any('rm -rf /var/lib/apt/lists' in lines[j] 
                      for j in range(i, min(i+10, len(lines)))):
                issues.append(Issue(
                    i, 'warning',
                    'apt-get install without cleanup',
                    'Add: && rm -rf /var/lib/apt/lists/* in same RUN'
                ))
        
        # Check for ARG/ENV with potential secrets
        if re.search(r'(ARG|ENV)\s+(.*?(PASSWORD|SECRET|TOKEN|KEY))', stripped, re.IGNORECASE):
            issues.append(Issue(
                i, 'error',
                'Potential secret in ARG/ENV',
                'Use: RUN --mount=type=secret,id=mysecret'
            ))
        
        # Check for missing cache mount on common package managers
        if stripped.startswith('RUN '):
            if 'pip install' in stripped and '--mount=type=cache' not in stripped:
                issues.append(Issue(
                    i, 'info',
                    'pip install without cache mount',
                    'Add: RUN --mount=type=cache,target=/root/.cache/pip'
                ))
            
            if ('npm install' in stripped or 'yarn install' in stripped) and '--mount=type=cache' not in stripped:
                issues.append(Issue(
                    i, 'info',
                    'npm/yarn install without cache mount',
                    'Add: RUN --mount=type=cache,target=/root/.npm'
                ))
            
            if 'apt-get' in stripped and '--mount=type=cache' not in stripped:
                issues.append(Issue(
                    i, 'info',
                    'apt-get without cache mount',
                    'Add: RUN --mount=type=cache,target=/var/cache/apt'
                ))
        
        # Check for WORKDIR
        if stripped.startswith('RUN cd '):
            issues.append(Issue(
                i, 'warning',
                'Using RUN cd instead of WORKDIR',
                'Use: WORKDIR /path'
            ))

        # Check for OS version pinning in base image
        os_versions = r'(bookworm|bullseye|buster|jammy|focal|bionic|alpine:3\.\d+)'
        if stripped.startswith('FROM '):
            match = re.search(os_versions, stripped, re.IGNORECASE)
            if match:
                issues.append(Issue(
                    i, 'warning',
                    f'Base image pins OS version ({match.group(1)})',
                    'Consider using version tag without OS release (e.g., python:3.12-slim instead of python:3.12-slim-bookworm) for automatic security updates'
                ))

        # Check for low UID/GID in user creation
        uid_pattern = r'(useradd|adduser).*?-u\s+(\d+)'
        gid_pattern = r'(groupadd|addgroup).*?-g\s+(\d+)'

        uid_match = re.search(uid_pattern, stripped)
        if uid_match:
            uid = int(uid_match.group(2))
            if uid < 10000:
                issues.append(Issue(
                    i, 'warning',
                    f'User created with UID {uid} (< 10000)',
                    'Consider using UID >10000 to avoid conflicts with host system users'
                ))

        gid_match = re.search(gid_pattern, stripped)
        if gid_match:
            gid = int(gid_match.group(2))
            if gid < 10000:
                issues.append(Issue(
                    i, 'warning',
                    f'Group created with GID {gid} (< 10000)',
                    'Consider using GID >10000 to avoid conflicts with host system users'
                ))

        # Check for user creation without explicit UID/GID
        if re.search(r'(useradd|adduser|groupadd|addgroup)', stripped):
            if not re.search(r'-[ug]\s+\d+', stripped):
                issues.append(Issue(
                    i, 'info',
                    'User/group created without explicit UID/GID',
                    'Consider explicit UID/GID >10000 if consistent permissions across environments are needed'
                ))

        # Check for USER root or missing USER
        if stripped.startswith('USER root'):
            issues.append(Issue(
                i, 'warning',
                'Running as root user',
                'Create and use non-root user for security'
            ))
    
    # Check if USER is never set
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
