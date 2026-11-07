"""Export real-data snapshots using an isolated DB and keep reference evidence."""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.backend import server, analysis_reporting, report_forms

output = ROOT / 'tmp/source-form-qa-20261020'
output.mkdir(parents=True, exist_ok=True)
source = ROOT / 'data/thimble.db'
digest = hashlib.sha256(source.read_bytes()).hexdigest()
with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
    with sqlite3.connect(output / 'test.db') as dst:
        src.backup(dst)
with patch.object(server, 'DB_PATH', output / 'test.db'), patch.object(server, 'REPORT_DIR', output), patch.object(server, 'EXCEL_DIR', output):
    server.init_db()
    with server.connect() as db:
        codes = [r[0] for r in db.execute("SELECT DISTINCT outage FROM findings WHERE is_deleted=0 AND unit_id=1 AND outage LIKE 'N1%' ORDER BY outage")]
    if len(codes) < 2:
        raise RuntimeError('宁德1号机至少需要两次真实大修用于验证')
    evidence = {'database_sha256': digest, 'outages': codes[-2:], 'exports': []}
    for kind in ['inspection', 'comparison']:
        payload = dict(site='N', unit=1, outage=codes[-1], old=codes[-2], kind=kind,
                       metadata={'电厂名称': '宁德核电厂', '机组': '1', '检查类型': codes[-1]})
        snapshot = analysis_reporting.report_snapshot(server, payload, rules=server.active_analysis_rules())
        for fmt in ['docx', 'xlsx']:
            result = analysis_reporting.export(server, {**payload, 'snapshot_id': snapshot['snapshot_id'], 'format': fmt}, rules=server.active_analysis_rules())
            evidence['exports'].append(result)
        (output / (kind + '.html')).write_text(report_forms.preview(server, snapshot), encoding='utf-8')
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    (output / 'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(evidence, ensure_ascii=False, indent=2))
