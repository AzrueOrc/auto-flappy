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
from flappy.settings import Crop, load_settings
from flappy.vision import Observation
from flappy.window import MainWindow


class JavaIntegrationTests(unittest.TestCase):
    def test_java_frame_becomes_overlay_observation(self):
        frame = parse_frame("EVT\tFRAME\t405\t900\t1\t80,400,140,470\t180,240,260,550;300,360,370,520\t180,240,260,550\n")
        self.assertEqual(frame.width, 405)
        self.assertEqual(frame.observation.scene, "GAMEPLAY_CANDIDATE")
        self.assertEqual(frame.observation.scooter.center_y, 435)
        self.assertEqual(len(frame.observation.gaps), 2)
        self.assertEqual(frame.observation.active_gap.left, 180)
        self.assertEqual(frame.observation.active_gap.right, 260)
        self.assertEqual(frame.observation.active_gap.top, 240)
        self.assertEqual(frame.observation.active_gap.bottom, 550)
        with self.assertRaises(ValueError):
            parse_frame("EVT\tFRAME\t1\tbroken\t-\t-")
        with self.assertRaisesRegex(ValueError, "oversized"):
            parse_frame("EVT\tFRAME\t405\t900\t1\t80,400,140,470\t100,240,300,550\t100,240,300,550")

    def test_gui_uses_java_engine_without_python_taps(self):
        app = QApplication.instance() or QApplication([])
        settings = load_settings(Path(__file__).resolve().parents[1] / "config" / "settings.example.json")
        window = MainWindow(settings)
        window.controller.serial = "test-device"
        window.controller._enabled = True
        window.capture_thread = object()
        window._update_controls()
        self.assertEqual(window.engine_choice.currentIndex(), 0)
        self.assertTrue(window.mark_gap.isEnabled())
        launched = threading.Event()
        with patch.object(window.java_engine, "launch", side_effect=launched.set), patch.object(
                window.java_engine, "send") as send, patch(
                "flappy.window.window_client_crop", return_value=Crop(-1800, 50, 405, 900)):
            window.autopilot.setChecked(True)
            self.assertTrue(launched.wait(2))
            window._java_ready()
            self.assertIn("set-crop -1800 50 405 900", [call.args[0] for call in send.call_args_list])
            self.assertFalse(window._auto_enabled.is_set())
            self.assertTrue(window.autopilot.isChecked())
            send.assert_called_with("start")
            window._java_frame(parse_frame(
                "EVT\tFRAME\t405\t900\t1\t80,400,140,470\t180,240,260,550\t180,240,260,550"))
            packet = FramePacket(bytes(405 * 900 * 4), 405, 900, time.monotonic(), 1,
                                 Crop(-1800, 50, 405, 900))
            window._show_frame(packet, Observation("MENU_OR_UNKNOWN", None, (), None), 0.0)
            self.assertIn("Java scan", window.metrics.text())
            self.assertIn("gaps 1", window.metrics.text())
            window._java_frame_skipped("Java pillar box is oversized or outside the frame")
            self.assertTrue(window.autopilot.isChecked())
            self.assertIsNone(window._java_frame_data)
            moved = FramePacket(packet.bgra, 405, 900, time.monotonic(), 2,
                                Crop(-1700, 55, 405, 900))
            window._show_frame(moved, Observation("MENU_OR_UNKNOWN", None, (), None), 0.0)
            self.assertEqual(send.call_args.args[0], "set-crop -1700 55 405 900")
            window._start_marking("scooter")
            window._mark_image_point(110, 435)
            send.assert_called_with("mark-scooter 110")
            window._start_marking("gap")
            window._mark_image_point(210, 425)
            send.assert_called_with("mark-gap 210 425")
            window._java_mark_cleared()
            self.assertIsNone(window.guidance.gap_point)
            window._java_frame(parse_frame(
                "EVT\tFRAME\t500\t900\t1\t80,400,140,470\t180,240,260,550\t180,240,260,550"))
            window._show_frame(packet, Observation("MENU_OR_UNKNOWN", None, (), None), 0.0)
            self.assertFalse(window.autopilot.isChecked())
            self.assertIn("capture sizes differ", window.status.text())
            window._java_state("STOPPED")
            window._java_failed("Java controller exited. Autopilot is off.")
            self.assertIn("capture sizes differ", window.status.text())
            self.assertIn("capture sizes differ", window.last_error.text())
            send.assert_called_with("stop")
        window.capture_thread = None
        window.close()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
