import tempfile
import unittest
from pathlib import Path
import json
from unittest.mock import patch

from bosshunter.config import load_config
from bosshunter.executor.monitor import _requires_human_confirmation


class HumanDeliveryGuardTests(unittest.TestCase):
    def test_loaded_runtime_config_requires_human_confirmation_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(Path(tmp) / "config.yaml")
        self.assertTrue(config["monitor"]["require_human_confirmation"])
        self.assertTrue(_requires_human_confirmation(config))

    def test_legacy_unit_config_can_explicitly_model_old_opt_out(self):
        self.assertFalse(_requires_human_confirmation({"monitor": {"require_human_confirmation": False}}))

    def test_runtime_gate_converts_auto_reply_to_pending_without_sending(self):
        from bosshunter.executor import monitor
        from bosshunter.db import get_db

        messages = [{"sender": "hr", "text": "请介绍一下你的 Python 项目"}]
        job = {"id": "guard-job", "company": "Example", "title": "Python", "hr_name": "HR", "url": "https://example.test/job"}
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "data" / "bosshunter.db"

            def open_db():
                return get_db(db_path)

            with patch.object(monitor, "get_db", side_effect=open_db), \
                 patch.object(monitor, "_open_conversation", return_value="target"), \
                 patch.object(monitor, "evaluate", return_value=json.dumps(messages, ensure_ascii=False)), \
                 patch.object(monitor, "_wait_or_stop", return_value=False), \
                 patch.object(monitor, "close_tab"), \
                 patch.object(monitor, "_generate_auto_reply", return_value="待确认回复") as generate, \
                 patch.object(monitor, "_send_message_in_chat") as send:
                action = monitor._handle_conversation(
                    job,
                    {"monitor": {"auto_reply_hr_questions": True, "require_human_confirmation": True}},
                )
        self.assertEqual(action, "reply_pending")
        generate.assert_called_once()
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
