"""Read-only TRAE source preview backed by an isolated SQLite snapshot."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18886)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[2]
    reference = project.parent / "10_TRAEqt优化版"
    artifacts = project.parent / "05_测试与验证" / "03_自动化临时产物"
    work = artifacts / ("native-trae-reference-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    work.mkdir(parents=True)
    database = work / "data" / "thimble.db"
    database.parent.mkdir()
    with closing(sqlite3.connect((project / "user-data/data/thimble.db").as_uri() + "?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(database)) as target:
            source.backup(target)
            target.executescript("DELETE FROM login_sessions; DELETE FROM user_roles; DELETE FROM users;")
            target.commit()
    for key, value in {"THIMBLE_USER_DATA_DIR": work, "THIMBLE_DATA_DIR": database.parent,
                       "THIMBLE_DB_PATH": database, "THIMBLE_OUTPUT_DIR": work / "exports",
                       "THIMBLE_REPORT_DIR": work / "reports", "THIMBLE_LOG_PATH": work / "server.log"}.items():
        os.environ[key] = str(value)
    os.environ.pop("THIMBLE_MIGRATE_LEGACY", None)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(reference))
    from src.backend import server
    server.init_db()
    httpd = server.LocalHTTPServer(("127.0.0.1", args.port), server.Handler)
    print(json.dumps({"url": f"http://127.0.0.1:{args.port}", "artifacts": str(work)}), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
