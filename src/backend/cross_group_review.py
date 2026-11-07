
try:
    from . import local_security
except ImportError:
    import local_security

"""Reversible statistical choices; acquisition records are never modified."""
import getpass
import hashlib
import json
from datetime import datetime

try:
    from . import analysis_reporting
except ImportError:
    import analysis_reporting


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def install(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS cross_group_reviews (
          id INTEGER PRIMARY KEY, group_key TEXT NOT NULL, outage TEXT NOT NULL,
          unit_id INTEGER NOT NULL, fingerprint TEXT NOT NULL, action TEXT NOT NULL,
          representative_id INTEGER, operator TEXT NOT NULL, reason TEXT NOT NULL,
          created_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
          members_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS cross_group_exclusions (
          review_id INTEGER NOT NULL, finding_id INTEGER NOT NULL,
          PRIMARY KEY(review_id,finding_id)
        );
        CREATE INDEX IF NOT EXISTS idx_cross_group_scope ON cross_group_reviews(outage,unit_id,active);
        CREATE INDEX IF NOT EXISTS idx_cross_group_key ON cross_group_reviews(group_key,id);
        CREATE INDEX IF NOT EXISTS idx_cross_group_exclusions_finding ON cross_group_exclusions(finding_id);
    """)
    expected = expected_triggers(db)
    # Legacy databases predate the maintenance_text field. Refresh only the
    # managed trigger names during the one-time migration; current databases
    # remain subject to strict schema validation.
    legacy = not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    existing = {
        name: sql for name, sql in db.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger'"
        )
    }
    for name, statement in expected.items():
        if legacy and name in existing:
            normalize = lambda sql: ' '.join(sql.lower().split()).replace(' if not exists ', ' ')
            if normalize(existing[name]) != normalize(statement):
                db.execute(f'DROP TRIGGER "{name}"')
        db.execute(statement.replace('CREATE TRIGGER ', 'CREATE TRIGGER IF NOT EXISTS ', 1))


def expected_triggers(db):
    result = {}
    # A restored acquisition must not silently reactivate an obsolete choice.
    columns = [r[1] for r in db.execute("PRAGMA table_info(findings)")]
    changed = " OR ".join(f'OLD."{c}" IS NOT NEW."{c}"' for c in columns)
    for event, reference in (("INSERT", "NEW"), ("DELETE", "OLD"), ("UPDATE", "NEW")):
        when = f" WHEN {changed}" if event == "UPDATE" else ""
        old_scope = " OR (outage=OLD.outage AND unit_id=OLD.unit_id)" if event == "UPDATE" else ""
        name = 'invalidate_cross_group_' + event.lower()
        result[name] = f"""CREATE TRIGGER {name}
            AFTER {event} ON findings{when} BEGIN
            UPDATE cross_group_reviews SET active=0 WHERE active=1
              AND ((outage={reference}.outage AND unit_id={reference}.unit_id){old_scope});
            END"""
    return result


def attach_view(db):
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='cross_group_reviews'").fetchone():
        db.execute("""CREATE TEMP VIEW statistical_findings AS SELECT f.* FROM findings f
            WHERE NOT EXISTS (SELECT 1 FROM cross_group_exclusions e
              JOIN cross_group_reviews r ON r.id=e.review_id AND r.active=1
              WHERE e.finding_id=f.id)""")


def groups(db):
    rows = [dict(r) for r in db.execute("SELECT * FROM findings WHERE is_deleted=0 ORDER BY id")]
    result = []
    for members in analysis_reporting.cross_group_duplicates(rows):
        first = members[0]
        key = digest(analysis_reporting.duplicate_signature(first))
        fingerprint = digest(members)
        history = [dict(r) for r in db.execute(
            "SELECT * FROM cross_group_reviews WHERE group_key=? ORDER BY id DESC", (key,))]
        latest = history[0] if history else None
        valid = bool(latest and latest["active"] and latest["fingerprint"] == fingerprint)
        result.append({"group_key": key, "outage": first["outage"], "unit_id": first["unit_id"],
                       "thimble_id": first["thimble_id"], "analyst": first["analyst"],
                       "members": members, "fingerprint": fingerprint,
                       "revision": digest([fingerprint, latest["id"] if latest else None,
                                           latest["active"] if latest else None]),
                       "status": latest["action"] if valid else "pending",
                       "representative_id": latest["representative_id"] if valid else None,
                       "history": history})
    return result


def listing(service, batch_id=None):
    with service.connect() as db:
        items = groups(db)
    if batch_id:
        items = [g for g in items if any(r.get("import_batch_id") == int(batch_id) for r in g["members"])]
    return {"items": items, "total": len(items),
            "pending": sum(g["status"] in {"pending", "reset"} for g in items)}


def save(service, payload):
    action = payload.get("action")
    if action not in {"representative", "keep_all", "reset"}:
        raise ValueError("请选择统计代表、保留全部或撤销复核")
    with service.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        group = next((g for g in groups(db) if g["group_key"] == payload.get("group_key")), None)
        if not group or payload.get("revision") != group["revision"]:
            raise ValueError("数据或复核结果已变化，请刷新后重新复核")
        representative = payload.get("representative_id") if action == "representative" else None
        if action == "representative" and (type(representative) is not int or representative not in {r["id"] for r in group["members"]}):
            raise ValueError("统计代表必须是当前组内的一条原始记录")
        db.execute("UPDATE cross_group_reviews SET active=0 WHERE group_key=?", (group["group_key"],))
        review = db.execute("""INSERT INTO cross_group_reviews
            (group_key,outage,unit_id,fingerprint,action,representative_id,operator,reason,created_at,members_json)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (group["group_key"], group["outage"], group["unit_id"], group["fingerprint"], action,
             representative, local_security.actor(),
             str(payload.get("reason") or "").strip(), datetime.now().isoformat(timespec="microseconds"),
             json.dumps(group["members"], ensure_ascii=False)))
        if action == "representative":
            db.executemany("INSERT INTO cross_group_exclusions VALUES(?,?)",
                           [(review.lastrowid, r["id"]) for r in group["members"] if r["id"] != representative])
    return {"saved": True, "action": action}
