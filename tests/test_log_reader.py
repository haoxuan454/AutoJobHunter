import tempfile
import unittest
from pathlib import Path

from bosshunter.web.log_reader import MAX_PAGE_SIZE, read_logs


class LogReaderTests(unittest.TestCase):
    def test_reads_utf8_bom_and_redacts_credentials_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "web.out.log").write_bytes(
                "old line\nnew line cookie=secret Bearer abc.def\n".encode("utf-8-sig")
            )
            result = read_logs(runtime, page_size=10)
            self.assertEqual(result["items"][0]["line"], "new line cookie=[REDACTED] Bearer [REDACTED]")
            self.assertEqual(result["items"][0]["source"], "web.out")

    def test_reads_gb18030_and_filters_with_pagination(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "web.err.log").write_bytes("错误一\nBOSS 投递失败\n错误三\n".encode("gb18030"))
            result = read_logs(runtime, source="web.err", query="boss", page_size=1)
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["items"][0]["line"], "BOSS 投递失败")
            self.assertFalse(result["has_more"])

    def test_bounds_page_size_and_rejects_unknown_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "web.out.log").write_text("x\n", encoding="utf-8")
            self.assertEqual(read_logs(runtime, page_size=9999)["page_size"], MAX_PAGE_SIZE)
            with self.assertRaises(ValueError):
                read_logs(runtime, source="../../secret")

    def test_task_lines_are_supported_and_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = read_logs(Path(tmp), source="task", task_lines=["task failed api_key=my-secret"])
            self.assertEqual(result["items"][0]["source"], "task")
            self.assertNotIn("my-secret", result["items"][0]["line"])


if __name__ == "__main__":
    unittest.main()
