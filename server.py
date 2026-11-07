"""Compatibility entry point for the reorganized backend."""
import sys

from src.backend import server as _backend

if __name__ == "__main__":
    _backend.main()
else:
    sys.modules[__name__] = _backend
