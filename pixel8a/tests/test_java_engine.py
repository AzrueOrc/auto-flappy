import os
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from flappy.capture import FramePacket
from flappy.java_engine import parse_frame
from flappy.settings import load_settings
from flappy.vision import Observation
from flappy.window import MainWindow


class JavaIntegrationTests(unittest.TestCase):
    def test_java_frame_becomes_overlay_observation(self):
        frame = parse_frame("EVT\tFRAME\t1\t80,400,140,470\t180,240,300,550;300,360,270,520\t180,240,300,550\n")
        self.assertEqual(frame.scene, "GAMEPLAY_CANDIDATE")
        self.assertEqual(frame.scooter.center_y, 435)
        self.assertEqual(len(frame.gaps), 2)
        self.assertEqual(frame.active_gap.left, 180)
        with self.assertRaises(ValueError):
            parse_frame("EVT\tFRAME\t1\tbroken\t-\t-")

    def test_gui_uses_java_engine_without_python_taps(self):
        app = QApplication.instance() or QApplication([])
        settings = load_settings(Path(__file__).resolve().parents[1] / "config" / "settings.example.json")
        window = MainWindow(settings)
        window.controller.serial = "test-device"
        window.controller._enabled = True
        window.capture_thread = object()
        window._update_controls()
        self.assertEqual(window.engine_choice.currentIndex(), 0)
        self.assertFalse(window.mark_gap.isEnabled())
        launched = threading.Event()
        with patch.object(window.java_engine, "launch", side_effect=launched.set), patch.object(
                window.java_engine, "send") as send:
            window.autopilot.setChecked(True)
            self.assertTrue(launched.wait(2))
            window._java_ready()
            self.assertFalse(window._auto_enabled.is_set())
            self.assertTrue(window.autopilot.isChecked())
            send.assert_called_with("start")
            window._java_frame(parse_frame(
                "EVT\tFRAME\t1\t80,400,140,470\t180,240,300,550\t180,240,300,550"))
            packet = FramePacket(bytes(4 * 4 * 4), 4, 4, time.monotonic(), 1)
            window._show_frame(packet, Observation("MENU_OR_UNKNOWN", None, (), None), 0.0)
            self.assertIn("Java scan", window.metrics.text())
            self.assertIn("gaps 1", window.metrics.text())
            window.autopilot.setChecked(False)
            send.assert_called_with("stop")
        window.capture_thread = None
        window.close()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
