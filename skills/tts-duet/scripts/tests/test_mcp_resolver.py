"""Resolver-default regression tests for the C2 PyPI pin.

The one named code change of the tts-duet plugin work points
``mcp_client._VENDORED_FALLBACK`` at the published PyPI spec
``gemini-tts-mcp==0.3.0`` (the ``--from`` form), replacing the legacy
git ref ``git+https://github.com/obeone/claude-skills@v2.3.0#...``.

- **T-U2** (offline, MUST pass now): with no env / no config and the
  binary not on ``$PATH``, ``resolve_mcp_command()`` returns exactly
  ``["uvx", "--from", "gemini-tts-mcp==0.3.0", "gemini-tts-mcp"]``; the
  legacy ``git+...@v2.3.0`` string is gone; ``TTS_DUET_MCP_COMMAND``
  still wins (precedence intact). No network.
- **T-U2x** (executable probe, skip-until-published): runs
  ``uvx --from gemini-tts-mcp==0.3.0 gemini-tts-mcp --protocol-version``
  and asserts exit 0 AND stdout == the MCP protocol version string
  (``"1"``, from ``gemini_tts_mcp.server.PROTOCOL_VERSION``;
  ``--protocol-version`` is a non-short-circuit ``store_true`` flag in
  ``cli._build_parser()``). Plus a negative sub-assertion that the
  broken bare-positional form
  ``uvx gemini-tts-mcp==0.3.0 gemini-tts-mcp --protocol-version`` exits
  non-zero (the trailing token is passed as argv to the entrypoint and
  argparse rejects it). T-U2x requires ``gemini-tts-mcp==0.3.0`` to
  exist on prod PyPI, which happens only at the owned prod-publish
  release step (build sequence step 10). It is therefore skipped unless
  ``TTS_DUET_PYPI_PUBLISHED=1`` is set. **The verification pass (build
  sequence step 11) sets that flag to flip this test on post-publish.**
  The skip is intentional and explicit — not a silent pass.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from lib._safe_env import safe_env  # noqa: E402 — sys.path patched by conftest

_mcp_client = pytest.importorskip(
    "lib.mcp_client",
    reason="lib.mcp_client not importable from scripts/ (conftest sys.path)",
)

#: The pinned PyPI fallback the C2 change must produce. Kept in lockstep
#: with ``mcp/pyproject.toml`` and ``plugin.json`` ``mcpServers`` args.
EXPECTED_PINNED_FALLBACK = [
    "uvx",
    "--from",
    "gemini-tts-mcp==0.3.0",
    "gemini-tts-mcp",
]

#: The MCP protocol version string the server prints for
#: ``--protocol-version`` (``gemini_tts_mcp.server.PROTOCOL_VERSION``).
EXPECTED_PROTOCOL_VERSION = "1"

_PYPI_PUBLISHED = os.environ.get("TTS_DUET_PYPI_PUBLISHED") == "1"


# ---------------------------------------------------------------------------
# T-U2 — resolver-default regression (offline, MUST pass now)
# ---------------------------------------------------------------------------


def test_resolver_default_is_pinned_pypi_from_form() -> None:
    """No env / no config / not on PATH → the pinned PyPI --from tuple."""
    resolved = _mcp_client.resolve_mcp_command(config=None, env={})
    assert resolved == EXPECTED_PINNED_FALLBACK


def test_resolver_default_is_pinned_not_floating() -> None:
    """The pin is exact (``==0.3.0``), never a floating ``>=`` spec."""
    spec = _mcp_client._VENDORED_FALLBACK
    assert spec == tuple(EXPECTED_PINNED_FALLBACK)
    joined = " ".join(spec)
    assert "==0.3.0" in joined
    assert ">=" not in joined


def test_resolver_legacy_git_ref_is_gone() -> None:
    """The legacy ``git+...@v2.3.0`` ref must not survive anywhere."""
    spec = " ".join(_mcp_client._VENDORED_FALLBACK)
    assert "git+" not in spec
    assert "v2.3.0" not in spec
    assert "github.com/obeone/claude-skills" not in spec


def test_env_command_still_wins_over_pinned_fallback() -> None:
    """``TTS_DUET_MCP_COMMAND`` precedence is unbroken by the C2 change."""
    resolved = _mcp_client.resolve_mcp_command(
        config=None,
        env={"TTS_DUET_MCP_COMMAND": "/opt/custom/gemini-tts-mcp --flag"},
    )
    assert resolved == ["/opt/custom/gemini-tts-mcp", "--flag"]
    assert resolved != EXPECTED_PINNED_FALLBACK


# ---------------------------------------------------------------------------
# T-U2x — executable uvx-form probe (skip until prod PyPI publish)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _PYPI_PUBLISHED,
    reason=(
        "requires gemini-tts-mcp==0.3.0 on prod PyPI; published at build "
        "sequence step 10 and verified at step 11 (set "
        "TTS_DUET_PYPI_PUBLISHED=1 to run)"
    ),
)
def test_uvx_from_form_resolves_and_runs_protocol_version() -> None:
    """``--from`` form exits 0 and prints the MCP protocol version.

    Flipped on by the post-publish verification pass (step 11) via
    ``TTS_DUET_PYPI_PUBLISHED=1``. Until then this is an explicit,
    intentional skip — never a silent pass.
    """
    proc = subprocess.run(
        [
            "uvx",
            "--from",
            "gemini-tts-mcp==0.3.0",
            "gemini-tts-mcp",
            "--protocol-version",
        ],
        capture_output=True,
        text=True,
        timeout=300.0,
        check=False,
        env=safe_env(for_mcp=False),
    )
    assert proc.returncode == 0, (
        f"--from form must exit 0, got {proc.returncode}; "
        f"stderr={proc.stderr[-400:]}"
    )
    assert proc.stdout.strip() == EXPECTED_PROTOCOL_VERSION, (
        f"expected protocol version {EXPECTED_PROTOCOL_VERSION!r}, "
        f"got stdout={proc.stdout!r}"
    )


@pytest.mark.skipif(
    not _PYPI_PUBLISHED,
    reason=(
        "requires gemini-tts-mcp==0.3.0 on prod PyPI; published at build "
        "sequence step 10 and verified at step 11 (set "
        "TTS_DUET_PYPI_PUBLISHED=1 to run)"
    ),
)
def test_uvx_bare_positional_form_exits_nonzero() -> None:
    """Negative sub-assert: the bare-positional form must fail.

    ``uvx gemini-tts-mcp==0.3.0 gemini-tts-mcp --protocol-version``
    passes ``gemini-tts-mcp`` as argv to the entrypoint instead of to
    uvx; argparse rejects the unexpected positional (SystemExit 2). This
    is exactly the C1 bug the ``--from`` form avoids.
    """
    proc = subprocess.run(
        [
            "uvx",
            "gemini-tts-mcp==0.3.0",
            "gemini-tts-mcp",
            "--protocol-version",
        ],
        capture_output=True,
        text=True,
        timeout=300.0,
        check=False,
        env=safe_env(for_mcp=False),
    )
    assert proc.returncode != 0, (
        "bare-positional form must exit non-zero (the trailing token is "
        f"passed as argv to the entrypoint); got {proc.returncode}; "
        f"stdout={proc.stdout[-200:]} stderr={proc.stderr[-200:]}"
    )
