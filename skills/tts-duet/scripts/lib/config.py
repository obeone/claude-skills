"""Multi-source configuration loader for the tts-duet skill.

Merges four layers in ascending priority order::

    hardcoded defaults < user config < project config < CLI overrides

Config files are YAML with two top-level sections: ``defaults`` and
``director``. Missing files are silently ignored; malformed YAML raises
:class:`RuntimeError` with the offending path.

Examples
--------
>>> from pathlib import Path
>>> cfg = load_config()
>>> cfg.defaults.model
'pro'
>>> cfg.director.mode
'auto'
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

__all__ = [
    "DefaultsConfig",
    "DirectorConfig",
    "Config",
    "load_config",
]


@dataclass(frozen=True)
class DefaultsConfig:
    """Hardcoded defaults for the generation pipeline.

    Parameters
    ----------
    model : str
        Model alias (``"pro"`` / ``"flash"``) or full Gemini model ID.
    format : str
        Output format: ``"wav"``, ``"mp3"``, or ``"both"``.
    preset : str
        Named preset from ``assets/voice_pairs.yaml``.
    approved_cost_usd : float or None
        Hard cap on estimated cost in USD. ``None`` means no cap.
    """

    model: str = "pro"
    format: str = "mp3"
    preset: str = "podcast-chill"
    approved_cost_usd: float | None = None


@dataclass(frozen=True)
class DirectorConfig:
    """Configuration for the Director LLM pre-TTS pass.

    Parameters
    ----------
    mode : {"auto", "always", "off"}
        When to invoke the director pass.
    model : {"flash", "pro"}
        Which model tier to use for the director pass.
    existing_notes : {"keep", "replace", "enrich"}
        How to handle a pre-existing ``## Director's Notes`` section.
    genre_default : str
        Default genre hint passed to the director prompt.
    """

    mode: Literal["auto", "always", "off"] = "auto"
    model: Literal["flash", "pro"] = "flash"
    existing_notes: Literal["keep", "replace", "enrich"] = "keep"
    genre_default: str = "pedagogical"


@dataclass(frozen=True)
class Config:
    """Top-level frozen configuration object.

    Parameters
    ----------
    defaults : DefaultsConfig
        Generation-pipeline defaults.
    director : DirectorConfig
        Director-pass configuration.
    """

    defaults: DefaultsConfig
    director: DirectorConfig


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file, returning ``{}`` for missing files.

    Parameters
    ----------
    path : Path
        Path to the YAML file.

    Returns
    -------
    dict
        Parsed YAML content, or an empty dict if the file does not exist.

    Raises
    ------
    RuntimeError
        If the file exists but cannot be parsed as valid YAML.
    """
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as err:
        raise RuntimeError(f"Malformed config at {path}: {err}") from err
    return data or {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base*, returning a new dict.

    Parameters
    ----------
    base : dict
        Base dictionary (lower priority).
    override : dict
        Override dictionary (higher priority).

    Returns
    -------
    dict
        Merged dictionary. Nested dicts are merged recursively; all other
        types are replaced by the override value.
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _build_config(merged: dict[str, Any]) -> Config:
    """Construct a frozen :class:`Config` from a merged dict.

    Parameters
    ----------
    merged : dict
        Fully merged configuration dict with optional ``defaults`` and
        ``director`` sub-dicts.

    Returns
    -------
    Config
        Frozen config dataclass.
    """
    d = merged.get("defaults") or {}
    director_d = merged.get("director") or {}

    defaults = DefaultsConfig(
        model=d.get("model", DefaultsConfig.model),
        format=d.get("format", DefaultsConfig.format),
        preset=d.get("preset", DefaultsConfig.preset),
        approved_cost_usd=d.get("approved_cost_usd", DefaultsConfig.approved_cost_usd),
    )
    director = DirectorConfig(
        mode=director_d.get("mode", DirectorConfig.mode),
        model=director_d.get("model", DirectorConfig.model),
        existing_notes=director_d.get("existing_notes", DirectorConfig.existing_notes),
        genre_default=director_d.get("genre_default", DirectorConfig.genre_default),
    )
    return Config(defaults=defaults, director=director)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_config(
    cli_overrides: dict[str, Any] | None = None,
    *,
    project_path: Path | None = None,
    user_path: Path | None = None,
) -> Config:
    """Load and merge configuration from all sources.

    Merge order (lowest → highest priority):

    1. Hardcoded dataclass defaults
    2. User config (``~/.config/tts-duet/config.yaml`` by default)
    3. Project config (``./tts-duet.yaml`` in CWD by default)
    4. ``cli_overrides`` dict

    Missing config files are silently ignored. Malformed YAML raises
    :class:`RuntimeError` with the offending path included in the message.

    Parameters
    ----------
    cli_overrides : dict or None
        Dict of CLI-supplied overrides. Should only contain keys for flags
        the user *explicitly* passed (use argparse sentinel ``default=None``
        to distinguish unset from same-as-default). Nested structure must
        mirror the YAML sections: ``{"defaults": {"model": "flash"}}``.
    project_path : Path or None
        Path to the project config file. Defaults to ``./tts-duet.yaml``
        (CWD search only, no upward traversal).
    user_path : Path or None
        Path to the user config file. Defaults to
        ``~/.config/tts-duet/config.yaml``.

    Returns
    -------
    Config
        Frozen :class:`Config` dataclass with all sections resolved.

    Raises
    ------
    RuntimeError
        If any located config file contains invalid YAML.

    Examples
    --------
    >>> cfg = load_config(cli_overrides={"defaults": {"model": "flash"}})
    >>> cfg.defaults.model
    'flash'
    """
    if user_path is None:
        user_path = Path.home() / ".config" / "tts-duet" / "config.yaml"
    if project_path is None:
        project_path = Path.cwd() / "tts-duet.yaml"

    merged: dict[str, Any] = {}
    merged = _deep_merge(merged, _read_yaml(user_path))
    merged = _deep_merge(merged, _read_yaml(project_path))
    if cli_overrides:
        merged = _deep_merge(merged, cli_overrides)

    return _build_config(merged)
