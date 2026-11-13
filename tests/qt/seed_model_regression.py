"""Create a read-only snapshot and seed genuine H209 RPT records for 3D probes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import sys


def main():
    project = Path(__file__).resolve().parents[2]
    artifact_root = (project.parent / "05_测试与验证/03_自动化临时产物").resolve()
    work = Path(sys.argv[1]).resolve()
    if not work.is_relative_to(artifact_root):
        raise ValueError("Regression data must stay within the test artifact directory")
    work.mkdir(parents=True, exist_ok=True)
    database = work / "real-data.db"
    if database.exists():
        raise FileExistsError(database)
    source = project / "user-data/data/thimble.db"
    with sqlite3.connect(source.resolve().as_uri()+"?mode=ro", uri=True) as src:
        with sqlite3.connect(database) as target:
            src.backup(target)
    for key, value in {"THIMBLE_QT_TEST_DATA_ROOT": work, "THIMBLE_DB_PATH": database,
                       "THIMBLE_DATA_DIR": work / "data", "THIMBLE_OUTPUT_DIR": work / "output",
                       "THIMBLE_REPORT_DIR": work / "reports"}.items():
        os.environ[key] = str(value)
    from src.backend import server
    server.init_db()
    directory = (project.parent / "02_项目原始资料/03_原始检测数据/测试数据/"
                 "指套管数据1/H209/数据/2.3 指套管")
    selected = server.automatic_report_selection(str(directory), "latest")
    imported = server.import_directory(str(directory), selected)
    with sqlite3.connect(database) as connection:
        tubes = connection.execute(
            "SELECT count(DISTINCT thimble_id) FROM findings WHERE outage='H209'").fetchone()[0]
    print(json.dumps({"reports": len(selected), "tubes": tubes, **imported}, ensure_ascii=False, default=str))
    if imported.get("errors") or imported.get("error_total") or tubes != 50:
        raise AssertionError("Genuine RPT seeding did not complete successfully")


if __name__ == "__main__":
    main()
