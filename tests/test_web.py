import time

import numpy as np
import pytest

from the_vision.config import AppConfig
from the_vision.types import FrameDetections
from the_vision.web.app import create_app

from .helpers import SEATS, person, phone_near, seat_center


class FakeCamera:
    def read(self, timeout=10.0):
        return np.zeros((480, 640, 3), np.uint8)

    def burst(self, n, interval):
        return [self.read() for _ in range(n)]


class FakeDetector:
    def detect(self, frame):
        p = person(*seat_center("S00"))
        return FrameDetections([p, person(*seat_center("S01"), head=-0.2)], [phone_near(p)])


@pytest.fixture
def client(tmp_path):
    cfg = AppConfig(data_dir=str(tmp_path), interval_sec=3600, save_snapshots="all")
    app = create_app(cfg, camera=FakeCamera(), detector_factory=FakeDetector)
    app.testing = True
    with app.test_client() as c:
        yield c
    app.config["monitor"].stop()


def save_layout(client):
    body = {"seats": [{"name": s.name, "bbox": list(s.bbox)} for s in SEATS[:3]], "ignore_zones": []}
    return client.post("/api/layout", json=body)


def test_pages_render(client):
    for path in ("/", "/setup", "/reports"):
        assert client.get(path).status_code == 200


def test_frame_endpoint(client):
    r = client.get("/api/frame.jpg")
    assert r.status_code == 200 and r.mimetype == "image/jpeg"


def test_layout_validation(client):
    r = client.post("/api/layout", json={"seats": [{"name": "", "bbox": [0, 0, 1, 1]}]})
    assert r.status_code == 400
    r = client.post("/api/layout", json={"seats": [{"name": "A", "bbox": [0, 0, 1, 1]},
                                                   {"name": "A", "bbox": [2, 2, 3, 3]}]})
    assert r.status_code == 400
    assert save_layout(client).get_json()["seats"] == 3
    assert len(client.get("/api/layout").get_json()["seats"]) == 3


def test_start_requires_layout(client):
    assert client.post("/api/session/start", json={}).status_code == 400


def test_full_session(client):
    save_layout(client)
    sid = client.post("/api/session/start", json={"title": "測試課"}).get_json()["session_id"]
    for _ in range(100):
        st = client.get("/api/status").get_json()
        if st["latest"]:
            break
        time.sleep(0.05)
    statuses = {s["name"]: s["status"] for s in st["latest"]["seats"]}
    assert statuses == {"S00": "phone", "S01": "sleeping", "S02": "absent"}
    assert client.post("/api/layout", json={"seats": []}).status_code == 409

    client.post("/api/session/stop")
    rep = client.get(f"/api/report/{sid}").get_json()
    assert rep["session"]["ended_at"] is not None
    assert {s["student"]: s["focus_score"] for s in rep["summary"]} == {"S00": 0, "S01": 0, "S02": 0}
    assert client.get(f"/report/{sid}").status_code == 200
    csv = client.get(f"/report/{sid}.csv").get_data(as_text=True)
    assert "玩手機" in csv and "趴睡" in csv
    snap = st["latest"]["snapshot"]
    assert client.get(f"/snapshots/{sid}/{snap}").status_code == 200
    assert client.get(f"/snapshots/{sid}/../../vision.db").status_code == 404


class WandererDetector:
    def detect(self, frame):
        return FrameDetections([person(*seat_center("S00")), person(700, 300)], [])


def test_repeated_alert_is_logged_once(tmp_path):
    cfg = AppConfig(data_dir=str(tmp_path), interval_sec=3600, alert_cooldown_sec=120)
    app = create_app(cfg, camera=FakeCamera(), detector_factory=WandererDetector)
    monitor, store = app.config["monitor"], app.config["store"]
    with app.test_client() as c:
        save_layout(c)
        from the_vision.storage import Layout
        monitor.layout = Layout.load(tmp_path / "layout.json")
        monitor.session_id = store.start_session("t", monitor.layout)
        monitor.tick()
        monitor.tick()
        assert [a["kind"] for a in store.alerts(monitor.session_id)] == ["wandering"]
        assert monitor.latest["alerts"][0]["kind"] == "wandering"  # 即時畫面仍顯示
