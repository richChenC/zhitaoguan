"""Test-only fixtures: no runtime auth bypass and no default credentials."""
import secrets
from src.backend import local_security


def admin_cookie(server):
    password = secrets.token_urlsafe(24)
    local_security.create_user(server, {'username':'test-admin','display_name':'Test administrator','password':password},setup=True)
    _, token = local_security.login(server, {'username':'test-admin','password':password})
    return local_security.cookie_header(token).split(';')[0]


def mark_legacy(server):
    # Model an actual pre-accounts database, not a damaged current-version DB.
    with server.connect() as db:
        db.execute('PRAGMA foreign_keys=OFF')
        for table in ('login_sessions','user_roles','role_permissions','permissions','roles','users',
                      'security_events','export_audits','backup_policy','state_preferences','schema_migrations'):
            db.execute('DROP TABLE IF EXISTS ' + table)
        db.execute('PRAGMA user_version=0')
