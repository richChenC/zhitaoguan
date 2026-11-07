from enterprise_fixtures import admin_cookie
import json
import tempfile
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from src.backend import server, task_progress


class TaskProgressTests(unittest.TestCase):
    def test_counts_are_real_and_unknown_total_has_no_percentage(self):
        token = str(uuid.uuid4())
        with task_progress.task(token):
            task_progress.step("等待总量", 0)
            self.assertIsNone(task_progress.snapshot(token)["percent"])
            values = task_progress.iterate([10, 20, 30], "读取")
            self.assertEqual(next(values), 10)
            self.assertEqual(task_progress.snapshot(token)["completed"], 0)
            self.assertEqual(next(values), 20)
            self.assertAlmostEqual(task_progress.snapshot(token)["percent"], 100 / 3)
            self.assertEqual(list(values), [30])
            self.assertEqual(task_progress.snapshot(token)["completed"], 3)
            task_progress.step("等待总量", 2)
            self.assertEqual(task_progress.snapshot(token)["percent"], 99)
        self.assertEqual(task_progress.snapshot(token)["status"], "succeeded")
        with self.assertRaises(ValueError):
            with task_progress.task(token):
                pass

    def test_failure_cannot_be_reported_as_success(self):
        token = str(uuid.uuid4())
        with self.assertRaises(ValueError):
            with task_progress.task(token):
                task_progress.step("写入", 2, 10)
                raise ValueError("failure")
        value = task_progress.snapshot(token)
        self.assertEqual(value["status"], "failed")
        self.assertEqual(value["percent"], 20)
        self.assertIsNone(value["remaining_seconds"])

    def test_parallel_threads_keep_their_own_counts(self):
        tokens = [str(uuid.uuid4()), str(uuid.uuid4())]
        barrier = threading.Barrier(2)
        def run(index):
            with task_progress.task(tokens[index]):
                task_progress.step(f"task-{index}", index + 1, 10)
                barrier.wait(timeout=5)
                return task_progress.snapshot(tokens[index])
        with ThreadPoolExecutor(2) as executor:
            values = list(executor.map(run, [0, 1]))
        self.assertEqual([value["completed"] for value in values], [1, 2])
        self.assertEqual([value["stage"] for value in values], ["task-0", "task-1"])

    def test_nested_phases_and_sheets_share_one_monotonic_percentage(self):
        token = str(uuid.uuid4())
        seen = []
        with task_progress.task(token):
            with task_progress.phase(0, 30):
                for sheet in task_progress.iterate([[1, 2], [3, 4, 5]], "识别工作表", partitions=True):
                    for _ in task_progress.iterate(sheet, "读取行"):
                        seen.append(task_progress.snapshot(token)["percent"])
            self.assertEqual(task_progress.snapshot(token)["percent"], 30)
            with task_progress.phase(30, 95):
                for _ in task_progress.iterate(range(5), "写入行", total=5):
                    seen.append(task_progress.snapshot(token)["percent"])
            task_progress.step("提交事务")
            self.assertEqual(task_progress.snapshot(token)["percent"], 95)
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(task_progress.snapshot(token)["percent"], 100)

    def test_confirmation_pause_is_not_a_success_or_one_hundred_percent(self):
        token = str(uuid.uuid4())
        with task_progress.task(token):
            with task_progress.phase(0, 35):
                list(task_progress.iterate([1, 2], "校验行"))
            task_progress.wait_for_confirmation()
        self.assertEqual(task_progress.snapshot(token)["status"], "awaiting_confirmation")
        self.assertEqual(task_progress.snapshot(token)["percent"], 35)

    def test_corrupt_excel_returns_an_actionable_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "broken.xlsx"
            source.write_bytes(b"not an Excel workbook")
            token = str(uuid.uuid4())
            with self.assertRaisesRegex(ValueError, "文件损坏"):
                with task_progress.task(token):
                    server.inspect_excel_file(str(source))
            self.assertEqual(task_progress.snapshot(token)["status"], "failed")

    def test_rpt_groups_share_one_progress_through_database_commit(self):
        from tests.test_server import write_sum, write_ect, write_report, report_entry
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reports = []
            for index, count in enumerate([2, 3], 1):
                group = root / f"TH2I09CAL{index:05d}"
                group.mkdir()
                write_sum(group)
                entries = []
                for tube in range(1, count + 1):
                    filename = f"DIR{tube:03d}C{tube:03d}I{index:03d}.ECT"
                    write_ect(group, filename, tube, tube, index)
                    entries.append(report_entry(filename, tube, tube, index,
                                                f"{index}-{tube}", calgroup=group.name))
                write_report(group, entries)
                reports.append(str(group / "Report-final.rpt"))
            seen = []
            token = str(uuid.uuid4())
            original = task_progress.step
            def capture(*args, **kwargs):
                original(*args, **kwargs)
                value = task_progress.snapshot(token)
                if value["percent"] is not None:
                    seen.append(value)
            with patch.object(server, "DB_PATH", root / "test.db"):
                server.init_db()
                with task_progress.task(token), patch.object(task_progress, "step", capture):
                    result = server.import_directory(str(root), reports)
                self.assertEqual(result["inserted"], 5)
            percents = [value["percent"] for value in seen]
            self.assertEqual(percents, sorted(percents))
            self.assertTrue(any(value["stage"].startswith("读取 ECT") and value["total"] == 2 for value in seen))
            self.assertTrue(any(value["stage"].startswith("读取 ECT") and value["total"] == 3 for value in seen))
            self.assertTrue(any(value["stage"] == "写入检测记录" and 70 <= value["percent"] <= 94 for value in seen))
            self.assertLess(percents[-1], 100)
            self.assertEqual(task_progress.snapshot(token)["percent"], 100)

    def test_invalid_tokens_and_active_capacity_are_rejected(self):
        for token in ["", "x", "../test", "x" * 65]:
            with self.assertRaises(ValueError):
                task_progress.snapshot(token)
        active = {str(index): {"status": "running", "updated": time.monotonic()}
                  for index in range(task_progress.MAX_TASKS)}
        with patch.object(task_progress, "_tasks", active):
            with self.assertRaises(ValueError):
                with task_progress.task(str(uuid.uuid4())):
                    pass


class HttpTaskProgressTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        changes = [patch.object(server, "DB_PATH", Path(folder.name) / "test.db"),
                   patch.object(server, "EXCEL_DIR", Path(folder.name) / "exports"),
                   patch.object(server, "REPORT_DIR", Path(folder.name) / "reports")]
        for change in changes:
            change.start()
            self.addCleanup(change.stop)
        server.init_db()
        self.auth_cookie = admin_cookie(server)
        class QuietHandler(server.Handler):
            def log_message(self, *_):
                pass
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.base = f"http://127.0.0.1:{self.http.server_port}"

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=5)

    def post(self, token, rows):
        request = Request(self.base + "/api/states/batch",
                          data=json.dumps({"confirmed": True, "rows": rows}).encode(),
                          headers={"Content-Type": "application/json", "X-Thimble-Task": token,"X-Thimble-Request":"1","Cookie":self.auth_cookie})
        with urlopen(request, timeout=20) as response:
            return json.load(response)

    def test_http_progress_changes_during_a_real_atomic_batch(self):
        token = str(uuid.uuid4())
        rows = [dict(outage="H209", unit_id=2, thimble_id=index, state="normal",
                     offset_mm=0, note="原文") for index in range(1, 31)]
        original = server.save_tube_state
        def slowed(*args, **kwargs):
            result = original(*args, **kwargs)
            time.sleep(.02)
            return result
        seen = []
        with patch.object(server, "save_tube_state", slowed), ThreadPoolExecutor(1) as executor:
            future = executor.submit(self.post, token, rows)
            while not future.done():
                with urlopen(Request(self.base + "/api/import-progress?id=" + token,headers={"Cookie":self.auth_cookie}), timeout=5) as response:
                    value = json.load(response)
                if value.get("stage") == "保存维护记录":
                    seen.append(value["completed"])
                time.sleep(.025)
            self.assertEqual(future.result()["changed"], 30)
        self.assertGreater(len(set(seen)), 3)
        self.assertEqual(task_progress.snapshot(token)["status"], "succeeded")
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tube_states").fetchone()[0], 30)

    def test_http_failure_rolls_back_and_marks_progress_failed(self):
        token = str(uuid.uuid4())
        rows = [dict(outage="H209", unit_id=2, thimble_id=index, state="normal",
                     offset_mm=0, note="原文") for index in range(1, 4)]
        original = server.save_tube_state
        def fail(row, **kwargs):
            if row["thimble_id"] == 3:
                raise ValueError("测试失败")
            return original(row, **kwargs)
        with patch.object(server, "save_tube_state", fail):
            try:
                self.post(token, rows)
            except HTTPError as error:
                self.assertEqual(error.code, 400)
                error.close()
            else:
                self.fail("The simulated failure should be returned to the caller")
        self.assertEqual(task_progress.snapshot(token)["status"], "failed")
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tube_states").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
