import os
from pathlib import Path
from unittest import TestCase, mock

import docker_entrypoint


class DockerEntrypointTest(TestCase):
    def test_plugin_pip_options_are_added(self):
        environment = {
            "PLUGIN_PIP_INDEX_URL": "https://mirrors.aliyun.com/pypi/simple/",
            "PLUGIN_PIP_TIMEOUT": "120",
            "PLUGIN_PIP_RETRIES": "6",
        }
        with mock.patch.dict(os.environ, environment, clear=False):
            command = docker_entrypoint.pip_install_command(
                Path("/app/plugins/example/requirements.txt")
            )

        self.assertIn("https://mirrors.aliyun.com/pypi/simple/", command)
        self.assertEqual(command[command.index("--timeout") + 1], "120")
        self.assertEqual(command[command.index("--retries") + 1], "6")
        self.assertIn("--prefer-binary", command)
        self.assertNotIn("--no-cache-dir", command)

    def test_invalid_timeout_is_rejected(self):
        with mock.patch.dict(
            os.environ, {"PLUGIN_PIP_TIMEOUT": "invalid"}, clear=False
        ):
            with self.assertRaises(SystemExit):
                docker_entrypoint.pip_install_command(Path("requirements.txt"))
