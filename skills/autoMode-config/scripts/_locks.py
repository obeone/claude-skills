"""Per-file advisory locking with stale-lock reclaim.

Each settings file the skill writes to has its own ``.lock`` sibling.
Locks are acquired with ``fcntl.flock(LOCK_EX | LOCK_NB)`` so a second
concurrent invocation fails immediately with ``BlockingIOError``.

A lock payload of ``"<PID> <ISO8601>"`` is written into the lock file at
acquire time so external tooling (and ``--repair``) can detect dead PIDs
or expired locks.

Stdlib-only.
"""

from __future__ import annotations

import datetime as _dt
import errno
import fcntl
import os
import signal
import sys
from dataclasses import dataclass
from pathlib import Path


LOCK_STALE_SECONDS = 300


class LockHeldError(Exception):
    """Raised when a lock cannot be acquired (held by another process)."""


class LockReclaimError(Exception):
    """Raised when stale-lock reclaim fails after the holder is gone."""


@dataclass
class LockHandle:
    """Handle for an acquired lock.

    Attributes
    ----------
    path : Path
        Path to the lock file.
    fd : int
        Underlying file descriptor; ``release()`` closes it.
    owner_pid : int
        PID of the process that holds the lock (always ``os.getpid()``).
    acquired_at : datetime
        Wall-clock acquisition time (UTC).
    """

    path: Path
    fd: int
    owner_pid: int
    acquired_at: _dt.datetime


def _now_iso() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec="seconds")


def _read_payload(path: Path) -> tuple[int, _dt.datetime] | None:
    """Return ``(pid, acquired_at)`` from ``path`` or ``None`` if invalid."""

    try:
        raw = path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, PermissionError):
        return None
    if not raw:
        return None
    parts = raw.split(maxsplit=1)
    if len(parts) != 2:
        return None
    try:
        pid = int(parts[0])
    except ValueError:
        return None
    try:
        ts = _dt.datetime.fromisoformat(parts[1])
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_dt.timezone.utc)
    return pid, ts


def _pid_alive(pid: int) -> bool:
    """Return True if ``pid`` exists and is signalable."""

    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        return True
    return True


def is_stale(path: Path, *, ttl_seconds: int = LOCK_STALE_SECONDS) -> bool:
    """Return True when the lock at ``path`` is stale.

    A lock is stale if its payload is missing, malformed, references a
    dead PID, or carries a timestamp older than ``ttl_seconds``.
    """

    payload = _read_payload(path)
    if payload is None:
        return True
    pid, ts = payload
    if pid != os.getpid() and not _pid_alive(pid):
        return True
    age = (_dt.datetime.now(tz=_dt.timezone.utc) - ts).total_seconds()
    return age > ttl_seconds


def reclaim_if_stale(path: Path, *, ttl_seconds: int = LOCK_STALE_SECONDS) -> bool:
    """Remove ``path`` when stale; return True if reclaimed."""

    if not path.exists():
        return False
    if not is_stale(path, ttl_seconds=ttl_seconds):
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise LockReclaimError(
            f"could not reclaim stale lock {path}: {exc}"
        ) from exc
    return True


def acquire(path: str | os.PathLike[str], *, ttl: int = LOCK_STALE_SECONDS) -> LockHandle:
    """Acquire ``path`` with ``LOCK_EX|LOCK_NB``, reclaiming stale locks.

    Parameters
    ----------
    path : str or os.PathLike
        Lock-file path. Created with mode 0600.
    ttl : int
        Stale-lock TTL in seconds (default: 300).

    Returns
    -------
    LockHandle
        Handle suitable for ``release(handle)``.

    Raises
    ------
    LockHeldError
        Another live process holds the lock.
    LockReclaimError
        Stale lock could not be removed.
    """

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    reclaim_if_stale(p, ttl_seconds=ttl)

    flags = os.O_RDWR | os.O_CREAT
    fd = os.open(p, flags, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(fd)
        raise LockHeldError(f"lock held: {p}") from exc

    pid = os.getpid()
    now = _dt.datetime.now(tz=_dt.timezone.utc)
    payload = f"{pid} {now.isoformat(timespec='seconds')}\n".encode("utf-8")
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, payload)
    os.fsync(fd)

    return LockHandle(path=p, fd=fd, owner_pid=pid, acquired_at=now)


def release(handle: LockHandle, *, remove_file: bool = True) -> None:
    """Release ``handle`` and (by default) remove the lock file."""

    try:
        fcntl.flock(handle.fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(handle.fd)
    except OSError:
        pass
    if remove_file:
        try:
            handle.path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def install_signal_release(handle: LockHandle) -> None:
    """Install best-effort SIGTERM/SIGINT handlers that release ``handle``.

    The original handlers are chained so the process still terminates.
    """

    def _make(orig):
        def _handler(signum, frame):
            try:
                release(handle)
            finally:
                if callable(orig):
                    try:
                        orig(signum, frame)
                    except Exception:
                        sys.exit(128 + signum)
                else:
                    sys.exit(128 + signum)
        return _handler

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            orig = signal.getsignal(sig)
            signal.signal(sig, _make(orig))
        except (ValueError, OSError):
            pass
