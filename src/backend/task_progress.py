"""Ephemeral, thread-isolated counters for the currently running import."""
import functools
import re
import threading
import time
from contextlib import contextmanager

_local = threading.local()
_lock = threading.Lock()
_tasks = {}
MAX_TASKS = 64
RETENTION_SECONDS = 600
PATHS = {"/api/import", "/api/import-excel", "/api/import-excel-inspect", "/api/report-options",
         "/api/export-folder-excel", "/api/states/import-preview", "/api/states/batch"}


def _validate(token):
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", token):
        raise ValueError("进度任务编号无效")


@contextmanager
def task(token):
    _validate(token)
    now = time.monotonic()
    with _lock:
        for key, value in list(_tasks.items()):
            if value["status"] != "running" and now - value["updated"] > RETENTION_SECONDS:
                del _tasks[key]
        if token in _tasks:
            raise ValueError("进度任务编号已使用，请重新发起")
        if len(_tasks) >= MAX_TASKS:
            finished = [key for key, value in _tasks.items() if value["status"] != "running"]
            if not finished:
                raise ValueError("正在处理的任务过多，请稍后重试")
            del _tasks[min(finished, key=lambda key: _tasks[key]["updated"])]
        _tasks[token] = dict(status="running", stage="准备处理", completed=0, total=None,
                             unit="行", started=now, percent=None, updated=now)
    previous = getattr(_local, "token", None)
    previous_span = getattr(_local, "span", (0, 100))
    _local.token = token
    _local.span = (0, 100)
    try:
        yield
    except BaseException:
        finish(False)
        raise
    else:
        finish(True)
    finally:
        _local.token = previous
        _local.span = previous_span


@contextmanager
def phase(start, end):
    """Map nested, real work counters into a planned part of the whole task."""
    parent = getattr(_local, "span", (0, 100))
    width = parent[1] - parent[0]
    _local.span = (parent[0] + width * start / 100, parent[0] + width * end / 100)
    try:
        yield
    finally:
        _local.span = parent


def step(stage, completed=0, total=None, unit="行"):
    token = getattr(_local, "token", None)
    if token is None:
        return
    now = time.monotonic()
    with _lock:
        value = _tasks[token]
        if value["status"] != "running":
            return
        start, end = getattr(_local, "span", (0, 100))
        if total:
            percent = start + (end - start) * min(1, max(0, completed / total))
            value["percent"] = min(99, max(value["percent"] or 0, percent))
        elif start:
            value["percent"] = max(value["percent"] or 0, min(99, start))
        value.update(stage=stage, completed=max(0, int(completed)),
                     total=max(0, int(total)) if total is not None else None,
                     unit=unit, updated=now)


def iterate(values, stage, total=None, unit="行", span=(0, 100), partitions=False):
    if getattr(_local, "token", None) is None:
        yield from values
        return
    if total is None and hasattr(values, "__len__"):
        total = len(values)
    with phase(*span):
        step(stage, 0, total, unit)
        for index, value in enumerate(values, 1):
            if partitions and total:
                with phase((index - 1) / total * 100, index / total * 100):
                    yield value
            else:
                yield value
            step(stage, index, total, unit)


def finish(success):
    token = getattr(_local, "token", None)
    if token is None:
        return
    with _lock:
        value = _tasks[token]
        if value["status"] != "running":
            return
        status = "awaiting_confirmation" if success and value.get("awaiting_confirmation") else "succeeded" if success else "failed"
        value.update(status=status, updated=time.monotonic())


def wait_for_confirmation():
    token = getattr(_local, "token", None)
    if token is not None:
        with _lock:
            _tasks[token]["awaiting_confirmation"] = True


def snapshot(token):
    _validate(token)
    with _lock:
        if token not in _tasks:
            return None
        value = dict(_tasks[token])
    now = time.monotonic() if value["status"] == "running" else value["updated"]
    completed, total = value["completed"], value["total"]
    percent = value["percent"]
    elapsed = now - value["started"]
    eta = elapsed * (100 - percent) / percent if percent else None
    if value["status"] == "succeeded":
        percent, eta = 100, 0
    elif value["status"] == "failed":
        eta = None
    return {key: value[key] for key in ("status", "stage", "completed", "total", "unit")} | {
        "percent": percent, "elapsed_seconds": now - value["started"],
        "remaining_seconds": eta,
    }


def track_http(handler):
    @functools.wraps(handler)
    def wrapped(self):
        token = self.headers.get("X-Thimble-Task")
        if not token or self.path not in PATHS or not self.request_is_local():
            return handler(self)
        try:
            with task(token):
                return handler(self)
        except ValueError as error:
            return self.json_response({"error": str(error)}, 400)
    return wrapped
