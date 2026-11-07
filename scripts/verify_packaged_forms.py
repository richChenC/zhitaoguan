"""Smoke-test the bundled backend using only copied database and output paths."""
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / 'data/thimble.db'
output = ROOT / 'tmp/packaged-form-qa-20261020'
output.mkdir(parents=True, exist_ok=True)
before = hashlib.sha256(source.read_bytes()).hexdigest()
with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
    with sqlite3.connect(output / 'test.db') as dst:
        src.backup(dst)
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
env = {**os.environ, 'THIMBLE_PORT': str(port), 'THIMBLE_DB_PATH': str(output / 'test.db'),
       'THIMBLE_OUTPUT_DIR': str(output), 'THIMBLE_REPORT_DIR': str(output),
       'THIMBLE_LOG_PATH': str(output / 'service.log')}


def request(route, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    with urlopen(Request(f'http://127.0.0.1:{port}' + route, data=data,
                         headers={'Content-Type': 'application/json'}), timeout=30) as response:
        return json.load(response)


with (output / 'process.log').open('wb') as log:
    process = subprocess.Popen([str(ROOT / 'build/backend/thimble-backend.exe')], env=env,
                               cwd=output, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        for attempt in range(120):
            try:
                health = request('/api/health')
                break
            except OSError:
                if process.poll() is not None:
                    raise RuntimeError('Bundled backend exited; inspect process.log')
                time.sleep(.5)
        else:
            raise RuntimeError('Bundled backend startup timed out')
        exports = []
        for kind in ['inspection', 'comparison']:
            payload = dict(kind=kind, site='N', unit=1, outage='N109', old='N105', metadata={})
            snapshot = request('/api/reports/preview', payload)
            assert 'source-form' in snapshot['html']
            for fmt in ['docx', 'xlsx']:
                result = request('/api/reports/export', {**payload, 'snapshot_id': snapshot['snapshot_id'], 'format': fmt})
                assert Path(result['file_path']).stat().st_size > 1000
                exports.append(result['filename'])
        document = ROOT.parent / '孔姐发的/指套管数据测试 202007/防城港/防城港指套管割管距离统计.docx'
        imported = request('/api/states/import-preview', dict(filename=document.name, content=base64.b64encode(document.read_bytes()).decode(), outage='F102', unit_id=1))
        assert len(imported['rows']) == 4 and imported['requires_direction']
        assert hashlib.sha256(source.read_bytes()).hexdigest() == before
        evidence = dict(health=health, exports=exports, maintenance_rows=4, source_unchanged=True)
        (output / 'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(evidence, ensure_ascii=False))
    finally:
        # PyInstaller onefile uses a child process; stop the test's entire tree.
        if process.poll() is None:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
