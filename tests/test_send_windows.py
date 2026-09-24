import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import yaml

from bosshunter.config import effective_send_windows, load_config, save_config
from bosshunter.web.tasks import _deadline_from_config


class SendWindowConfigTests(unittest.TestCase):
    def test_legacy_non_empty_windows_enable_the_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(yaml.safe_dump({"throttle": {"send_windows": ["09:00-18:00"]}}), encoding="utf-8")

            loaded = load_config(path)

        self.assertTrue(loaded["throttle"]["send_window_enabled"])
        self.assertEqual(effective_send_windows(loaded), ["09:00-18:00"])

    def test_explicit_false_disables_guard_without_deleting_windows(self):
        config = {"throttle": {"send_window_enabled": False, "send_windows": ["09:00-18:00"]}}

        self.assertEqual(effective_send_windows(config), [])
        self.assertEqual(config["throttle"]["send_windows"], ["09:00-18:00"])

    def test_string_false_is_not_treated_as_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(
                yaml.safe_dump({"throttle": {"send_window_enabled": "false", "send_windows": ["09:00-18:00"]}}),
                encoding="utf-8",
            )

            loaded = load_config(path)

        self.assertFalse(loaded["throttle"]["send_window_enabled"])
        self.assertEqual(effective_send_windows(loaded), [])

    def test_save_and_reload_preserves_disabled_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            save_config(
                {"throttle": {"send_window_enabled": False, "send_windows": ["10:00-12:00"]}},
                path,
            )

            loaded = load_config(path)

        self.assertFalse(loaded["throttle"]["send_window_enabled"])
        self.assertEqual(loaded["throttle"]["send_windows"], ["10:00-12:00"])

    def test_deadline_is_only_added_when_guard_is_enabled(self):
        config = {
            "throttle": {
                "send_window_enabled": True,
                "send_windows": ["09:00-18:00"],
            }
        }

        deadline = _deadline_from_config("deliver", config)

        self.assertIsInstance(deadline, datetime)
        self.assertEqual((deadline.hour, deadline.minute), (18, 0))
        self.assertIsNone(
            _deadline_from_config(
                "deliver",
                {"throttle": {"send_window_enabled": False, "send_windows": ["09:00-18:00"]}},
            )
        )


if __name__ == "__main__":
    unittest.main()
