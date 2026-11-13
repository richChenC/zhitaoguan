"""Private pipe-only mesh calculator; no GUI, service, or database startup."""
from __future__ import annotations

import base64
import json
import os
import sys


def pipe_stream(name, identifier, mode):
    stream = getattr(sys, name)
    if stream is not None:
        return stream
    # Windowed PyInstaller sets sys.stdin/stdout to None despite QProcess's inherited pipes.
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    handle = kernel.GetStdHandle(identifier)
    if handle in (None, wintypes.HANDLE(-1).value):
        raise OSError("Missing inherited section pipe")
    flags = (os.O_RDONLY if mode == "r" else os.O_WRONLY) | os.O_BINARY
    descriptor = msvcrt.open_osfhandle(handle, flags)
    return open(descriptor, mode, encoding="utf-8", newline="\n")


def main():
    from PySide6.QtCore import QCoreApplication
    from .native_sections import SectionEngine
    app = QCoreApplication([])
    engine = SectionEngine(app)
    source = pipe_stream("stdin", -10, "r")
    output = pipe_stream("stdout", -11, "w")
    for line in source:
        results = []
        for identity, revision, options in json.loads(line):
            try:
                data = engine.mesh(*options)
                serialized = (base64.b64encode(data[0]).decode("ascii"),
                              base64.b64encode(data[1]).decode("ascii"), *data[2:])
                results.append((identity, revision, serialized, None))
            except (OSError, ValueError, RuntimeError, KeyError) as error:
                results.append((identity, revision, None, str(error)))
        output.write(json.dumps(results) + "\n")
        output.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
