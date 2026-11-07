import http.client
import csv
import io
import json
import socket
import threading
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote
from enterprise_fixtures import admin_cookie
from src.backend import server


class ReleaseHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.db_patch = patch.object(server, "DB_PATH", Path(cls.temp.name)/"test.db")
        cls.db_patch.start()
        server.init_db()
        cls.http = server.LocalHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.worker = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.worker.join(timeout=5)
        cls.db_patch.stop()
        cls.temp.cleanup()

    def request(self, method='GET', route='/api/health', body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=5)
        self.addCleanup(connection.close)
        connection.request(method, route, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()

    def test_health_headers_and_local_origin(self):
        status, headers, body = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['service'], 'thimble-local')
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(headers['X-Frame-Options'], 'SAMEORIGIN')

    def test_csv_filename_describes_the_actual_filtered_scope_including_ndd(self):
        cookie = admin_cookie(server)
        with server.connect() as db:
            for unit in (1, 2):
                db.execute(
                    "INSERT INTO findings(outage,unit_id,thimble_id,position,indication,site_code,"
                    "source_key,business_key,imported_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (f"D{unit}01", unit, 1, server.position_for(unit, 1), "NDD", "D",
                     f"csv-name-{unit}", f"csv-name-{unit}", "2026-11-04T00:00:00"))
        try:
            status, headers, body = self.request(
                route='/api/export?site=D&unit=2&outage=D201&thimble=1',
                headers={'Cookie': cookie})
            self.assertEqual(status, 200, body)
            name = unquote(headers['Content-Disposition'].split("filename*=UTF-8''")[1])
            self.assertTrue(name.startswith("TH_检测数据_大亚湾_2号机组_D201_1号管_"), name)
            records = list(csv.DictReader(io.StringIO(body.decode('utf-8-sig'))))
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]['unit_id'], '2')
            self.assertEqual(records[0]['indication'], 'NDD')
            status, headers, _ = self.request(route='/api/export', headers={'Cookie': cookie})
            self.assertEqual(status, 200)
            self.assertIn("TH_检测数据_全部记录_", unquote(headers['Content-Disposition']))
        finally:
            with server.connect() as db:
                db.execute("DELETE FROM findings WHERE source_key LIKE 'csv-name-%'")

    def test_startup_connection_burst_fits_before_requests_are_accepted(self):
        with server.LocalHTTPServer(('127.0.0.1', 0), server.Handler) as listener:
            connections = []
            try:
                for _ in range(24):
                    connections.append(socket.create_connection(listener.server_address, timeout=1))
            finally:
                for connection in connections:
                    connection.close()

    def test_foreign_hosts_and_origins_are_rejected(self):
        for headers in ({'Host': 'example.invalid'}, {'Origin': 'https://example.invalid'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request(headers=headers)[0], 403)

    def test_invalid_request_bodies_fail_before_business_dispatch(self):
        for body in ('[]', 'null', '"text"', '{invalid'):
            with self.subTest(body=body):
                status, _, response = self.request('POST', '/api/import', body, {'Content-Type': 'application/json'})
                self.assertEqual(status, 400)
                self.assertIn('error', json.loads(response))

    def test_invalid_and_oversized_lengths_do_not_block_the_service(self):
        for length in ('-1', 'bad', str(server.Handler.MAX_BODY_BYTES + 1)):
            with self.subTest(length=length):
                status, _, _ = self.request('POST', '/api/import', b'', {'Content-Type': 'application/json', 'Content-Length': length})
                self.assertEqual(status, 400)
                self.assertEqual(self.request()[0], 200)

    def test_unsupported_media_and_unknown_endpoint(self):
        self.assertEqual(self.request('POST', '/api/import', '{}', {'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(self.request('POST', '/api/unknown-release-test', '{}', {'Content-Type': 'application/json'})[0], 404)

    def test_static_app_has_fresh_cache_policy_and_no_directory_escape(self):
        status, headers, body = self.request(route='/')
        self.assertEqual(status, 302)
        status,headers,body=self.request(route='/login.html')
        self.assertEqual(status,200)
        self.assertIn('no-store', headers.get('Cache-Control', ''))
        self.assertIn('Content-Security-Policy', headers)
        self.assertNotIn(b'data-view="reports"', body)
        for route in ('/../package.json', '/%2e%2e/package.json'):
            with self.subTest(route=route):
                self.assertIn(self.request(route=route)[0], (403, 404))
