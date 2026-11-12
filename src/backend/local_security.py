"""Local accounts and server-owned identities. No remote provider or default password."""
from contextvars import ContextVar
from contextlib import contextmanager
import functools
import hashlib
import hmac
from http.cookies import SimpleCookie, CookieError
import os
import re
import secrets
import sqlite3
import time
import uuid
import sys
from urllib.parse import parse_qs, urlparse, quote

try:
    from . import schema_migrations
    from .database_runtime import GATE
except ImportError:
    import schema_migrations
    from database_runtime import GATE

PERMISSIONS = {
    'data.read':'查询数据', 'data.import':'导入数据', 'data.edit':'编辑检测记录',
    'state.write':'维护管状态', 'review.write':'审核数据', 'export.create':'导出报告和数据',
    'audit.read':'查看审计', 'backup.manage':'备份管理', 'database.restore':'恢复数据库',
    'data.delete':'删除和回收站恢复', 'data.purge':'永久删除', 'settings.manage':'管理专业设置',
    'users.manage':'管理本地账户',
}
ROLES = {
    'admin': ('系统管理员', set(PERMISSIONS)),
    'importer': ('数据导入员', {'data.read','data.import'}),
    'editor': ('数据编辑员', {'data.read','data.edit','state.write'}),
    'reviewer': ('审核员', {'data.read','review.write','audit.read'}),
    'reporter': ('报告用户', {'data.read','export.create'}),
    'viewer': ('只读用户', {'data.read'}),
}
IDENTITY_TABLES = ('users','roles','permissions','role_permissions','user_roles','security_events','export_audits')
COOKIE = 'thimble_session'
INSTANCE = secrets.token_hex(16)
SESSION_SECONDS = 8 * 3600
IDLE_SECONDS = 30 * 60
REMEMBER_SECONDS = 7 * 24 * 3600
REMEMBER_IDLE_SECONDS = 8 * 3600
MAX_LOGIN_FAILURES = 5
LOCK_SECONDS = 300
_principal = ContextVar('thimble_principal', default=None)
_DUMMY = None
_activity = {}


class AccessError(ValueError):
    def __init__(self, message, status=403, details=None):
        super().__init__(message)
        self.status = status
        self.details = details or {}


def actor():
    principal = _principal.get()
    return principal['username'] if principal else 'system:maintenance'


def actor_id():
    principal = _principal.get()
    return principal['id'] if principal else 'system'


def can_any(*permissions):
    principal = _principal.get()
    return principal is None or any(code in principal['permissions'] for code in permissions)


@contextmanager
def identity(principal):
    token = _principal.set(principal)
    try:
        yield
    finally:
        _principal.reset(token)


def _password(password):
    if not isinstance(password, str) or not 6 <= len(password) <= 128:
        raise ValueError('密码需至少 6 位，最多 128 位')
    return password


def hash_password(password):
    password = _password(password)
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
    return f'pbkdf2_sha256$600000${salt}${digest}'


def verify_password(password, encoded):
    if not isinstance(password, str) or len(password) > 128:
        return False
    try:
        algorithm, rounds, salt, expected = encoded.split('$')
        if algorithm != 'pbkdf2_sha256' or not 600000 <= int(rounds) <= 2000000:
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def seed(db):
    for code, label in PERMISSIONS.items():
        db.execute('INSERT OR IGNORE INTO permissions VALUES(?,?)', (code,label))
    for code, (label, permissions) in ROLES.items():
        db.execute('INSERT OR IGNORE INTO roles VALUES(?,?)', (code,label))
        for permission in sorted(permissions):
            db.execute('INSERT OR IGNORE INTO role_permissions VALUES(?,?)', (code,permission))


def event(db, kind, outcome='success', resource=''):
    db.execute('INSERT INTO security_events(event_id,created_at,actor_id,operator,event_type,outcome,resource) VALUES(?,?,?,?,?,?,?)',
               (uuid.uuid4().hex, schema_migrations.utcnow(), actor_id(), actor(), kind, outcome, str(resource)[:200]))


def public_user(db, user):
    result = {key: user[key] for key in ('id','username','display_name','active')}
    result['roles'] = [r[0] for r in db.execute('SELECT role_code FROM user_roles WHERE user_id=? ORDER BY role_code', (user['id'],))]
    result['permissions'] = [r[0] for r in db.execute('SELECT DISTINCT permission_code FROM role_permissions p JOIN user_roles r ON p.role_code=r.role_code WHERE r.user_id=? ORDER BY permission_code', (user['id'],))]
    return result


def initialized(server):
    with server.connect() as db:
        return bool(db.execute('SELECT 1 FROM users LIMIT 1').fetchone())


def _normalize(data):
    username = data.get('username', '')
    display = data.get('display_name', '')
    if not isinstance(username, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{1,63}', username):
        raise ValueError('用户名需为 2–64 位字母、数字、点、下划线或短横线')
    if not isinstance(display, str) or not 1 <= len(display.strip()) <= 80 or any(ord(c)<32 for c in display):
        raise ValueError('请填写 1–80 字符的显示名称')
    roles = data.get('roles')
    if not isinstance(roles, list) or not roles or not all(isinstance(r,str) and r in ROLES for r in roles):
        raise ValueError('请选择有效的本地角色')
    return username.lower(), display.strip(), sorted(set(roles))


def create_user(server, data, setup=False):
    if setup:
        data = {**data, 'roles':['admin']}
    username, display, roles = _normalize(data)
    encoded = hash_password(data.get('password'))
    ident = uuid.uuid4().hex
    active = True if setup else data.get('active',True)
    if type(active) is not bool:
        raise ValueError('账户状态必须为布尔值')
    with server.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if setup and db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            raise AccessError('管理员已经初始化，不能重复初始化')
        try:
            db.execute('INSERT INTO users(id,username,display_name,password_hash,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                       (ident,username,display,encoded,int(active),schema_migrations.utcnow(),schema_migrations.utcnow()))
        except sqlite3.IntegrityError:
            raise ValueError('用户名已存在') from None
        for role in roles:
            db.execute('INSERT INTO user_roles VALUES(?,?)',(ident,role))
        if setup:
            with identity({'id':ident,'username':username}):
                event(db,'admin_setup',resource=ident)
        else:
            event(db,'user_create',resource=ident)
    return {'ok':True, 'user_id':ident}


def login(server, data):
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password(secrets.token_urlsafe(24))
    username = str(data.get('username',''))[:64].lower()
    lifetime = REMEMBER_SECONDS if data.get('remember') is True else SESSION_SECONDS
    now = int(time.time())
    raw_token = secrets.token_urlsafe(32)
    failures = None
    locked_until = 0
    with server.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        user = db.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
        valid = verify_password(data.get('password',''), user['password_hash'] if user else _DUMMY)
        if not user or not valid or not user['active'] or user['locked_until'] > now:
            if user and user['locked_until'] <= now:
                failures = user['failures'] + 1
                locked_until = now + LOCK_SECONDS if failures >= MAX_LOGIN_FAILURES else 0
                db.execute('UPDATE users SET failures=?,locked_until=? WHERE id=?',
                           (failures, locked_until, user['id']))
            elif user:
                failures, locked_until = user['failures'], user['locked_until']
            event(db,'login','failed')
            result = None
        else:
            db.execute('UPDATE users SET failures=0,locked_until=0 WHERE id=?',(user['id'],))
            db.execute('DELETE FROM login_sessions WHERE expires_at<=? OR service_instance<>?', (now,INSTANCE))
            db.execute('INSERT INTO login_sessions VALUES(?,?,?,?,?,?)',
                       (hashlib.sha256(raw_token.encode()).hexdigest(),user['id'],now,now+lifetime,now,INSTANCE))
            result = public_user(db,user)
            with identity(result):
                event(db,'login')
    if result is None:
        details = {}
        if user and not user['active']:
            message = '账户已停用，请联系系统管理员'
            details['account_disabled'] = True
        elif locked_until > now:
            message = '账户已锁定，请稍后重试'
            details['locked_seconds'] = max(0, int(locked_until - now))
        else:
            message = '用户名或密码错误'
            if failures is not None and failures < MAX_LOGIN_FAILURES:
                details['remaining_attempts'] = MAX_LOGIN_FAILURES - failures
        raise AccessError(message, 401, details)
    return result, raw_token


def token_from_cookie(header):
    try:
        cookies = SimpleCookie();cookies.load(header or '')
        token = cookies.get(COOKIE)
        return token.value if token and len(token.value) <= 128 else ''
    except CookieError:
        return ''


def session(server, cookie):
    raw = token_from_cookie(cookie)
    if not raw:
        return None
    digest = hashlib.sha256(raw.encode()).hexdigest()
    now = int(time.time())
    with server.connect() as db:
        user = db.execute('SELECT u.*,s.token_hash,s.last_seen,(s.expires_at-s.created_at) AS session_seconds FROM users u JOIN login_sessions s ON s.user_id=u.id WHERE s.token_hash=? AND s.expires_at>? AND s.service_instance=? AND u.active=1',
                          (digest,now,INSTANCE)).fetchone()
        if not user:
            return None
        idle = REMEMBER_IDLE_SECONDS if (user['session_seconds'] or 0) > SESSION_SECONDS else IDLE_SECONDS
        if _activity.get(digest,user['last_seen']) <= now-idle:
            _activity.pop(digest, None)
            return None
        _activity[digest] = now
        if len(_activity) > 8192:
            _activity.clear()
        # Progress polling must not wait for the import writer's transaction.
        # Sessions never survive a service restart; the in-process idle clock
        # remains authoritative when SQLite is temporarily busy.
        if now-user['last_seen'] >= 60:
            db.execute('PRAGMA busy_timeout=0')
            try:
                db.execute('UPDATE login_sessions SET last_seen=? WHERE token_hash=?',(now,digest))
            except sqlite3.OperationalError as error:
                if error.sqlite_errorcode not in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):
                    raise
            finally:
                db.execute('PRAGMA busy_timeout=10000')
        return public_user(db,user)


def cookie_header(token='', max_age=0):
    # HTTP loopback only. Secure cannot be set until transport uses HTTPS.
    header = f'{COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/'
    return header + ('; Max-Age=0' if not token else f'; Max-Age={int(max_age)}' if max_age else '')


def update_user(server,data):
    ident = str(data.get('id',''))
    with server.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        user = db.execute('SELECT * FROM users WHERE id=?',(ident,)).fetchone()
        if not user:
            raise ValueError('账户不存在')
        roles = data.get('roles',public_user(db,user)['roles'])
        active = data.get('active',bool(user['active']))
        if not isinstance(active,bool):
            raise ValueError('账户状态必须为布尔值')
        username, display, roles = _normalize({'username':user['username'], 'display_name':data.get('display_name',user['display_name']), 'roles':roles})
        others = db.execute("SELECT COUNT(DISTINCT u.id) FROM users u JOIN user_roles r ON r.user_id=u.id WHERE u.active=1 AND r.role_code='admin' AND u.id<>?",(ident,)).fetchone()[0]
        if not others and ('admin' not in roles or not active):
            raise ValueError('必须保留至少一个启用的管理员账户')
        db.execute('UPDATE users SET display_name=?,active=?,updated_at=? WHERE id=?',(display,int(active),schema_migrations.utcnow(),ident))
        if data.get('password'):
            db.execute('UPDATE users SET password_hash=?,failures=0,locked_until=0 WHERE id=?',(hash_password(data['password']),ident))
        db.execute('DELETE FROM user_roles WHERE user_id=?',(ident,))
        for role in roles:
            db.execute('INSERT INTO user_roles VALUES(?,?)',(ident,role))
        db.execute('DELETE FROM login_sessions WHERE user_id=?',(ident,))
        event(db,'user_update',resource=ident)
    return {'ok':True}


GET_PERMISSIONS = {
    '/api/health':None,'/api/auth/status':None,'/api/auth/me':'authenticated',
    '/api/auth/users':'users.manage','/api/security/events':'audit.read',
    '/api/security/exports':'audit.read','/api/schema-migrations':'audit.read',
    '/api/backups':'backup.manage','/api/backup-policy':'backup.manage',
    '/api/recycle-bin/list':'data.delete','/api/operation-logs':'audit.read','/api/logs/recent':'audit.read',
    '/api/state-history':'data.read', '/api/export':'export.create',
    '/api/download-excel':'export.create','/api/download-report':'export.create',
    '/api/settings/data-source':'data.read',
    '/api/settings/state-direction':'authenticated',
}
READ_PATHS = {'/api/documentation','/api/import-progress','/api/reports/templates','/api/overview',
              '/api/analysis/visualization','/api/analysis/live','/api/analysis/tube',
              '/api/duplicates','/api/analysis-rules','/api/cross-group-reviews',
              '/api/validation-issues','/api/import-batches','/api/data-quality',
              '/api/analytics/summary','/api/analytics/bases','/api/analytics/group-trend',
              '/api/analytics/p-position','/api/analytics/tube-status','/api/states',
              '/api/states/scope','/api/findings','/api/tube-history','/api/unit-evolution',
              '/api/analysis/tube-longitudinal'}
GET_PERMISSIONS.update({path:'data.read' for path in READ_PATHS})
GET_PERMISSIONS['/api/compare'] = 'data.read'
POST_PERMISSIONS = {
    '/api/auth/setup':None,'/api/auth/login':None,'/api/auth/logout':'authenticated',
    '/api/auth/password':'authenticated','/api/auth/users':'users.manage','/api/auth/users/update':'users.manage',
    '/api/findings/edit':'data.edit','/api/data-ledger/export':'export.create',
    '/api/settings/data-source':'settings.manage','/api/settings/data-source/validate':'settings.manage',
    '/api/settings/state-direction':'authenticated',
    '/api/cross-group-reviews':'review.write','/api/reports/preview':'data.read','/api/reports/export':'export.create',
    '/api/report-options':'data.import','/api/discover-server':'data.import',
    '/api/import':'data.import','/api/import-excel':'data.import','/api/import-excel-inspect':'data.import',
      '/api/import-directory-preview':'data.import',
    '/api/data-quality/export':'export.create','/api/import-batches/action':'data.delete',
    '/api/export-indication-warnings':'export.create','/api/deduplicate':'data.purge',
    '/api/analysis-rules':'settings.manage','/api/backup':'backup.manage',
    '/api/backup-validate':'backup.manage','/api/backup-policy':'backup.manage','/api/restore':'database.restore',
    '/api/export-comparison':'export.create','/api/export-evolution':'export.create','/api/export-report':'export.create',
    '/api/report-preview':'data.read','/api/data/delete-preview':'data.delete','/api/data/delete':'data.delete',
    '/api/recycle-bin/restore':'data.delete','/api/recycle-bin/purge':'data.purge','/api/clear':'data.purge',
    '/api/export-folder-excel':'export.create','/api/state':'state.write','/api/states/scopes':'state.write',
    '/api/states/dismiss-recognition':'state.write','/api/states/batch':'state.write',
    '/api/states/batch-preview':'state.write','/api/states/import-preview':'state.write',
    '/api/states/export':'export.create','/api/states/delete-batch':'state.write',
    '/api/states/recognize-note':'state.write','/api/state-delete':'state.write',
    '/api/security/image-export':'export.create',
    '/api/audits/export':'export.create',
}


def require(server, handler, path, method):
    permission = (GET_PERMISSIONS if method=='GET' else POST_PERMISSIONS).get(path,'unknown')
    if permission == 'unknown':
        raise AccessError('接口不存在',404)
    if method=='POST' and handler.headers.get('X-Thimble-Request') != '1':
        raise AccessError('请求缺少本地交互校验')
    if permission is None:
        return None
    principal = session(server,handler.headers.get('Cookie'))
    if not principal:
        raise AccessError('请先登录本地账户',401)
    if permission != 'authenticated' and permission not in principal['permissions']:
        with identity(principal), server.connect() as db:
            event(db,'permission_denied','denied',path)
        raise AccessError('当前账户没有此操作权限')
    return principal


def auth_get(server, handler, path):
    if path=='/api/auth/status':
        return {'initialized':initialized(server),'offline':True}
    if path=='/api/auth/me':
        return {'user':_principal.get()}
    if path=='/api/auth/users':
        with server.connect() as db:
            users = []
            for user in db.execute('SELECT * FROM users ORDER BY username'):
                item = public_user(db, user)
                last = db.execute("SELECT created_at FROM security_events WHERE event_type='login' "
                                  "AND outcome='success' AND operator=? ORDER BY created_at DESC LIMIT 1",
                                  (user['username'],)).fetchone()
                item['last_login'] = last[0] if last else ''
                users.append(item)
            return {'users':users,
                    'roles':[{'code':code,'label':values[0],'permissions':sorted(values[1])} for code,values in ROLES.items()]}
    if path in ('/api/security/events','/api/security/exports','/api/schema-migrations'):
        table = {'/api/security/events':'security_events','/api/security/exports':'export_audits','/api/schema-migrations':'schema_migrations'}[path]
        with server.connect() as db:
            query = parse_qs(urlparse(handler.path).query)
            page = max(1, int(query.get('page', [1])[0]))
            size = max(1, min(200, int(query.get('size', [100])[0])))
            return {'items':[dict(r) for r in db.execute(
                f'SELECT * FROM {table} ORDER BY id DESC LIMIT ? OFFSET ?', (size, (page - 1) * size))],
                'total': db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 'page': page, 'size': size}
    return None


def auth_post(server, handler, path, data):
    if path == '/api/audits/export':
        principal = _principal.get()
        if principal is not None and 'audit.read' not in principal['permissions']:
            raise AccessError('当前账户没有查看审计权限')
        from openpyxl import Workbook
        try:
            from . import artifact_naming
        except ImportError:
            import artifact_naming
        book = Workbook()
        book.remove(book.active)
        with server.connect() as db:
            for table, title in (('operation_logs', '操作审计'), ('security_events', '安全审计'),
                                 ('export_audits', '导出校验')):
                sheet = book.create_sheet(title)
                cursor = db.execute(f'SELECT * FROM {table} ORDER BY id')
                sheet.append([column[0] for column in cursor.description])
                for row in cursor:
                    sheet.append(list(row))
                for row in sheet.iter_rows():
                    for cell in row:
                        if isinstance(cell.value, str):
                            cell.data_type = 's'
        return server.workbook_result(artifact_naming.filename('审计台账', '完整历史', 'xlsx'), book)
    if path=='/api/security/image-export':
        resource = str(data.get('name','image'))[:200]
        digest = data.get('sha256','')
        size = data.get('size_bytes',0)
        if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest) or type(size) is not int or not 0 < size <= 50*1024*1024:
            raise ValueError('图片导出校验信息无效')
        with server.connect() as db:
            db.execute('INSERT INTO export_audits(event_id,created_at,actor_id,operator,resource,sha256,size_bytes) VALUES(?,?,?,?,?,?,?)',
                       (uuid.uuid4().hex,schema_migrations.utcnow(),actor_id(),actor(),resource,digest,size))
        return {'ok':True}
    if path=='/api/auth/setup':
        return create_user(server,data,setup=True)
    if path=='/api/auth/login':
        user, token = login(server,data)
        handler.auth_cookie = cookie_header(token, REMEMBER_SECONDS if data.get('remember') is True else 0)
        return {'user':user}
    if path=='/api/auth/logout':
        raw = token_from_cookie(handler.headers.get('Cookie'))
        with server.connect() as db:
            db.execute('DELETE FROM login_sessions WHERE token_hash=?',(hashlib.sha256(raw.encode()).hexdigest(),))
            event(db,'logout')
        handler.auth_cookie = cookie_header()
        return {'ok':True}
    if path=='/api/auth/password':
        with server.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            user = db.execute('SELECT * FROM users WHERE id=?',(actor_id(),)).fetchone()
            if not verify_password(data.get('current_password',''),user['password_hash']):
                raise AccessError('当前密码错误')
            db.execute('UPDATE users SET password_hash=?,updated_at=? WHERE id=?',
                       (hash_password(data.get('password')),schema_migrations.utcnow(),actor_id()))
            db.execute('DELETE FROM login_sessions WHERE user_id=?',(actor_id(),))
            event(db,'password_change')
        handler.auth_cookie = cookie_header()
        return {'ok':True,'login_required':True}
    if path=='/api/auth/users':
        return create_user(server,data)
    if path=='/api/auth/users/update':
        return update_user(server,data)
    return None


def export_bytes(server, resource, payload):
    with server.connect() as db:
        db.execute('INSERT INTO export_audits(event_id,created_at,actor_id,operator,resource,sha256,size_bytes) VALUES(?,?,?,?,?,?,?)',
                   (uuid.uuid4().hex,schema_migrations.utcnow(),actor_id(),actor(),str(resource)[:200],hashlib.sha256(payload).hexdigest(),len(payload)))


def audit_response(server, handler, data, status):
    if not getattr(handler,'principal',None) or getattr(handler,'_response_audited',False):
        return
    handler._response_audited = True
    path = urlparse(handler.path).path
    if handler.command=='POST' and path not in ('/api/auth/login','/api/auth/setup'):
        with server.connect() as db:
            event(db, 'request', 'success' if status < 400 else 'failed', path)
    permission = POST_PERMISSIONS.get(path)
    if status < 400 and permission=='export.create' and isinstance(data,dict):
        # Only server-produced output files; never follow a client supplied path here.
        roots = [server.EXCEL_DIR.resolve(),server.REPORT_DIR.resolve()]
        seen = set()
        def visit(item):
            if isinstance(item,dict):
                for key,value in item.items():
                    if key in ('path','file_path') and isinstance(value,str):
                        from pathlib import Path
                        file = Path(value).resolve()
                        if file not in seen and file.is_file() and any(root in file.parents for root in roots):
                            seen.add(file)
                            export_bytes(server,file.name,file.read_bytes())
                    elif isinstance(value,(dict,list)):
                        visit(value)
            elif isinstance(item,list):
                for value in item:
                    visit(value)
        visit(data)


def http_boundary(method):
    def decorate(function):
        @functools.wraps(function)
        def wrapped(handler):
            server = sys.modules[function.__module__]
            path = urlparse(handler.path).path
            handler.auth_cookie = None
            handler.principal = None
            handler._response_audited = False
            if not handler.request_is_local():
                return handler.json_response({'error':'Forbidden'},403)
            gate = GATE.exclusive if method=='POST' and path=='/api/restore' else GATE.shared
            try:
                with gate():
                    if method=='POST':
                        if handler.headers.get_content_type() != 'application/json':
                            return handler.json_response({'error':'Content-Type must be application/json'},415)
                        handler.request_data = handler.body()
                    if path.startswith('/api/'):
                        principal = require(server,handler,path,method)
                    else:
                        principal = None
                        if path in ('/','/index.html'):
                            principal = session(server,handler.headers.get('Cookie'))
                            if not principal:
                                handler.send_response(302)
                                handler.send_header('Location','/login.html?next=' + quote(handler.path,safe=''))
                                handler.send_header('Cache-Control','no-store')
                                handler.send_header('Content-Length','0')
                                handler.end_headers()
                                return
                    handler.principal = principal
                    with identity(principal):
                        if path.startswith('/api/'):
                            result = auth_get(server,handler,path) if method=='GET' else auth_post(server,handler,path,handler.request_data)
                            if result is not None:
                                return handler.json_response(result)
                        if method=="POST" and path in ("/api/state-delete","/api/states/delete-batch"):
                            server._auto_backup("state_delete")
                        return function(handler)
            except AccessError as error:
                return handler.json_response({'error':str(error), **error.details},error.status)
            except (ValueError,sqlite3.DatabaseError) as error:
                message = str(error) if isinstance(error,ValueError) else '本地数据库不可用，请使用已校验的备份恢复'
                return handler.json_response({'error':message},400 if isinstance(error,ValueError) else 503)
        return wrapped
    return decorate
