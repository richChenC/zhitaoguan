"""Local import provenance, quality lists and reversible batch operations."""
from __future__ import annotations

try:
    from . import local_security
except ImportError:
    import local_security

import functools
import getpass
import hashlib
import inspect
import json
import sys
from datetime import datetime
from pathlib import Path
try:
    from .analysis_reporting import cross_group_duplicates
    from . import artifact_naming, task_progress
    from .setup_parser import parse_setup
except ImportError:
    from analysis_reporting import cross_group_duplicates
    import artifact_naming
    import task_progress
    from setup_parser import parse_setup


def now():
    return datetime.now().isoformat(timespec="seconds")


def issue(db, batch_id, code, message, source="", severity="error", sheet="", row=None, field="", payload=None):
    db.execute("""INSERT OR IGNORE INTO validation_issues(
        batch_id,created_at,severity,code,message,source_path,sheet_name,row_number,field_name,payload_json
    ) VALUES(?,?,?,?,?,?,?,?,?,?)""", (
        batch_id, now(), severity, code, message, str(source), sheet, row, field,
        json.dumps(payload or {}, ensure_ascii=False, default=str),
    ))


def tracked(kind):
    """Commit records and their audit together; retain failed attempts separately."""
    def decorate(function):
        signature = inspect.signature(function)

        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            from sys import modules
            server = modules[function.__module__]
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            policy = bound.arguments.get("blank_indication_policy")
            if kind == "excel" and policy in ("", "check"):
                return function(*args, **kwargs)
            source = str(Path(bound.arguments.get("directory") or bound.arguments["filename"]).expanduser().resolve())
            operator = local_security.actor()
            if "operator" in bound.arguments:
                bound.arguments["operator"] = operator
            server.require_import_space()
            server._auto_backup("import")
            with server.connect() as db:
                batch_id = db.execute("""INSERT INTO import_batches(
                    started_at,source_path,import_kind,operator,parser_version
                ) VALUES(?,?,?,?,?)""", (now(), source, kind, operator, server.SERVICE_VERSION)).lastrowid
            try:
                with server.connect() as db:
                    bound.arguments["_audit"] = (db, batch_id)
                    result = function(*bound.args, **bound.kwargs)
                    pending = result.get("requires_indication_decision", False)
                    errors = db.execute("SELECT COUNT(*) FROM validation_issues WHERE batch_id=? AND severity='error'", (batch_id,)).fetchone()[0]
                    files = db.execute("SELECT COUNT(*) FROM import_batch_artifacts WHERE batch_id=?", (batch_id,)).fetchone()[0]
                    db.execute("""UPDATE import_batches SET finished_at=?,status=?,files_seen=?,
                        rows_parsed=?,rows_inserted=?,rows_skipped=?,error_count=?,note=? WHERE id=?""", (
                        now(), "awaiting_confirmation" if pending else "completed", files,
                        result.get("parsed", 0), result.get("inserted", 0), result.get("skipped", 0), errors,
                        "待确认三字符处理方式" if pending else "", batch_id,
                    ))
                    task_progress.step("提交数据库事务")
                return {**result, "batch_id": batch_id, "error_count": errors}
            except Exception as exc:
                try:
                    with server.connect() as db:
                        db.execute("UPDATE import_batches SET status='failed',finished_at=?,error_count=1,note=? WHERE id=?", (now(), str(exc), batch_id))
                        issue(db, batch_id, "IMPORT_FAILED", str(exc), source)
                    exc.import_batch_id = batch_id
                except Exception:
                    server.LOGGER.exception("Failed to retain import failure for batch %s", batch_id)
                raise
        return wrapper
    return decorate


def artifact(db, batch_id, path, status="parsed", error="", parsed=None):
    path = Path(path).resolve()
    try:
        # Reuse the importer cache when available.  Directory preview and
        # commit both need the same SHA-256; hashing the same large ECT again
        # was a measurable part of long imports.
        server = sys.modules.get("src.backend.server") or sys.modules.get("server")
        sha256 = getattr(server, "_cached_sha256", None)
        digest_value = sha256(path) if sha256 else None
        if digest_value is None:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            digest_value = digest.hexdigest()
        stat = path.stat()
        sha = digest_value
        db.execute("""INSERT OR IGNORE INTO file_artifacts(
            batch_id,path,filename,extension,sha256,file_size,modified_at,file_kind,parse_status,error_message
        ) VALUES(?,?,?,?,?,?,?,?,?,?)""", (
            batch_id, str(path), path.name, path.suffix.lower(), sha, stat.st_size,
            datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            path.suffix.lower().lstrip("."), status, error,
        ))
        row = db.execute("SELECT id FROM file_artifacts WHERE path=? AND sha256=?", (str(path), sha)).fetchone()
        if parsed is not None:
            db.execute("""UPDATE file_artifacts SET parse_status=?,error_message=?,parsed_json=?
                WHERE id=?""", (status, error, json.dumps(parsed, ensure_ascii=False), row["id"]))
        db.execute("INSERT OR IGNORE INTO import_batch_artifacts VALUES(?,?)", (batch_id, row["id"]))
    except OSError as exc:
        issue(db, batch_id, "FILE_READ_FAILED", str(exc), path)


def directory_quality(db, batch_id, processed, selected_reports):
    sources = {}
    for context in processed["contexts"]:
        for path in context.path.iterdir():
            if path.is_file() and path.suffix.lower() in {".ect", ".rpt", ".sum", ".set"}:
                sources[str(path.resolve())] = path
    errors = {str(Path(item["file"]).resolve()): item["message"] for item in processed["parse_errors"]}
    for item in processed["ect_mismatches"]:
        errors[str(Path(item["path"]).resolve())] = "ECT 文件名与 HeaderTube 不一致"
    selected = {str(path.resolve()).casefold() for path in processed["reports"]}
    for path in task_progress.iterate(list(sources.values()), "归档原始文件与哈希", unit="文件"):
        parsed = None
        error = errors.get(str(path.resolve()), "")
        status = "failed" if error else ("candidate" if path.suffix.lower() == ".rpt" and str(path.resolve()).casefold() not in selected else "parsed")
        if path.suffix.lower() == ".set" and not error:
            try:
                parsed = parse_setup(path)
                status = "parsed_configuration"
            except (ValueError, OSError) as exc:
                status, error = "archived_unparsed", str(exc)
            except Exception as exc:
                status, error = "archived_unparsed", str(exc)
            if error:
                issue(db, batch_id, "SET_UNPARSED", "SET 参数未解析：" + error, path, "warning")
        artifact(db, batch_id, path, status, error, parsed)
    categories = (
        ("parse_errors", "PARSE_FAILED", "error", "解析失败"),
        ("report_reference_errors", "ECT_REFERENCE", "error", "报告与 ECT 关联失败"),
        ("ect_mismatches", "ECT_HEADER_MISMATCH", "error", "ECT 文件名与 HeaderTube 不一致"),
        ("mapping_failures", "MAPPING_ERROR", "error", "机组或管号映射失败"),
        ("sum_warnings", "SUM_WARNING", "error", "SUM 信息不一致"),
        ("unreported_ect", "MISSING_REPORT", "warning", "ECT 无对应 ReportEntry，不能判为 NDD"),
        ("duplicate_same_hash", "DUPLICATE_ACQUISITION", "warning", "重复采集：文件哈希相同"),
        ("same_name_different_hash", "HASH_CONFLICT", "warning", "同名 ECT 存在不同哈希版本"),
    )
    for key, code, severity, fallback in categories:
        for item in processed[key]:
            payload = {k: v for k, v in item.items() if k != "context"}
            source = item.get("path") or item.get("file") or item.get("report") or ""
            item_code = "RPT_UNIT_MISMATCH" if "RPT Id" in item.get("message", "") else code
            issue(db, batch_id, item_code, item.get("message") or fallback, source, severity, payload=payload)
    for context in processed["contexts"]:
        reports = [path for path in context.path.iterdir() if path.is_file() and path.suffix.lower() == ".rpt"]
        if not reports:
            issue(db, batch_id, "MISSING_REPORT_FILE", "数据组缺少 RPT 报告", context.path, "warning")
        for path in reports:
            chosen = str(path.resolve()).casefold() in selected
            file_row = db.execute("SELECT sha256 FROM file_artifacts WHERE path=? ORDER BY id DESC LIMIT 1", (str(path.resolve()),)).fetchone()
            db.execute("""INSERT INTO report_versions(
                outage,unit_id,calgroup,filename,source_path,version_label,selected,selected_at,selected_by,sha256
            ) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(outage,unit_id,calgroup,filename,source_path)
            DO UPDATE SET sha256=excluded.sha256,selected=excluded.selected,
                selected_at=excluded.selected_at,selected_by=excluded.selected_by""", (
                context.outage, context.unit_id, context.calgroup, path.name, str(path.resolve()),
                path.stem, int(chosen), now() if chosen else None,
                db.execute("SELECT operator FROM import_batches WHERE id=?", (batch_id,)).fetchone()["operator"] if chosen else "",
                file_row["sha256"] if file_row else "",
            ))
            version = db.execute("""SELECT id FROM report_versions WHERE outage=? AND unit_id=?
                AND calgroup=? AND filename=? AND source_path=?""",
                (context.outage, context.unit_id, context.calgroup, path.name, str(path.resolve()))).fetchone()
            db.execute("INSERT INTO import_batch_reports VALUES(?,?,?)", (batch_id, version["id"], int(chosen)))


def remember_change(db, batch_id, finding_id, before=None, fields=None, after=None):
    after = after or dict(db.execute("SELECT * FROM findings WHERE id=?", (finding_id,)).fetchone())
    if before is None:
        keys = [key for key in after if key not in {"is_deleted", "deleted_at", "deleted_by", "delete_batch_id"}]
    else:
        keys = list(fields) if fields is not None else ["indication", "source_indication", "indication_resolution"]
        if all(before.get(key) == after.get(key) for key in keys):
            return
    db.execute("""INSERT INTO import_finding_changes VALUES(?,?,?,?)
        ON CONFLICT(batch_id,finding_id) DO UPDATE SET after_json=excluded.after_json""", (
        batch_id, finding_id,
        json.dumps({key: before.get(key) for key in keys}, ensure_ascii=False) if before is not None else None,
        json.dumps({key: after.get(key) for key in keys}, ensure_ascii=False),
    ))
    return after


def finding_source(db, batch_id, finding_id, path, raw, sheet="", row=None,
                   finding_values=None, duplicate_cache=None):
    db.execute("""INSERT INTO import_finding_sources(
        batch_id,finding_id,source_path,sheet_name,row_number,raw_json
    ) VALUES(?,?,?,?,?,?)""", (batch_id, finding_id, str(path), sheet, row,
        json.dumps(raw, ensure_ascii=False, default=str)))
    if finding_id is not None:
        values = finding_values
        if values is None:
            values = dict(db.execute("SELECT * FROM findings WHERE id=?", (finding_id,)).fetchone())
        else:
            values = dict(values)
        scope = (values["outage"], values["unit_id"], values["thimble_id"])
        if duplicate_cache is None:
            candidates = [dict(item) for item in db.execute("""SELECT * FROM findings
                WHERE outage=? AND unit_id=? AND thimble_id=? AND is_deleted=0""", scope)]
        else:
            candidates = duplicate_cache.get(scope)
            if candidates is None:
                candidates = [dict(item) for item in db.execute("""SELECT * FROM findings
                    WHERE outage=? AND unit_id=? AND thimble_id=? AND is_deleted=0""", scope)]
                duplicate_cache[scope] = candidates
            if not any(item.get("id") == finding_id for item in candidates):
                candidates.append(values)
        for group in cross_group_duplicates(candidates):
            if any(item["id"] == finding_id for item in group):
                issue(db, batch_id, "CROSS_GROUP_DUPLICATE",
                      "跨数据组同分析人员的缺陷字段相同，保留全部来源待复核，未自动删除",
                      path, "warning", sheet, row, payload={"records": group})


def change_batch(server, batch_id, action):
    if action not in {"rollback", "restore"}:
        raise ValueError("批次操作无效")
    server._auto_backup("import_batch_action")
    with server.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        batch = db.execute("SELECT * FROM import_batches WHERE id=?", (batch_id,)).fetchone()
        expected = "completed" if action == "rollback" else "rolled_back"
        if not batch or batch["status"] != expected or batch["is_deleted"]:
            raise ValueError("批次状态已变化，请刷新后重试")
        changes = db.execute("SELECT * FROM import_finding_changes WHERE batch_id=?", (batch_id,)).fetchall()
        if not changes:
            raise ValueError("该批次没有可回滚的记录")
        delete_tag = f"import_{batch_id}"
        for change in changes:
            row = db.execute("SELECT * FROM findings WHERE id=?", (change["finding_id"],)).fetchone()
            before = json.loads(change["before_json"]) if change["before_json"] else None
            after = json.loads(change["after_json"])
            expected_values = after if action == "rollback" or before is None else before
            # Keep historical snapshots immutable while allowing an audited mapping repair.
            if expected_values.get("position") == "M5":
                correction = db.execute("""SELECT after_json FROM core_mapping_corrections
                    WHERE finding_id=? ORDER BY id DESC LIMIT 1""", (change["finding_id"],)).fetchone()
                if correction:
                    corrected = json.loads(correction["after_json"])
                    if corrected.get("position") == "N5":
                        expected_values = {**expected_values, "position": "N5"}
                        if "business_key" in expected_values:
                            expected_values["business_key"] = server.finding_business_key(expected_values)
            if not row or any(row[key] != value for key, value in expected_values.items()):
                raise ValueError("批次中的记录已被后续修改，操作已取消")
            deleted = row["is_deleted"]
            if action == "restore" and before is None:
                if not deleted or row["delete_batch_id"] != delete_tag:
                    raise ValueError("记录已被其他删除操作处理，不能恢复该批次")
            elif deleted:
                raise ValueError("记录已在回收站中，请先恢复对应删除操作")
            later = db.execute("""SELECT 1 FROM import_finding_changes c JOIN import_batches b ON b.id=c.batch_id
                WHERE c.finding_id=? AND c.batch_id>? AND b.status='completed' LIMIT 1""", (change["finding_id"], batch_id)).fetchone()
            if later:
                raise ValueError("存在后续批次修改，请先处理后续批次")
        for change in changes:
            if change["before_json"] is None:
                db.execute("""UPDATE findings SET is_deleted=?,deleted_at=?,delete_batch_id=?
                    WHERE id=?""", (int(action == "rollback"), now() if action == "rollback" else None,
                    delete_tag if action == "rollback" else None, change["finding_id"]))
            else:
                values = json.loads(change["before_json"] if action == "rollback" else change["after_json"])
                columns = {item[1] for item in db.execute("PRAGMA table_info(findings)")}
                if not values or not set(values).issubset(columns - {"id"}):
                    raise ValueError("批次字段记录无效，操作已取消")
                db.execute("UPDATE findings SET " + ",".join(f"{key}=?" for key in values) + " WHERE id=?",
                           [*values.values(), change["finding_id"]])
        try:
            from . import inspection_states
        except ImportError:
            import inspection_states
        inspection_states.change_batch_states(server, db, batch_id, action)
        db.execute("UPDATE import_batches SET status=?,rollback_at=? WHERE id=?",
            ("rolled_back" if action == "rollback" else "completed", now() if action == "rollback" else None, batch_id))
        db.execute("""INSERT INTO operation_logs(operation_type,scope,scope_detail,record_count,operator,created_at)
            VALUES(?,?,?,?,?,?)""", (f"import_{action}", "import_batch", str(batch_id), len(changes), local_security.actor(), now()))
    return {"ok": True, "batch_id": batch_id, "changed": len(changes)}


def quality_snapshot(db, batch_id=None):
    where, args = ("WHERE id=?", [batch_id]) if batch_id else ("", [])
    batches = [dict(row) for row in db.execute(f"SELECT * FROM import_batches {where} ORDER BY id DESC", args)]
    clause = " WHERE batch_id=?" if batch_id else ""
    issues = [dict(row) for row in db.execute(f"SELECT * FROM validation_issues{clause} ORDER BY id DESC", args)]
    artifacts = [dict(row) for row in db.execute("""SELECT ba.batch_id,a.* FROM import_batch_artifacts ba
        JOIN file_artifacts a ON a.id=ba.artifact_id""" + (" WHERE ba.batch_id=?" if batch_id else "") + " ORDER BY ba.batch_id DESC,a.id", args)]
    versions = [dict(row) for row in db.execute("""SELECT br.batch_id,br.selected batch_selected,v.*
        FROM import_batch_reports br JOIN report_versions v ON v.id=br.version_id""" +
        (" WHERE br.batch_id=?" if batch_id else "") + " ORDER BY br.batch_id DESC,v.id", args)]
    return {"batches": batches, "issues": issues, "artifacts": artifacts, "versions": versions}


def quality(server, batch_id=None, category="", page=1, size=50):
    page, size = max(1, int(page)), max(1, min(200, int(size)))
    with server.connect() as db:
        data = quality_snapshot(db, batch_id)
        batches = [dict(row) for row in db.execute("SELECT * FROM import_batches ORDER BY id DESC LIMIT 200")]
        batch_total = db.execute("SELECT COUNT(*) FROM import_batches").fetchone()[0]
        legacy = db.execute("SELECT COUNT(*) FROM findings WHERE is_deleted=0 AND import_batch_id IS NULL").fetchone()[0]
    if category:
        data["issues"] = [row for row in data["issues"] if row["code"] == category]
    for issue_row in data["issues"]:
        if issue_row["code"] != "MAPPING_ERROR":
            continue
        try:
            raw = json.loads(issue_row.get("payload_json") or "{}")
            if not isinstance(raw, dict):
                continue
            unit = server.number(raw.get("机组号"), int)
            outage = str(raw.get("大修号") or issue_row.get("sheet_name") or "").strip().upper()
            if not server.re.fullmatch(r"[A-Z]{1,2}\d{3}", outage):
                outage = ""
            if not unit and outage:
                unit = server.infer_unit(outage, "")
            tube = server.number(raw.get("通道编号"), int)
            position = str(raw.get("在堆芯内的位置") or "").strip().upper()
            normalized = server.re.sub(r"^([A-Z])0+(\d+)$", r"\1\2", position)
            if not unit or unit < 1 or not tube or not 1 <= tube <= 50:
                continue
            positions = server.ODD_POSITIONS if unit % 2 else server.EVEN_POSITIONS
            issue_row["mapping_hint"] = {
                "unit": unit, "outage": outage, "tube": tube, "raw_position": position,
                "expected_position": positions[tube - 1],
                "position_tube": positions.index(normalized) + 1 if normalized in positions else None,
            }
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    totals = {key: len(data[key]) for key in ("issues", "artifacts", "versions")}
    codes = sorted({row["code"] for row in data["issues"]})
    start = (page - 1) * size
    return {
        "batches": batches, "batch_total": batch_total,
        **{key: data[key][start:start + size] for key in totals},
        "totals": totals, "codes": codes, "page": page, "size": size, "legacy_rows": legacy,
    }


def export_quality(server, batch_id=None, category=""):
    with server.connect() as db:
        data = quality_snapshot(db, batch_id)
        data["findings"] = [dict(row) for row in db.execute(
            "SELECT * FROM findings WHERE is_deleted=0" +
            (" AND import_batch_id=?" if batch_id else "") + " ORDER BY outage,unit_id,thimble_id,id",
            [batch_id] if batch_id else [])]
        data["sources"] = [dict(row) for row in db.execute("SELECT * FROM import_finding_sources" +
            (" WHERE batch_id=?" if batch_id else "") + " ORDER BY id", [batch_id] if batch_id else [])]
        data["mapping_corrections"] = [dict(row) for row in db.execute("SELECT * FROM core_mapping_corrections ORDER BY id")]
        if batch_id:
            ids = {row["id"] for row in data["findings"]} | {row["finding_id"] for row in data["sources"]}
            data["mapping_corrections"] = [row for row in data["mapping_corrections"] if row["finding_id"] in ids]
        data["cross_reviews"] = [dict(row) for row in db.execute(
            "SELECT * FROM cross_group_reviews ORDER BY id")]
        if batch_id:
            source_ids = {row["finding_id"] for row in data["sources"]}
            data["cross_reviews"] = [r for r in data["cross_reviews"]
                if any(m["id"] in source_ids for m in json.loads(r["members_json"]))]
        data["cross_review_sources"] = [
            {**m, "review_id": r["id"], "statistical_selected":
                "否" if r["action"] == "representative" and m["id"] != r["representative_id"] else "是"}
            for r in data["cross_reviews"] for m in json.loads(r["members_json"])]
    if category:
        data["issues"] = [row for row in data["issues"] if row["code"] == category]
    legacy = sum(row.get("import_batch_id") is None for row in data["findings"])
    data["overview"] = [
        {"item": "导出时间", "value": datetime.now().isoformat(timespec="seconds")},
        {"item": "批次范围", "value": f"批次 #{batch_id}" if batch_id else "全部批次及无批次历史记录"},
        {"item": "异常类型筛选", "value": category or "全部类型"},
        {"item": "筛选口径", "value": "异常类型仅筛选校验问题；其他工作表按批次范围导出。检测记录不含回收站数据。"},
        {"item": "有效检测记录", "value": len(data["findings"])},
        {"item": "无批次历史记录", "value": legacy},
        {"item": "历史记录说明", "value": "保留现有检测值和来源路径；缺失的导入过程无法补推，不能据此认定校验通过。"},
        *({"item": title, "value": len(data[key])} for title, key in (
            ("导入批次", "batches"), ("校验问题", "issues"), ("文件校验", "artifacts"),
            ("报告版本", "versions"), ("记录原值", "sources"), ("跨组复核历史", "cross_reviews"),
            ("管位映射修正", "mapping_corrections"))),
        {"item": "空表说明", "value": "只有表头表示本范围未保存对应审计记录，不代表检测记录为空或校验已通过。"},
    ]
    definitions = (
        ("导出概览", "overview", [("item", "项目"), ("value", "内容")]),
        ("管位映射修正", "mapping_corrections", [
            ("finding_id", "数据库记录"), ("reason", "修正依据"),
            ("corrected_at", "修正时间"), ("before_json", "修正前完整记录"),
            ("after_json", "修正后完整记录")]),
        ("有效检测记录", "findings", [
            ("id", "数据库记录"), ("outage", "大修"), ("unit_id", "机组"),
            ("thimble_id", "通道编号"), ("position", "堆芯位置"), ("indication", "显示类型"),
            ("location", "磨损位置"), ("volts", "幅值(V)"), ("degrees", "相位(°)"),
            ("percent", "壁厚(%)"), ("analyst", "分析人员"), ("calgroup", "数据组"),
            ("report_path", "来源报告"), ("filepath", "采集文件路径"),
            ("import_batch_id", "导入批次（空白为历史记录）")]),
        ("导入批次", "batches", [
            ("id", "批次"), ("started_at", "导入时间"), ("source_path", "来源路径"),
            ("operator", "操作人员"), ("parser_version", "解析器版本"), ("status", "状态"),
            ("files_seen", "文件数"), ("rows_parsed", "解析行数"), ("rows_inserted", "入库行数"),
            ("rows_skipped", "重复拦截"), ("error_count", "错误数"), ("rollback_at", "回滚时间"),
            ("selection_json", "报告确认信息"), ("note", "备注")]),
        ("校验问题", "issues", [
            ("batch_id", "批次"), ("severity", "级别"), ("code", "类型"), ("message", "问题"),
            ("source_path", "来源路径"), ("sheet_name", "工作表"), ("row_number", "行号"),
            ("field_name", "字段"), ("payload_json", "原始信息"), ("created_at", "记录时间")]),
        ("文件校验", "artifacts", [
            ("batch_id", "批次"), ("path", "来源路径"), ("extension", "类型"),
            ("sha256", "SHA-256"), ("file_size", "字节数"), ("modified_at", "修改时间"),
            ("parse_status", "解析状态"), ("error_message", "错误"),
            ("parsed_json", "配置原始字段")]),
        ("报告版本", "versions", [
            ("batch_id", "批次"), ("outage", "大修"), ("unit_id", "机组"), ("calgroup", "数据组"),
            ("filename", "报告文件"), ("source_path", "来源路径"), ("batch_selected", "本批次选用"),
            ("sha256", "SHA-256")]),
        ("记录原值", "sources", [
            ("batch_id", "批次"), ("finding_id", "数据库记录"), ("source_path", "来源路径"),
            ("sheet_name", "工作表"), ("row_number", "行号"), ("raw_json", "原始字段")]),
        ("跨组复核历史", "cross_reviews", [
            ("id", "复核编号"), ("group_key", "缺陷组标识"), ("outage", "大修"), ("unit_id", "机组"),
            ("action", "复核决定"), ("representative_id", "统计代表记录"), ("operator", "操作人员"),
            ("reason", "复核依据"), ("created_at", "复核时间"), ("active", "决定仍有效"),
            ("fingerprint", "复核时来源指纹")]),
        ("跨组复核来源", "cross_review_sources", [
            ("review_id", "复核编号"), ("id", "原始记录"), ("outage", "大修"), ("unit_id", "机组"),
            ("thimble_id", "管号"), ("calgroup", "数据组"), ("filename", "采集文件"),
            ("analyst", "分析人员"), ("location", "磨损位置"), ("volts", "幅值(V)"),
            ("degrees", "相位(°)"), ("percent", "壁厚(%)"), ("indication", "显示"),
            ("measurement_type", "测量类型"), ("channel", "通道"), ("report_path", "来源报告"),
            ("statistical_selected", "该次决定计入统计（有效性见复核历史）")]),
    )
    book = server.Workbook()
    book.remove(book.active)
    for title, key, columns in definitions:
        sheet = book.create_sheet(title)
        sheet.append([label for _, label in columns])
        for row_number, row in enumerate(data[key], 2):
            sheet.append([row.get(field) for field, _ in columns])
            for column_number in range(1, len(columns) + 1):
                cell = sheet.cell(row_number, column_number)
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        server.apply_plain_excel_table(sheet)
        for index, (field, _) in enumerate(columns, 1):
            sheet.column_dimensions[server.get_column_letter(index)].width = 52 if field.endswith(("path", "json")) else 22
        if key == "overview":
            sheet.column_dimensions["B"].width = 95
            sheet.sheet_view.showGridLines = False
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = server.Alignment(vertical="top", wrap_text=True)
    server.EXCEL_DIR.mkdir(parents=True, exist_ok=True)
    filename = artifact_naming.filename("数据质量清单", f"批次{batch_id}" if batch_id else "全部数据", "xlsx")
    target = server.EXCEL_DIR / filename
    book.properties.creator = local_security.actor()
    book.properties.lastModifiedBy = local_security.actor()
    book.save(target)
    book.close()
    return {"filename": filename, "file_path": str(target), "rows": len(data["issues"]),
        "finding_rows": len(data["findings"]), "legacy_rows": legacy,
        "download_url": f"/api/download-excel?name={server.quote(filename)}"}
