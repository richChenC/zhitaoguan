"""Serve the read-only TRAE sources against a disposable real-data snapshot."""
from datetime import datetime
import argparse
import os
from pathlib import Path
import sqlite3
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18789)
    args = parser.parse_args()
    native = Path(__file__).resolve().parents[2]
    reference = native.parent / "10_TRAEqt优化版"
    work = native.parent / "05_测试与验证" / "03_自动化临时产物" / (
        "native-reference-details-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    work.mkdir(parents=True)
    database = work / "data.db"
    source_path = native / "user-data/data/thimble.db"
    with sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True) as source, \
            sqlite3.connect(database) as target:
        source.backup(target)
        target.executescript("DELETE FROM login_sessions; DELETE FROM user_roles; DELETE FROM users;")
    for key, value in {
        "THIMBLE_USER_DATA_DIR": work, "THIMBLE_DB_PATH": database,
        "THIMBLE_DATA_DIR": work / "data", "THIMBLE_OUTPUT_DIR": work / "exports",
        "THIMBLE_REPORT_DIR": work / "reports", "THIMBLE_LOG_PATH": work / "server.log",
        "THIMBLE_MIGRATE_LEGACY": "0", "THIMBLE_PORT": args.port,
    }.items():
        os.environ[key] = str(value)
    sys.path.insert(0, str(reference))
    sys.path.insert(0, str(reference / ".vendor"))
    from src.backend import server
    print(f"Isolated TRAE data: {work}", flush=True)
    server.main()


if __name__ == "__main__":
    main()
