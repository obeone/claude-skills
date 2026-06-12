"""Filesystem layout helpers for the automode-config skill.

Resolves the four paths the skill cares about and exposes a small
``ProjectFiles`` dataclass that callers use to read, write, and reason
about each one.

Files
-----
- ``user_settings``    : ``~/.claude/settings.json``
- ``shared_settings``  : ``<project>/.claude/settings.json``
- ``local_settings``   : ``<project>/.claude/settings.local.json``
- ``approved_cache``   : ``<project>/.claude/.auto_mode_approved.json``

Stdlib-only.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path


USER_SETTINGS_NAME = "settings.json"
SHARED_SETTINGS_NAME = "settings.json"
LOCAL_SETTINGS_NAME = "settings.local.json"
APPROVED_CACHE_NAME = ".auto_mode_approved.json"

USER_DIR = ".claude"
PROJECT_DIR = ".claude"

EXPECTED_SECRET_MODE = 0o600
EXPECTED_PARENT_MODE = 0o700


@dataclass(frozen=True)
class ProjectFiles:
    """Resolved filesystem paths for a single project root.

    Attributes
    ----------
    project_root : Path
        Absolute path to the project root (cwd by default).
    user_settings : Path
        ``~/.claude/settings.json``.
    shared_settings : Path
        ``<project>/.claude/settings.json``.
    local_settings : Path
        ``<project>/.claude/settings.local.json``.
    approved_cache : Path
        ``<project>/.claude/.auto_mode_approved.json``.
    user_dir : Path
        ``~/.claude/``.
    project_dir : Path
        ``<project>/.claude/``.
    """

    project_root: Path
    user_settings: Path
    shared_settings: Path
    local_settings: Path
    approved_cache: Path
    user_dir: Path
    project_dir: Path

    def all_files(self) -> tuple[Path, Path, Path, Path]:
        """Return the four files in canonical order (user, shared, local, cache)."""

        return (
            self.user_settings,
            self.shared_settings,
            self.local_settings,
            self.approved_cache,
        )

    def exists(self, which: str) -> bool:
        """Return True if ``which`` (``user``/``shared``/``local``/``cache``) exists."""

        return self._select(which).is_file()

    def mode_check(self, which: str) -> tuple[bool, int | None]:
        """Return ``(ok, mode)`` for the requested file.

        ``ok`` is True when the file's permission bits are exactly
        ``0o600`` (or the file is absent — in which case ``mode`` is
        ``None``). ``shared_settings`` is always considered ``ok`` since
        it is committed and expected to be 0644.
        """

        target = self._select(which)
        if not target.exists():
            return True, None
        mode = stat.S_IMODE(target.stat().st_mode)
        if which == "shared":
            return True, mode
        return mode == EXPECTED_SECRET_MODE, mode

    def _select(self, which: str) -> Path:
        mapping = {
            "user": self.user_settings,
            "shared": self.shared_settings,
            "local": self.local_settings,
            "cache": self.approved_cache,
        }
        try:
            return mapping[which]
        except KeyError as exc:
            raise ValueError(
                f"unknown file selector {which!r}; expected one of "
                f"{sorted(mapping)}"
            ) from exc


def resolve(project_root: str | os.PathLike[str] | None = None) -> ProjectFiles:
    """Return a ``ProjectFiles`` for the given project root.

    Parameters
    ----------
    project_root : str or os.PathLike, optional
        Project root to resolve. Defaults to ``Path.cwd()``.

    Returns
    -------
    ProjectFiles
        Frozen dataclass with absolute paths.
    """

    root = Path(project_root) if project_root is not None else Path.cwd()
    root = root.resolve()
    user_dir = Path.home() / USER_DIR
    project_dir = root / PROJECT_DIR
    return ProjectFiles(
        project_root=root,
        user_settings=user_dir / USER_SETTINGS_NAME,
        shared_settings=project_dir / SHARED_SETTINGS_NAME,
        local_settings=project_dir / LOCAL_SETTINGS_NAME,
        approved_cache=project_dir / APPROVED_CACHE_NAME,
        user_dir=user_dir,
        project_dir=project_dir,
    )


def ensure_project_dir(files: ProjectFiles, *, mode: int = EXPECTED_PARENT_MODE) -> None:
    """Create ``<project>/.claude/`` if missing, with restrictive mode."""

    files.project_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(files.project_dir, mode)
    except PermissionError:
        pass


def ensure_user_dir(files: ProjectFiles, *, mode: int = EXPECTED_PARENT_MODE) -> None:
    """Create ``~/.claude/`` if missing, with restrictive mode."""

    files.user_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(files.user_dir, mode)
    except PermissionError:
        pass
