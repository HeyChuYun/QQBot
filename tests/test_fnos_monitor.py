import json
import tempfile
from pathlib import Path
from unittest import TestCase

from plugins.fnos_monitor.monitor import (
    FnosSnapshot,
    UpsPowerState,
    UpsStateStore,
    classify_ups_state,
    format_snapshot,
    ups_transition_message,
)
from plugins.fnos_monitor.plugin import FnosPluginSettings, load_administrators


class UpsStateTest(TestCase):
    def test_understands_common_nut_status_values(self):
        self.assertEqual(
            classify_ups_state({"data": {"ups.status": "OL CHRG"}}),
            UpsPowerState.ONLINE,
        )
        self.assertEqual(
            classify_ups_state({"data": {"ups.status": "OB DISCHRG"}}),
            UpsPowerState.ON_BATTERY,
        )

    def test_understands_boolean_power_fields(self):
        self.assertEqual(
            classify_ups_state({"data": {"acPresent": False}}),
            UpsPowerState.ON_BATTERY,
        )
        self.assertEqual(
            classify_ups_state({"data": {"lineOnline": True}}),
            UpsPowerState.ONLINE,
        )

    def test_unknown_response_does_not_create_false_alarm(self):
        self.assertEqual(
            classify_ups_state({"result": "succ", "data": {"enabled": True}}),
            UpsPowerState.UNKNOWN,
        )

    def test_initial_battery_state_alerts_but_online_state_does_not(self):
        self.assertIsNotNone(
            ups_transition_message(None, UpsPowerState.ON_BATTERY, True)
        )
        self.assertIsNone(ups_transition_message(None, UpsPowerState.ONLINE, True))

    def test_repeated_battery_state_is_silent_and_recovery_alerts(self):
        self.assertIsNone(
            ups_transition_message(
                UpsPowerState.ON_BATTERY, UpsPowerState.ON_BATTERY, True
            )
        )
        recovery = ups_transition_message(
            UpsPowerState.ON_BATTERY, UpsPowerState.ONLINE, True
        )
        self.assertIn("恢复", recovery or "")

    def test_state_is_persisted_per_administrator(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            UpsStateStore(path).set("admin-one", UpsPowerState.ON_BATTERY)
            self.assertEqual(
                UpsStateStore(path).get("admin-one"), UpsPowerState.ON_BATTERY
            )
            self.assertIsNone(UpsStateStore(path).get("admin-two"))


class FnosFormattingTest(TestCase):
    def test_formats_system_resources_disks_and_ups(self):
        snapshot = FnosSnapshot(
            system={
                "host": {"data": {"hostName": "HomeNAS"}},
                "version": {"data": {"trimVersion": "1.0.0"}},
                "hardware": {"data": {"cpuModel": "Intel N100", "cores": 4}},
                "uptime": {"data": {"uptime": 90061}},
            },
            cpu={"data": {"cpuBusy": 23, "temperature": 48}},
            memory={"data": {"memPercent": 61, "total": "16 GiB"}},
            disks={
                "data": {
                    "disks": [
                        {
                            "name": "sda",
                            "model": "Disk A",
                            "health": "healthy",
                            "temperature": 36,
                            "size": "4 TB",
                        }
                    ]
                }
            },
            ups={"data": {"status": "OL"}},
        )
        text = format_snapshot(snapshot)
        for expected in (
            "HomeNAS",
            "Intel N100",
            "23%",
            "61%",
            "sda",
            "36°C",
            "市电供电",
        ):
            self.assertIn(expected, text)


class FnosSettingsTest(TestCase):
    def _write_admins(self, directory: Path) -> None:
        (directory / "admins.json").write_text(
            json.dumps(
                {
                    "admins": [
                        {"name": "管理员", "openid": "user-openid-12345"}
                    ]
                }
            ),
            encoding="utf-8",
        )

    def test_settings_are_read_directly_from_plugin_files(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self._write_admins(directory)
            (directory / "config.env").write_text(
                "FNOS_ENDPOINT=192.168.1.10:5666\n"
                "FNOS_USERNAME=admin\n"
                "FNOS_PASSWORD=secret\n"
                "FNOS_POLL_INTERVAL_SECONDS=30\n",
                encoding="utf-8",
            )
            settings = FnosPluginSettings.load(directory)
            self.assertEqual(settings.endpoint, "192.168.1.10:5666")
            self.assertEqual(settings.poll_interval, 30)
            self.assertEqual(settings.administrators[0].openid, "user-openid-12345")

    def test_environment_references_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self._write_admins(directory)
            (directory / "config.env").write_text(
                "FNOS_ENDPOINT=${FNOS_ENDPOINT}\n"
                "FNOS_USERNAME=admin\n"
                "FNOS_PASSWORD=secret\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "不允许引用环境变量"):
                FnosPluginSettings.load(directory)

    def test_invalid_admin_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "admins.json"
            path.write_text(
                '{"admins":[{"name":"管理员","openid":"请填写"}]}',
                encoding="utf-8",
            )
            self.assertEqual(load_administrators(path), ())
