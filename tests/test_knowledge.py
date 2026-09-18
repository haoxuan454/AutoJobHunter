import sqlite3
import unittest

from bosshunter.knowledge import (
    ingest_document,
    init_knowledge_tables,
    list_facts,
    parse_document,
    search_confirmed_facts,
    safe_knowledge_filename,
    update_fact_status,
)


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        init_knowledge_tables(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_markdown_is_split_into_unconfirmed_facts(self):
        result = ingest_document(
            self.conn,
            user_id="default",
            filename="experience.md",
            content="# 项目经验\n使用 Python 和 Flask 开发接口\n\n## 数据处理\n使用 SQLite 保存任务状态".encode(),
            storage_path="data/knowledge/experience.md",
        )
        self.assertEqual(result["facts_created"], 2)
        facts = list_facts(self.conn)
        self.assertTrue(all(fact["fact_status"] == "needs_confirmation" for fact in facts))
        self.assertEqual(search_confirmed_facts(self.conn, "Python"), [])

    def test_only_confirmed_public_facts_are_searchable(self):
        result = ingest_document(
            self.conn,
            user_id="default",
            filename="project.md",
            content="# Python项目\n使用 Python 处理岗位数据".encode(),
            storage_path="project.md",
        )
        fact_id = self.conn.execute("SELECT id FROM know_facts WHERE document_id = ?", (result["document"]["id"],)).fetchone()[0]
        update_fact_status(self.conn, fact_id, status="confirmed", public_allowed=True)
        matches = search_confirmed_facts(self.conn, "Python")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["id"], fact_id)

    def test_duplicate_document_is_idempotent(self):
        kwargs = dict(user_id="default", filename="same.md", content=b"# A\nB", storage_path="same.md")
        first = ingest_document(self.conn, **kwargs)
        second = ingest_document(self.conn, **kwargs)
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["facts_created"], 0)

    def test_supported_document_extensions_are_explicit(self):
        self.assertEqual(parse_document("a.txt", "hello".encode()), "hello")
        with self.assertRaises(ValueError):
            parse_document("a.exe", b"x")

    def test_filename_is_basename_only_and_extension_is_allowlisted(self):
        self.assertEqual(safe_knowledge_filename(r"..\outside/经验.md"), "经验.md")
        with self.assertRaises(ValueError):
            safe_knowledge_filename("../../config.yaml")


if __name__ == "__main__":
    unittest.main()
