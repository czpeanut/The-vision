"""系統設定。可由 config.yaml 覆寫任何欄位。"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class CameraConfig:
    # 可為 RTSP 網址 (rtsp://user:pass@ip:554/stream1)、USB 攝影機編號 (0) 或影片檔路徑
    source: str = "0"
    # 每次辨識時連續擷取幾張影像，用來估計動作幅度 (打鬧、揮手)
    burst_frames: int = 5
    burst_interval_sec: float = 0.4


@dataclass
class DetectorConfig:
    pose_model: str = "yolo11n-pose.pt"   # 人體姿態 (17 個關鍵點)
    object_model: str = "yolo11s.pt"      # 物件偵測 (手機 / 書 / 筆電)
    device: str = ""                      # "" 自動、"cpu"、"0" (第一張 GPU)
    img_size: int = 1280                  # 教室全景人很小，建議用較大的輸入尺寸
    person_conf: float = 0.35
    phone_conf: float = 0.30
    object_classes: list[str] = field(default_factory=lambda: ["cell phone", "book", "laptop"])


@dataclass
class RuleConfig:
    """行為判斷的門檻。數值皆以「肩寬」為單位正規化，與學生離鏡頭遠近無關。

    不同教室的鏡頭角度差異很大，建議用實際錄影跑 `python -m the_vision.tools.replay` 微調。
    """

    # 一次辨識的影像中，至少多少比例偵測到人才算「在座位」
    presence_ratio: float = 0.5
    # 手機出現在座位範圍內的影像比例
    phone_ratio: float = 0.3
    # 頭部高度 = (肩膀 y - 鼻子 y) / 肩寬。低於此值視為頭埋下去 (趴睡)
    sleep_head_height: float = 0.15
    sleep_ratio: float = 0.6
    # 鼻子相對兩肩中點的水平偏移 / 肩寬。高於此值視為轉頭 (與鄰座聊天、東張西望)
    turn_head_offset: float = 0.45
    distracted_ratio: float = 0.6
    # 連拍影像間關鍵點的位移 / 肩寬。高於此值視為動作過大
    active_motion: float = 0.6
    # 走道上有人超過多少比例的影像才發出「離座走動」警示
    wander_ratio: float = 0.5
    # 兩人距離 (中心距 / 平均肩寬) 小於此值且有大動作，視為疑似打鬧
    fight_distance: float = 2.0
    fight_motion: float = 0.8
    # 不在座位上、身體框寬/高大於此值且軀幹接近水平，視為疑似跌倒
    fall_aspect: float = 1.3


@dataclass
class AppConfig:
    camera: CameraConfig = field(default_factory=CameraConfig)
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    rules: RuleConfig = field(default_factory=RuleConfig)
    interval_sec: float = 30.0
    # 保存哪些畫面供事後檢視："all" 每次辨識都存、"alerts" 只存有警示的、"none" 都不存
    save_snapshots: str = "alerts"
    # 同一個警示持續發生時，多久內不重複記錄 (看板上的即時畫面仍會標示)
    alert_cooldown_sec: float = 120.0
    data_dir: str = "data"
    host: str = "0.0.0.0"
    port: int = 8000

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


def _merge(dc: Any, values: dict[str, Any]) -> Any:
    for f in fields(dc):
        if f.name not in values:
            continue
        cur = getattr(dc, f.name)
        if is_dataclass(cur) and isinstance(values[f.name], dict):
            _merge(cur, values[f.name])
        else:
            setattr(dc, f.name, values[f.name])
    return dc


def load_config(path: str | Path | None = "config.yaml") -> AppConfig:
    cfg = AppConfig()
    if path and Path(path).exists():
        with open(path, encoding="utf-8") as fh:
            _merge(cfg, yaml.safe_load(fh) or {})
    cfg.camera.source = str(cfg.camera.source)
    return cfg
