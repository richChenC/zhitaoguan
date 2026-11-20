"""Versioned, checked, staged SQLite upgrades. No business fields are redefined."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3
import uuid

try:
    from .database_runtime import GATE
except ImportError:
    from database_runtime import GATE

VERSION = 7
class ClosingConnection(sqlite3.Connection):
    def close(self):
        try:
            return super().close()
        finally:
            if getattr(self, '_gate_held', False):
                self._gate_held = False
                GATE.leave()

    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()
AUTH_SQL = (
    "CREATE TABLE users(id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE, display_name TEXT NOT NULL, password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), failures INTEGER NOT NULL DEFAULT 0, locked_until INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
    "CREATE TABLE roles(code TEXT PRIMARY KEY, label TEXT NOT NULL)",
    "CREATE TABLE permissions(code TEXT PRIMARY KEY, label TEXT NOT NULL)",
    "CREATE TABLE role_permissions(role_code TEXT NOT NULL REFERENCES roles(code), permission_code TEXT NOT NULL REFERENCES permissions(code), PRIMARY KEY(role_code,permission_code))",
    "CREATE TABLE user_roles(user_id TEXT NOT NULL REFERENCES users(id), role_code TEXT NOT NULL REFERENCES roles(code), PRIMARY KEY(user_id,role_code))",
    "CREATE TABLE login_sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, last_seen INTEGER NOT NULL, service_instance TEXT NOT NULL)",
    "CREATE INDEX sessions_user ON login_sessions(user_id)",
    "CREATE TABLE security_events(id INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, actor_id TEXT NOT NULL, operator TEXT NOT NULL, event_type TEXT NOT NULL, outcome TEXT NOT NULL, resource TEXT NOT NULL DEFAULT '')",
    "CREATE TABLE export_audits(id INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, actor_id TEXT NOT NULL, operator TEXT NOT NULL, resource TEXT NOT NULL, sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL)",
)
BACKUP_SQL = (
    "CREATE TABLE backup_policy(id INTEGER PRIMARY KEY CHECK(id=1), automatic_keep INTEGER NOT NULL CHECK(automatic_keep BETWEEN 5 AND 200))",
    "INSERT INTO backup_policy VALUES(1,20)",
)
STATE_PREFERENCES_SQL = (
    "CREATE TABLE state_preferences(id INTEGER PRIMARY KEY CHECK(id=1), shift_direction TEXT NOT NULL CHECK(shift_direction IN ('1','-1','pending')))",
)
VERSIONS = ((1, '001_legacy_business_baseline', ()),
            (2, '002_local_identity_and_audits', AUTH_SQL),
            (3, '003_backup_retention', BACKUP_SQL),
            (4, '004_state_direction_preference', STATE_PREFERENCES_SQL),
            (5, '005_cross_group_exclusion_lookup', (
                "CREATE INDEX IF NOT EXISTS idx_cross_group_exclusions_finding ON cross_group_exclusions(finding_id)",
            )),
            (6, '006_analysis_rule_lineage', (
                "ALTER TABLE analysis_rules ADD COLUMN parent_version INTEGER NOT NULL DEFAULT 0",
            )),
            (7, '007_outage_plans_and_tubes', (
                "CREATE TABLE IF NOT EXISTS outage_plans("
                "id TEXT PRIMARY KEY, plan_code TEXT NOT NULL UNIQUE, site_code TEXT NOT NULL, unit_id INTEGER NOT NULL, "
                "outage TEXT, title TEXT NOT NULL, planned_at TEXT NOT NULL, "
                "status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','completed','archived')))",
                "CREATE TABLE IF NOT EXISTS outage_plan_tubes("
                "plan_id TEXT NOT NULL REFERENCES outage_plans(id) ON DELETE CASCADE, "
                "thimble_id INTEGER NOT NULL, PRIMARY KEY(plan_id, thimble_id))",
                "CREATE INDEX IF NOT EXISTS idx_plan_tubes_thimble ON outage_plan_tubes(thimble_id)",
                "CREATE INDEX IF NOT EXISTS idx_plans_site_unit ON outage_plans(site_code, unit_id)",
            )))


def checksum(name, statements):
    return hashlib.sha256((name + '\n' + '\n'.join(statements)).encode()).hexdigest()


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def inspect_version(db):
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations' AND type='table'").fetchone()
    if not exists:
        return 0
    records = db.execute('SELECT version,name,checksum FROM schema_migrations ORDER BY version').fetchall()
    if [r[0] for r in records] != list(range(1, len(records) + 1)) or len(records) > VERSION:
        raise ValueError('数据库迁移版本不连续或高于当前软件，拒绝降级打开')
    for row, (version, name, statements) in zip(records, VERSIONS):
        if row[1] != name or row[2] != checksum(name, statements):
            raise ValueError('数据库迁移记录校验失败')
    return len(records)


def readonly(path):
    GATE.enter()
    db = None
    try:
        db = sqlite3.connect(
            Path(path).resolve().as_uri() + '?mode=ro',
            uri=True, factory=ClosingConnection, timeout=30,
        )
        db._gate_held = True
        db.execute('PRAGMA busy_timeout=30000')
        db.execute('PRAGMA query_only=ON')
        return db
    except Exception:
        if db is not None:
            db.close()
        else:
            GATE.leave()
        raise


def validate(path, current=False):
    with readonly(path) as db:
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('数据库完整性检查失败')
        try:
            from .cross_group_review import expected_triggers
        except ImportError:
            from cross_group_review import expected_triggers
        allowed = expected_triggers(db)
        normalize = lambda sql: ' '.join(sql.lower().split()).replace(' if not exists ', ' ')
        for kind, name, sql in db.execute("SELECT type,name,sql FROM sqlite_master WHERE type IN ('trigger','view')"):
            if kind != 'trigger' or name not in allowed or normalize(sql) != normalize(allowed[name]):
                raise ValueError('数据库包含非本软件定义的视图或触发器')
        required = {'findings': {'id','outage','unit_id','thimble_id','imported_at'},
                    'tube_states': {'outage','unit_id','thimble_id','state'},
                    'analysis_rules': {'id','version','match_tolerance_mm'},
                    'report_exports': {'id','path','created_at'}}
        if current:
            required['analysis_rules'].add('parent_version')
            required['findings'].update({'maintenance_text','business_key','is_deleted','import_batch_id','deleted_by'})
            required['tube_states'].update({'events_json','replacement_stage','offset_confirmed','unsigned_offset_mm','is_deleted'})
            required.update({'users': {'id','username','display_name','password_hash','active','failures','locked_until','created_at','updated_at'},
                             'login_sessions': {'token_hash','user_id','created_at','expires_at','last_seen','service_instance'},
                             'roles': {'code','label'}, 'permissions': {'code','label'},
                             'role_permissions': {'role_code','permission_code'},
                             'user_roles': {'user_id','role_code'},
                             'security_events': {'id','event_id','created_at','actor_id','operator','event_type','outcome','resource'},
                             'export_audits': {'id','event_id','created_at','actor_id','operator','resource','sha256','size_bytes'},
                             'restore_points': {'id','created_at','path','sha256','size_bytes','operator','note','kind'},
                             'backup_policy': {'id','automatic_keep'},
                             'state_preferences': {'id','shift_direction'},
                             'outage_plans': {'id','plan_code','site_code','unit_id','outage','title','planned_at','status'},
                             'outage_plan_tubes': {'plan_id','thimble_id'}})
        for table, columns in required.items():
            actual = {r[1] for r in db.execute(f'PRAGMA table_info({table})')}
            if not columns <= actual:
                raise ValueError('数据库表结构不兼容：' + table)
        version = inspect_version(db)
        if current and version != VERSION:
            raise ValueError('数据库尚未完成升级')
        if current and db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('数据库关联完整性检查失败')
        return version


def upgrade(path, legacy_upgrade):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with GATE.exclusive():
        old_version = 0
        if path.exists():
            with readonly(path) as db:
                if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                    raise ValueError('数据库损坏，已停止启动；请从已校验的备份恢复')
                old_version = inspect_version(db)
            if old_version == VERSION:
                validate(path, current=True)
                return False
        stage = path.with_name('.migration-' + uuid.uuid4().hex + '.db')
        try:
            if path.exists():
                with readonly(path) as source, sqlite3.connect(stage, factory=ClosingConnection) as target:
                    source.backup(target)
            if old_version == 0:
                legacy_upgrade(stage)
            with sqlite3.connect(stage, factory=ClosingConnection) as db:
                db.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY,name TEXT NOT NULL,checksum TEXT NOT NULL,applied_at TEXT NOT NULL)")
                for version, name, statements in VERSIONS:
                    if version <= old_version:
                        continue
                    for statement in statements:
                        # TRAE databases may already contain this compatible column.
                        if version == 6 and any(row[1] == 'parent_version' for row in
                                                db.execute('PRAGMA table_info(analysis_rules)')):
                            continue
                        db.execute(statement)
                    db.execute('INSERT INTO schema_migrations VALUES(?,?,?,?)',
                               (version, name, checksum(name, statements), utcnow()))
                    db.execute(f'PRAGMA user_version={version}')
            validate(stage, current=True)
            if path.exists():
                directory = path.parent / 'backups'
                directory.mkdir(exist_ok=True)
                safety = directory / ('migration-' + uuid.uuid4().hex + '.db')
                with readonly(path) as source, sqlite3.connect(safety, factory=ClosingConnection) as target:
                    source.backup(target)
                import json
                value = hashlib.sha256()
                with safety.open('rb') as stream:
                    for block in iter(lambda: stream.read(1024*1024), b''):
                        value.update(block)
                Path(str(safety)+'.sha256.json').write_text(json.dumps({'sha256':value.hexdigest(),'kind':'migration','created_at':utcnow()},ensure_ascii=False),encoding='utf-8')
                # Every managed connection is drained by the exclusive gate.
                with sqlite3.connect(path, factory=ClosingConnection) as db:
                    db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                    db.execute('PRAGMA journal_mode=DELETE')
            with sqlite3.connect(stage, factory=ClosingConnection) as db:
                db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                db.execute('PRAGMA journal_mode=DELETE')
            stage.replace(path)
            return True
        finally:
            for extra in (stage, Path(str(stage)+'-wal'), Path(str(stage)+'-shm')):
                extra.unlink(missing_ok=True)
