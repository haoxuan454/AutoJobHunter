import unittest

from bosshunter.platform_delivery import DeliveryContext, get_delivery_adapter


class PlatformDeliveryAdapterTests(unittest.TestCase):
    def test_every_supported_platform_has_an_explicit_adapter(self):
        for platform in ("boss", "zhilian", "51job", "liepin"):
            adapter = get_delivery_adapter(platform)
            self.assertEqual(adapter.platform, platform)

    def test_unverified_platforms_fail_closed_without_dom_reuse(self):
        for platform in ("zhilian", "51job", "liepin"):
            result = get_delivery_adapter(platform).send_greeting(
                {"id": "fixture-job", "url": "https://fixture.invalid/job"},
                "本地测试，不发送到外部平台",
                DeliveryContext(dry_run=True),
            )
            self.assertFalse(result.success)
            self.assertFalse(result.verified)
            self.assertEqual(result.error, "platform_delivery_not_verified")
            self.assertIn("不会复用 BOSS", result.history_detail)

    def test_boss_adapter_does_not_bypass_legacy_sender(self):
        result = get_delivery_adapter("boss").send_greeting(
            {"id": "fixture-job"}, "本地测试", DeliveryContext(dry_run=True)
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error, "legacy_sender_required")


if __name__ == "__main__":
    unittest.main()
