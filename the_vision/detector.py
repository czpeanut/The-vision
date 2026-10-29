"""YOLO 偵測器：人體姿態 (關鍵點) + 物件 (手機 / 書 / 筆電)。

模型第一次執行會自動下載。若教室環境中手機很小、偵測不到，可以：
  * 提高 detector.img_size (例如 1600)
  * 換較大的物件模型 (yolo11m.pt)
  * 用自家教室影像微調一個手機模型，再把 object_model 指向它
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

import numpy as np

from .config import DetectorConfig
from .types import DetectedObject, FrameDetections, Person


class Detector(Protocol):
    def detect(self, frame: np.ndarray) -> FrameDetections: ...


class ModelMissingError(RuntimeError):
    pass


def configure_offline() -> None:
    """關閉 ultralytics 的連網檢查與使用統計回傳。必須在第一次 import ultralytics 之前呼叫才完全有效。"""
    os.environ["YOLO_OFFLINE"] = "1"
    from ultralytics.utils import SETTINGS

    if SETTINGS.get("sync"):
        SETTINGS.update({"sync": False})


def resolve_model(path: str, offline: bool) -> str:
    if Path(path).exists() or not offline:
        return path  # 非離線模式下，找不到的模型交給 ultralytics 自動下載
    raise ModelMissingError(
        f"找不到模型檔 {path}。離線模式不會自動下載，請在有網路的電腦執行 "
        f"`python -m the_vision.tools.fetch_models`，再把 models/ 資料夾複製到這台電腦。"
    )


class YoloDetector:
    def __init__(self, cfg: DetectorConfig):
        if cfg.offline:
            configure_offline()
        from ultralytics import YOLO  # 延遲載入，讓沒有安裝 torch 的環境也能跑設定介面與測試

        self.cfg = cfg
        self.pose = YOLO(resolve_model(cfg.pose_model, cfg.offline))
        self.objects = YOLO(resolve_model(cfg.object_model, cfg.offline))
        names = self.objects.names
        self.class_ids = [i for i, n in names.items() if n in cfg.object_classes]

    def detect(self, frame: np.ndarray) -> FrameDetections:
        kw = dict(imgsz=self.cfg.img_size, verbose=False)
        if self.cfg.device:
            kw["device"] = self.cfg.device

        persons: list[Person] = []
        res = self.pose.predict(frame, conf=self.cfg.person_conf, **kw)[0]
        if res.boxes is not None and len(res.boxes):
            boxes = res.boxes.xyxy.cpu().numpy()
            confs = res.boxes.conf.cpu().numpy()
            kps = res.keypoints.data.cpu().numpy() if res.keypoints is not None else None
            for i, (b, c) in enumerate(zip(boxes, confs)):
                pts = [tuple(map(float, k)) for k in kps[i]] if kps is not None else []
                persons.append(Person(bbox=tuple(map(float, b)), conf=float(c), keypoints=pts))

        objects: list[DetectedObject] = []
        res = self.objects.predict(frame, conf=self.cfg.phone_conf, classes=self.class_ids, **kw)[0]
        if res.boxes is not None:
            for b, c, k in zip(res.boxes.xyxy.cpu().numpy(), res.boxes.conf.cpu().numpy(),
                               res.boxes.cls.cpu().numpy()):
                objects.append(DetectedObject(self.objects.names[int(k)], tuple(map(float, b)), float(c)))
        return FrameDetections(persons=persons, objects=objects)
