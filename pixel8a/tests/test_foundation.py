import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from flappy.adb import ADBController, DeviceError, parse_devices
from flappy.settings import load_settings


class FoundationTests(unittest.TestCase):
    def test_device_parser_and_explicit_target(self):
        output = "List of devices attached\nA1\tdevice\nB2\tunauthorized\n"
        self.assertEqual(parse_devices(output), {"A1": "device", "B2": "unauthorized"})
        calls = []

        def runner(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, output if argv[-1] == "devices" else "", "")

        controller = ADBController("A1", "adb", runner, persistent=False)
        self.assertEqual(controller.connect(), "A1")
        controller.tap(12, 34)
        self.assertEqual(calls[-1], ["adb", "-s", "A1", "shell", "input", "tap", "12", "34"])
        controller.disable_output()
        self.assertFalse(controller.input_enabled)
        with self.assertRaises(DeviceError):
            controller.tap(12, 34)

    def test_multiple_devices_require_serial(self):
        def runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0,
                                               "List of devices attached\nA1\tdevice\nB2\tdevice\n", "")
        with self.assertRaisesRegex(DeviceError, "exactly one"):
            ADBController("", "adb", runner, persistent=False).connect()

    def test_uncertain_tap_repairs_channel_without_repeating_touch(self):
        controller = ADBController("A1", "adb", persistent=True)
        controller.serial = "A1"
        controller._enabled = True
        commands = []
        controller._send_shell_locked = lambda command: (commands.append(command),
                                                           (_ for _ in ()).throw(DeviceError("timeout")))
        repairs = []
        controller._close_shell_locked = lambda: repairs.append("close")
        controller._start_shell_locked = lambda: repairs.append("start")
        with self.assertRaisesRegex(DeviceError, "completion unknown.*recovered"):
            controller.tap(12, 34)
        self.assertEqual(commands, ["input tap 12 34"])
        self.assertEqual(repairs, ["close", "start"])
        self.assertTrue(controller.input_enabled)

    def test_failed_channel_repair_disables_input(self):
        controller = ADBController("A1", "adb", persistent=True)
        controller.serial = "A1"
        controller._enabled = True
        controller._send_shell_locked = lambda command: (_ for _ in ()).throw(DeviceError("timeout"))
        controller._close_shell_locked = lambda: None
        controller._start_shell_locked = lambda: (_ for _ in ()).throw(DeviceError("offline"))
        with self.assertRaisesRegex(DeviceError, "input disabled"):
            controller.tap(12, 34)
        self.assertFalse(controller.input_enabled)

    def test_unauthorized_target_is_rejected(self):
        def runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0,
                                               "List of devices attached\nA1\tunauthorized\n", "")
        with self.assertRaisesRegex(DeviceError, "unauthorized"):
            ADBController("A1", "adb", runner, persistent=False).connect()

    def test_settings_validation(self):
        source = Path(__file__).resolve().parents[1] / "config" / "settings.example.json"
        settings = load_settings(source)
        self.assertEqual(settings.target_fps, 60)
        self.assertEqual(settings.video_codec, "h264")
        self.assertEqual(settings.video_encoder, "")
        self.assertEqual(settings.scrcpy_max_size, 1024)
        with tempfile.TemporaryDirectory(dir=source.parents[1]) as folder:
            path = Path(folder) / "settings.json"
            raw = json.loads(source.read_text(encoding="utf-8"))
            raw["capture"]["crop"]["width"] = 0
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_settings(path)


if __name__ == "__main__":
    unittest.main()
