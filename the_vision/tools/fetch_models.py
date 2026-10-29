"""在有網路的電腦上預先下載模型，之後教室電腦即可完全離線執行。

    python -m the_vision.tools.fetch_models [--config config.yaml]

下載完成後，把整個 models/ 資料夾複製到教室電腦的專案目錄即可。
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from ..config import load_config


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()
    cfg = load_config(args.config)

    from ultralytics import YOLO

    for target in (cfg.detector.pose_model, cfg.detector.object_model):
        dest = Path(target)
        if dest.exists():
            print(f"已存在：{dest}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        model = YOLO(dest.name)  # ultralytics 依檔名從官方來源下載到目前目錄
        src = Path(model.ckpt_path)
        if src.resolve() != dest.resolve():
            shutil.move(str(src), dest)
        print(f"已下載：{dest} ({dest.stat().st_size / 1e6:.1f} MB)")
    print("完成。把 models/ 資料夾複製到教室電腦即可離線使用。")


if __name__ == "__main__":
    main()
