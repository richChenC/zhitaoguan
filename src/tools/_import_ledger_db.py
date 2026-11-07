"""将「导入台账_全量72次大修.xlsx」全量写入 thimble.db（干净替换）。

为什么是「替换」而非「追加」：
- server.import_excel_file 用 INSERT OR IGNORE，主键 (outage,unit_id,thimble_id)。
- 库里原有 584 条 H/N/Y 会与 xlsx 中同名行主键冲突被跳过，导致：
  (a) 总数停留在 ~584+新增，达不到 4867；(b) 4 处已校正录入错误（H1 ch3、H4 ch13 等）
  因旧行不更新而无法生效。
- 故先清空 findings 及其子表，再调用 import_excel_file，使全部 4867 条（含校正值）落库。

复用 server.import_excel_file 而非自写解析，确保列别名/校验逻辑与软件完全一致。
server.py 本身不改动（仅作为模块被调用）。
"""
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP_DIR))
from src.backend import server  # noqa: E402

XLSX = APP_DIR / "项目资料" / "06_台账与计划" / "导入台账_全量72次大修.xlsx"


def main() -> None:
    generated = APP_DIR / "output" / "ledgers" / XLSX.name
    workbook = generated if generated.is_file() else XLSX
    if not workbook.is_file():
        raise SystemExit(f"找不到台账 Excel：{workbook}")
    server.init_db()  # 确保 schema/WAL 就绪（幂等）

    with server.connect() as db:
        n0 = db.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
    print(f"[before] findings = {n0}")

    # 干净替换：先清子表再清主表（无 FK 约束，但按依赖顺序更稳）
    with server.connect() as db:
        db.execute("DELETE FROM indication_resolution_audit")
        db.execute("DELETE FROM duplicate_records")
        db.execute("DELETE FROM findings")
    print("[cleared] findings / duplicate_records / indication_resolution_audit")

    # 调用软件自身的导入逻辑（blank_indication_policy="" 会先 check 再 review 插入）
    result = server.import_excel_file(str(workbook), "")
    print("[import_excel_file] ->")
    for k in ("file", "sheet", "header_row", "parsed", "inserted", "skipped", "invalid_rows"):
        print(f"    {k}: {result.get(k)}")
    bi = result.get("blank_indication", {})
    print(f"    blank_indication.count: {bi.get('count')}")

    with server.connect() as db:
        total = db.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
        by_site = db.execute(
            "SELECT site_code, COUNT(*) c FROM findings GROUP BY site_code ORDER BY site_code"
        ).fetchall()
    print(f"[after] total findings = {total}")
    print("[after] by site =", {r["site_code"]: r["c"] for r in by_site})

    # 校正值落库抽检（4 处真实录入错误，校正后应存在）
    checks = [
        ("D", 1, 1, "L11"),   # D1 ch1: L1 -> L11
        ("D", 2, 48, "L8"),   # D2 ch48: C8 -> L8
        ("H", 1, 3, "N7"),    # H1 ch3: G14 -> N7
        ("H", 4, 13, "F6"),   # H4 ch13: N10 -> F6
    ]
    with server.connect() as db:
        for site, unit, thim, expect in checks:
            row = db.execute(
                "SELECT position FROM findings WHERE site_code=? AND unit_id=? AND thimble_id=?",
                (site, unit, thim),
            ).fetchone()
            got = row["position"] if row else None
            mark = "OK" if got == expect else "MISMATCH"
            print(f"    [{mark}] {site}{unit} ch{thim}: position={got!r} (expect {expect!r})")


if __name__ == "__main__":
    main()
