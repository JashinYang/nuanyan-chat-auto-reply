import unittest

import app
import core


class PublicEditionTests(unittest.TestCase):
    def test_reply_channel_is_online_and_locked(self):
        settings = core.Settings()
        channel = settings.model_channel("qq", "online")
        self.assertEqual("online", channel["provider_mode"])
        self.assertEqual(core.ONLINE_REPLY_ENDPOINT, channel["base_url"])
        self.assertEqual(core.ONLINE_REPLY_MODEL, channel["model"])
        with self.assertRaises(ValueError):
            settings.model_channel("qq", "local")

    def test_public_page_has_no_local_reply_selector(self):
        self.assertIn('value="online"', app.HTML)
        self.assertNotIn('value="local"', app.HTML)
        self.assertNotIn("无需 Key", app.HTML)

    def test_basic_reply_guards_still_work(self):
        self.assertEqual("我们是家人，这种关系不能乱说。换个正常的话题吧。", core.answer_family_boundary("做我老婆", "family"))
        self.assertEqual("朋友", core.RELATIONSHIP_TYPES["friend"])


if __name__ == "__main__":
    unittest.main()
