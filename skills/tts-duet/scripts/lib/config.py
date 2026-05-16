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
import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "JobConfig",
    "JOB_CONFIG_VERSION",
    "AdaptationDefaults",
    "DirectorDefaults",
    "MCPDefaults",
    "UserConfig",
    "VALID_ADAPTATION_BACKENDS",
    "VALID_DIRECTOR_BACKENDS",
    "VALID_PROMPT_AT_CALL_FIELDS",
    "VALID_SHAPES",
    "load_user_config",
    "default_user_config_path",
    "write_job_config",
    "read_job_config",
    "load_config_json",
]

#: Allowed values for ``DirectorDefaults.backend``.
VALID_DIRECTOR_BACKENDS: frozenset[str] = frozenset({"agent", "gemini", "off"})

#: Allowed values for ``AdaptationDefaults.backend``. Adaptation has
#: no ``"off"`` since the pre-pass is only invoked when the user
#: explicitly asks for raw-text → script adaptation.
VALID_ADAPTATION_BACKENDS: frozenset[str] = frozenset({"agent", "gemini"})

#: Allowed values for ``UserConfig.shape`` / the adaptation ``--shape``
#: CLI flag.
VALID_SHAPES: frozenset[str] = frozenset({"dialogue", "mono", "interview"})

#: Fields the user can flag as "ask me at every /tts-duet call" instead
#: of using the persisted default. Anything else in
#: ``prompt_at_call`` is dropped silently to keep older configs forward
#: compatible.
VALID_PROMPT_AT_CALL_FIELDS: frozenset[str] = frozenset(
    {"preset", "style", "director", "shape", "language", "adaptation"}
)

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
class DirectorDefaults:
    """Parsed contents of ``config.yaml`` ``director:`` section.

    Parameters
    ----------
    backend : {"agent", "gemini", "off"}, optional
        Which backend to use for the director rewrite pass.

        * ``"gemini"`` — call the MCP ``text_transform`` tool (default).
        * ``"agent"`` — write a handoff prompt to the job dir and stop;
          the calling agent produces the rewritten script.
        * ``"off"`` — skip the director pass entirely.
    model : str, optional
        Gemini model ID for the ``gemini`` backend. Default:
        ``"gemini-2.5-flash"``.
    temperature : float, optional
        Sampling temperature forwarded to ``text_transform``. Default:
        ``0.2``.
    max_output_tokens : int, optional
        Output-token budget forwarded to ``text_transform``. Default:
        ``8192``.
    existing_notes_policy : {"preserve", "replace"}, optional
        How to handle pre-existing Director's Notes. Default:
        ``"preserve"``.
    """

    backend: str = "gemini"
    model: str = "gemini-2.5-flash"
    temperature: float = 0.2
    max_output_tokens: int = 8192
    existing_notes_policy: str = "preserve"


@dataclass(frozen=True)
class AdaptationDefaults:
    """Parsed contents of ``config.yaml`` ``adaptation:`` section.

    Parameters
    ----------
    backend : {"agent", "gemini"}, optional
        Which backend handles the raw-text -> script adaptation pre-pass.

        * ``"agent"`` — the calling agent does it locally; the skill
          writes a handoff prompt and exits (default).
        * ``"gemini"`` — call the MCP ``text_transform`` tool with an
          adaptation prompt.
    model : str, optional
        Gemini model ID for the ``gemini`` backend. Default:
        ``"gemini-2.5-flash"``.
    temperature : float, optional
        Sampling temperature forwarded to ``text_transform``. Slightly
        higher than the director's 0.2 because adaptation is creative.
        Default: ``0.3``.
    max_output_tokens : int, optional
        Output-token budget forwarded to ``text_transform``. Default:
        ``8192``.
    """

    backend: str = "agent"
    model: str = "gemini-2.5-flash"
    temperature: float = 0.3
    max_output_tokens: int = 8192


@dataclass(frozen=True)
class UserConfig:
    """Parsed ``~/.config/tts-duet/config.yaml`` document.

    Parameters
    ----------
    raw : dict
        The full parsed YAML document, kept verbatim for forward
        compatibility with keys the skill does not yet understand.
    mcp : MCPDefaults
        Parsed ``mcp:`` section.
    director : DirectorDefaults
        Parsed ``director:`` section.
    adaptation : AdaptationDefaults
        Parsed ``adaptation:`` section.
    shape : {"dialogue", "mono", "interview"}, optional
        Default script shape used by the adaptation pre-pass. Default:
        ``"dialogue"``.
    language : str, optional
        Default language for adaptation. ``"auto"`` lets the model
        match the input; otherwise a BCP-47 tag (``"fr"``, ``"en"``,
        ...). Default: ``"auto"``.
    prompt_at_call : frozenset of str
        Fields the user wants re-prompted at every ``/tts-duet``
        invocation instead of taking the saved default. Each entry must
        be in :data:`VALID_PROMPT_AT_CALL_FIELDS`. Empty set means
        "use defaults silently" (legacy behaviour).
    """

    raw: dict[str, Any] = field(default_factory=dict)
    mcp: MCPDefaults = field(default_factory=MCPDefaults)
    director: DirectorDefaults = field(default_factory=DirectorDefaults)
    adaptation: AdaptationDefaults = field(default_factory=AdaptationDefaults)
    shape: str = "dialogue"
    language: str = "auto"
    prompt_at_call: frozenset[str] = field(default_factory=frozenset)


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


def _parse_director_defaults(raw: dict[str, Any]) -> DirectorDefaults:
    """Parse the top-level ``director:`` section of the user config.

    The block lives at the YAML root (not under ``mcp:``) so the
    skill's text-pass behaviour stays orthogonal to MCP transport
    knobs.

    Parameters
    ----------
    raw : dict
        The full parsed YAML document.

    Returns
    -------
    DirectorDefaults
        Defaults populated from the document. Invalid backend values
        silently fall back to ``"gemini"`` so a malformed config never
        blocks a generation.
    """
    section = raw.get("director")
    if not isinstance(section, dict):
        return DirectorDefaults()

    raw_backend = section.get("backend", "gemini")
    # YAML 1.1 parses bare ``off`` / ``on`` as bool — round-trip those
    # back to strings so users can write ``backend: off`` naturally.
    if isinstance(raw_backend, bool):
        backend = "off" if raw_backend is False else "gemini"
    else:
        backend = str(raw_backend or "gemini").strip().lower()
        if backend == "false":
            backend = "off"
    if backend not in VALID_DIRECTOR_BACKENDS:
        backend = "gemini"

    model = str(section.get("model", "gemini-2.5-flash") or "gemini-2.5-flash")

    def _num(key: str, default: float) -> float:
        value = section.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _intval(key: str, default: int) -> int:
        value = section.get(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    notes_policy = str(
        section.get("existing_notes_policy", "preserve") or "preserve"
    ).strip().lower()
    if notes_policy not in {"preserve", "replace"}:
        notes_policy = "preserve"

    return DirectorDefaults(
        backend=backend,
        model=model,
        temperature=_num("temperature", 0.2),
        max_output_tokens=_intval("max_output_tokens", 8192),
        existing_notes_policy=notes_policy,
    )


def _parse_adaptation_defaults(raw: dict[str, Any]) -> AdaptationDefaults:
    """Parse the top-level ``adaptation:`` section of the user config.

    Mirrors :func:`_parse_director_defaults`: the block lives at the
    YAML root and only the ``backend`` field is strictly validated.
    Invalid backend values silently fall back to ``"agent"`` so a
    malformed config never blocks an adaptation run.

    Parameters
    ----------
    raw : dict
        The full parsed YAML document.

    Returns
    -------
    AdaptationDefaults
        Defaults populated from the document.
    """
    section = raw.get("adaptation")
    if not isinstance(section, dict):
        return AdaptationDefaults()

    raw_backend = section.get("backend", "agent")
    if isinstance(raw_backend, bool):
        backend = "agent"
    else:
        backend = str(raw_backend or "agent").strip().lower()
    if backend not in VALID_ADAPTATION_BACKENDS:
        backend = "agent"

    model = str(section.get("model", "gemini-2.5-flash") or "gemini-2.5-flash")

    def _num(key: str, default: float) -> float:
        value = section.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _intval(key: str, default: int) -> int:
        value = section.get(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    return AdaptationDefaults(
        backend=backend,
        model=model,
        temperature=_num("temperature", 0.3),
        max_output_tokens=_intval("max_output_tokens", 8192),
    )


def _parse_shape(raw: dict[str, Any]) -> str:
    """Parse the top-level ``shape:`` field. Invalid -> ``"dialogue"``."""
    value = raw.get("shape", "dialogue")
    candidate = str(value or "dialogue").strip().lower()
    if candidate not in VALID_SHAPES:
        return "dialogue"
    return candidate


def _parse_language(raw: dict[str, Any]) -> str:
    """Parse the top-level ``language:`` field.

    Empty / missing values fall back to ``"auto"``. The skill does not
    validate BCP-47 syntax — it forwards the tag verbatim to the
    adaptation prompt.
    """
    value = raw.get("language", "auto")
    if value in (None, "", False):
        return "auto"
    return str(value).strip() or "auto"


def _parse_prompt_at_call(raw: dict[str, Any]) -> frozenset[str]:
    """Parse the top-level ``prompt_at_call:`` list.

    Accepts a YAML list of strings, a single string (split on commas
    and whitespace), or absent / null (returns the empty set). Unknown
    or whitespace-only entries are dropped silently so older configs
    keep loading after we add new fields.

    Parameters
    ----------
    raw : dict
        The full parsed YAML document.

    Returns
    -------
    frozenset of str
        Subset of :data:`VALID_PROMPT_AT_CALL_FIELDS`.
    """
    value = raw.get("prompt_at_call")
    if value in (None, "", False):
        return frozenset()
    items: list[str] = []
    if isinstance(value, str):
        items = [tok.strip() for tok in value.replace(",", " ").split()]
    elif isinstance(value, (list, tuple, set, frozenset)):
        items = [str(tok).strip() for tok in value]
    selected = {tok.lower() for tok in items if tok}
    return frozenset(selected & VALID_PROMPT_AT_CALL_FIELDS)


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
    def _apply_env_override(director: DirectorDefaults) -> DirectorDefaults:
        env_override = os.environ.get("TTS_DUET_DIRECTOR")
        if not env_override:
            return director
        candidate = env_override.strip().lower()
        if candidate not in VALID_DIRECTOR_BACKENDS:
            return director
        return DirectorDefaults(
            backend=candidate,
            model=director.model,
            temperature=director.temperature,
            max_output_tokens=director.max_output_tokens,
            existing_notes_policy=director.existing_notes_policy,
        )

    target = path if path is not None else default_user_config_path()
    if not target.is_file():
        return UserConfig(director=_apply_env_override(DirectorDefaults()))
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return UserConfig(director=_apply_env_override(DirectorDefaults()))
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return UserConfig(director=_apply_env_override(DirectorDefaults()))
    if not isinstance(raw, dict):
        return UserConfig(director=_apply_env_override(DirectorDefaults()))
    director = _apply_env_override(_parse_director_defaults(raw))
    return UserConfig(
        raw=raw,
        mcp=_parse_mcp_defaults(raw),
        director=director,
        adaptation=_parse_adaptation_defaults(raw),
        shape=_parse_shape(raw),
        language=_parse_language(raw),
        prompt_at_call=_parse_prompt_at_call(raw),
    )


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
