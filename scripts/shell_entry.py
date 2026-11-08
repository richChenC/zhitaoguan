"""Frozen native Qt entry point, with normal event-loop teardown."""
import sys

from qt_shell.main import main

sys.exit(main())
