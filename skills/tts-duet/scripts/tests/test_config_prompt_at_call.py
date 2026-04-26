"""Unit tests for the ``prompt_at_call:`` user-config field.

The setup command (Step 1bis) lets the user mark a subset of
``{preset, style, director}`` as "ask me at every /tts-duet call".
:func:`lib.config.load_user_config` exposes the result as a
``frozenset[str]`` on :class:`UserConfig`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("yaml", reason="pyyaml is required for the user-config parser")

from lib.config import (  # noqa: E402  — sys.path patched by conftest
    VALID_PROMPT_AT_CALL_FIELDS,
    load_user_config,
)


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_absent_key_yields_empty_set(tmp_path: Path) -> None:
    cfg_path = _write(tmp_path / "config.yaml", "model: flash\n")
    cfg = load_user_config(cfg_path)
    assert cfg.prompt_at_call == frozenset()


def test_explicit_empty_list_yields_empty_set(tmp_path: Path) -> None:
    cfg_path = _write(
        tmp_path / "config.yaml",
        "prompt_at_call: []\n",
    )
    cfg = load_user_config(cfg_path)
    assert cfg.prompt_at_call == frozenset()


def test_yaml_list_form(tmp_path: Path) -> None:
    cfg_path = _write(
        tmp_path / "config.yaml",
        "prompt_at_call:\n  - preset\n  - director\n",
    )
    cfg = load_user_config(cfg_path)
    assert cfg.prompt_at_call == frozenset({"preset", "director"})


def test_string_form_split_on_commas_and_whitespace(tmp_path: Path) -> None:
    cfg_path = _write(
        tmp_path / "config.yaml",
        "prompt_at_call: 'preset, style director'\n",
    )
    cfg = load_user_config(cfg_path)
    assert cfg.prompt_at_call == frozenset({"preset", "style", "director"})


def test_unknown_entries_are_dropped_silently(tmp_path: Path) -> None:
    cfg_path = _write(
        tmp_path / "config.yaml",
        "prompt_at_call: [preset, voodoo, none]\n",
    )
    cfg = load_user_config(cfg_path)
    # ``voodoo`` and ``none`` are not in the allowlist; dropped.
    assert cfg.prompt_at_call == frozenset({"preset"})


def test_case_is_normalised_to_lower(tmp_path: Path) -> None:
    cfg_path = _write(
        tmp_path / "config.yaml",
        "prompt_at_call: ['PRESET', 'Director', '  STYLE  ']\n",
    )
    cfg = load_user_config(cfg_path)
    assert cfg.prompt_at_call == frozenset({"preset", "director", "style"})


def test_valid_set_only_contains_documented_fields() -> None:
    """Pin the public allowlist — bumping it is a SKILL.md change."""
    assert VALID_PROMPT_AT_CALL_FIELDS == frozenset(
        {"preset", "style", "director", "shape", "language", "adaptation"}
    )
