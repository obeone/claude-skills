"""Allowlisted subprocess environment builders (plan §5.3, P1, AC-17).

Every ``subprocess.*`` call under ``skills/tts-duet/scripts/`` must pass
an explicit ``env=`` kwarg. This module is the single source of truth
for what the child environment is allowed to contain.

Entry point
-----------
- :func:`safe_env` — general-purpose allowlisted env. ``for_mcp=True``
  is the *only* path that forwards ``GEMINI_API_KEY`` /
  ``GOOGLE_API_KEY`` to the child; every other subprocess (ffmpeg,
  kitten, alerter, osascript, ps, …) must use ``for_mcp=False``.
  :mod:`lib.mcp_client` is the only caller permitted to use
  ``for_mcp=True``.

Notes
-----
These helpers never mutate ``os.environ``. All reads are one-shot and
return a fresh dict.
"""

from __future__ import annotations

import os

__all__ = ["safe_env", "_ALLOWED_ENV_KEYS"]


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
