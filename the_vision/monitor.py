"""背景監看：每 interval_sec 秒擷取一段連拍 → 偵測 → 判斷 → 寫入資料庫。"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, replace
from typing import Any, Callable, Optional

import cv2

from .camera import Camera
from .classifier import classify
from .config import AppConfig
from .detector import Detector
from .storage import Layout, Store
from .types import TickResult

log = logging.getLogger(__name__)


def tick_to_dict(tick: TickResult) -> dict[str, Any]:
    return {
        "timestamp": tick.timestamp,
        "seats": [
            {"name": s.name, "status": s.status.value, "label": s.status.label, "reason": s.reason,
             "person_bbox": s.person_bbox}
            for s in tick.seats
        ],
        "alerts": [asdict(a) for a in tick.alerts],
    }


class Monitor:
    def __init__(self, cfg: AppConfig, camera: Camera, store: Store,
                 detector_factory: Callable[[], Detector]):
        self.cfg = cfg
        self.camera = camera
        self.store = store
        self._detector_factory = detector_factory
        self._detector: Optional[Detector] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.session_id: Optional[int] = None
        self.layout: Optional[Layout] = None
        self.latest: Optional[dict[str, Any]] = None
        self.error: Optional[str] = None
        self.next_tick_at: Optional[float] = None
        self._alert_last_seen: dict[tuple[str, str], float] = {}

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def detector(self) -> Detector:
        if self._detector is None:
            self._detector = self._detector_factory()
        return self._detector

    def start(self, title: str, layout: Layout) -> int:
        if self.running:
            raise RuntimeError("已有課堂正在監看中")
        if not layout.seats:
            raise ValueError("請先框選學生座位")
        self.layout = layout
        self.session_id = self.store.start_session(title, layout)
        self.latest = None
        self.error = None
        self._alert_last_seen = {}
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self.session_id

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.cfg.interval_sec + 30)
        self._thread = None
        if self.session_id is not None:
            self.store.end_session(self.session_id)
        self.next_tick_at = None

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.time()
            try:
                self.tick()
                self.error = None
            except Exception as e:  # 單次失敗不中斷整堂課
                log.exception("辨識失敗")
                self.error = str(e)
            self.next_tick_at = started + self.cfg.interval_sec
            self._stop.wait(max(0.0, self.next_tick_at - time.time()))

    def tick(self) -> TickResult:
        assert self.layout is not None and self.session_id is not None
        cam = self.cfg.camera
        frames = self.camera.burst(cam.burst_frames, cam.burst_interval_sec)
        if not frames:
            raise RuntimeError("無法取得監視器畫面")
        det = self.detector()
        detections = [det.detect(f) for f in frames]
        tick = classify(detections, self.layout.seats, self.cfg.rules, self.layout.ignore_zones)

        # 持續中的同一個警示只在第一次 (或冷卻時間過後) 寫入紀錄
        new_alerts = []
        for a in tick.alerts:
            key = (a.kind, a.message)
            last = self._alert_last_seen.get(key)
            if last is None or tick.timestamp - last >= self.cfg.alert_cooldown_sec:
                new_alerts.append(a)
                self._alert_last_seen[key] = tick.timestamp

        snap_dir = self.cfg.data_path / "snapshots" / str(self.session_id)
        snap_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(snap_dir / "latest.jpg"), frames[-1])
        snapshot = None
        if self.cfg.save_snapshots == "all" or (self.cfg.save_snapshots == "alerts" and new_alerts):
            snapshot = f"{int(tick.timestamp)}.jpg"
            cv2.imwrite(str(snap_dir / snapshot), frames[-1])

        self.store.add_tick(self.session_id, replace(tick, alerts=new_alerts), snapshot)
        self.latest = tick_to_dict(tick) | {"snapshot": snapshot}
        for a in new_alerts:
            log.warning("[%s] %s", a.level, a.message)
        return tick
