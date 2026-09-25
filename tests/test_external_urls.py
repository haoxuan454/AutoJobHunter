import sqlite3
import unittest

from bosshunter.conversations import ConversationRepository, normalize_platform_external_url


class ExternalUrlTests(unittest.TestCase):

    def test_list_conversations_exposes_link_availability_metadata(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, title TEXT, company TEXT, hr_title TEXT, url TEXT, source_platform TEXT, score INTEGER, score_reason TEXT, status TEXT)")
        repo = ConversationRepository(conn)
        conn.execute("INSERT INTO jobs (id, title, company, hr_title, url, source_platform, score, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (
            "job-1", "Python backend", "Example Co", "HR", "https://www.zhaopin.com/jobdetail/1.htm", "zhilian", 88, "sent"
        ))
        repo.upsert_conversation({
            "id": "zhilian:delivery:job-1", "platform": "zhilian", "job_id": "job-1",
            "hr_name": "HR", "company_id": "Example Co",
        })
        item = repo.list_conversations()[0]
        self.assertTrue(item["job_url_available"])
        self.assertFalse(item["conversation_url_available"])
        self.assertTrue(item["job_url_reason"])
        self.assertTrue(item["conversation_url_reason"])
    def test_zhilian_generic_im_entry_is_not_a_specific_hr_link(self):
        self.assertIsNone(
            normalize_platform_external_url(
                "zhilian", "https://i.zhaopin.com/im?refcode=4019", kind="conversation"
            )
        )

    def test_zhilian_session_url_is_accepted(self):
        url = "https://i.zhaopin.com/im?sessionId=session-123&refcode=4019"
        self.assertEqual(normalize_platform_external_url("zhilian", url, kind="conversation"), url)

    def test_local_dashboard_url_is_never_external(self):
        self.assertIsNone(
            normalize_platform_external_url(
                "zhilian", "http://127.0.0.1:8686/jobs?job_id=1", kind="conversation"
            )
        )

    def test_job_url_cannot_be_used_as_conversation_url(self):
        self.assertIsNone(
            normalize_platform_external_url(
                "liepin", "https://www.liepin.com/job/1985759577.shtml", kind="conversation"
            )
        )

    def test_platform_job_url_is_separate_from_chat_url(self):
        job_url = "https://www.liepin.com/job/1985759577.shtml"
        self.assertEqual(normalize_platform_external_url("liepin", job_url, kind="job"), job_url)


if __name__ == "__main__":
    unittest.main()
