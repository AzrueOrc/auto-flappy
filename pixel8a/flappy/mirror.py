from __future__ import annotations

import shutil
import subprocess


class Mirror:
    def __init__(self) -> None:
        self.process: subprocess.Popen[bytes] | None = None

    def launch(self, serial: str, title: str, path: str | None = None,
               x: int = 0, y: int = 0, width: int = 405, height: int = 900,
               video_codec: str = "h264", video_encoder: str = "",
               max_fps: int = 60, max_size: int = 0) -> None:
        binary = path or shutil.which("scrcpy")
        if not binary:
            raise RuntimeError("scrcpy was not found on PATH")
        if self.process and self.process.poll() is None:
            return
        args = [binary, "--serial", serial, f"--max-fps={max_fps}",
                f"--video-codec={video_codec}", "--no-audio", "--window-title", title,
                f"--window-x={x}", f"--window-y={y}",
                f"--window-width={width}", f"--window-height={height}"]
        if video_encoder:
            args.append(f"--video-encoder={video_encoder}")
        if max_size:
            args.append(f"--max-size={max_size}")
        self.process = subprocess.Popen(args,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop(self) -> None:
        process = self.process
        self.process = None
        if process and process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=3)
