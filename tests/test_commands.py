from unittest import TestCase

from qqbot_app.commands import build_text_reply, is_command, panel_commands


class CommandsTest(TestCase):
    def test_channel_mention_is_removed(self):
        self.assertTrue(is_command("<@!12345> /帮助", "帮助"))

    def test_panel_has_context_specific_ids(self):
        self.assertIn("我的ID", {item["name"] for item in panel_commands("c2c")})
        self.assertIn("本群ID", {item["name"] for item in panel_commands("group")})
        self.assertNotIn("本群ID", {item["name"] for item in panel_commands("channel")})

    def test_removed_example_commands_are_not_registered(self):
        removed = {"状态", "虚拟", "你好", "表情", "图片", "仓库状态"}
        for scope in ("c2c", "group", "channel"):
            registered = {item["name"] for item in panel_commands(scope)}
            self.assertTrue(removed.isdisjoint(registered))

    def test_help_does_not_list_removed_commands(self):
        reply = build_text_reply("/帮助")
        for command in ("状态", "虚拟", "你好", "表情", "图片", "仓库状态"):
            self.assertNotIn(f"/{command}", reply)
