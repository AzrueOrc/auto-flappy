from __future__ import annotations

import ctypes
import sys
import time
from dataclasses import dataclass
from typing import Any

from .settings import Crop


def window_client_crop(title: str) -> Crop:
    if sys.platform != "win32":
        raise RuntimeError("Window client capture is available only on Windows")

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    user32 = ctypes.windll.user32
    user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    user32.FindWindowW.restype = ctypes.c_void_p
    handle = user32.FindWindowW(None, title)
    if not handle:
        raise RuntimeError(f"scrcpy window {title!r} was not found")
    rect = RECT()
    point = POINT(0, 0)
    if not user32.GetClientRect(ctypes.c_void_p(handle), ctypes.byref(rect)):
        raise RuntimeError("Could not read scrcpy client rectangle")
    if not user32.ClientToScreen(ctypes.c_void_p(handle), ctypes.byref(point)):
        raise RuntimeError("Could not locate scrcpy client area on the desktop")
    return Crop(point.x, point.y, rect.right - rect.left, rect.bottom - rect.top)


@dataclass(frozen=True)
class FramePacket:
    bgra: bytes
    width: int
    height: int
    timestamp: float
    sequence: int


class ScreenFrameSource:
    def __init__(self, crop: Crop, target_fps: int, window_title: str | None = None) -> None:
        self.crop = crop
        self.target_fps = target_fps
        self.window_title = window_title
        self._sct: Any = None
        self._sequence = 0

    def __enter__(self) -> "ScreenFrameSource":
        import mss
        self._sct = mss.mss()
        return self

    def __exit__(self, *_: object) -> None:
        if self._sct:
            self._sct.close()
            self._sct = None

    def read(self) -> FramePacket:
        if self._sct is None:
            raise RuntimeError("Frame source is not started")
        crop = window_client_crop(self.window_title) if self.window_title else self.crop
        image = self._sct.grab(crop.as_mss())
        self._sequence += 1
        return FramePacket(image.bgra, image.width, image.height,
                           time.monotonic(), self._sequence)
