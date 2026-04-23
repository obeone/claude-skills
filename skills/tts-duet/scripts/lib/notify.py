"""Cross-platform notification chain for the tts-duet skill.

A single entry point, :func:`notify`, tries notifiers in order and
returns the name of the first one that succeeded:

1. ``kitten`` — when running under Kitty (``$TERM=xterm-kitty`` or
   ``$KITTY_WINDOW_ID`` set) AND the parent PTY exists as a
   ``/dev/<tty>`` node. Uses ``--only-print-escape-code`` to emit the
   OSC 99 sequence directly to the parent PTY.
2. ``alerter`` — on macOS only, when the ``alerter`` binary is on
   ``$PATH``.
3. ``osascript`` — on macOS only, via ``display notification``.
4. ``not-available`` — no notifier worked; the caller can fall back to
   a status file.

The function is intentionally total: it never raises. Failures are
logged at DEBUG only so background jobs (§3.5) stay green even when
the host has no notification stack. When ``job_dir`` is provided, the
winning tier is written to ``<job_dir>/notification`` (a single line),
so remote tooling can consult the notification outcome without
re-deriving it.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal

from ._safe_env import safe_env

__all__ = ["notify"]

_LOG = logging.getLogger(__name__)

_Tier = Literal["kitten", "alerter", "osascript", "not-available"]
_Urgency = Literal["low", "normal", "critical"]


def _in_kitty() -> bool:
    """Return whether the current session looks like a Kitty terminal."""
    if os.environ.get("TERM") == "xterm-kitty":
        return True
    return bool(os.environ.get("KITTY_WINDOW_ID"))


def _parent_tty() -> str | None:
    """Return the parent process' TTY device name, or ``None``.

    Uses ``ps -o tty= -p $PPID`` and only returns a value when the
    corresponding ``/dev/<tty>`` node exists and is writable.
    """
    try:
        proc = subprocess.run(
            ["ps", "-o", "tty=", "-p", str(os.getppid())],
            check=False,
            capture_output=True,
            timeout=5,
            env=safe_env(for_mcp=False),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _LOG.debug("ps lookup for parent TTY failed: %s", exc)
        return None
    if proc.returncode != 0:
        return None
    tty_name = proc.stdout.decode("utf-8", errors="replace").strip()
    if not tty_name or tty_name == "?":
        return None
    dev_path = Path("/dev") / tty_name
    if not dev_path.exists():
        return None
    return str(dev_path)


def _try_kitten(title: str, message: str, urgency: _Urgency) -> bool:
    """Attempt the ``kitten notify`` tier. Return ``True`` on success."""
    if not _in_kitty():
        return False
    if shutil.which("kitten") is None:
        return False
    dev_path = _parent_tty()
    if dev_path is None:
        return False
    try:
        proc = subprocess.run(
            [
                "kitten",
                "notify",
                "--only-print-escape-code",
                f"--urgency={urgency}",
                title,
                message,
            ],
            check=False,
            capture_output=True,
            timeout=5,
            env=safe_env(for_mcp=False),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _LOG.debug("kitten notify failed: %s", exc)
        return False
    if proc.returncode != 0 or not proc.stdout:
        return False
    try:
        with open(dev_path, "wb") as handle:
            handle.write(proc.stdout)
    except OSError as exc:
        _LOG.debug("writing OSC 99 to %s failed: %s", dev_path, exc)
        return False
    return True


def _try_alerter(title: str, message: str) -> bool:
    """Attempt the ``alerter`` tier. Return ``True`` on success."""
    if sys.platform != "darwin":
        return False
    if shutil.which("alerter") is None:
        return False
    try:
        proc = subprocess.run(
            [
                "alerter",
                "--title",
                title,
                "--message",
                message,
                "--sender",
                "com.microsoft.VSCode",
            ],
            check=False,
            capture_output=True,
            timeout=5,
            env=safe_env(for_mcp=False),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _LOG.debug("alerter failed: %s", exc)
        return False
    return proc.returncode == 0


def _try_osascript(title: str, message: str) -> bool:
    """Attempt the ``osascript`` tier. Return ``True`` on success."""
    if sys.platform != "darwin":
        return False
    if shutil.which("osascript") is None:
        return False
    safe_title = title.replace('"', '\\"')
    safe_message = message.replace('"', '\\"')
    script = f'display notification "{safe_message}" with title "{safe_title}"'
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            timeout=5,
            env=safe_env(for_mcp=False),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _LOG.debug("osascript failed: %s", exc)
        return False
    return proc.returncode == 0


def notify(
    title: str,
    message: str,
    *,
    job_dir: Path | None = None,
    urgency: _Urgency = "normal",
) -> _Tier:
    """Try every notification tier in order and return the one that won.

    Parameters
    ----------
    title : str
        Notification title.
    message : str
        Notification body.
    job_dir : Path or None, optional
        If set, the winning tier is written (as a single line) to
        ``<job_dir>/notification``. Failures to write are swallowed.
    urgency : {"low", "normal", "critical"}, optional
        Forwarded to notifiers that support it (``kitten``). Default
        is ``"normal"``.

    Returns
    -------
    {"kitten", "alerter", "osascript", "not-available"}
        Name of the first tier that succeeded. ``"not-available"``
        when every tier was unavailable or failed.

    Notes
    -----
    This function never raises. Individual tier failures are logged at
    DEBUG. Background callers should treat the returned value as
    advisory and rely on the status file for authoritative state.
    """
    winner: _Tier = "not-available"

    # Suppress actual notification spawns inside test runs or when the
    # caller opts out explicitly. The ``<job_dir>/notification`` file is
    # still written below so downstream tooling can observe the outcome.
    suppressed = bool(
        os.environ.get("TTS_DUET_NO_NOTIFY")
        or os.environ.get("PYTEST_CURRENT_TEST")
    )

    if suppressed:
        pass
    elif _try_kitten(title, message, urgency):
        winner = "kitten"
    elif _try_alerter(title, message):
        winner = "alerter"
    elif _try_osascript(title, message):
        winner = "osascript"

    if job_dir is not None:
        try:
            job_dir.mkdir(parents=True, exist_ok=True)
            (job_dir / "notification").write_text(
                winner + "\n", encoding="utf-8"
            )
        except OSError as exc:
            _LOG.debug("failed to record notification tier to %s: %s", job_dir, exc)

    return winner
