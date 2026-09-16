from unittest import TestCase

from qqbot_app.commands import build_text_reply, is_command, panel_commands


class CommandsTest(TestCase):
    def test_channel_mention_is_removed(self):
        self.assertTrue(is_command("<@!12345> /仓库状态", "仓库状态"))

    def test_panel_has_context_specific_ids(self):
        self.assertIn("我的ID", {item["name"] for item in panel_commands("c2c")})
        self.assertIn("本群ID", {item["name"] for item in panel_commands("group")})
        self.assertNotIn("本群ID", {item["name"] for item in panel_commands("channel")})

    def test_help_contains_plugin_commands(self):
        reply = build_text_reply("/帮助", ("/仓库状态 - 查看GitHub监听状态",))
        self.assertIn("/仓库状态", reply)
