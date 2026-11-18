import json
import os
import socket
import time

import pytest

from earlydata_weekly_publisher.locking import FileLock, LockError, report_lock


def test_lock_blocks_a_second_holder_until_release(tmp_path):
    lock = report_lock(tmp_path, description="build")

    with lock:
        with pytest.raises(LockError, match="another build is already running"):
            FileLock(tmp_path / ".earlydata.lock", description="build").acquire()

    assert not (tmp_path / ".earlydata.lock").exists()
    with report_lock(tmp_path, description="build"):
        pass


def test_lock_file_records_the_owner(tmp_path):
    with report_lock(tmp_path, description="build"):
        info = json.loads((tmp_path / ".earlydata.lock").read_text(encoding="utf-8"))

    assert info["pid"] == os.getpid()
    assert info["host"] == socket.gethostname()
    assert isinstance(info["created_at"], float)


def test_lock_released_even_when_the_action_fails(tmp_path):
    lock = report_lock(tmp_path, description="build")

    with pytest.raises(RuntimeError):
        with lock:
            raise RuntimeError("boom")

    assert not (tmp_path / ".earlydata.lock").exists()


def test_lock_owned_by_a_dead_pid_is_reclaimed(tmp_path):
    path = tmp_path / ".earlydata.lock"
    path.write_text(
        json.dumps({"pid": 2**31 - 1, "host": socket.gethostname(), "created_at": time.time()}),
        encoding="utf-8",
    )

    lock = FileLock(path)
    lock.acquire()

    assert lock._held
    lock.release()


def test_old_lock_is_reclaimed_by_age(tmp_path):
    path = tmp_path / ".earlydata.lock"
    path.write_text(
        json.dumps({"pid": os.getpid(), "host": "other-host", "created_at": time.time() - 120}),
        encoding="utf-8",
    )

    lock = FileLock(path, stale_after=60)
    lock.acquire()

    assert lock._held
    lock.release()
