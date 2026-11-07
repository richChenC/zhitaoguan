"""Recognize maintenance remarks within the inspection import transaction."""
import hashlib
import json
import re

try:
    from . import task_progress, state_preferences
    from .state_recognition import parse_description, parse_direction, text, CODE, STATE_PATTERN, MAX_STATE_ROWS
except ImportError:
    import task_progress
    import state_preferences
    from state_recognition import parse_description, parse_direction, text, CODE, STATE_PATTERN, MAX_STATE_ROWS


def init_schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS inspection_state_candidates (
            id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL,
            outage TEXT NOT NULL, unit_id INTEGER NOT NULL, thimble_id INTEGER NOT NULL,
            fingerprint TEXT NOT NULL, row_json TEXT NOT NULL, reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            UNIQUE(batch_id,fingerprint)
        );
        CREATE TABLE IF NOT EXISTS import_state_changes (
            batch_id INTEGER NOT NULL, outage TEXT NOT NULL, unit_id INTEGER NOT NULL,
            thimble_id INTEGER NOT NULL, before_json TEXT, after_json TEXT NOT NULL,
            PRIMARY KEY(batch_id,outage,unit_id,thimble_id)
        );
    """)


def snapshot(db, row):
    current = db.execute("SELECT * FROM tube_states WHERE outage=? AND unit_id=? AND thimble_id=?",
                         (row["outage"], row["unit_id"], row["thimble_id"])).fetchone()
    return dict(current) if current else None


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def remember_state_change(db, batch_id, row, before):
    db.execute("""INSERT INTO import_state_changes VALUES(?,?,?,?,?,?)
        ON CONFLICT(batch_id,outage,unit_id,thimble_id) DO UPDATE SET after_json=excluded.after_json""",
        (batch_id, row["outage"], row["unit_id"], row["thimble_id"],
         dumps(before) if before else None, dumps(snapshot(db, row))))


def recognize_import(server, db, batch_id, entries, *, replace_existing=False):
    groups = {}
    direction = state_preferences.direction(server, db)
    for entry in task_progress.iterate(entries, "识别检测备注中的维护状态", span=(0, 50)):
        original = str(entry.get("note") or "")
        normalized = text(original)
        if not re.search(STATE_PATTERN + r"|正常|\bnormal\b", normalized, re.I):
            continue
        raw_offset = entry.get("offset_mm")
        raw_unsigned = entry.get("unsigned_offset_mm")
        raw_direction = entry.get("direction")
        explicit_direction = parse_direction(raw_direction)
        if text(raw_direction):
            explicit_direction = explicit_direction or "pending"
        offset_value = raw_offset if raw_offset not in (None, "") else raw_unsigned
        signed_column = raw_offset not in (None, "")
        effective_direction = explicit_direction or direction
        facts, reason = parse_description(original, offset=offset_value,
                                          signed_column=signed_column,
                                          default_direction=effective_direction)
        if facts and facts["offset_mm"] is None and facts["unsigned_offset_mm"] is not None:
            reason = "无符号移位默认方向设为留待核对，请确认方向"
        other_outage = any(value != entry["outage"] for value in re.findall(CODE, normalized.upper()))
        tubes = re.findall(r"(?:通道(?:号|编号)?|管号|指套管编号)\s*0*(\d{1,2})(?!\d)", normalized)
        if other_outage or any(int(value) != entry["thimble_id"] for value in tubes):
            facts, reason = None, "说明含其他大修或管号，需核对适用范围"
        if re.search(r"此前|历史|曾经|曾于|上次|历次|大修前", normalized):
            facts, reason = None, "说明含历史处理信息，需确认是否在本次检查后生效"
        row = {**entry, **(facts or {"state": "", "offset_mm": None, "unsigned_offset_mm": None})}
        row["note"] = original
        key = row["outage"], row["unit_id"], row["thimble_id"]
        groups.setdefault(key, []).append((row, reason))
    summary = dict(applied=0, pending=0, skipped=0)
    for key, members in task_progress.iterate(list(groups.items()), "核对并保存识别状态", unit="管", span=(50, 100)):
        unique = {}
        for row, reason in members:
            fingerprint = hashlib.sha256(dumps([key, row["note"]]).encode("utf-8")).hexdigest()
            if fingerprint in unique:
                old = unique[fingerprint][0]
                if row["source"] not in old["source"].split("\n"):
                    old["source"] += "\n" + row["source"]
            else:
                unique[fingerprint] = (row, reason)
        current = snapshot(db, members[0][0])
        refresh_default = bool(
            current and not current.get("is_deleted")
            and int(current.get("offset_confirmed", 1) or 0) == 0
            and current.get("unsigned_offset_mm") is not None
            and direction in {"1", "-1"}
        )
        multiple = len(unique) > 1
        for fingerprint, (row, reason) in unique.items():
            previous = db.execute("""SELECT c.status FROM inspection_state_candidates c
                JOIN import_batches b ON b.id=c.batch_id
                WHERE c.fingerprint=? AND b.status IN ('completed','running')
                AND COALESCE(b.is_deleted,0)=0 LIMIT 1""", (fingerprint,)).fetchone()
            refresh_pending = bool(previous and previous["status"] == "pending"
                                   and direction in {"1", "-1"})
            if previous and not replace_existing and not refresh_default and not refresh_pending:
                summary["skipped"] += 1
                continue
            if multiple:
                reason = "同管有不同原始说明，需逐条核对；确认其中一条后请忽略其余记录"
            elif current and not replace_existing and not refresh_default:
                reason = "已有维护或撤销记录，需核对后决定是否覆盖"
            if not reason:
                try:
                    server.validate_state_payload(row)
                except ValueError as error:
                    reason = str(error)
            status = "pending" if reason else "applied"
            db.execute("""INSERT OR IGNORE INTO inspection_state_candidates
                (batch_id,outage,unit_id,thimble_id,fingerprint,row_json,reason,status)
                VALUES(?,?,?,?,?,?,?,?)""",
                (batch_id, *key, fingerprint, dumps(row), reason, status))
            if reason:
                summary["pending"] += 1
                continue
            server.save_tube_state(row, connection=db)
            remember_state_change(db, batch_id, row, current)
            if refresh_pending:
                db.execute("UPDATE inspection_state_candidates SET status='confirmed' WHERE fingerprint=? AND status='pending'",
                           (fingerprint,))
            summary["applied"] += 1
    return summary


def refresh_default_direction(server, db, direction):
    """Apply a newly selected default direction to existing unsigned candidates.

    Only candidates that were blocked specifically because the default direction
    was pending are eligible. Other pending reasons (existing state conflicts,
    ambiguous scope, missing distance, etc.) must remain human-reviewed.
    """
    if direction not in {"1", "-1"}:
        return {"applied": 0, "skipped": 0}
    reason_marker = "无符号移位默认方向设为留待核对"
    applied = skipped = 0
    candidates = db.execute(
        """SELECT c.* FROM inspection_state_candidates c
           JOIN import_batches b ON b.id=c.batch_id
           WHERE c.status='pending' AND b.status='completed'
             AND COALESCE(b.is_deleted,0)=0
           ORDER BY c.id"""
    ).fetchall()
    eligible = {}
    for candidate in candidates:
        if reason_marker not in str(candidate["reason"] or ""):
            continue
        key = (candidate["outage"], candidate["unit_id"], candidate["thimble_id"])
        eligible.setdefault(key, []).append(candidate)
    for key, group in eligible.items():
        if len(group) != 1:
            skipped += len(group)
            continue
        candidate = group[0]
        row = json.loads(candidate["row_json"])
        unsigned = row.get("unsigned_offset_mm")
        if unsigned in (None, "") or row.get("offset_mm") is not None:
            skipped += 1
            continue
        if snapshot(db, row) is not None:
            skipped += 1
            continue
        try:
            amount = float(unsigned)
            if not amount == amount:
                skipped += 1
                continue
            signed = float(direction) * amount
            if signed.is_integer():
                signed = int(signed)
            updated = {**row, "offset_mm": signed, "unsigned_offset_mm": None}
            server.validate_state_payload(updated)
            before = snapshot(db, updated)
            server.save_tube_state(updated, connection=db)
            remember_state_change(db, candidate["batch_id"], updated, before)
            db.execute(
                """UPDATE inspection_state_candidates
                   SET row_json=?, reason='', status='confirmed' WHERE id=?""",
                (dumps(updated), candidate["id"]),
            )
            applied += 1
        except (TypeError, ValueError):
            skipped += 1
    return {"applied": applied, "skipped": skipped}


def pending_rows(db):
    result = []
    for candidate in db.execute("""SELECT c.* FROM inspection_state_candidates c
        JOIN import_batches b ON b.id=c.batch_id WHERE c.status='pending'
        AND b.status='completed' AND COALESCE(b.is_deleted,0)=0 ORDER BY c.id"""):
        row = json.loads(candidate["row_json"])
        result.append({**row, "recognition_id": candidate["id"], "review_reason": candidate["reason"],
                       "expected_state": snapshot(db, row)})
    return result


def confirm_candidate(db, original):
    candidate = db.execute("""SELECT c.* FROM inspection_state_candidates c JOIN import_batches b ON b.id=c.batch_id
        WHERE c.id=? AND c.status='pending' AND b.status='completed' AND COALESCE(b.is_deleted,0)=0""",
        (original["recognition_id"],)).fetchone()
    if not candidate:
        raise ValueError("待核对记录已变化，请刷新后重试")
    stored = json.loads(candidate["row_json"])
    if any(original.get(k) != stored.get(k) for k in ("outage", "unit_id", "thimble_id")):
        raise ValueError("待核对记录范围不能更改")
    if "expected_state" not in original or snapshot(db, stored) != original["expected_state"]:
        raise ValueError("该管维护记录已变化，请刷新后重新核对")
    db.execute("UPDATE inspection_state_candidates SET status='confirmed' WHERE id=?", (candidate["id"],))
    return candidate["batch_id"]


def dismiss(server, data):
    ids = data.get("ids")
    if data.get("confirmed") is not True or not isinstance(ids, list) or not 1 <= len(ids) <= MAX_STATE_ROWS:
        raise ValueError("请选择要忽略的识别记录")
    with server.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for candidate_id in ids:
            db.execute("UPDATE inspection_state_candidates SET status='dismissed' WHERE id=? AND status='pending'",
                       (int(candidate_id),))
    return {"ok": True}


def change_batch_states(server, db, batch_id, action):
    def stored_state(raw):
        if raw is None:
            return None
        # Older snapshots predate optional distances; retain their signed values.
        return {"offset_confirmed": 1, "unsigned_offset_mm": None,
                "events_json": None, "replacement_stage": "unknown", **json.loads(raw)}

    changes = db.execute("SELECT * FROM import_state_changes WHERE batch_id=?", (batch_id,)).fetchall()
    for change in changes:
        before = stored_state(change["before_json"])
        after = stored_state(change["after_json"])
        expected = after if action == "rollback" else before
        if snapshot(db, dict(change)) != expected:
            raise ValueError("该批次自动识别的管状态已被后续维护，不能回滚或恢复")
    for change in changes:
        before = stored_state(change["before_json"])
        after = stored_state(change["after_json"])
        target = before if action == "rollback" else after
        key = (change["outage"], change["unit_id"], change["thimble_id"])
        if target is None:
            db.execute("DELETE FROM tube_states WHERE outage=? AND unit_id=? AND thimble_id=?", key)
        else:
            columns = list(target)
            db.execute(f"INSERT OR REPLACE INTO tube_states ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                       [target[k] for k in columns])
