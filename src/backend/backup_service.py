"""Offline SQLite snapshots and staged restore; no live-file copies."""
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

try:
    from . import artifact_naming, local_security, schema_migrations
    from .database_runtime import GATE
except ImportError:
    import artifact_naming, local_security, schema_migrations
    from database_runtime import GATE


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def manifest_path(path):
    return Path(str(path) + '.sha256.json')


def kind_label(kind):
    labels = {'manual': '手动备份', 'exported': '导出备份', 'safety': '恢复前备份',
              'auto': '自动备份', 'legacy': '历史备份（未登记）'}
    if kind in labels:
        return labels[kind]
    if str(kind).startswith('auto:'):
        reason = {'startup': '启动前', 'deduplicate': '去重前', 'purge': '彻底删除前',
                  'finding': '删除记录前', 'selected': '批量删除前',
                  'tube_outage': '删除单次大修管记录前', 'tube_all': '删除管历史前',
                  'outage': '删除大修前', 'unit': '删除机组前', 'site': '删除基地前',
                  'all': '清空前'}.get(kind[5:], '操作前')
        return reason + '自动备份'
    return '其他备份'


def copy_database(source, target, *, timeout=30):
    deadline = time.monotonic() + timeout

    def progress(status, remaining, total):
        if status != sqlite3.SQLITE_DONE and time.monotonic() >= deadline:
            raise ValueError('数据库持续忙碌或复制超时，操作已取消，请关闭占用数据库的程序后重试')

    source.backup(target, pages=128, progress=progress, sleep=.05)


def snapshot(source, target):
    with schema_migrations.readonly(source) as src, sqlite3.connect(target, factory=schema_migrations.ClosingConnection) as dst:
        copy_database(src, dst)


def policy(server, data=None):
    with server.connect() as db:
        if data is not None:
            keep = data.get('automatic_keep')
            if type(keep) is not int or not 5 <= keep <= 200:
                raise ValueError('自动备份保留数量应为 5–200')
            db.execute('UPDATE backup_policy SET automatic_keep=? WHERE id=1', (keep,))
            local_security.event(db, 'backup_policy_update', resource=str(keep))
        return {'automatic_keep': db.execute('SELECT automatic_keep FROM backup_policy WHERE id=1').fetchone()[0]}


def prune(server):
    keep = policy(server)['automatic_keep']
    root = server._backup_dir().resolve()
    with server.connect() as db:
        rows = db.execute("SELECT * FROM restore_points WHERE kind LIKE 'auto:%' ORDER BY id DESC").fetchall()
        for row in rows[keep:]:
            target = Path(row['path']).resolve()
            if target.parent != root or target.suffix != '.db':
                continue
            # Only registered automatic snapshots with unchanged bytes are eligible.
            if target.exists() and digest(target) != row['sha256']:
                continue
            target.unlink(missing_ok=True)
            manifest_path(target).unlink(missing_ok=True)
            db.execute('DELETE FROM restore_points WHERE id=?', (row['id'],))


def create(server, note='', target='', kind=''):
    with GATE.shared():
        directory = Path(target).expanduser().resolve() if target else server._backup_dir()
        if not directory.is_dir():
            raise ValueError('备份目标文件夹不存在')
        kind = kind or ('exported' if target else 'manual')
        label = kind_label(kind)
        path = directory / artifact_naming.filename('数据库备份', label.removesuffix('备份'), 'db')
        try:
            snapshot(server.DB_PATH, path)
            schema_migrations.validate(path, current=True)
            result = {'name': path.name, 'path': str(path), 'size_bytes': path.stat().st_size,
                      'sha256': digest(path), 'created_at': schema_migrations.utcnow(),
                      'kind': kind, 'kind_label': label, 'operator': local_security.actor(), 'note': str(note)[:500]}
            manifest_path(path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            with server.connect() as db:
                result['id'] = db.execute('INSERT INTO restore_points(created_at,path,sha256,size_bytes,operator,note,kind) VALUES(?,?,?,?,?,?,?)',
                    tuple(result[k] for k in ('created_at','path','sha256','size_bytes','operator','note','kind'))).lastrowid
                server._log_operation('backup', 'database', path.name, backup_file=str(path), note=str(note)[:500], connection=db)
        except Exception as error:
            path.unlink(missing_ok=True)
            manifest_path(path).unlink(missing_ok=True)
            if (isinstance(error, sqlite3.Error) and
                    (getattr(error, "sqlite_errorcode", None) == sqlite3.SQLITE_FULL or
                     "database or disk is full" in str(error).lower())) or (
                    isinstance(error, OSError) and error.errno == 28):
                raise ValueError(
                    f"备份失败：磁盘空间不足。保存目录：{directory}。"
                    "请释放空间或选择其他备份目录后重试；本次操作未继续执行。"
                ) from error
            raise
        if kind.startswith('auto:'):
            prune(server)
        return result


def validate(server, path):
    target = Path(str(path or '')).expanduser().resolve()
    if not target.is_file() or target == Path(server.DB_PATH).resolve():
        raise ValueError('请选择当前数据库以外的有效备份文件')
    try:
        actual = digest(target)
        expected = []
        with server.connect() as db:
            row = db.execute('SELECT sha256 FROM restore_points WHERE path=? ORDER BY id DESC LIMIT 1', (str(target),)).fetchone()
            if row:
                expected.append(row[0])
        sidecar = manifest_path(target)
        if sidecar.exists():
            if sidecar.stat().st_size > 65536:
                raise ValueError('备份校验清单过大')
            expected.append(json.loads(sidecar.read_text(encoding='utf-8'))['sha256'])
        if any(value != actual for value in expected):
            raise ValueError('备份 SHA-256 校验失败，禁止恢复')
        version = schema_migrations.validate(target)
        with schema_migrations.readonly(target) as db:
            count = db.execute('SELECT COUNT(*) FROM findings').fetchone()[0]
    except (sqlite3.Error, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('备份文件或校验清单无效') from exc
    return {'path':str(target),'name':target.name,'size_bytes':target.stat().st_size,
            'integrity':'ok','findings':count,'schema_version':version,'sha256':actual,
            'hash_verified':bool(expected), 'verification': 'sha256' if expected else 'legacy_integrity_only'}


def restore(server, path):
    with GATE.exclusive():
        verified = validate(server, path)
        current = Path(server.DB_PATH).resolve()
        stage = current.with_name('.restore-' + uuid.uuid4().hex + '.db')
        try:
            # Copy bytes first, then verify this exact staged snapshot (TOCTOU safe).
            with Path(verified['path']).open('rb') as src, stage.open('xb') as dst:
                for block in iter(lambda: src.read(1024 * 1024), b''):
                    dst.write(block)
            if digest(stage) != verified['sha256']:
                raise ValueError('备份在校验后发生变化，恢复已取消')
            server.init_db(stage)
            # Accounts, audit trail and backup registry belong to this installation.
            preserve = local_security.IDENTITY_TABLES + ('operation_logs', 'restore_points', 'backup_policy')
            safety = create(server, note='数据库恢复前安全备份', kind='safety')
            with server.connect() as source, sqlite3.connect(stage, factory=schema_migrations.ClosingConnection) as target:
                target.execute('PRAGMA foreign_keys=OFF')
                target.execute('BEGIN IMMEDIATE')
                target.execute('DELETE FROM login_sessions')
                for table in preserve:
                    columns = [r[1] for r in source.execute(f'PRAGMA table_info({table})')]
                    rows = source.execute(f'SELECT * FROM {table}').fetchall()
                    target.execute(f'DELETE FROM {table}')
                    placeholders = ','.join('?' for _ in columns)
                    target.executemany(f'INSERT INTO {table}({",".join(columns)}) VALUES({placeholders})', [tuple(row) for row in rows])
                local_security.event(target, 'database_restore', resource=verified['sha256'])
                server._log_operation('restore','database',verified['name'],backup_file=verified['path'],note='安全备份：'+safety['path'],connection=target)
                if target.execute('PRAGMA foreign_key_check').fetchone():
                    raise ValueError('恢复后的账户关联校验失败')
            schema_migrations.validate(stage, current=True)
            # All managed connections are drained by the maintenance gate.
            # The current database is about to be replaced.  Touching its
            # journal mode can fail on Windows when an external read handle
            # still exists even though all managed connections are drained.
            # Only the staged copy needs WAL finalization before replacement.
            for file in (stage,):
                with sqlite3.connect(
                    file, factory=schema_migrations.ClosingConnection, timeout=30
                ) as db:
                    db.execute('PRAGMA busy_timeout=30000')
                    db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                    db.commit()
            # Keep the live database path open on Windows. Replacing the file
            # with os.replace() is rejected while the service or an external
            # reader still owns a handle. SQLite's backup API is transactional
            # and writes the verified staged snapshot into the existing path.
            with sqlite3.connect(
                stage, factory=schema_migrations.ClosingConnection, timeout=30
            ) as source, sqlite3.connect(
                current, factory=schema_migrations.ClosingConnection, timeout=30
            ) as target:
                target.execute('PRAGMA busy_timeout=30000')
                copy_database(source, target)
                target.commit()
                try:
                    target.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                except sqlite3.OperationalError:
                    # A reader may briefly hold the WAL; the backup itself is
                    # already committed and SQLite will checkpoint later.
                    pass
            with server.connect() as db:
                after = db.execute('SELECT COUNT(*),COUNT(DISTINCT outage) FROM findings WHERE is_deleted=0').fetchone()
            return {'restored_from':verified['path'],'safety_backup':safety['path'],
                    'findings_after':after[0],'outages_after':after[1],'login_required':True}
        finally:
            for extra in (stage, Path(str(stage)+'-wal'), Path(str(stage)+'-shm')):
                extra.unlink(missing_ok=True)
