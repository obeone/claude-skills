"""Unit tests for the job-dir ``config.json`` schema v1 (plan §5.5).

The contract: every background job writes ``<job_dir>/config.json``
before the first MCP call, and every required field listed in §5.5
appears with the correct type. ``version`` is a hard gate; readers must
refuse unknown values.

Worker-b (task #2) wires the writer/reader. Until that lands, the
import of the helper module fails and the suite skips. The fixture
JSON below is the canonical v1 shape and is exercised both by the
file-on-disk path and by a programmatic ``write_config_json`` if
worker-b ships one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# The reader/writer module name is not pinned by the plan; try the most
# obvious locations in §5.3 / §5.5 order and fall back to importskip.
try:  # pragma: no cover - selection branch
    from lib import config as _config_mod  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    _config_mod = pytest.importorskip(
        "lib.config",
        reason="lib.config not yet landed by worker-b (task #2)",
    )


REQUIRED_FIELDS: dict[str, type | tuple[type, ...]] = {
    "version": int,
    "created_at": str,
    "script_path": str,
    "script_hash": str,
    "model": str,
    "voices": dict,
    "lang": str,
    "format": str,
    "chunk_count": int,
    "chunks_done": int,
    "mcp_command": list,
    "mcp_version": str,
    "protocol_version": str,
    "cli_snapshot": dict,
}


def _sample_config_v1() -> dict[str, Any]:
    return {
        "version": 1,
        "created_at": "2026-04-23T12:00:00Z",
        "script_path": "/tmp/script.md",
        "script_hash": "a" * 64,
        "model": "gemini-2.5-flash-preview-tts",
        "preset": "podcast-chill",
        "voices": {"voice_a": "Charon", "voice_b": "Aoede"},
        "lang": "auto",
        "format": "wav",
        "chunk_count": 3,
        "chunks_done": 0,
        "mcp_command": ["gemini-tts-mcp"],
        "mcp_version": "2.0.0",
        "protocol_version": "1",
        "approved_cost_usd": None,
        "director": None,
        "cli_snapshot": {"background": True, "preset": "podcast-chill"},
    }


@pytest.fixture()
def sample_config_path(tmp_path: Path) -> Path:
    cfg = _sample_config_v1()
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Field presence + type tests (work even without a custom reader)
# ---------------------------------------------------------------------------


def test_sample_config_has_every_required_field() -> None:
    cfg = _sample_config_v1()
    missing = [k for k in REQUIRED_FIELDS if k not in cfg]
    assert not missing, f"sample missing fields: {missing}"


def test_sample_config_field_types_match_schema() -> None:
    cfg = _sample_config_v1()
    for key, expected in REQUIRED_FIELDS.items():
        value = cfg[key]
        assert isinstance(value, expected), (
            f"field {key!r}={value!r} is {type(value).__name__}, "
            f"expected {expected}"
        )


def test_sample_config_voices_block_has_voice_a() -> None:
    cfg = _sample_config_v1()
    assert "voice_a" in cfg["voices"]
    assert cfg["voices"]["voice_a"]


def test_sample_config_format_value_is_known() -> None:
    cfg = _sample_config_v1()
    assert cfg["format"] in {"wav", "mp3", "both"}


def test_sample_config_version_is_one() -> None:
    cfg = _sample_config_v1()
    assert cfg["version"] == 1


def test_sample_config_cli_snapshot_has_no_env_keys() -> None:
    """§5.5 stability rule: cli_snapshot NEVER contains env vars."""
    cfg = _sample_config_v1()
    snap_keys = set(cfg["cli_snapshot"])
    forbidden = {"GEMINI_API_KEY", "GOOGLE_API_KEY", "env"}
    assert not (snap_keys & forbidden)


# ---------------------------------------------------------------------------
# Round-trip via worker-b's reader, when available
# ---------------------------------------------------------------------------


def _resolve_reader():
    """Return the first available reader callable, or skip."""
    for name in ("read_job_config", "load_config_json", "load_job_config"):
        fn = getattr(_config_mod, name, None)
        if callable(fn):
            return fn
    pytest.skip(
        "no job-config reader found in lib.config "
        "(worker-b: expose read_job_config / load_config_json)"
    )


def test_round_trip_through_worker_b_reader(sample_config_path: Path) -> None:
    reader = _resolve_reader()
    loaded = reader(sample_config_path)
    # Reader may return a dataclass or a dict; normalise to dict.
    if hasattr(loaded, "__dict__") and not isinstance(loaded, dict):
        loaded_dict = {k: getattr(loaded, k) for k in REQUIRED_FIELDS}
    else:
        loaded_dict = dict(loaded)
    for key in REQUIRED_FIELDS:
        assert key in loaded_dict, f"reader dropped required field {key!r}"


def test_reader_refuses_unknown_version(tmp_path: Path) -> None:
    reader = _resolve_reader()
    cfg = _sample_config_v1()
    cfg["version"] = 99
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    with pytest.raises(Exception):  # noqa: BLE001 — reader picks the type
        reader(path)
