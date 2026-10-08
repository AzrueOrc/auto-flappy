import os
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from flappy.capture import FramePacket
from flappy.settings import load_settings
from flappy.vision import Observation
from flappy.window import ClickableFrame, MainWindow


class WindowTests(unittest.TestCase):
    def test_overlay_click_maps_to_capture_coordinates(self):
        app = QApplication.instance() or QApplication([])
        image = ClickableFrame("")
        image.resize(480, 480)
        image.frame_width = 405
        image.frame_height = 900
        image.setPixmap(QPixmap(216, 480))
        points = []
        image.clicked.connect(lambda x, y: points.append((x, y)))
        QTest.mouseClick(image, Qt.MouseButton.LeftButton, pos=QPoint(240, 240))
        self.assertEqual(points, [(202, 450)])
        app.processEvents()

    def test_autopilot_stays_armed_before_and_after_gameplay(self):
        app = QApplication.instance() or QApplication([])
        settings = load_settings(Path(__file__).resolve().parents[1] / "config" / "settings.example.json")
        window = MainWindow(settings)
        window.engine_choice.setCurrentIndex(1)
        window.controller.serial = "test-device"
        window.controller._enabled = True
        window.capture_thread = object()
        window._update_controls()
        self.assertTrue(window.autopilot.isEnabled())
        window.autopilot.setChecked(True)

        packet = FramePacket(bytes(4 * 4 * 4), 4, 4, time.monotonic(), 1)
        window._show_frame(packet, Observation("MENU_OR_UNKNOWN", None, (), None), 0.0)
        self.assertTrue(window.autopilot.isChecked())
        window._show_frame(packet, Observation("GAMEPLAY_CANDIDATE", None, (), None), 0.0)
        for _ in range(3):
            window._show_frame(packet, Observation("MENU_OR_UNKNOWN", None, (), None), 0.0)
        self.assertTrue(window.autopilot.isChecked())
        self.assertIn("waiting for gameplay", window.status.text())
        window._show_frame(packet, Observation("GAMEPLAY_CANDIDATE", None, (), None), 0.0)
        self.assertTrue(window.autopilot.isChecked())
        self.assertEqual(window.autopilot.text(), "Enable Autopilot")
        window.capture_thread = None
        window.close()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
