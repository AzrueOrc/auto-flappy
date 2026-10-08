from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Crop:
    left: int
    top: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Capture width and height must be positive")

    def as_mss(self) -> dict[str, int]:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}


@dataclass(frozen=True)
class Settings:
    serial: str
    adb_path: str
    touch_x: int
    touch_y: int
    crop: Crop
    use_scrcpy_window: bool
    target_fps: int
    launch_scrcpy: bool
    scrcpy_path: str
    window_title: str
    video_codec: str
    video_encoder: str
    scrcpy_max_fps: int
    scrcpy_max_size: int
    window_x: int
    window_y: int
    window_width: int
    window_height: int


def load_settings(path: Path) -> Settings:
    raw = json.loads(path.read_text(encoding="utf-8"))
    device = raw["device"]
    capture = raw["capture"]
    mirror = raw["scrcpy"]
    crop = Crop(**capture["crop"])
    fps = int(capture["target_fps"])
    if not 1 <= fps <= 120:
        raise ValueError("target_fps must be between 1 and 120")
    x, y = int(device["touch_x"]), int(device["touch_y"])
    if x < 0 or y < 0:
        raise ValueError("Touch coordinates must be nonnegative")
    window_width = int(mirror.get("window_width", 405))
    window_height = int(mirror.get("window_height", 900))
    if window_width <= 0 or window_height <= 0:
        raise ValueError("scrcpy window dimensions must be positive")
    mirror_fps = int(mirror.get("max_fps", 60))
    if not 1 <= mirror_fps <= 120:
        raise ValueError("scrcpy max_fps must be between 1 and 120")
    mirror_size = int(mirror.get("max_size", 0))
    if mirror_size < 0:
        raise ValueError("scrcpy max_size cannot be negative")
    codec = str(mirror.get("video_codec", "h264")).strip()
    if codec not in {"h264", "h265", "av1", "vp8", "vp9"}:
        raise ValueError("Unsupported scrcpy video codec")
    return Settings(str(device["serial"]).strip(), str(device.get("adb_path", "")).strip(),
                    x, y, crop, bool(capture.get("use_scrcpy_window", False)), fps,
                    bool(mirror["launch_automatically"]), str(mirror.get("path", "")).strip(),
                    str(mirror["window_title"]), codec,
                    str(mirror.get("video_encoder", "")).strip(),
                    mirror_fps, mirror_size, int(mirror.get("window_x", 0)),
                    int(mirror.get("window_y", 0)), window_width, window_height)
