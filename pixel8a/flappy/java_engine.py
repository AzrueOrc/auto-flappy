"""Subprocess bridge for the Java Pixel 8a detector and tap planner."""
from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .settings import Settings
from .vision import Box, Observation, PillarGap


def _box(value: str, kind: type[Box] | type[PillarGap]):
    if value == "-":
        return None
    values = [int(part) for part in value.split(",")]
    if len(values) != 4:
        raise ValueError("Expected four coordinates")
    return kind(*values)


def parse_frame(line: str) -> Observation:
    parts = line.rstrip("\r\n").split("\t")
    if len(parts) != 6 or parts[:2] != ["EVT", "FRAME"]:
        raise ValueError("Invalid Java frame event")
    if parts[2] not in {"0", "1"}:
        raise ValueError("Invalid Java gameplay flag")
    scooter = _box(parts[3], Box)
    gaps = () if parts[4] == "-" else tuple(
        _box(value, PillarGap) for value in parts[4].split(";"))
    if any(gap is None for gap in gaps):
        raise ValueError("Invalid Java gap")
    active = _box(parts[5], PillarGap)
    return Observation("GAMEPLAY_CANDIDATE" if parts[2] == "1" else "MENU_OR_UNKNOWN",
                       scooter, gaps, active)


class JavaEngine(QObject):
    ready = Signal()
    state = Signal(str)
    frame = Signal(object)
    tap = Signal(int, int)
    mark_cleared = Signal()
    failed = Signal(str)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.root = Path(__file__).resolve().parents[2]
        self.process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._closed = False

    @staticmethod
    def _jdk() -> tuple[str, str]:
        compiler = shutil.which("javac")
        runtime = shutil.which("java")
        if compiler and runtime:
            return compiler, runtime
        bundled = Path(r"C:\Program Files\Android\Android Studio\jbr\bin")
        if (bundled / "javac.exe").is_file() and (bundled / "java.exe").is_file():
            return str(bundled / "javac.exe"), str(bundled / "java.exe")
        raise RuntimeError("JDK not found. Install a JDK or Android Studio.")

    def _config(self) -> Path:
        config = self.root / "pixel8a-java" / "config.gui.properties"
        values = {
            "mirror.title": self.settings.window_title,
            "mirror.left": self.settings.crop.left,
            "mirror.top": self.settings.crop.top,
            "mirror.width": self.settings.crop.width,
            "mirror.height": self.settings.crop.height,
            "adb.path": self.settings.adb_path.replace("\\", "/") or "adb",
            "adb.serial": self.settings.serial,
            "touch.x": self.settings.touch_x,
            "touch.y": self.settings.touch_y,
        }
        if any("\n" in str(value) or "\r" in str(value) for value in values.values()):
            raise ValueError("Java engine settings cannot contain newlines")
        config.write_text("".join(f"{key}={value}\n" for key, value in values.items()),
                          encoding="utf-8")
        return config

    def launch(self) -> None:
        """Compile and launch on a worker thread; signals return to the Qt GUI."""
        try:
            with self._lock:
                if self._closed:
                    return
                if self.process and self.process.poll() is None:
                    self.ready.emit()
                    return
            compiler, runtime = self._jdk()
            source = sorted((self.root / "src" / "autoflappy").glob("*.java"))
            if not source:
                raise RuntimeError("Java AutoFlappy sources are missing")
            classes = self.root / "build" / "pixel8a-classes"
            classes.mkdir(parents=True, exist_ok=True)
            result = subprocess.run([compiler, "-d", str(classes),
                                     *(str(path) for path in source)],
                                    cwd=self.root, capture_output=True, text=True,
                                    timeout=30, check=False)
            if result.returncode:
                raise RuntimeError("Java compilation failed: " +
                                   (result.stderr or result.stdout).strip())
            config = self._config()
            process = subprocess.Popen(
                [runtime, "-cp", str(classes), "autoflappy.Main", "--pixel8a",
                 str(config), "--events"], cwd=self.root, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            with self._lock:
                if self._closed:
                    process.terminate()
                    return
                self.process = process
            threading.Thread(target=self._read, args=(process,), daemon=True).start()
        except Exception as exc:
            self.failed.emit(str(exc))

    def _read(self, process: subprocess.Popen[str]) -> None:
        assert process.stdout is not None
        try:
            for line in process.stdout:
                parts = line.rstrip("\r\n").split("\t")
                if len(parts) < 3 or parts[0] != "EVT":
                    continue
                kind = parts[1]
                if kind == "FRAME":
                    try:
                        self.frame.emit(parse_frame(line))
                    except ValueError as exc:
                        self.failed.emit("Invalid Java frame: " + str(exc))
                elif kind == "TAP" and len(parts) >= 4:
                    self.tap.emit(int(parts[2]), int(parts[3]))
                elif kind == "STATE":
                    self.state.emit(parts[2])
                    if parts[2] == "READY":
                        self.ready.emit()
                elif kind == "ERROR":
                    self.failed.emit("\t".join(parts[2:]))
                elif kind == "MARK" and parts[2] == "GAP_CLEARED":
                    self.mark_cleared.emit()
        except (OSError, ValueError) as exc:
            self.failed.emit("Java engine output failed: " + str(exc))
        finally:
            with self._lock:
                expected = self._closed
                if self.process is process:
                    self.process = None
            if not expected:
                self.failed.emit("Java controller exited. Autopilot is off.")

    def send(self, command: str) -> None:
        with self._lock:
            process = self.process
            if self._closed or process is None or process.poll() is not None or process.stdin is None:
                raise RuntimeError("Java controller is not running")
            process.stdin.write(command + "\n")
            process.stdin.flush()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            process = self.process
        if process and process.poll() is None:
            try:
                if process.stdin is not None:
                    process.stdin.write("stop\nquit\n")
                    process.stdin.flush()
                process.wait(timeout=5)
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
