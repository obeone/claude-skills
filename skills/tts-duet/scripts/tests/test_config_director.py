"""Unit tests for the user-config ``director:`` section parser.

These tests pin the behaviour added in v2.1.0:

- A top-level ``director:`` mapping in ``~/.config/tts-duet/config.yaml``
  is parsed into a :class:`lib.config.DirectorDefaults` instance.
- Defaults: ``backend="gemini"``, ``model="gemini-2.5-flash"``,
  ``temperature=0.2``, ``max_output_tokens=8192``,
  ``existing_notes_policy="preserve"``.
- The ``$TTS_DUET_DIRECTOR`` env var overrides the parsed backend.
- Invalid backend values silently fall back to ``"gemini"`` so a
  malformed config never blocks a generation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("yaml", reason="pyyaml is required for the user-config parser")

from lib.config import (  # noqa: E402  — sys.path patched by conftest
    DirectorDefaults,
    VALID_DIRECTOR_BACKENDS,
    load_user_config,
)


def _write_yaml(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_valid_backends_are_exactly_three() -> None:
    """Guards against accidental backend additions."""
    assert VALID_DIRECTOR_BACKENDS == frozenset({"agent", "gemini", "off"})


def test_no_director_section_yields_default_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TTS_DUET_DIRECTOR", raising=False)
    cfg_path = tmp_path / "config.yaml"
    _write_yaml(cfg_path, "model: flash\n")
    cfg = load_user_config(cfg_path)
    assert cfg.director == DirectorDefaults()


def test_full_director_section_is_parsed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TTS_DUET_DIRECTOR", raising=False)
    cfg_path = tmp_path / "config.yaml"
    _write_yaml(
        cfg_path,
        """
director:
  backend: agent
  model: gemini-2.5-pro
  temperature: 0.7
  max_output_tokens: 4096
  existing_notes_policy: replace
""",
    )
    cfg = load_user_config(cfg_path)
    assert cfg.director.backend == "agent"
    assert cfg.director.model == "gemini-2.5-pro"
    assert cfg.director.temperature == pytest.approx(0.7)
    assert cfg.director.max_output_tokens == 4096
    assert cfg.director.existing_notes_policy == "replace"


def test_invalid_backend_falls_back_to_gemini(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TTS_DUET_DIRECTOR", raising=False)
    cfg_path = tmp_path / "config.yaml"
    _write_yaml(cfg_path, "director:\n  backend: bogus\n")
    cfg = load_user_config(cfg_path)
    assert cfg.director.backend == "gemini"


def test_invalid_notes_policy_falls_back_to_preserve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TTS_DUET_DIRECTOR", raising=False)
    cfg_path = tmp_path / "config.yaml"
    _write_yaml(
        cfg_path,
        "director:\n  backend: off\n  existing_notes_policy: bogus\n",
    )
    cfg = load_user_config(cfg_path)
    assert cfg.director.existing_notes_policy == "preserve"


def test_env_override_replaces_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path = tmp_path / "config.yaml"
    _write_yaml(cfg_path, "director:\n  backend: gemini\n")
    monkeypatch.setenv("TTS_DUET_DIRECTOR", "agent")
    cfg = load_user_config(cfg_path)
    assert cfg.director.backend == "agent"


def test_env_override_invalid_value_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path = tmp_path / "config.yaml"
    _write_yaml(cfg_path, "director:\n  backend: off\n")
    monkeypatch.setenv("TTS_DUET_DIRECTOR", "nonsense")
    cfg = load_user_config(cfg_path)
    # Original value preserved, env override silently dropped.
    assert cfg.director.backend == "off"


def test_env_override_works_without_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TTS_DUET_DIRECTOR", "off")
    missing = tmp_path / "does-not-exist.yaml"
    cfg = load_user_config(missing)
    assert cfg.director.backend == "off"
