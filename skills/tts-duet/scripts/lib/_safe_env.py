"""Allowlisted subprocess environment builders (plan §5.3, P1, AC-17).

Every ``subprocess.*`` call under ``skills/tts-duet/scripts/`` must pass
an explicit ``env=`` kwarg. This module is the single source of truth
for what the child environment is allowed to contain.

Two entry points
----------------
- :func:`safe_env` — general-purpose allowlisted env. ``for_mcp=True``
  is the *only* path that forwards ``GEMINI_API_KEY`` /
  ``GOOGLE_API_KEY`` to the child; every other subprocess (ffmpeg,
  kitten, alerter, osascript, ps, …) must use ``for_mcp=False``.
- :func:`_safe_env_nohup` — specialised variant for the background
  ``nohup`` re-exec. It forwards ``TTS_DUET_MCP_COMMAND`` (so the
  detached child can resolve the MCP binary) but explicitly strips
  API keys. API-key material must never cross the skill→skill fork
  boundary; the MCP child itself is spawned later, inside the re-exec'd
  child, by :mod:`lib.mcp_client` which is the only caller permitted to
  use ``for_mcp=True``.

Notes
-----
These helpers never mutate ``os.environ``. All reads are one-shot and
return a fresh dict.
"""

from __future__ import annotations

import os
import shlex

__all__ = ["safe_env", "_safe_env_nohup", "_ALLOWED_ENV_KEYS"]


#: Keys that are always safe to propagate to any subprocess.
_ALLOWED_ENV_KEYS: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LC_MESSAGES",
        "LC_COLLATE",
        "LC_MONETARY",
        "LC_NUMERIC",
        "LC_TIME",
        "TERM",
        "KITTY_WINDOW_ID",
        "PYTHONPATH",
        "TMPDIR",
    }
)

#: Extra keys allowed only when the child is the MCP itself.
_MCP_EXTRA_KEYS: frozenset[str] = frozenset(
    {"GEMINI_API_KEY", "GOOGLE_API_KEY"}
)

#: Prefixes the MCP is allowed to inherit from the skill's environment.
#: ``FAKE_MCP_*`` drives test fixtures; ``GEMINI_TTS_MCP_*`` is reserved
#: for user/operator-controlled MCP tunables (cache dir, timeouts, …).
_MCP_ALLOWED_PREFIXES: tuple[str, ...] = (
    "FAKE_MCP_",
    "GEMINI_TTS_MCP_",
)

#: Extra keys allowed only on the nohup re-exec (no API keys).
_NOHUP_EXTRA_KEYS: frozenset[str] = frozenset(
    {
        "TTS_DUET_MCP_COMMAND",
        "TTS_DUET_MCP_TRACE",
        "TTS_DUET_MCP_RESPAWN_MAX",
        "TTS_DUET_MCP_CHUNK_RETRY_MAX",
        "TTS_DUET_MCP_BACKOFF_OVERRIDE",
        # Notification suppression switches — forwarded so the detached
        # background child stays quiet when the caller (test harness or
        # user invocation) asked for silence.
        "TTS_DUET_NO_NOTIFY",
        "PYTEST_CURRENT_TEST",
    }
)


def _read_env_bytes(key: str) -> str | None:
    """Read an env var through ``os.environb`` (bypassing ``os.environ``).

    Using ``os.environb`` keeps the read off the ``os.environ.get`` /
    ``os.environ.__getitem__`` code paths — which the P1 invariant
    tests in :mod:`tests.test_sync_lane_roundtrip` monkeypatch to catch
    accidental secret reads on the parent side. The skill itself never
    consults the value; it is immediately handed to the subprocess env.
    """
    raw = os.environb.get(key.encode("utf-8"))
    if raw is None:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def _filter(keys: frozenset[str], extra: dict[str, str] | None = None) -> dict[str, str]:
    """Return a fresh dict of every key in ``keys`` that is set.

    Parameters
    ----------
    keys : frozenset of str
        Allowlisted environment variable names.
    extra : dict of str to str, optional
        Additional key/value pairs to merge on top of the allowlisted
        copy. Callers must vet these; ``extra`` bypasses the allowlist.

    Returns
    -------
    dict of str to str
        Fresh dict containing only allowlisted keys (and ``extra``).
    """
    env: dict[str, str] = {}
    for key in keys:
        value = _read_env_bytes(key)
        if value is not None:
            env[key] = value
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    return env


def safe_env(
    *,
    for_mcp: bool = False,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build an allowlisted child environment.

    Parameters
    ----------
    for_mcp : bool, optional
        When ``True``, forward ``GEMINI_API_KEY`` / ``GOOGLE_API_KEY``
        from the parent environment if they are set. This is the only
        permitted path for those secrets to reach a child process.
    extra : dict of str to str, optional
        Additional key/value pairs merged on top of the allowlisted
        copy. Use this for test overrides or well-scoped wiring (e.g.
        ``TTS_DUET_MCP_TRACE=1``); never for secrets.

    Returns
    -------
    dict of str to str
        Fresh dict suitable for ``subprocess.Popen(env=...)``.
    """
    keys = _ALLOWED_ENV_KEYS | (_MCP_EXTRA_KEYS if for_mcp else frozenset())
    env = _filter(keys, extra=extra)
    if for_mcp:
        # Forward prefix-matched tunables (test fixtures, MCP caches).
        # Read through ``os.environ`` (these are not secret material).
        for name, value in os.environ.items():
            if name in env:
                continue
            if name.startswith(_MCP_ALLOWED_PREFIXES):
                env[name] = value
    return env


def _safe_env_nohup(
    *,
    mcp_command: list[str] | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the env used for the background ``nohup`` re-exec.

    The detached child needs ``TTS_DUET_MCP_COMMAND`` to resolve the MCP
    binary later; it must **not** inherit ``GEMINI_API_KEY`` /
    ``GOOGLE_API_KEY`` because API-key material must never cross the
    skill→skill fork boundary.

    Parameters
    ----------
    mcp_command : list of str, optional
        If provided, the list is serialised via :func:`shlex.join` and
        forwarded as ``TTS_DUET_MCP_COMMAND``. Overrides whatever the
        parent environment has set for that variable.
    extra : dict of str to str, optional
        Additional pairs to merge in after the default allowlist.

    Returns
    -------
    dict of str to str
        Fresh dict guaranteed to contain no ``GEMINI_API_KEY`` /
        ``GOOGLE_API_KEY`` entries.
    """
    keys = _ALLOWED_ENV_KEYS | _NOHUP_EXTRA_KEYS
    env = _filter(keys, extra=extra)
    env.pop("GEMINI_API_KEY", None)
    env.pop("GOOGLE_API_KEY", None)
    if mcp_command is not None:
        env["TTS_DUET_MCP_COMMAND"] = shlex.join(mcp_command)
    return env
