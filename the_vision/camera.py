"""監視器影像來源 (RTSP / USB 攝影機 / 影片檔)。

RTSP 串流若只在需要時才讀取，OpenCV 的緩衝區會累積舊畫面；
因此用背景執行緒持續讀取，只保留最新一張。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import cv2
import numpy as np

log = logging.getLogger(__name__)


class Camera:
    def __init__(self, source: str):
        self.source: int | str = int(source) if source.isdigit() else source
        self.is_file = isinstance(self.source, str) and not self.source.lower().startswith(("rtsp", "http"))
        self._frame: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cap: Optional[cv2.VideoCapture] = None

    def start(self) -> "Camera":
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._thread = None

    def _open(self) -> cv2.VideoCapture:
        cap = cv2.VideoCapture(self.source)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _run(self) -> None:
        fps_delay = 0.0
        while not self._stop.is_set():
            if self._cap is None or not self._cap.isOpened():
                self._cap = self._open()
                if not self._cap.isOpened():
                    log.warning("無法開啟影像來源 %s，5 秒後重試", self.source)
                    time.sleep(5)
                    continue
                if self.is_file:
                    fps = self._cap.get(cv2.CAP_PROP_FPS) or 25
                    fps_delay = 1.0 / fps  # 影片檔以原速播放，模擬即時串流
            ok, frame = self._cap.read()
            if not ok:
                if self.is_file:
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # 影片播完從頭重播
                else:
                    log.warning("影像中斷，重新連線…")
                    self._cap.release()
                    self._cap = None
                    time.sleep(1)
                continue
            with self._lock:
                self._frame = frame
            if fps_delay:
                time.sleep(fps_delay)
        if self._cap is not None:
            self._cap.release()

    def read(self, timeout: float = 10.0) -> Optional[np.ndarray]:
        self.start()
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if self._frame is not None:
                    return self._frame.copy()
            time.sleep(0.05)
        return None

    def burst(self, n: int, interval: float) -> list[np.ndarray]:
        frames = []
        for i in range(n):
            f = self.read()
            if f is not None:
                frames.append(f)
            if i < n - 1:
                time.sleep(interval)
        return frames
