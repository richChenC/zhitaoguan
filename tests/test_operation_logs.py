import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.backend import server


class OperationLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_patch = patch.object(server, 'DB_PATH', Path(self.temp.name) / 'audit.db')
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        server.init_db()

    def test_logs_survive_removed_recycle_batches_and_paginate_stably(self):
        with server.connect() as db:
            db.executemany(
                "INSERT INTO operation_logs(operation_type,scope,scope_detail,record_count,created_at) VALUES(?,?,?,?,?)",
                [(kind, 'selected', '<original scope>', index, '2026-10-19 12:00:00')
                 for index, kind in enumerate(['soft_delete', 'restore', 'purge'], 1)])
        first = server.api_operation_logs(1, 2)
        second = server.api_operation_logs(2, 2)
        self.assertEqual(first['total'], 3)
        self.assertEqual([row['operation_type'] for row in first['items']], ['purge', 'restore'])
        self.assertEqual([row['operation_type'] for row in second['items']], ['soft_delete'])
        self.assertEqual(first['items'][0]['scope_detail'], '<original scope>')
        self.assertEqual(server.api_recycle_list(1, 20)['items'], [])

    def test_pagination_is_bounded_for_both_endpoints(self):
        for endpoint in [server.api_operation_logs, server.api_recycle_list]:
            result = endpoint(-20, 100000)
            self.assertEqual(result['page'], 1)
            self.assertEqual(result['size'], 200)
            self.assertEqual(endpoint(1, 0)['size'], 1)
            with self.assertRaises(ValueError):
                endpoint('invalid', 10)


if __name__ == '__main__':
    unittest.main()
