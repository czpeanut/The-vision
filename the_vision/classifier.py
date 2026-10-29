"""把偵測結果 (人體關鍵點 + 物件) 轉換成每位學生的狀態與全班的危險警示。

每次辨識會拿到一小段連拍影像 (預設 5 張、間隔 0.4 秒)：
  * 靜態姿勢 (趴睡、轉頭、手機) 取多數決，降低單張誤判。
  * 連拍間的關鍵點位移用來估計動作幅度 (起身、揮手、打鬧)。
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from . import geometry as g
from .config import RuleConfig
from .types import (
    KP,
    Alert,
    BBox,
    FrameDetections,
    Person,
    Seat,
    SeatResult,
    Status,
    TickResult,
)

MOTION_KEYPOINTS = (KP.NOSE, KP.L_SHOULDER, KP.R_SHOULDER, KP.L_ELBOW, KP.R_ELBOW, KP.L_WRIST, KP.R_WRIST)


@dataclass
class Track:
    """同一個人在連拍影像中的軌跡。persons[i] 為第 i 張影像中的偵測結果 (或 None)。"""

    persons: list[Optional[Person]]
    seats: list[Optional[int]] = field(default_factory=list)

    def latest(self) -> Optional[Person]:
        for p in reversed(self.persons):
            if p is not None:
                return p
        return None

    def present(self) -> list[Person]:
        return [p for p in self.persons if p is not None]

    def seat(self) -> Optional[int]:
        votes = Counter(s for s in self.seats if s is not None)
        if not votes:
            return None
        idx, n = votes.most_common(1)[0]
        return idx if n * 2 >= len(self.present()) else None


def assign_seats(persons: list[Person], seats: list[Seat], ignore_zones: list[BBox]) -> list[Optional[int]]:
    """把每個人分配到一個座位 (一個座位最多一人)。回傳 persons 對應的座位索引，-1 表示在忽略區 (如講台)。"""
    result: list[Optional[int]] = [None] * len(persons)
    candidates: list[tuple[float, int, int]] = []
    for pi, p in enumerate(persons):
        a = g.anchor(p)
        if any(g.contains(z, a) for z in ignore_zones):
            result[pi] = -1
            continue
        for si, s in enumerate(seats):
            if not g.contains(s.bbox, a):
                continue
            overlap = g.intersection(p.bbox, s.bbox) / max(1.0, min(g.area(p.bbox), g.area(s.bbox)))
            # 錨點越接近座位中心越優先，避免相鄰座位框重疊時搶到隔壁同學
            sc = g.center(s.bbox)
            closeness = 1 - g.dist(a, sc) / max(1.0, (s.bbox[2] - s.bbox[0] + s.bbox[3] - s.bbox[1]) / 2)
            candidates.append((overlap + closeness, pi, si))
    taken_p, taken_s = set(), set()
    for _, pi, si in sorted(candidates, reverse=True):
        if pi in taken_p or si in taken_s:
            continue
        result[pi] = si
        taken_p.add(pi)
        taken_s.add(si)
    return result


def build_tracks(frames: list[FrameDetections], min_iou: float = 0.2) -> list[Track]:
    """以 IoU 貪婪配對把連拍中的人串成軌跡 (連拍間隔很短，IoU 足以應付)。"""
    n = len(frames)
    tracks: list[Track] = []
    for fi, fr in enumerate(frames):
        unmatched = set(range(len(fr.persons)))
        pairs = []
        for ti, t in enumerate(tracks):
            last = t.latest()
            if last is None:
                continue
            for pi in unmatched:
                v = g.iou(last.bbox, fr.persons[pi].bbox)
                if v >= min_iou:
                    pairs.append((v, ti, pi))
        used_t = set()
        for _, ti, pi in sorted(pairs, reverse=True):
            if ti in used_t or pi not in unmatched:
                continue
            tracks[ti].persons[fi] = fr.persons[pi]
            used_t.add(ti)
            unmatched.discard(pi)
        for pi in sorted(unmatched):
            persons: list[Optional[Person]] = [None] * n
            persons[fi] = fr.persons[pi]
            tracks.append(Track(persons=persons))
    return tracks


def motion_score(track: Track) -> float:
    """連拍間最大的動作幅度 (單位：肩寬)。"""
    best = 0.0
    prev: Optional[Person] = None
    for p in track.persons:
        if p is None:
            continue
        if prev is not None:
            scale = (g.body_scale(p) + g.body_scale(prev)) / 2
            moves = []
            for k in MOTION_KEYPOINTS:
                a, b = prev.kp(k), p.kp(k)
                if a and b:
                    moves.append(g.dist(a, b))
            if len(moves) >= 2:
                moves.sort()
                # 取第二大的位移，避免單一關鍵點跳動造成誤判
                m = moves[-2]
            else:
                m = g.dist(g.center(prev.bbox), g.center(p.bbox))
            best = max(best, m / scale)
        prev = p
    return best


def head_height(p: Person) -> Optional[float]:
    """(兩肩 y - 臉部 y) / 肩寬。抬頭坐正約 0.8~1.2，低頭看書約 0.3~0.7，趴在桌上 < 0.15。"""
    sm, sw = g.shoulder_mid(p), g.shoulder_width(p)
    if not sm or not sw:
        return None
    face = [p.kp(k) for k in (KP.NOSE, KP.L_EYE, KP.R_EYE)]
    face = [f for f in face if f]
    if not face:
        # 看得到雙肩但看不到臉：頭埋進手臂裡，或背對鏡頭
        ears = [p.kp(KP.L_EAR), p.kp(KP.R_EAR)]
        if not any(ears):
            return 0.0
        face = [e for e in ears if e]
    fy = sum(f[1] for f in face) / len(face)
    return (sm[1] - fy) / sw


def head_turn(p: Person) -> Optional[float]:
    """鼻子相對兩肩中點的水平偏移 / 肩寬 (正負代表左右)。"""
    sm, sw, nose = g.shoulder_mid(p), g.shoulder_width(p), p.kp(KP.NOSE)
    if not sm or not sw or not nose:
        return None
    return (nose[0] - sm[0]) / sw


def arms_raised(p: Person) -> bool:
    nose = p.kp(KP.NOSE) or g.shoulder_mid(p)
    if not nose:
        return False
    return any(w and w[1] < nose[1] for w in (p.kp(KP.L_WRIST), p.kp(KP.R_WRIST)))


def has_phone(p: Person, seat: Seat, frame: FrameDetections) -> bool:
    zone = g.expand(seat.bbox, 0.1)
    for o in frame.objects:
        if o.name != "cell phone":
            continue
        c = g.center(o.bbox)
        if not (g.contains(zone, c) or g.contains(p.bbox, c)):
            continue
        # 有看到手腕時，手機要在手附近才算 (排除放在桌角沒在用的手機)
        wrists = [w for w in (p.kp(KP.L_WRIST), p.kp(KP.R_WRIST)) if w]
        if wrists and min(g.dist(c, w) for w in wrists) > 1.5 * g.body_scale(p):
            continue
        return True
    return False


def _ratio(flags: list[bool]) -> float:
    return sum(flags) / len(flags) if flags else 0.0


def classify_seat(seat: Seat, track: Optional[Track], frames: list[FrameDetections], rules: RuleConfig) -> SeatResult:
    n = len(frames)
    if track is None or len(track.present()) / n < rules.presence_ratio:
        return SeatResult(seat.name, Status.ABSENT, "座位上沒有偵測到人")

    present = [(fi, p) for fi, p in enumerate(track.persons) if p is not None]
    latest = track.latest()
    assert latest is not None
    bbox = latest.bbox

    phone = _ratio([has_phone(p, seat, frames[fi]) for fi, p in present])
    if phone >= rules.phone_ratio:
        return SeatResult(seat.name, Status.PHONE, f"手上有手機 ({phone:.0%} 影像)", bbox)

    motion = motion_score(track)
    raised = _ratio([arms_raised(p) for _, p in present])
    if motion >= rules.active_motion:
        why = "手舉高且動作大" if raised >= 0.4 else "身體大幅移動"
        return SeatResult(seat.name, Status.ACTIVE, f"{why} (幅度 {motion:.1f})", bbox)

    heights = [h for h in (head_height(p) for _, p in present) if h is not None]
    if not heights:
        return SeatResult(seat.name, Status.UNKNOWN, "在座位上，但姿勢被遮擋", bbox)

    sleeping = _ratio([h < rules.sleep_head_height for h in heights])
    if sleeping >= rules.sleep_ratio:
        return SeatResult(seat.name, Status.SLEEPING, "頭部低於肩膀 / 埋在手臂中", bbox)

    turns = [t for t in (head_turn(p) for _, p in present) if t is not None]
    turned = _ratio([abs(t) > rules.turn_head_offset for t in turns])
    if turns and turned >= rules.distracted_ratio:
        side = "右" if sum(turns) > 0 else "左"
        return SeatResult(seat.name, Status.DISTRACTED, f"頭轉向畫面{side}側", bbox)

    book = any(
        o.name in ("book", "laptop") and g.contains(g.expand(seat.bbox, 0.1), g.center(o.bbox))
        for fi, _ in present
        for o in frames[fi].objects
    )
    posture = "坐姿端正" if sorted(heights)[len(heights) // 2] >= 0.75 else "低頭閱讀 / 書寫"
    return SeatResult(seat.name, Status.FOCUSED, posture + ("，桌上有書本" if book else ""), bbox)


def _neighbors(a: BBox, b: BBox) -> bool:
    """兩個座位框是否相鄰 (中心距離小於 1.6 個座位寬)。"""
    w = ((a[2] - a[0]) + (b[2] - b[0])) / 2
    return g.dist(g.center(a), g.center(b)) < 1.6 * w


def class_alerts(
    tracks: list[Track],
    seat_of: dict[int, int],
    seats: list[Seat],
    results: list[SeatResult],
    frames: list[FrameDetections],
    rules: RuleConfig,
) -> list[Alert]:
    n = len(frames)
    alerts: list[Alert] = []
    motions = {ti: motion_score(t) for ti, t in enumerate(tracks)}

    # 1. 離開座位、在走道上走動的人 (不含忽略區，例如講台上的老師)
    wanderers = [
        ti for ti, t in enumerate(tracks)
        if ti not in seat_of and -1 not in t.seats and len(t.present()) / n >= rules.wander_ratio
    ]
    if wanderers:
        alerts.append(Alert("wandering", f"有 {len(wanderers)} 人離開座位在走道活動", "warning"))

    # 2. 疑似跌倒：不在座位上、身體呈橫躺
    for ti in wanderers:
        p = tracks[ti].latest()
        assert p is not None
        w, h = p.bbox[2] - p.bbox[0], p.bbox[3] - p.bbox[1]
        sm = g.shoulder_mid(p)
        hips = [x for x in (p.kp(KP.L_HIP), p.kp(KP.R_HIP)) if x]
        horizontal = bool(sm and hips and abs(sm[1] - hips[0][1]) < 0.5 * abs(sm[0] - hips[0][0]))
        if h > 0 and w / h >= rules.fall_aspect and (horizontal or not hips):
            alerts.append(Alert("fall", "疑似有人跌倒 / 倒地", "danger", p.bbox))

    # 3. 疑似打鬧 / 肢體衝突：兩人距離很近，且至少一人動作很大
    active = [ti for ti, t in enumerate(tracks) if t.latest() is not None and -1 not in t.seats]
    reported: set[tuple[int, int]] = set()
    for i, a in enumerate(active):
        for b in active[i + 1:]:
            pa, pb = tracks[a].latest(), tracks[b].latest()
            assert pa and pb
            scale = (g.body_scale(pa) + g.body_scale(pb)) / 2
            d = g.dist(g.anchor(pa), g.anchor(pb)) / scale
            if d > rules.fight_distance or max(motions[a], motions[b]) < rules.fight_motion:
                continue
            # 兩位都在自己座位上，且只有一位在動 → 交給座位層級的「動作過大」即可
            if a in seat_of and b in seat_of and min(motions[a], motions[b]) < rules.active_motion:
                continue
            box = (min(pa.bbox[0], pb.bbox[0]), min(pa.bbox[1], pb.bbox[1]),
                   max(pa.bbox[2], pb.bbox[2]), max(pa.bbox[3], pb.bbox[3]))
            names = [seats[seat_of[x]].name for x in (a, b) if x in seat_of]
            who = "、".join(names) if names else "走道上的學生"
            alerts.append(Alert("fighting", f"疑似打鬧 / 肢體衝突：{who}", "danger", box))
            reported.add((a, b))

    # 4. 相鄰座位同時動作過大 (未被第 3 點涵蓋時)
    active_seats = [i for i, r in enumerate(results) if r.status == Status.ACTIVE]
    if not reported:
        for i, a in enumerate(active_seats):
            for b in active_seats[i + 1:]:
                if _neighbors(seats[a].bbox, seats[b].bbox):
                    alerts.append(Alert(
                        "fighting", f"相鄰座位同時有大動作：{seats[a].name}、{seats[b].name}", "danger"))
    return alerts


def classify(
    frames: list[FrameDetections],
    seats: list[Seat],
    rules: RuleConfig,
    ignore_zones: Optional[list[BBox]] = None,
    timestamp: Optional[float] = None,
) -> TickResult:
    if not frames:
        raise ValueError("frames 不可為空")
    ignore_zones = ignore_zones or []
    tracks = build_tracks(frames)
    for fi, fr in enumerate(frames):
        assigned = assign_seats(fr.persons, seats, ignore_zones)
        for pi, si in enumerate(assigned):
            for t in tracks:
                if t.persons[fi] is fr.persons[pi]:
                    t.seats.append(si)
                    break

    # 每個座位挑出在該座位出現最多次的軌跡
    seat_of: dict[int, int] = {}
    best: dict[int, tuple[int, int]] = {}
    for ti, t in enumerate(tracks):
        s = t.seat()
        if s is None or s < 0:
            continue
        cnt = len(t.present())
        if s not in best or cnt > best[s][1]:
            best[s] = (ti, cnt)
    for s, (ti, _) in best.items():
        seat_of[ti] = s
    track_for_seat = {s: tracks[ti] for s, (ti, _) in best.items()}

    results = [classify_seat(seat, track_for_seat.get(i), frames, rules) for i, seat in enumerate(seats)]
    alerts = class_alerts(tracks, seat_of, seats, results, frames, rules)
    return TickResult(timestamp=timestamp or time.time(), seats=results, alerts=alerts)
