from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path
from typing import Any


LOCK_NAME = ".earlydata.lock"
STALE_AFTER_SECONDS = 6 * 60 * 60


class LockError(RuntimeError):
    """Raised when another process already holds a lock."""


class FileLock:
    """A small cross-platform advisory lock based on atomic file creation.

    The lock file records the owning pid, host and creation time. A lock is
    treated as stale when it is older than ``stale_after`` seconds, or when
    it belongs to a pid that no longer exists on this host.
    """

    def __init__(self, path: Path, *, description: str = "operation", stale_after: float = STALE_AFTER_SECONDS) -> None:
        self.path = Path(path)
        self.description = description
        self.stale_after = stale_after
        self._held = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _attempt in range(2):
            try:
                handle = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if self._clear_if_stale():
                    continue
                raise LockError(self._conflict_message()) from None
            try:
                os.write(
                    handle,
                    json.dumps(
                        {
                            "pid": os.getpid(),
                            "host": socket.gethostname(),
                            "created_at": time.time(),
                        }
                    ).encode("utf-8"),
                )
            finally:
                os.close(handle)
            self._held = True
            return
        raise LockError(self._conflict_message())

    def release(self) -> None:
        if not self._held:
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        self._held = False

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc: BaseException | None, traceback: Any) -> bool:
        self.release()
        return False

    def _clear_if_stale(self) -> bool:
        info = self._read()
        created = info.get("created_at")
        if isinstance(created, (int, float)) and time.time() - created > self.stale_after:
            return self._unlink()
        pid = info.get("pid")
        host = info.get("host")
        if isinstance(pid, int) and host == socket.gethostname() and not _pid_alive(pid):
            return self._unlink()
        try:
            modified = self.path.stat().st_mtime
        except OSError:
            return False
        if time.time() - modified > self.stale_after:
            return self._unlink()
        return False

    def _read(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def _unlink(self) -> bool:
        try:
            self.path.unlink()
        except FileNotFoundError:
            return True
        except OSError:
            return False
        return True

    def _conflict_message(self) -> str:
        info = self._read()
        owner = ""
        if info.get("pid"):
            owner = f" (pid {info['pid']} on {info.get('host') or 'unknown host'})"
        return (
            f"another {self.description} is already running for {self.path.parent}{owner}; "
            f"remove {self.path} if that run crashed."
        )


def report_lock(directory: Path, *, description: str) -> FileLock:
    """Lock one report directory so build, run and publish cannot overlap."""
    return FileLock(Path(directory) / LOCK_NAME, description=description)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OverflowError):
        return False
    except PermissionError:
        return True
    return True


def _pid_alive_windows(pid: int) -> bool:
    import ctypes

    process_query_limited_information = 0x1000
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True
