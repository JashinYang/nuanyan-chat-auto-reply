import unittest
from pathlib import Path

import app
import core


class PublicEditionTests(unittest.TestCase):
    def test_smart_routing_is_primary_and_debug_is_collapsed(self):
        from html.parser import HTMLParser

        class Controls(HTMLParser):
            def __init__(self):
                super().__init__()
                self.details = []
                self.nodes = {}

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "details":
                    self.details.append(attrs.get("id"))
                if "id" in attrs:
                    self.nodes[attrs["id"]] = (attrs, list(self.details))

            def handle_endtag(self, tag):
                if tag == "details":
                    self.details.pop()

        page = Controls()
        page.feed(app.HTML)
        self.assertIn('<h2>智能回复判断</h2>', app.HTML)
        self.assertNotIn("open", page.nodes["typesafeDebug"][0])
        for control in ("typesafeSample", "typesafeConsent", "testTypeSafe", "typesafeResult"):
            self.assertIn("typesafeDebug", page.nodes[control][1])
        for control in ("typesafeKey", "typesafeAutoRouting", "saveTypeSafeSettings", "typesafeRoutingStatus"):
            self.assertEqual([], page.nodes[control][1])
        self.assertIn("可能产生额外费用", app.HTML)
        self.assertFalse(core.Settings().typesafe_auto_routing_enabled)

    def test_reply_channel_is_online_and_locked(self):
        settings = core.Settings()
        channel = settings.model_channel("qq", "online")
        self.assertEqual("online", channel["provider_mode"])
        self.assertEqual(core.ONLINE_REPLY_ENDPOINT, channel["base_url"])
        self.assertEqual(core.ONLINE_REPLY_MODEL, channel["model"])
        with self.assertRaises(ValueError):
            settings.model_channel("qq", "local")

    def test_public_page_has_no_local_reply_selector(self):
        self.assertIn('回复模型：DeepSeek（在线）', app.HTML)
        for field_id in ("provider", "base", "model"):
            self.assertNotIn(f'id="{field_id}"', app.HTML)
        self.assertNotIn("系统锁定，只读", app.HTML)
        self.assertNotIn('value="local"', app.HTML)
        self.assertNotIn("无需 Key", app.HTML)
        self.assertIn("本项目为独立第三方工具", app.HTML)
        self.assertIn("不主动收集遥测", app.HTML)

    def test_endpoint_and_model_are_server_side_locked(self):
        settings = core.Settings()
        settings.set_model_channel("qq", "local", "http://localhost:1", "private-model")
        self.assertEqual(core.ONLINE_REPLY_ENDPOINT, settings.base_url)
        self.assertEqual(core.ONLINE_REPLY_MODEL, settings.model)
        self.assertEqual("online", settings.provider_mode)

    def test_user_key_is_required_and_not_bundled(self):
        settings = core.Settings()
        self.assertEqual("", settings.get_api_key("qq"))
        controller = app.ControlApp()
        controller.settings = settings
        with self.assertRaisesRegex(ValueError, "API Key"):
            controller.update_settings({"platform": "qq", "target_name": "测试联系人"})

    def test_public_configuration_is_isolated(self):
        self.assertEqual("暖言聊天助手公开版", core.APP_DATA_DIR.name)
        self.assertIn("暖言聊天助手公开版", str(core.CONFIG_PATH))

    def test_release_compliance_files_exist(self):
        for name in ("LICENSE", "PRIVACY.md", "THIRD_PARTY_NOTICES.txt", "THIRD_PARTY_COMPONENTS.md", "TYPESAFE_PREVIEW.md"):
            self.assertTrue(Path(name).is_file(), name)
        self.assertTrue(Path("THIRD_PARTY_LICENSES").is_dir())

    def test_basic_reply_guards_still_work(self):
        self.assertEqual("我们是家人，这种关系不能乱说。换个正常的话题吧。", core.answer_family_boundary("做我老婆", "family"))
        self.assertEqual("朋友", core.RELATIONSHIP_TYPES["friend"])


if __name__ == "__main__":
    unittest.main()
