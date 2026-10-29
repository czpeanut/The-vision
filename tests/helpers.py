"""產生合成的姿態偵測結果，用來測試判斷規則。"""

from __future__ import annotations

from the_vision.types import KP, DetectedObject, FrameDetections, Person, Seat

SW = 40.0  # 肩寬 (像素)


def person(cx: float, sy: float, head: float = 0.5, turn: float = 0.0, face: bool = True,
           wrists_up: bool = False, dx: float = 0.0, lying: bool = False) -> Person:
    """cx, sy：兩肩中點。head：頭部高度 (肩寬單位)。turn：鼻子水平偏移 (肩寬單位)。"""
    cx += dx
    kps = [(0.0, 0.0, 0.0)] * 17

    def put(i, x, y, c=0.9):
        kps[i] = (x, y, c)

    put(KP.L_SHOULDER, cx + SW / 2, sy)
    put(KP.R_SHOULDER, cx - SW / 2, sy)
    if face:
        ny = sy - head * SW
        put(KP.NOSE, cx + turn * SW, ny)
        put(KP.L_EYE, cx + turn * SW + 6, ny - 5)
        put(KP.R_EYE, cx + turn * SW - 6, ny - 5)
    wy = sy - 2.0 * SW if wrists_up else sy + 0.8 * SW
    put(KP.L_ELBOW, cx + SW * 0.7, sy + 0.5 * SW)
    put(KP.R_ELBOW, cx - SW * 0.7, sy + 0.5 * SW)
    put(KP.L_WRIST, cx + SW * 0.3, wy)
    put(KP.R_WRIST, cx - SW * 0.3, wy)
    if lying:
        put(KP.L_HIP, cx + 2.5 * SW, sy + 5)
        put(KP.R_HIP, cx + 2.5 * SW, sy - 5)
        bbox = (cx - 1.5 * SW, sy - 0.8 * SW, cx + 4 * SW, sy + 0.8 * SW)
    else:
        bbox = (cx - SW, sy - 1.6 * SW, cx + SW, sy + 1.5 * SW)
    return Person(bbox=bbox, conf=0.9, keypoints=kps)


def phone_near(p: Person) -> DetectedObject:
    x, y, _ = p.keypoints[KP.L_WRIST]
    return DetectedObject("cell phone", (x - 6, y - 10, x + 6, y + 10), 0.7)


def frames(*per_frame: list[Person], objects=None, n: int = 5) -> list[FrameDetections]:
    """若只給一組人物，就複製成 n 張靜止影像。"""
    if len(per_frame) == 1:
        per_frame = per_frame * n
    return [FrameDetections(list(ps), list(objects or [])) for ps in per_frame]


# 兩排各三個座位，座位寬 100、高 140
SEATS = [
    Seat(f"S{r}{c}", (100 + c * 110, 100 + r * 160, 200 + c * 110, 240 + r * 160))
    for r in range(2) for c in range(3)
]


def seat_center(name: str) -> tuple[float, float]:
    s = next(s for s in SEATS if s.name == name)
    return ((s.bbox[0] + s.bbox[2]) / 2, (s.bbox[1] + s.bbox[3]) / 2)
