"""簡單的幾何工具函式。"""

from __future__ import annotations

from typing import Optional

from .types import BBox, KP, Person


def area(b: BBox) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def intersection(a: BBox, b: BBox) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    return area((x1, y1, x2, y2))


def iou(a: BBox, b: BBox) -> float:
    inter = intersection(a, b)
    union = area(a) + area(b) - inter
    return inter / union if union > 0 else 0.0


def center(b: BBox) -> tuple[float, float]:
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def contains(b: BBox, p: tuple[float, float]) -> bool:
    return b[0] <= p[0] <= b[2] and b[1] <= p[1] <= b[3]


def expand(b: BBox, ratio: float) -> BBox:
    w, h = b[2] - b[0], b[3] - b[1]
    return (b[0] - w * ratio, b[1] - h * ratio, b[2] + w * ratio, b[3] + h * ratio)


def dist(p: tuple[float, float], q: tuple[float, float]) -> float:
    return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5


def shoulder_mid(person: Person) -> Optional[tuple[float, float]]:
    ls, rs = person.kp(KP.L_SHOULDER), person.kp(KP.R_SHOULDER)
    if ls and rs:
        return ((ls[0] + rs[0]) / 2, (ls[1] + rs[1]) / 2)
    return ls or rs


def shoulder_width(person: Person) -> Optional[float]:
    ls, rs = person.kp(KP.L_SHOULDER), person.kp(KP.R_SHOULDER)
    if ls and rs:
        w = dist(ls, rs)
        if w > 1:
            return w
    return None


def body_scale(person: Person) -> float:
    """人物的尺度，用來把位移、距離正規化，使遠近座位可以共用同一組門檻。"""
    sw = shoulder_width(person)
    if sw:
        return sw
    # 沒有肩膀時，以框的寬度估計 (上半身框寬約為肩寬的 1.3 倍)
    return max(1.0, (person.bbox[2] - person.bbox[0]) / 1.3)


def anchor(person: Person) -> tuple[float, float]:
    """判斷人坐在哪個座位時所用的代表點：優先用兩肩中點，否則用框的上半部中心。"""
    sm = shoulder_mid(person)
    if sm:
        return sm
    x1, y1, x2, y2 = person.bbox
    return ((x1 + x2) / 2, y1 + (y2 - y1) * 0.3)
