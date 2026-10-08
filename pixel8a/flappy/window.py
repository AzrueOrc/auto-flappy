from __future__ import annotations

import threading
import time
import sys

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QHBoxLayout, QLabel,
                               QMainWindow, QPushButton,
                               QVBoxLayout, QWidget)

from .adb import ADBController
from .autopilot import FlapPlanner, aim_height, clearance_bounds, click_zone, scan_lines
from .capture import FramePacket, ScreenFrameSource, window_client_crop
from .guidance import GapContinuity, ManualGuidance
from .java_engine import JavaEngine
from .mirror import Mirror
from .settings import Settings
from .vision import Observation, analyze

import numpy as np


class Events(QObject):
    status = Signal(str)
    connected = Signal(str)
    failed = Signal(str)
    connection_finished = Signal()
    tap_finished = Signal()
    auto_tap_finished = Signal()
    auto_tap_completed = Signal(float)
    auto_failed = Signal(str)


class ClickableFrame(QLabel):
    clicked = Signal(int, int)

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.frame_width = 0
        self.frame_height = 0

    def mousePressEvent(self, event) -> None:
        pixmap = self.pixmap()
        if (pixmap is None or self.frame_width <= 0 or self.frame_height <= 0
                or event.button() != Qt.MouseButton.LeftButton):
            return super().mousePressEvent(event)
        x0 = (self.width() - pixmap.width()) / 2
        y0 = (self.height() - pixmap.height()) / 2
        px = event.position().x() - x0
        py = event.position().y() - y0
        if 0 <= px < pixmap.width() and 0 <= py < pixmap.height():
            self.clicked.emit(min(self.frame_width - 1, round(px * self.frame_width / pixmap.width())),
                              min(self.frame_height - 1, round(py * self.frame_height / pixmap.height())))


class CaptureThread(QThread):
    failed = Signal(str)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._stop = threading.Event()
        self._frame_lock = threading.Lock()
        self._latest: tuple[FramePacket, Observation, float] | None = None
        self._python_vision = threading.Event()
        self._python_vision.set()

    def set_python_vision(self, enabled: bool) -> None:
        if enabled:
            self._python_vision.set()
        else:
            self._python_vision.clear()

    def latest(self) -> tuple[FramePacket, Observation, float] | None:
        with self._frame_lock:
            packet = self._latest
            self._latest = None
            return packet

    def stop(self) -> None:
        self._stop.set()
        self.wait()

    def run(self) -> None:
        interval = 1.0 / self.settings.target_fps
        try:
            title = self.settings.window_title if self.settings.use_scrcpy_window else None
            with ScreenFrameSource(self.settings.crop, self.settings.target_fps, title) as source:
                missing_since: float | None = None
                while not self._stop.is_set():
                    started = time.monotonic()
                    try:
                        packet = source.read()
                        missing_since = None
                    except RuntimeError as exc:
                        if title and "was not found" in str(exc):
                            missing_since = missing_since or time.monotonic()
                            if time.monotonic() - missing_since < 8:
                                self._stop.wait(.1)
                                continue
                        raise
                    if self._python_vision.is_set():
                        bgra = np.frombuffer(packet.bgra, dtype=np.uint8).reshape(
                            packet.height, packet.width, 4)
                        observation = analyze(bgra[:, :, [2, 1, 0]])
                    else:
                        observation = Observation("MENU_OR_UNKNOWN", None, (), None)
                    vision_ms = (time.monotonic() - packet.timestamp) * 1000
                    with self._frame_lock:
                        self._latest = (packet, observation, vision_ms)
                    self._stop.wait(max(0.0, interval - (time.monotonic() - started)))
        except Exception as exc:
            self.failed.emit(f"Capture stopped: {exc}")


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.controller = ADBController(settings.serial, settings.adb_path or None)
        self.planner = FlapPlanner()
        self.guidance = ManualGuidance()
        self.gap_continuity = GapContinuity()
        self.java_engine = JavaEngine(settings)
        self.java_engine.ready.connect(self._java_ready)
        self.java_engine.state.connect(self._java_state)
        self.java_engine.frame.connect(self._java_frame)
        self.java_engine.tap.connect(self._java_tap)
        self.java_engine.failed.connect(self._java_failed)
        self._java_observation: Observation | None = None
        self._java_frame_at = 0.0
        self._mark_mode: str | None = None
        self._auto_enabled = threading.Event()
        self._auto_tap_in_flight = False
        self._auto_seen_gameplay = False
        self._non_gameplay_frames = 0
        self._auto_tap_count = 0
        self._last_auto_tap_ms = 0.0
        self.mirror = Mirror()
        self.capture_thread: CaptureThread | None = None
        self.events = Events()
        self.events.status.connect(self._set_status)
        self.events.connected.connect(self._connected)
        self.events.failed.connect(self._failed)
        self.events.connection_finished.connect(lambda: self.connect_button.setEnabled(True))
        self.events.tap_finished.connect(self._update_controls)
        self.events.auto_tap_finished.connect(self._auto_tap_done)
        self.events.auto_tap_completed.connect(self._auto_tap_completed)
        self.events.auto_failed.connect(self._auto_failed)
        self._last_frame_time: float | None = None
        self._last_sequence = 0
        self.frame_timer = QTimer(self)
        self.frame_timer.timeout.connect(self._poll_frame)
        self.frame_timer.start(16)
        self.setWindowTitle("Flappy Autopilot | Pixel 8a")
        self.resize(900, 780)

        root = QWidget()
        layout = QVBoxLayout(root)
        self.status = QLabel("Disconnected. No input will be sent.")
        layout.addWidget(self.status)
        self.image = ClickableFrame("Connect the Pixel 8a, open the game in scrcpy, then start capture.")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.clicked.connect(self._mark_image_point)
        self.image.setMinimumSize(480, 480)
        self.image.setStyleSheet("background: #171b22; color: white;")
        layout.addWidget(self.image, 1)
        self.metrics = QLabel("Capture: stopped")
        layout.addWidget(self.metrics)

        buttons = QHBoxLayout()
        self.connect_button = QPushButton("Connect ADB")
        self.connect_button.clicked.connect(self.connect_device)
        buttons.addWidget(self.connect_button)
        self.start_button = QPushButton("Start Capture")
        self.start_button.clicked.connect(self.start_capture)
        buttons.addWidget(self.start_button)
        self.stop_capture_button = QPushButton("Stop Capture")
        self.stop_capture_button.clicked.connect(self.stop_capture)
        buttons.addWidget(self.stop_capture_button)
        layout.addLayout(buttons)

        engine_row = QHBoxLayout()
        engine_row.addWidget(QLabel("Autopilot engine:"))
        self.engine_choice = QComboBox()
        self.engine_choice.addItems(("Java scan-line (fork)", "Python visual / manual points"))
        self.engine_choice.currentIndexChanged.connect(self._update_controls)
        engine_row.addWidget(self.engine_choice, 1)
        layout.addLayout(engine_row)

        controls = QHBoxLayout()
        self.confirm_tap = QCheckBox("Enable deliberate test flap")
        self.confirm_tap.stateChanged.connect(self._update_controls)
        controls.addWidget(self.confirm_tap)
        self.tap_button = QPushButton("TEST FLAP")
        self.tap_button.clicked.connect(self.test_flap)
        controls.addWidget(self.tap_button)
        self.autopilot = QCheckBox("Enable Autopilot")
        self.autopilot.stateChanged.connect(self._set_autopilot)
        controls.addWidget(self.autopilot)
        self.estop_button = QPushButton("STOP INPUT")
        self.estop_button.setStyleSheet("background: #a92626; color: white; font-weight: bold;")
        self.estop_button.clicked.connect(self.stop_input)
        controls.addWidget(self.estop_button)
        layout.addLayout(controls)

        marks = QHBoxLayout()
        self.mark_scooter = QPushButton("Mark scooter")
        self.mark_scooter.clicked.connect(lambda: self._start_marking("scooter"))
        marks.addWidget(self.mark_scooter)
        self.mark_gap = QPushButton("Mark next gap center")
        self.mark_gap.clicked.connect(lambda: self._start_marking("gap"))
        marks.addWidget(self.mark_gap)
        self.clear_marks = QPushButton("Clear points / automatic gaps")
        self.clear_marks.clicked.connect(self._clear_marks)
        marks.addWidget(self.clear_marks)
        layout.addLayout(marks)

        layout.addWidget(QLabel("Green box: scooter. Yellow: detected gaps. Red outline: target. "
                                "Green band: no click. Red band: click zone. White: center aim."))
        layout.addWidget(QLabel("Blue vertical lines: passed pillar, scooter, approaching pillar. "
                                "Cyan horizontal lines: 15% pillar clearance."))
        layout.addWidget(QLabel("Optional points: click Mark scooter, then click its image; "
                                "click Mark next gap center for each new pillar."))
        layout.addWidget(QLabel("Device and mirror settings: config/settings.local.json (optional)."))
        self.setCentralWidget(root)
        self._update_controls()

    def _set_status(self, message: str) -> None:
        self.status.setText(message)

    def _failed(self, message: str) -> None:
        if self._auto_enabled.is_set():
            self.autopilot.setChecked(False)
        self.status.setText(message)
        self._update_controls()

    def _connected(self, serial: str) -> None:
        self.status.setText(f"ADB connected: {serial}. Manual test input is available.")
        self._update_controls()
        if self.settings.launch_scrcpy:
            try:
                try:
                    window_client_crop(self.settings.window_title)
                    QTimer.singleShot(200, self.start_capture)
                except RuntimeError:
                    self.mirror.launch(serial, self.settings.window_title,
                                       self.settings.scrcpy_path or None,
                                       self.settings.window_x, self.settings.window_y,
                                       self.settings.window_width, self.settings.window_height,
                                       self.settings.video_codec, self.settings.video_encoder,
                                       self.settings.scrcpy_max_fps,
                                       self.settings.scrcpy_max_size)
                    QTimer.singleShot(2000, self.start_capture)
            except RuntimeError as exc:
                self.status.setText(f"ADB connected; mirror launch failed: {exc}")

    def _update_controls(self) -> None:
        self.tap_button.setEnabled(self.controller.input_enabled and self.confirm_tap.isChecked()
                                   and not self._auto_enabled.is_set())
        self.autopilot.setEnabled(self.autopilot.isChecked() or self._auto_enabled.is_set() or
                                  (self.controller.input_enabled and self.capture_thread is not None))
        self.engine_choice.setEnabled(not self.autopilot.isChecked())
        manual = self.engine_choice.currentIndex() == 1
        for button in (self.mark_scooter, self.mark_gap, self.clear_marks):
            button.setEnabled(manual)
        self.start_button.setEnabled(self.capture_thread is None)
        self.stop_capture_button.setEnabled(self.capture_thread is not None)

    def connect_device(self) -> None:
        self.connect_button.setEnabled(False)
        self.status.setText("Checking ADB device...")

        def work() -> None:
            try:
                self.events.connected.emit(self.controller.connect())
            except Exception as exc:
                self.events.failed.emit(str(exc))
            finally:
                self.events.connection_finished.emit()

        threading.Thread(target=work, daemon=True).start()

    def start_capture(self) -> None:
        if self.capture_thread is not None:
            return
        self.capture_thread = CaptureThread(self.settings)
        self.capture_thread.failed.connect(self._failed)
        self.capture_thread.finished.connect(self._capture_finished)
        self.capture_thread.start()
        self.status.setText("Capture started. Verify the crop shows only game pixels.")
        self._update_controls()

    def _capture_finished(self) -> None:
        self.capture_thread = None
        self._update_controls()

    def stop_capture(self) -> None:
        self.autopilot.setChecked(False)
        if self.capture_thread:
            self.capture_thread.stop()
            self.capture_thread = None
            self.metrics.setText("Capture: stopped")
            self._update_controls()

    def _poll_frame(self) -> None:
        if self.capture_thread:
            latest = self.capture_thread.latest()
            if latest:
                self._show_frame(*latest)

    def _start_marking(self, mode: str) -> None:
        if mode == "gap" and self.guidance.scooter_x is None:
            self.status.setText("Mark the scooter first, then mark the gap center.")
            return
        self._mark_mode = mode
        self.status.setText(f"Click the {mode} on the dashboard image.")

    def _mark_image_point(self, x: int, y: int) -> None:
        if self._mark_mode == "scooter":
            self.guidance.mark_scooter(x)
            self.status.setText("Scooter lane marked. Mark the center of the next pillar gap.")
        elif self._mark_mode == "gap":
            self.guidance.mark_gap(x, y)
            self.gap_continuity.reset()
            self.planner.reset()
            self.status.setText("Gap center marked. Mark the next gap after this pillar clears.")
        self._mark_mode = None

    def _clear_marks(self) -> None:
        self.guidance.clear()
        self.gap_continuity.reset()
        self.planner.reset()
        self._mark_mode = None
        self.status.setText("Manual points cleared. Automatic gap selection restored.")

    def _show_frame(self, packet: FramePacket, observation: Observation,
                    vision_ms: float) -> None:
        java_active = self.autopilot.isChecked() and self.engine_choice.currentIndex() == 0
        if java_active:
            observation = (self._java_observation if time.monotonic() - self._java_frame_at < .25
                           and self._java_observation is not None else
                           Observation("MENU_OR_UNKNOWN", None, (), None))
        else:
            observation = self.guidance.guide(observation, packet.timestamp,
                                              packet.width, packet.height)
            if self.guidance.manual_mode and self.guidance.gap_point is None:
                self.gap_continuity.reset()
            observation = self.gap_continuity.guide(observation, packet.timestamp,
                                                    packet.width)
        frame = QImage(packet.bgra, packet.width, packet.height, packet.width * 4,
                       QImage.Format.Format_ARGB32).copy()
        painter = QPainter(frame)
        if observation.scooter:
            rear_scan, scooter_scan, forward_scan = scan_lines(
                observation.scooter.center_x, packet.width)
            painter.setPen(QPen(QColor(0, 168, 255, 150), 2))
            for scan_x in (rear_scan, scooter_scan, forward_scan):
                painter.drawLine(scan_x, 0, scan_x, packet.height - 1)
        if observation.scooter:
            box = observation.scooter
            painter.setPen(QPen(QColor("#00ff55"), 4))
            painter.drawRect(box.left, box.top, box.right - box.left, box.bottom - box.top)
        displayed_gaps = list(observation.gaps)
        if observation.active_gap is not None and observation.active_gap not in displayed_gaps:
            displayed_gaps.append(observation.active_gap)
        for gap in displayed_gaps:
            painter.setPen(QPen(QColor("#ff3030" if gap == observation.active_gap else "#ffe02a"), 4))
            painter.drawRect(gap.left, gap.top, gap.right - gap.left, gap.bottom - gap.top)
            if gap == observation.active_gap and observation.scooter:
                upper, lower = clearance_bounds(gap)
                click_start, click_end = click_zone(
                    gap, observation.scooter.bottom - observation.scooter.top)
                if click_start < click_end:
                    painter.fillRect(gap.left, round(upper), gap.right - gap.left,
                                     max(0, round(click_start - upper)), QColor(23, 206, 89, 60))
                    painter.fillRect(gap.left, round(click_start), gap.right - gap.left,
                                     max(0, round(click_end - click_start)), QColor(245, 50, 51, 72))
                painter.setPen(QPen(QColor("#00e5ff"), 2))
                painter.drawLine(gap.left, round(upper), gap.right, round(upper))
                painter.drawLine(gap.left, round(lower), gap.right, round(lower))
                painter.setPen(QPen(QColor("#ffffff"), 2))
                target_y = round(aim_height(gap))
                painter.drawLine(gap.left, target_y, gap.right, target_y)
        if not java_active and self.guidance.scooter_x is not None:
            y = round(observation.scooter.center_y) if observation.scooter else packet.height // 2
            painter.setPen(QPen(QColor("#ff55f5"), 3))
            painter.drawEllipse(self.guidance.scooter_x - 7, y - 7, 14, 14)
        if not java_active and self.guidance.gap_point is not None:
            if observation.active_gap is not None:
                gap = observation.active_gap
                x, y = round((gap.left + gap.right) / 2), round(aim_height(gap))
            else:
                x, y = self.guidance.gap_point
            painter.setPen(QPen(QColor("#ff55f5"), 3))
            painter.drawEllipse(x - 8, y - 8, 16, 16)
        painter.end()
        self.image.frame_width = packet.width
        self.image.frame_height = packet.height
        self.image.setPixmap(QPixmap.fromImage(frame).scaled(
            self.image.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation))
        now = time.monotonic()
        fps = 0 if self._last_frame_time is None else 1 / max(now - self._last_frame_time, 1e-6)
        self._last_frame_time = now
        gap_state = ("seen" if observation.active_gap else "none") if java_active else (
            "estimated" if self.gap_continuity.estimated else
            "seen" if observation.active_gap else "none")
        self.metrics.setText(f"Frame {packet.sequence} | display {fps:.1f} FPS | "
                             f"age {(now - packet.timestamp) * 1000:.0f} ms | "
                             f"{'Java scan' if java_active else f'vision {vision_ms:.1f} ms'} | "
                             f"scene {observation.scene} | "
                             f"scooter {'yes' if observation.scooter else 'no'} | "
                             f"gaps {len(observation.gaps)} | "
                             f"gap {gap_state} | "
                             f"auto taps {self._auto_tap_count}")
        if self._auto_enabled.is_set():
            if observation.scene == "GAMEPLAY_CANDIDATE":
                self._auto_seen_gameplay = True
                self._non_gameplay_frames = 0
            else:
                self._non_gameplay_frames += 1
                if self._auto_seen_gameplay and self._non_gameplay_frames >= 3:
                    self._auto_seen_gameplay = False
                    self.planner.reset()
                    self.status.setText("Autopilot armed; waiting for gameplay to resume.")
        if (self._auto_enabled.is_set() and not self._auto_tap_in_flight
                and self.planner.observe(observation, packet.timestamp, now,
                                         packet.width, packet.height)):
            self._auto_tap_in_flight = True
            threading.Thread(target=self._send_auto_tap, daemon=True).start()

    def _set_autopilot(self) -> None:
        if self.autopilot.isChecked():
            if not self.controller.input_enabled or self.capture_thread is None:
                self.autopilot.setChecked(False)
                self.status.setText("Connect ADB and start capture before enabling Autopilot.")
                return
            self.confirm_tap.setChecked(False)
            if self.engine_choice.currentIndex() == 0:
                self._auto_enabled.clear()
                if hasattr(self.capture_thread, "set_python_vision"):
                    self.capture_thread.set_python_vision(False)
                self._auto_tap_count = 0
                self._java_observation = None
                self.status.setText("Starting Java scan-line controller...")
                threading.Thread(target=self.java_engine.launch, daemon=True).start()
                self._update_controls()
                return
            self.planner.reset()
            self._auto_seen_gameplay = False
            self._non_gameplay_frames = 0
            self._auto_tap_count = 0
            self._auto_enabled.set()
            self.status.setText("Autopilot armed. Resume the game; taps start after stable gameplay detections.")
        else:
            if self.engine_choice.currentIndex() == 0:
                try:
                    self.java_engine.send("stop")
                except RuntimeError:
                    pass
                if self.capture_thread is not None and hasattr(self.capture_thread, "set_python_vision"):
                    self.capture_thread.set_python_vision(True)
            self._auto_enabled.clear()
            self.planner.reset()
            self._auto_seen_gameplay = False
            self._non_gameplay_frames = 0
            self.status.setText("Autopilot off.")
        self._update_controls()

    def _java_ready(self) -> None:
        if self.autopilot.isChecked() and self.engine_choice.currentIndex() == 0:
            try:
                self.java_engine.send("start")
            except RuntimeError as exc:
                self._java_failed(str(exc))

    def _java_state(self, state: str) -> None:
        if state == "RUNNING":
            self.status.setText("Java Autopilot armed. Waiting for gameplay; STOP INPUT disables taps.")
        elif state == "STOPPING":
            self.status.setText("Java input command is finishing...")
        elif state == "STOPPED" and not self.autopilot.isChecked():
            self.status.setText("Java Autopilot stopped.")

    def _java_frame(self, observation: Observation) -> None:
        self._java_observation = observation
        self._java_frame_at = time.monotonic()

    def _java_tap(self, count: int, elapsed_ms: int) -> None:
        self._auto_tap_count = count
        self.status.setText(f"Java Autopilot armed | taps sent {count} | "
                            f"last ADB command {elapsed_ms} ms")

    def _java_failed(self, message: str) -> None:
        if self.autopilot.isChecked() and self.engine_choice.currentIndex() == 0:
            self.autopilot.setChecked(False)
        self.status.setText("Java controller: " + message)
        self._update_controls()

    def _send_auto_tap(self) -> None:
        try:
            if self._auto_enabled.is_set():
                started = time.monotonic()
                self.controller.tap(self.settings.touch_x, self.settings.touch_y)
                self.events.auto_tap_completed.emit((time.monotonic() - started) * 1000)
        except Exception as exc:
            self._auto_enabled.clear()
            self.events.auto_failed.emit(f"Autopilot stopped: {exc}")
        finally:
            self.events.auto_tap_finished.emit()

    def _auto_tap_done(self) -> None:
        self._auto_tap_in_flight = False
        self._update_controls()

    def _auto_tap_completed(self, elapsed_ms: float) -> None:
        self._auto_tap_count += 1
        self._last_auto_tap_ms = elapsed_ms
        self.status.setText(f"Autopilot armed | taps sent {self._auto_tap_count} | "
                            f"last ADB command {elapsed_ms:.0f} ms")

    def _auto_failed(self, message: str) -> None:
        self.autopilot.setChecked(False)
        self.status.setText(message)
        self._update_controls()

    def test_flap(self) -> None:
        if not self.confirm_tap.isChecked():
            return
        self.tap_button.setEnabled(False)
        requested_at = time.monotonic()

        def work() -> None:
            try:
                self.controller.tap(self.settings.touch_x, self.settings.touch_y)
                elapsed_ms = (time.monotonic() - requested_at) * 1000
                self.events.status.emit(f"One test tap completed in {elapsed_ms:.0f} ms; "
                                        "verify the flap on the phone.")
            except Exception as exc:
                self.events.failed.emit(str(exc))
            finally:
                self.events.tap_finished.emit()

        threading.Thread(target=work, daemon=True).start()

    def stop_input(self) -> None:
        self.autopilot.setChecked(False)
        self._auto_enabled.clear()
        self.confirm_tap.setChecked(False)
        self.tap_button.setEnabled(False)
        self.status.setText("Stopping input...")

        def work() -> None:
            self.controller.disable_output()
            self.events.status.emit("Input stopped. Connect ADB again to re-enable manual test input.")

        threading.Thread(target=work, daemon=True).start()

    def closeEvent(self, event) -> None:
        self._auto_enabled.clear()
        self.java_engine.close()
        self.stop_capture()
        self.controller.close()
        self.mirror.stop()
        event.accept()


def run_app(settings: Settings) -> None:
    app = QApplication(sys.argv)
    window = MainWindow(settings)
    window.show()
    QTimer.singleShot(250, window.connect_device)
    sys.exit(app.exec())
