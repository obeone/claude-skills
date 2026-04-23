"""Configuration helpers for the tts-duet skill (plan §5.3 / §5.5).

Exposes two concerns:

1. **User defaults** (``~/.config/tts-duet/config.yaml``) — consumed by
   :func:`load_user_config` and friends. Only the ``mcp:`` subsection
   is load-bearing in the rewrite; other keys are preserved verbatim
   and forwarded to callers.
2. **Job-dir schema v1** (``<job_dir>/config.json``) — written before
   the first MCP call by ``generate_tts.py``, read by any tool
   inspecting a background job. See :class:`JobConfig`.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "JobConfig",
    "JOB_CONFIG_VERSION",
    "MCPDefaults",
    "UserConfig",
    "load_user_config",
    "default_user_config_path",
    "write_job_config",
    "read_job_config",
    "load_config_json",
]

JOB_CONFIG_VERSION: int = 1

_REQUIRED_JOB_FIELDS: tuple[str, ...] = (
    "version",
    "created_at",
    "script_path",
    "script_hash",
    "model",
    "voices",
    "lang",
    "format",
    "chunk_count",
    "chunks_done",
    "mcp_command",
    "mcp_version",
    "protocol_version",
    "cli_snapshot",
)


# ---------------------------------------------------------------------------
# User defaults (~/.config/tts-duet/config.yaml)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MCPDefaults:
    """Parsed contents of ``config.yaml`` ``mcp:`` section.

    Parameters
    ----------
    command : list of str or None
        Explicit MCP spawn command. Accepts either a YAML list or a
        string (shlex-split). ``None`` when the user has not set one.
    spawn_timeout_s : float, optional
        Max seconds to wait for the MCP child to produce a usable
        session. Default: 120.
    chunk_retry_max : int, optional
        Per-chunk retry budget (§6.2). Default: 2.
    respawn_max : int, optional
        Per-job MCP respawn budget (§6.2). Default: 3.
    """

    command: list[str] | None = None
    spawn_timeout_s: float = 120.0
    chunk_retry_max: int = 2
    respawn_max: int = 3


@dataclass(frozen=True)
class UserConfig:
    """Parsed ``~/.config/tts-duet/config.yaml`` document."""

    raw: dict[str, Any] = field(default_factory=dict)
    mcp: MCPDefaults = field(default_factory=MCPDefaults)


def default_user_config_path() -> Path:
    """Return the canonical user-config path."""
    return Path.home() / ".config" / "tts-duet" / "config.yaml"


def _parse_mcp_defaults(raw: dict[str, Any]) -> MCPDefaults:
    mcp_section = raw.get("mcp") or {}
    if not isinstance(mcp_section, dict):
        return MCPDefaults()

    command: list[str] | None = None
    configured = mcp_section.get("command")
    if isinstance(configured, list) and configured:
        command = [str(x) for x in configured]
    elif isinstance(configured, str) and configured.strip():
        command = shlex.split(configured)

    def _num(key: str, default: float) -> float:
        value = mcp_section.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _intval(key: str, default: int) -> int:
        value = mcp_section.get(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    return MCPDefaults(
        command=command,
        spawn_timeout_s=_num("spawn_timeout_s", 120.0),
        chunk_retry_max=_intval("chunk_retry_max", 2),
        respawn_max=_intval("respawn_max", 3),
    )


def load_user_config(path: Path | None = None) -> UserConfig:
    """Load the user-defaults YAML file.

    Parameters
    ----------
    path : Path, optional
        File path. Defaults to :func:`default_user_config_path`.

    Returns
    -------
    UserConfig
        Empty config with defaults when the file does not exist, parses
        as non-mapping, or fails to parse.
    """
    target = path if path is not None else default_user_config_path()
    if not target.is_file():
        return UserConfig()
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return UserConfig()
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return UserConfig()
    if not isinstance(raw, dict):
        return UserConfig()
    return UserConfig(raw=raw, mcp=_parse_mcp_defaults(raw))


# ---------------------------------------------------------------------------
# Job-dir config.json (schema v1)
# ---------------------------------------------------------------------------


@dataclass
class JobConfig:
    """Structured view of ``<job_dir>/config.json`` (schema v1)."""

    version: int
    created_at: str
    script_path: str
    script_hash: str
    model: str
    voices: dict[str, Any]
    lang: str
    format: str
    chunk_count: int
    chunks_done: int
    mcp_command: list[str]
    mcp_version: str
    protocol_version: str
    cli_snapshot: dict[str, Any]
    preset: str | None = None
    approved_cost_usd: float | None = None
    director: dict[str, Any] | None = None
    extras: dict[str, Any] = field(default_factory=dict)


def write_job_config(path: Path, data: dict[str, Any]) -> None:
    """Write a validated ``config.json`` to ``path``.

    The ``version`` field is stamped to :data:`JOB_CONFIG_VERSION`
    before serialisation. ``cli_snapshot`` is scrubbed of any known
    env-key shapes (§5.5 stability rule) so secrets never leak into a
    job dir.

    Parameters
    ----------
    path : Path
        Destination file path.
    data : dict
        Payload to persist. Missing required fields are rejected with
        :class:`ValueError`.
    """
    payload = dict(data)
    payload["version"] = JOB_CONFIG_VERSION

    snapshot = payload.get("cli_snapshot") or {}
    if isinstance(snapshot, dict):
        for forbidden in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "env"):
            snapshot.pop(forbidden, None)
        payload["cli_snapshot"] = snapshot
    else:
        payload["cli_snapshot"] = {}

    missing = [field_name for field_name in _REQUIRED_JOB_FIELDS if field_name not in payload]
    if missing:
        raise ValueError(f"write_job_config: missing required fields: {missing}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def read_job_config(path: Path) -> JobConfig:
    """Load a ``config.json`` from disk.

    Parameters
    ----------
    path : Path
        File path.

    Returns
    -------
    JobConfig
        Parsed view of the document.

    Raises
    ------
    ValueError
        If the schema version is unknown or a required field is
        missing.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("config.json: top-level must be an object")
    version = raw.get("version")
    if version != JOB_CONFIG_VERSION:
        raise ValueError(
            f"config.json: unsupported schema version {version!r}; "
            f"expected {JOB_CONFIG_VERSION}"
        )
    missing = [field_name for field_name in _REQUIRED_JOB_FIELDS if field_name not in raw]
    if missing:
        raise ValueError(f"config.json: missing required fields: {missing}")
    known = set(_REQUIRED_JOB_FIELDS) | {"preset", "approved_cost_usd", "director"}
    extras = {k: v for k, v in raw.items() if k not in known}
    return JobConfig(
        version=int(raw["version"]),
        created_at=str(raw["created_at"]),
        script_path=str(raw["script_path"]),
        script_hash=str(raw["script_hash"]),
        model=str(raw["model"]),
        voices=dict(raw["voices"]),
        lang=str(raw["lang"]),
        format=str(raw["format"]),
        chunk_count=int(raw["chunk_count"]),
        chunks_done=int(raw["chunks_done"]),
        mcp_command=list(raw["mcp_command"]),
        mcp_version=str(raw["mcp_version"]),
        protocol_version=str(raw["protocol_version"]),
        cli_snapshot=dict(raw["cli_snapshot"]),
        preset=raw.get("preset"),
        approved_cost_usd=raw.get("approved_cost_usd"),
        director=raw.get("director"),
        extras=extras,
    )


def load_config_json(path: Path) -> dict[str, Any]:
    """Return ``config.json`` as a plain dict (also validates version).

    This is the flavour the contract tests in
    :mod:`tests.test_config_schema` drive against.
    """
    cfg = read_job_config(path)
    payload: dict[str, Any] = {
        "version": cfg.version,
        "created_at": cfg.created_at,
        "script_path": cfg.script_path,
        "script_hash": cfg.script_hash,
        "model": cfg.model,
        "voices": cfg.voices,
        "lang": cfg.lang,
        "format": cfg.format,
        "chunk_count": cfg.chunk_count,
        "chunks_done": cfg.chunks_done,
        "mcp_command": cfg.mcp_command,
        "mcp_version": cfg.mcp_version,
        "protocol_version": cfg.protocol_version,
        "cli_snapshot": cfg.cli_snapshot,
        "preset": cfg.preset,
        "approved_cost_usd": cfg.approved_cost_usd,
        "director": cfg.director,
    }
    payload.update(cfg.extras)
    return payload
