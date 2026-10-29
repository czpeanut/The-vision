"""用錄好的教室影片離線跑一次辨識，方便調整門檻。

    python -m the_vision.tools.replay 影片.mp4 --layout data/layout.json [--out result.csv] [--debug]

依影片時間每 interval_sec 秒取一段連拍，輸出每位學生的狀態。--debug 會額外印出
頭部高度、轉頭幅度、動作幅度等原始數值，對照實際畫面就能知道門檻該往哪調。
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import cv2

from ..classifier import build_tracks, head_height, head_turn, motion_score
from ..classifier import classify
from ..config import load_config
from ..detector import YoloDetector
from ..storage import Layout


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--layout", default="data/layout.json")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--out")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config)
    layout = Layout.load(Path(args.layout))
    if not layout.seats:
        sys.exit(f"{args.layout} 沒有座位設定，請先在網頁上框選並儲存")

    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    det = YoloDetector(cfg.detector)

    writer = None
    if args.out:
        fh = open(args.out, "w", newline="", encoding="utf-8-sig")
        writer = csv.writer(fh)
        writer.writerow(["秒數", "學生", "狀態", "原因"])

    t = 0.0
    while t < total:
        frames = []
        for i in range(cfg.camera.burst_frames):
            cap.set(cv2.CAP_PROP_POS_MSEC, (t + i * cfg.camera.burst_interval_sec) * 1000)
            ok, f = cap.read()
            if ok:
                frames.append(f)
        if not frames:
            break
        dets = [det.detect(f) for f in frames]
        tick = classify(dets, layout.seats, cfg.rules, layout.ignore_zones, timestamp=t)
        print(f"\n=== {int(t // 60):02d}:{int(t % 60):02d} ===")
        for s in tick.seats:
            print(f"  {s.name:<8} {s.status.label:<6} {s.reason}")
            if writer:
                writer.writerow([round(t, 1), s.name, s.status.label, s.reason])
        for a in tick.alerts:
            print(f"  ⚠ [{a.level}] {a.message}")
        if args.debug:
            for tr in build_tracks(dets):
                p = tr.latest()
                hh, ht = head_height(p), head_turn(p)
                print(f"    人物 bbox={tuple(round(v) for v in p.bbox)} 頭高={hh and round(hh, 2)} "
                      f"轉頭={ht and round(ht, 2)} 動作={round(motion_score(tr), 2)}")
        t += cfg.interval_sec


if __name__ == "__main__":
    main()
