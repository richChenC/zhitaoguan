import hashlib
import http.client
import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from xml.etree import ElementTree

from openpyxl import Workbook, load_workbook

from src.backend import server, local_security, schema_migrations, backup_service, local_storage
from src.backend.database_runtime import GATE
from enterprise_fixtures import mark_legacy


class LocalEnterpriseTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        for name,value in {'DB_PATH':self.root/'local.db','EXCEL_DIR':self.root/'excel','REPORT_DIR':self.root/'reports'}.items():
            patcher=patch.object(server,name,value);patcher.start();self.addCleanup(patcher.stop)
        server.init_db()
        self.password=secrets.token_urlsafe(24)
        local_security.create_user(server,{'username':'admin','display_name':'Administrator','password':self.password},setup=True)
        self.admin,self.token=local_security.login(server,{'username':'admin','password':self.password})
        self.cookie=local_security.cookie_header(self.token).split(';')[0]
        self.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close_http)

    def close_http(self):
        self.http.shutdown();self.http.server_close();self.thread.join(5)

    def request(self,path,method='GET',data=None,cookie=None,header=True):
        connection=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=15)
        headers={'Content-Type':'application/json'}
        if header:headers['X-Thimble-Request']='1'
        if cookie:headers['Cookie']=cookie
        connection.request(method,path,body=json.dumps(data) if data is not None else None,headers=headers)
        response=connection.getresponse();raw=response.read();status=response.status
        values=dict(response.getheaders());connection.close()
        try:body=json.loads(raw)
        except (ValueError,UnicodeError):body=raw
        return status,body,values

    def user(self,role):
        password=secrets.token_urlsafe(24)
        result=local_security.create_user(server,{'username':'user-'+role,'display_name':role,'password':password,'roles':[role]})
        user,token=local_security.login(server,{'username':'user-'+role,'password':password})
        return user,local_security.cookie_header(token).split(';')[0],result['user_id']

    def test_every_business_route_requires_a_session(self):
        for method,paths in (('GET',local_security.GET_PERMISSIONS),('POST',local_security.POST_PERMISSIONS)):
            for path,permission in paths.items():
                if permission is None:continue
                with self.subTest(path=path):self.assertEqual(self.request(path,method,{} if method=='POST' else None)[0],401)

    def test_audit_pagination_and_export_require_read_and_export_permissions(self):
        with server.connect() as db:
            for index in range(205):
                db.execute("INSERT INTO security_events(event_id,created_at,actor_id,operator,event_type,outcome,resource)"
                           " VALUES(?,?,?,?,?,?,?)",
                           (str(index), '2026-11-08', 'system', '=FORMULA()', 'regression', 'success', str(index)))
        status, first, _ = self.request('/api/security/events?page=1&size=100', cookie=self.cookie)
        status2, second, _ = self.request('/api/security/events?page=2&size=100', cookie=self.cookie)
        self.assertEqual((status, status2), (200, 200))
        self.assertEqual(len(first['items']), 100)
        self.assertEqual(len(second['items']), 100)
        self.assertFalse({r['id'] for r in first['items']} & {r['id'] for r in second['items']})
        _, reporter, _ = self.user('reporter')
        _, reviewer, _ = self.user('reviewer')
        self.assertEqual(self.request('/api/audits/export', 'POST', {}, reporter)[0], 403)
        self.assertEqual(self.request('/api/audits/export', 'POST', {}, reviewer)[0], 403)
        status, result, _ = self.request('/api/audits/export', 'POST', {}, self.cookie)
        self.assertEqual(status, 200, result)
        book = load_workbook(result['file_path'])
        try:
            self.assertGreater(book['安全审计'].max_row, 205)
            formula = next(cell for row in book['安全审计'] for cell in row if cell.value == '=FORMULA()')
            self.assertEqual(formula.data_type, 's')
        finally:
            book.close()

    def test_state_direction_setting_enforces_roles_and_preserves_saved_value(self):
        _, viewer_cookie, _ = self.user('viewer')
        _, editor_cookie, _ = self.user('editor')
        route = '/api/settings/state-direction'
        status, _, _ = self.request(route, 'POST', {'shift_direction': '-1'}, editor_cookie)
        self.assertEqual(status, 200)
        status, _, _ = self.request(route, 'POST', {'shift_direction': '1'}, viewer_cookie)
        self.assertEqual(status, 403)
        status, data, _ = self.request(route, cookie=viewer_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(data['shift_direction'], '-1')
        self.assertFalse(data['writable'])

    def test_all_six_roles_are_enforced_for_every_denied_route(self):
        for role in ('viewer','reporter','reviewer','editor','importer'):
            user,cookie,_=self.user(role)
            self.assertEqual(self.request('/api/overview',cookie=cookie)[0],200)
            for method,paths in (('GET',local_security.GET_PERMISSIONS),('POST',local_security.POST_PERMISSIONS)):
                for path,permission in paths.items():
                    if permission in (None,'authenticated') or permission in user['permissions']:continue
                    with self.subTest(role=role,path=path):
                        self.assertEqual(self.request(path,method,{} if method=='POST' else None,cookie)[0],403)

    def test_cookie_security_csrf_and_setup_cannot_be_repeated(self):
        code,_,headers=self.request('/api/auth/login','POST',{'username':'admin','password':self.password})
        self.assertEqual(code,200)
        self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('SameSite=Strict',headers['Set-Cookie'])
        self.assertNotIn(self.token,headers['Set-Cookie'])
        self.assertEqual(self.request('/api/auth/logout','POST',{},self.cookie,header=False)[0],403)
        self.assertEqual(self.request('/api/auth/setup','POST',{'username':'rogue','display_name':'Rogue','password':secrets.token_urlsafe(24)})[0],403)

    def test_password_hashes_salts_lockout_and_last_admin(self):
        first=local_security.hash_password(self.password);second=local_security.hash_password(self.password)
        self.assertNotEqual(first,second);self.assertTrue(local_security.verify_password(self.password,first))
        self.assertFalse(local_security.verify_password('wrong',first))
        self.assertNotIn(self.password,first)
        self.assertEqual(self.request('/api/auth/users/update','POST',{'id':self.admin['id'],'roles':['viewer']},self.cookie)[0],400)
        for _ in range(5):self.assertEqual(self.request('/api/auth/login','POST',{'username':'admin','password':'incorrect'})[0],401)
        self.assertEqual(self.request('/api/auth/login','POST',{'username':'admin','password':self.password})[0],401)

    def test_six_digit_numeric_password_and_initials_account(self):
        for password in ('123456','000000','12345678'):
            with self.subTest(password=password):
                encoded=local_security.hash_password(password)
                self.assertTrue(local_security.verify_password(password,encoded))
        with self.assertRaisesRegex(ValueError,'6 位'):
            local_security.hash_password('12345')
        local_security.create_user(server,{'username':'ZS','display_name':'张三','password':'123456','roles':['viewer']})
        user,_=local_security.login(server,{'username':'zs','password':'123456'})
        self.assertEqual(user['username'],'zs')
        with self.assertRaisesRegex(ValueError,'用户名已存在'):
            local_security.create_user(server,{'username':'zs','display_name':'另一个人','password':'654321','roles':['viewer']})

    def test_logout_idle_expiry_and_restart_invalidate_sessions(self):
        with server.connect() as db:db.execute('UPDATE login_sessions SET last_seen=?',(int(time.time())-1900,))
        self.assertEqual(self.request('/api/auth/me',cookie=self.cookie)[0],401)
        _,token=local_security.login(server,{'username':'admin','password':self.password});cookie=local_security.cookie_header(token).split(';')[0]
        with patch.object(local_security,'INSTANCE','different-service'):
            self.assertEqual(self.request('/api/auth/me',cookie=cookie)[0],401)
        self.assertEqual(self.request('/api/auth/logout','POST',{},cookie)[0],200)
        self.assertEqual(self.request('/api/auth/me',cookie=cookie)[0],401)

    def test_role_changes_and_disable_revoke_existing_sessions(self):
        user,cookie,ident=self.user('editor')
        self.assertEqual(self.request('/api/auth/users/update','POST',{'id':ident,'active':False},self.cookie)[0],200)
        self.assertEqual(self.request('/api/auth/me',cookie=cookie)[0],401)

    def test_forged_operator_never_controls_state_or_export_audit(self):
        user,cookie,_=self.user('editor')
        row={'outage':'H209','unit_id':2,'thimble_id':1,'state':'plugged','operator':'forged-admin'}
        self.assertEqual(self.request('/api/state','POST',row,cookie)[0],200)
        with server.connect() as db:self.assertEqual(db.execute('SELECT operator FROM tube_state_history').fetchone()[0],user['username'])
        payload=b'export evidence'
        code,_,_=self.request('/api/security/image-export','POST',{'name':'sample.png','sha256':hashlib.sha256(payload).hexdigest(),'size_bytes':len(payload),'operator':'forged-admin'},self.cookie)
        self.assertEqual(code,200)
        with server.connect() as db:self.assertEqual(db.execute('SELECT operator FROM export_audits').fetchone()[0],'admin')

    def test_export_download_records_server_operator_and_hash(self):
        status,payload,_=self.request('/api/export',cookie=self.cookie)
        self.assertEqual(status,200)
        with server.connect() as db:
            record=db.execute('SELECT * FROM export_audits ORDER BY id DESC').fetchone()
            self.assertEqual(record['operator'],'admin');self.assertEqual(record['sha256'],hashlib.sha256(payload).hexdigest())

    def test_office_export_author_uses_current_session(self):
        for username in ('admin', 'zs'):
            with self.subTest(username=username), local_security.identity({'username':username, 'id':username}):
                result=server.workbook_result(username+'.xlsx',Workbook())
                book=load_workbook(result['file_path'],read_only=True)
                try:
                    self.assertEqual(book.properties.creator,username)
                    self.assertEqual(book.properties.lastModifiedBy,username)
                finally:
                    book.close()
                document=server._write_docx(username+'.docx',[])
                with ZipFile(document['file_path']) as archive:
                    core=ElementTree.fromstring(archive.read('docProps/core.xml'))
                    self.assertEqual(core.find('{http://purl.org/dc/elements/1.1/}creator').text,username)

    def test_migrations_are_idempotent_reject_future_and_detect_tampering(self):
        with server.connect() as db:before=db.execute('SELECT * FROM schema_migrations').fetchall()
        server.init_db()
        with server.connect() as db:self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM schema_migrations')],[tuple(r) for r in before])
        with server.connect() as db:db.execute("UPDATE schema_migrations SET checksum='tampered' WHERE version=2")
        with self.assertRaisesRegex(ValueError,'迁移'):server.init_db()

    def test_failed_staged_upgrade_preserves_original_database(self):
        mark_legacy(server);before=backup_service.digest(server.DB_PATH)
        def failing(path):
            server._legacy_init_db(path)
            raise ValueError('simulated migration interruption')
        with self.assertRaises(ValueError):schema_migrations.upgrade(server.DB_PATH,failing)
        self.assertEqual(backup_service.digest(server.DB_PATH),before)
        server.init_db();self.assertEqual(schema_migrations.validate(server.DB_PATH,True),schema_migrations.VERSION)

    def test_backup_hash_corruption_and_unknown_trigger_are_rejected(self):
        info=server.create_database_backup()
        with sqlite3.connect(info['path'],factory=schema_migrations.ClosingConnection) as db:db.execute('CREATE TABLE unexpected(value TEXT)')
        with self.assertRaisesRegex(ValueError,'SHA-256'):server.restore_database(info['path'])
        untrusted=self.root/'trigger.db';backup_service.snapshot(server.DB_PATH,untrusted)
        with sqlite3.connect(untrusted,factory=schema_migrations.ClosingConnection) as db:db.execute('CREATE TRIGGER malicious AFTER INSERT ON findings BEGIN DELETE FROM users; END')
        with self.assertRaisesRegex(ValueError,'触发器'):server.validate_backup_file(str(untrusted))

    def test_restore_preserves_current_accounts_audits_and_revokes_sessions(self):
        backup=server.create_database_backup()
        user,_,ident=self.user('viewer')
        with local_security.identity(self.admin),server.connect() as db:local_security.event(db,'after_backup_marker')
        status,result,_=self.request('/api/restore','POST',{'path':backup['path'],'operator':'forged'},self.cookie)
        self.assertEqual(status,200);self.assertTrue(result['login_required'])
        with server.connect() as db:
            self.assertIsNotNone(db.execute('SELECT id FROM users WHERE id=?',(ident,)).fetchone())
            self.assertIsNotNone(db.execute("SELECT 1 FROM security_events WHERE event_type='after_backup_marker'").fetchone())
            self.assertEqual(db.execute('SELECT COUNT(*) FROM login_sessions').fetchone()[0],0)
            self.assertEqual(db.execute("SELECT operator FROM security_events WHERE event_type='database_restore'").fetchone()[0],'admin')
        self.assertTrue(Path(result['safety_backup']).is_file())

    def test_restore_upgrade_failure_does_not_replace_live_database(self):
        info=server.create_database_backup();before=backup_service.digest(server.DB_PATH)
        with patch.object(server,'init_db',side_effect=ValueError('simulated staging failure')):
            with self.assertRaises(ValueError):server.restore_database(info['path'])
        self.assertEqual(backup_service.digest(server.DB_PATH),before)
        self.assertIsNotNone(local_security.session(server,self.cookie))

    def test_wal_snapshot_includes_committed_rows_and_retention_keeps_manual(self):
        with server.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute("INSERT INTO findings(outage,unit_id,thimble_id,imported_at) VALUES('H209',2,1,'now')")
        manual=server.create_database_backup()
        backup_service.policy(server,{'automatic_keep':5})
        automatic=[server._auto_backup('test') for _ in range(7)]
        self.assertTrue(Path(manual['path']).exists());self.assertFalse(Path(automatic[0]).exists())
        self.assertEqual(sum(Path(p).exists() for p in automatic),5)
        self.assertEqual(server.validate_backup_file(automatic[-1])['findings'],1)

    def test_delete_failure_rolls_back_data_and_delete_audit_together(self):
        with server.connect() as db:db.execute("INSERT INTO findings(outage,unit_id,thimble_id,imported_at) VALUES('H209',2,1,'now')")
        original=server._log_operation
        def fail(kind,*args,**kwargs):
            if kind=='soft_delete':raise ValueError('simulated audit failure')
            return original(kind,*args,**kwargs)
        with patch.object(server,'_log_operation',fail),self.assertRaises(ValueError):
            server.api_data_delete({'scope':'finding','data':{'findingId':1},'options':{'backup':False}})
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT is_deleted FROM findings').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM delete_batches').fetchone()[0],0)

    def test_restore_gate_waits_for_existing_readers(self):
        entered=threading.Event();release=threading.Event();finished=threading.Event()
        def reader():
            with GATE.shared():entered.set();release.wait(3)
        def maintenance():
            with GATE.exclusive():finished.set()
        first=threading.Thread(target=reader);first.start();self.assertTrue(entered.wait(2))
        second=threading.Thread(target=maintenance);second.start()
        try:self.assertFalse(finished.wait(.1))
        finally:release.set();first.join(3);second.join(3)
        self.assertTrue(finished.is_set())

    def test_local_storage_paths_are_outside_installation_directory(self):
        with patch.dict('os.environ',{'APPDATA':str(self.root)},clear=True):
            self.assertEqual(local_storage.user_root(),self.root/'ThimbleInspection')


if __name__=='__main__':unittest.main()
