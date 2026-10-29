"""YOLO 偵測器：人體姿態 (關鍵點) + 物件 (手機 / 書 / 筆電)。

模型第一次執行會自動下載。若教室環境中手機很小、偵測不到，可以：
  * 提高 detector.img_size (例如 1600)
  * 換較大的物件模型 (yolo11m.pt)
  * 用自家教室影像微調一個手機模型，再把 object_model 指向它
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from .config import DetectorConfig
from .types import DetectedObject, FrameDetections, Person


class Detector(Protocol):
    def detect(self, frame: np.ndarray) -> FrameDetections: ...


class YoloDetector:
    def __init__(self, cfg: DetectorConfig):
        from ultralytics import YOLO  # 延遲載入，讓沒有安裝 torch 的環境也能跑設定介面與測試

        self.cfg = cfg
        self.pose = YOLO(cfg.pose_model)
        self.objects = YOLO(cfg.object_model)
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
