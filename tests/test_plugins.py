import json
import shutil
import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase

from qqbot_app.plugin import MessageContext, PluginManager
from plugins.github_monitor.plugin import GitHubPluginSettings, load_subscriptions


PLUGIN_CODE = """\
from qqbot_app.plugin import BotPlugin, PluginCommand

class ExamplePlugin(BotPlugin):
    commands = (PluginCommand(name="示例", description="示例指令"),)

    async def handle_command(self, context, command):
        return "插件回复"
"""


def create_plugin(root: Path) -> Path:
    directory = root / "example"
    directory.mkdir()
    (directory / "plugin.json").write_text(
        json.dumps(
            {
                "id": "example",
                "name": "示例插件",
                "version": "1.0.0",
                "entrypoint": "plugin.py:ExamplePlugin",
            }
        ),
        encoding="utf-8",
    )
    (directory / "plugin.py").write_text(PLUGIN_CODE, encoding="utf-8")
    return directory


class PluginDiscoveryTest(TestCase):
    def test_directory_with_manifest_is_loaded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            create_plugin(root)
            manager = PluginManager(root)
            manager.load()

            self.assertEqual([plugin.metadata.plugin_id for plugin in manager.plugins], ["example"])
            self.assertEqual(manager.panel_commands("group")[0]["name"], "示例")

    def test_removing_directory_removes_plugin(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = create_plugin(root)
            manager = PluginManager(root)
            manager.load()
            shutil.rmtree(directory)
            manager.load()

            self.assertEqual(manager.plugins, [])

    def test_subscription_lists_are_loaded(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "subscriptions.json"
            path.write_text(
                json.dumps(
                    {
                        "personal": [
                            {
                                "name": "管理员",
                                "openid": "user-openid-12345",
                                "repositories": ["owner/repo"],
                            }
                        ],
                        "groups": [
                            {
                                "name": "开发群",
                                "openid": "group-openid-12345",
                                "repositories": ["owner/another"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            subscriptions = load_subscriptions(path)

            self.assertEqual(len(subscriptions), 2)
            self.assertEqual(subscriptions[0].target_type, "personal")
            self.assertEqual(subscriptions[1].repositories, ("owner/another",))

    def test_placeholder_openid_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "subscriptions.json"
            path.write_text(
                json.dumps(
                    {
                        "personal": [
                            {
                                "name": "管理员",
                                "openid": "通过单聊发送/我的ID后填写",
                                "repositories": ["owner/repo"],
                            }
                        ],
                        "groups": [],
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(load_subscriptions(path), ())

    def test_environment_references_are_rejected_in_subscriptions(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "subscriptions.json"
            path.write_text(
                json.dumps(
                    {
                        "personal": [],
                        "groups": [
                            {
                                "name": "开发群",
                                "openid": "${QQ_BOT_NOTIFY_GROUP_OPENID}",
                                "repositories": ["owner/repo"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "不允许引用环境变量"):
                load_subscriptions(path)

    def test_plugin_settings_are_read_directly_from_files(self):
        with tempfile.TemporaryDirectory() as temp:
            plugin_dir = Path(temp)
            (plugin_dir / "config.env").write_text(
                "GITHUB_TOKEN=file-token\n"
                "GITHUB_POLL_INTERVAL_SECONDS=180\n"
                "BROWSER_EXECUTABLE=/usr/bin/chromium\n",
                encoding="utf-8",
            )
            (plugin_dir / "subscriptions.json").write_text(
                json.dumps(
                    {
                        "personal": [
                            {
                                "name": "管理员",
                                "openid": "user-openid-12345",
                                "repositories": ["owner/repo"],
                            }
                        ],
                        "groups": [],
                    }
                ),
                encoding="utf-8",
            )

            settings = GitHubPluginSettings.load(plugin_dir)
            self.assertEqual(settings.token, "file-token")
            self.assertEqual(settings.interval_seconds, 180)
            self.assertEqual(settings.browser_executable, "/usr/bin/chromium")

    def test_environment_references_are_rejected_in_plugin_config(self):
        with tempfile.TemporaryDirectory() as temp:
            plugin_dir = Path(temp)
            (plugin_dir / "config.env").write_text(
                "GITHUB_TOKEN=${GITHUB_TOKEN}\n", encoding="utf-8"
            )
            (plugin_dir / "subscriptions.json").write_text(
                '{"personal": [], "groups": []}', encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "不允许引用环境变量"):
                GitHubPluginSettings.load(plugin_dir)


class PluginDispatchTest(IsolatedAsyncioTestCase):
    async def test_plugin_command_is_dispatched(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            create_plugin(root)
            manager = PluginManager(root)
            manager.load()

            response = await manager.dispatch(
                MessageContext(
                    client=object(),
                    message=object(),
                    scope="group",
                    content="/示例",
                )
            )
            self.assertEqual(response, "插件回复")
