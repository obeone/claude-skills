"""Schema contract test.

Runs the in-process equivalent of ``python -m gemini_tts_mcp
--dump-schemas`` and compares each tool schema against the committed
fixture. Pass ``--update-fixtures`` to regenerate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gemini_tts_mcp.cli import SCHEMA_FIXTURES_DIR, dump_schemas


def _read_committed(name: str) -> dict:
    path: Path = SCHEMA_FIXTURES_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_dump_schemas_matches_committed_fixtures(tmp_path, request):
    if request.config.getoption("--update-fixtures"):
        written = dump_schemas(SCHEMA_FIXTURES_DIR)
        assert written, "expected at least one fixture to be written"
        return

    written = dump_schemas(tmp_path)
    assert written, "no schemas produced"

    for path in written:
        regenerated = json.loads(path.read_text(encoding="utf-8"))
        committed = _read_committed(path.name)
        assert regenerated == committed, (
            f"Schema drift in {path.name}. "
            "Run `pytest --update-fixtures` after intentional changes."
        )


def test_every_registered_tool_has_a_fixture():
    from gemini_tts_mcp.tools import all_definitions

    expected = {tool.name.replace(".", "_") + ".json" for tool in all_definitions()}
    present = {p.name for p in SCHEMA_FIXTURES_DIR.glob("*.json")}
    missing = expected - present
    assert not missing, f"missing fixtures: {sorted(missing)}"
