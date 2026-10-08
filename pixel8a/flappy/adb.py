from __future__ import annotations

import re
import shutil
import subprocess
import threading
import queue
from collections.abc import Callable


class DeviceError(RuntimeError):
    pass


Run = Callable[..., subprocess.CompletedProcess[str]]


def parse_devices(output: str) -> dict[str, str]:
    devices: dict[str, str] = {}
    for line in output.splitlines():
        if line.startswith("List of devices") or not line.strip() or line.startswith("*"):
            continue
        fields = line.split()
        if len(fields) >= 2:
            devices[fields[0]] = fields[1]
    return devices


class ADBController:
    def __init__(self, requested_serial: str = "", adb_path: str | None = None,
                 runner: Run = subprocess.run, persistent: bool = True) -> None:
        self.adb_path = adb_path or shutil.which("adb")
        self.requested_serial = requested_serial
        self.serial: str | None = None
        self._run = runner
        self._lock = threading.Lock()
        self._enabled = False
        self._persistent = persistent
        self._shell: subprocess.Popen[str] | None = None
        self._responses: queue.Queue[str | None] | None = None
        self._command_id = 0

    @property
    def input_enabled(self) -> bool:
        with self._lock:
            return self._enabled and self.serial is not None

    def connect(self) -> str:
        if not self.adb_path:
            raise DeviceError("adb was not found on PATH. Install Android platform tools.")
        try:
            result = self._run([self.adb_path, "devices"], capture_output=True,
                               text=True, timeout=5, check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise DeviceError(f"ADB device discovery failed: {exc}") from exc
        devices = parse_devices(result.stdout)
        if self.requested_serial:
            if self.requested_serial not in devices:
                raise DeviceError(f"Configured device {self.requested_serial!r} is not connected")
            serial = self.requested_serial
        else:
            if len(devices) != 1:
                raise DeviceError(f"Expected exactly one ADB device; found {len(devices)}. Set device.serial.")
            serial = next(iter(devices))
        state = devices[serial]
        if state != "device":
            raise DeviceError(f"Device {serial} is {state}; unlock/authorize it before continuing")
        with self._lock:
            self._enabled = False
            self._close_shell_locked()
            self.serial = serial
            if self._persistent:
                try:
                    self._start_shell_locked()
                except (OSError, subprocess.SubprocessError, DeviceError) as exc:
                    self._close_shell_locked()
                    self.serial = None
                    raise DeviceError(f"Could not start a responsive ADB shell: {exc}") from exc
            self._enabled = True
        return serial

    def _start_shell_locked(self) -> None:
        if not self.serial:
            raise DeviceError("No selected ADB device")
        self._shell = subprocess.Popen(
            [self.adb_path, "-s", self.serial, "shell"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1)
        if self._shell.stdin is None or self._shell.stdout is None:
            raise OSError("ADB shell has no input/output stream")
        self._responses = queue.Queue()
        responses = self._responses
        stdout = self._shell.stdout

        def read_responses() -> None:
            try:
                for line in stdout:
                    responses.put(line.strip())
            finally:
                responses.put(None)

        threading.Thread(target=read_responses, daemon=True).start()
        self._send_shell_locked(":")

    def _send_shell_locked(self, command: str) -> None:
        shell = self._shell
        responses = self._responses
        if shell is None or shell.stdin is None or responses is None or shell.poll() is not None:
            raise DeviceError("Persistent ADB shell is unavailable")
        self._command_id += 1
        marker = f"CODEX_FLAPPY_DONE_{self._command_id}"
        try:
            shell.stdin.write(f"{command}\necho {marker}\n")
            shell.stdin.flush()
            while True:
                line = responses.get(timeout=3)
                if line == marker:
                    return
                if line is None:
                    raise DeviceError("ADB shell closed before completing the command")
        except (OSError, queue.Empty) as exc:
            raise DeviceError(f"ADB shell command timed out or failed: {exc}") from exc

    def _close_shell_locked(self) -> None:
        shell = self._shell
        self._shell = None
        self._responses = None
        if shell and shell.poll() is None:
            shell.terminate()
            try:
                shell.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                shell.kill()
                shell.communicate(timeout=1)

    def ping(self) -> None:
        """Measure the ready input channel without sending a touch event."""
        with self._lock:
            if not self._enabled or not self._persistent:
                raise DeviceError("Persistent input channel is unavailable")
            self._send_shell_locked(":")

    def disable_output(self) -> None:
        with self._lock:
            self._enabled = False

    def tap(self, x: int, y: int) -> None:
        if x < 0 or y < 0:
            raise ValueError("Touch coordinates must be nonnegative")
        # Keep the lock through the command. Stop then waits for any in-flight tap
        # and guarantees that no later tap can start once Stop returns.
        with self._lock:
            if not self._enabled or not self.serial:
                raise DeviceError("Input is disabled. Connect explicitly before sending a tap.")
            try:
                if self._persistent:
                    self._send_shell_locked(f"input tap {x} {y}")
                else:
                    self._run([self.adb_path, "-s", self.serial, "shell", "input", "tap",
                               str(x), str(y)], capture_output=True, text=True, timeout=3, check=True)
            except (OSError, subprocess.SubprocessError, DeviceError) as exc:
                if self._persistent:
                    self._close_shell_locked()
                    try:
                        self._start_shell_locked()
                    except (OSError, subprocess.SubprocessError, DeviceError):
                        self._enabled = False
                        self._close_shell_locked()
                        raise DeviceError(f"Tap completion unknown; ADB input disabled. "
                                          f"Press Connect ADB to recover. Cause: {exc}") from exc
                    raise DeviceError("Tap completion unknown; ADB input channel recovered. "
                                      "Check the phone before pressing TEST FLAP again.") from exc
                self._enabled = False
                raise DeviceError(f"ADB tap failed; input disabled: {exc}") from exc

    def close(self) -> None:
        self.disable_output()
        with self._lock:
            self._close_shell_locked()
            self.serial = None
