"""Stable per-user storage, with a one-time copy of an old local database."""
import json
import os
from pathlib import Path
import uuid

try:
    from . import backup_service, schema_migrations
except ImportError:
    import backup_service, schema_migrations


def user_root():
    if os.environ.get('THIMBLE_USER_DATA_DIR'):
        return Path(os.environ['THIMBLE_USER_DATA_DIR']).expanduser().resolve()
    roaming = os.environ.get('APPDATA')
    if roaming:
        return Path(roaming) / 'ThimbleInspection'
    profile = os.environ.get('USERPROFILE')
    if profile:
        return Path(profile) / 'AppData' / 'Roaming' / 'ThimbleInspection'
    return Path.home() / '.local' / 'share' / 'ThimbleInspection'


def migrate_legacy(server):
    target = Path(server.DB_PATH).resolve()
    if target.exists() or (os.environ.get('THIMBLE_MIGRATE_LEGACY') != '1' and (os.environ.get('THIMBLE_DB_PATH') or os.environ.get('THIMBLE_DATA_DIR'))):
        return None
    candidates = [server.ROOT/'data'/'thimble.db', server.ROOT/'.user-data'/'data'/'thimble.db']
    if os.environ.get('THIMBLE_MIGRATE_LEGACY') == '1':
        candidates = [Path(item)/'thimble.db' for item in json.loads(os.environ.get('THIMBLE_LEGACY_DATA_DIRS','[]'))]
    existing = list(dict.fromkeys(p.resolve() for p in candidates if p.is_file() and p.resolve()!=target))
    if not existing:
        return None
    if len(existing) > 1 and backup_service.digest(existing[0]) != backup_service.digest(existing[1]):
        raise ValueError('发现两个不同的旧版数据库，请先确认使用哪一个，通过 THIMBLE_DB_PATH 指定；软件未自动覆盖或合并')
    source = existing[0]
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.with_name('.relocation-' + uuid.uuid4().hex + '.db')
    try:
        backup_service.snapshot(source, stage)
        schema_migrations.validate(stage)
        server.init_db(stage)
        stage.replace(target)
        record={'source':str(source),'destination':str(target),'created_at':schema_migrations.utcnow(),
                'source_preserved':True,'destination_sha256':backup_service.digest(target)}
        (target.parent/'storage-relocation.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        return record
    finally:
        for extra in (stage,Path(str(stage)+'-wal'),Path(str(stage)+'-shm')):
            extra.unlink(missing_ok=True)
