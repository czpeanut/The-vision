"""網頁介面：框選座位、即時看板、課後報表。"""

from __future__ import annotations

import csv
import io
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import cv2
from flask import Flask, Response, abort, jsonify, render_template, request, send_from_directory

from ..camera import Camera
from ..config import AppConfig
from ..detector import Detector
from ..monitor import Monitor
from ..storage import Layout, Store
from ..types import STATUS_LABELS, Status

STATUS_META = [{"value": s.value, "label": STATUS_LABELS[s]} for s in Status]


def create_app(cfg: AppConfig, camera: Optional[Camera] = None,
               detector_factory: Optional[Callable[[], Detector]] = None) -> Flask:
    app = Flask(__name__)
    data = cfg.data_path
    layout_path = data / "layout.json"
    store = Store(data / "vision.db")
    camera = camera or Camera(cfg.camera.source)

    if detector_factory is None:
        def detector_factory() -> Detector:
            from ..detector import YoloDetector
            return YoloDetector(cfg.detector)

    monitor = Monitor(cfg, camera, store, detector_factory)
    app.config["monitor"] = monitor
    app.config["store"] = store

    @app.context_processor
    def inject():
        return {"statuses": STATUS_META, "interval": cfg.interval_sec}

    # ---------- 頁面 ----------
    @app.get("/")
    def dashboard():
        return render_template("dashboard.html")

    @app.get("/setup")
    def setup():
        return render_template("setup.html")

    @app.get("/reports")
    def reports():
        return render_template("reports.html", sessions=store.sessions(), fmt=_fmt_time)

    @app.get("/report/<int:sid>")
    def report(sid: int):
        sess = store.session(sid) or abort(404)
        return render_template("report.html", session=sess, fmt=_fmt_time)

    # ---------- API ----------
    @app.get("/api/frame.jpg")
    def frame():
        f = camera.read()
        if f is None:
            return Response("無法取得監視器畫面", status=503)
        ok, buf = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return Response(buf.tobytes(), mimetype="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/api/layout")
    def get_layout():
        return jsonify(Layout.load(layout_path).to_dict())

    @app.post("/api/layout")
    def save_layout():
        if monitor.running:
            return jsonify(error="監看中無法修改座位，請先結束本堂課"), 409
        try:
            layout = Layout.from_dict(request.get_json(force=True))
        except (KeyError, TypeError, ValueError) as e:
            return jsonify(error=f"格式錯誤：{e}"), 400
        names = [s.name.strip() for s in layout.seats]
        if any(not n for n in names):
            return jsonify(error="每個座位都要填學生姓名"), 400
        if len(set(names)) != len(names):
            return jsonify(error="學生姓名重複"), 400
        layout.save(layout_path)
        return jsonify(ok=True, seats=len(layout.seats))

    @app.post("/api/session/start")
    def start():
        body = request.get_json(silent=True) or {}
        title = (body.get("title") or "").strip() or datetime.now().strftime("%Y-%m-%d %H:%M 自習課")
        try:
            sid = monitor.start(title, Layout.load(layout_path))
        except (RuntimeError, ValueError) as e:
            return jsonify(error=str(e)), 400
        return jsonify(ok=True, session_id=sid)

    @app.post("/api/session/stop")
    def stop():
        sid = monitor.session_id
        monitor.stop()
        return jsonify(ok=True, session_id=sid)

    @app.get("/api/status")
    def status():
        sid = monitor.session_id
        return jsonify(
            running=monitor.running,
            session_id=sid,
            session=store.session(sid) if sid else None,
            latest=monitor.latest,
            error=monitor.error,
            next_tick_in=max(0, monitor.next_tick_at - time.time()) if monitor.next_tick_at else None,
            layout=monitor.layout.to_dict() if monitor.layout else Layout.load(layout_path).to_dict(),
            summary=store.summary(sid) if sid else [],
            alerts=store.alerts(sid)[-30:] if sid else [],
        )

    @app.post("/api/alerts/<int:aid>/ack")
    def ack(aid: int):
        store.acknowledge(aid)
        return jsonify(ok=True)

    @app.get("/api/report/<int:sid>")
    def report_json(sid: int):
        sess = store.session(sid) or abort(404)
        return jsonify(
            session=sess | {"layout": json.loads(sess["layout"])},
            summary=store.summary(sid),
            observations=store.observations(sid),
            alerts=store.alerts(sid),
        )

    @app.get("/report/<int:sid>.csv")
    def report_csv(sid: int):
        sess = store.session(sid) or abort(404)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["學生", "專注度(%)", "辨識次數"] + [m["label"] for m in STATUS_META])
        for row in store.summary(sid):
            w.writerow([row["student"], row["focus_score"] if row["focus_score"] is not None else "", row["total"]]
                       + [row["counts"].get(m["value"], 0) for m in STATUS_META])
        w.writerow([])
        w.writerow(["時間", "學生", "狀態", "原因"])
        for o in store.observations(sid):
            w.writerow([_fmt_time(o["ts"]), o["student"], STATUS_LABELS[Status(o["status"])], o["reason"]])
        w.writerow([])
        w.writerow(["時間", "警示等級", "內容"])
        for a in store.alerts(sid):
            w.writerow([_fmt_time(a["ts"]), a["level"], a["message"]])
        name = f"report_{sid}.csv"
        # 加上 BOM 讓 Excel 正確顯示中文
        return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={name}"})

    @app.get("/snapshots/<int:sid>/<path:name>")
    def snapshot(sid: int, name: str):
        d = Path(data / "snapshots" / str(sid)).resolve()
        return send_from_directory(d, name, max_age=0)

    return app


def _fmt_time(ts: Optional[float]) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "—"
