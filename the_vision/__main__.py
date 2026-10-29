"""啟動網頁伺服器：python -m the_vision [--config config.yaml]"""

from __future__ import annotations

import argparse
import logging

from .config import load_config
from .web.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="自習課學生讀書狀況辨識系統")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--source", help="覆寫影像來源 (RTSP 網址 / 攝影機編號 / 影片檔)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    if args.source:
        cfg.camera.source = args.source
    app = create_app(cfg)
    print(f"開啟瀏覽器：http://localhost:{cfg.port}")
    app.run(host=cfg.host, port=cfg.port, threaded=True)


if __name__ == "__main__":
    main()
