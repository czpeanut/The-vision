"""共用資料結構。座標一律使用影像像素座標 (x 向右、y 向下)。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

BBox = tuple[float, float, float, float]  # x1, y1, x2, y2


class Status(str, Enum):
    """單一學生在某次辨識時的狀態。"""

    FOCUSED = "focused"          # 專心讀書
    PHONE = "phone"              # 玩手機
    SLEEPING = "sleeping"        # 趴睡
    DISTRACTED = "distracted"    # 分心 / 東張西望 / 與鄰座聊天
    ACTIVE = "active"            # 座位上動作過大 (起身、揮手、打鬧)
    ABSENT = "absent"            # 離開座位
    UNKNOWN = "unknown"          # 畫面被遮擋、無法判斷

    @property
    def label(self) -> str:
        return STATUS_LABELS[self]


STATUS_LABELS = {
    Status.FOCUSED: "專心讀書",
    Status.PHONE: "玩手機",
    Status.SLEEPING: "趴睡",
    Status.DISTRACTED: "分心",
    Status.ACTIVE: "動作過大",
    Status.ABSENT: "離開座位",
    Status.UNKNOWN: "無法判斷",
}

STATUS_COLORS = {  # BGR，用於標註影像
    Status.FOCUSED: (80, 175, 76),
    Status.PHONE: (0, 140, 255),
    Status.SLEEPING: (180, 105, 255),
    Status.DISTRACTED: (0, 215, 255),
    Status.ACTIVE: (60, 20, 220),
    Status.ABSENT: (128, 128, 128),
    Status.UNKNOWN: (200, 200, 200),
}


# COCO-17 關鍵點索引
class KP:
    NOSE = 0
    L_EYE = 1
    R_EYE = 2
    L_EAR = 3
    R_EAR = 4
    L_SHOULDER = 5
    R_SHOULDER = 6
    L_ELBOW = 7
    R_ELBOW = 8
    L_WRIST = 9
    R_WRIST = 10
    L_HIP = 11
    R_HIP = 12


@dataclass
class Person:
    bbox: BBox
    conf: float
    # 17 x (x, y, conf)；若模型沒有輸出關鍵點則為空 list
    keypoints: list[tuple[float, float, float]] = field(default_factory=list)

    def kp(self, idx: int, min_conf: float = 0.4) -> Optional[tuple[float, float]]:
        if idx >= len(self.keypoints):
            return None
        x, y, c = self.keypoints[idx]
        return (x, y) if c >= min_conf else None


@dataclass
class DetectedObject:
    name: str          # 例如 "cell phone", "book", "laptop"
    bbox: BBox
    conf: float


@dataclass
class FrameDetections:
    persons: list[Person]
    objects: list[DetectedObject]


@dataclass
class Seat:
    name: str
    bbox: BBox  # 老師在畫面上框出的範圍


@dataclass
class SeatResult:
    name: str
    status: Status
    reason: str
    person_bbox: Optional[BBox] = None


@dataclass
class Alert:
    kind: str        # wandering / fighting / fall / waving
    message: str
    level: str       # "warning" | "danger"
    bbox: Optional[BBox] = None


@dataclass
class TickResult:
    """一次 (每 30 秒) 辨識的結果。"""

    timestamp: float
    seats: list[SeatResult]
    alerts: list[Alert]
