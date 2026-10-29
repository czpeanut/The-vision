"""SQLite 紀錄：座位設定、每次辨識結果、警示。"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .types import BBox, Seat, Status, TickResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    started_at REAL NOT NULL,
    ended_at REAL,
    layout TEXT NOT NULL            -- 開始時的座位設定 (JSON)
);
CREATE TABLE IF NOT EXISTS observations (
    session_id INTEGER NOT NULL,
    ts REAL NOT NULL,
    student TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT,
    snapshot TEXT
);
CREATE INDEX IF NOT EXISTS idx_obs_session ON observations(session_id, student, ts);
CREATE TABLE IF NOT EXISTS alerts (
    session_id INTEGER NOT NULL,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    snapshot TEXT,
    acknowledged INTEGER NOT NULL DEFAULT 0
);
"""


class Layout:
    """老師框好的座位與忽略區，存成 JSON 檔以便下一堂課直接沿用。"""

    def __init__(self, seats: list[Seat], ignore_zones: list[BBox], frame_size: Optional[tuple[int, int]] = None):
        self.seats = seats
        self.ignore_zones = ignore_zones
        self.frame_size = frame_size

    def to_dict(self) -> dict[str, Any]:
        return {
            "seats": [{"name": s.name, "bbox": list(s.bbox)} for s in self.seats],
            "ignore_zones": [list(z) for z in self.ignore_zones],
            "frame_size": list(self.frame_size) if self.frame_size else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Layout":
        return cls(
            seats=[Seat(s["name"], tuple(s["bbox"])) for s in d.get("seats", [])],
            ignore_zones=[tuple(z) for z in d.get("ignore_zones", [])],
            frame_size=tuple(d["frame_size"]) if d.get("frame_size") else None,
        )

    @classmethod
    def load(cls, path: Path) -> "Layout":
        if not path.exists():
            return cls([], [])
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


class Store:
    def __init__(self, path: Path):
        self._lock = threading.Lock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur

    def _query(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def start_session(self, title: str, layout: Layout) -> int:
        cur = self._exec(
            "INSERT INTO sessions(title, started_at, layout) VALUES (?, ?, ?)",
            (title, time.time(), json.dumps(layout.to_dict(), ensure_ascii=False)),
        )
        return int(cur.lastrowid)

    def end_session(self, session_id: int) -> None:
        self._exec("UPDATE sessions SET ended_at=? WHERE id=? AND ended_at IS NULL", (time.time(), session_id))

    def add_tick(self, session_id: int, tick: TickResult, snapshot: Optional[str]) -> None:
        with self._lock:
            self.db.executemany(
                "INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?)",
                [(session_id, tick.timestamp, s.name, s.status.value, s.reason, snapshot) for s in tick.seats],
            )
            self.db.executemany(
                "INSERT INTO alerts(session_id, ts, kind, level, message, snapshot) VALUES (?, ?, ?, ?, ?, ?)",
                [(session_id, tick.timestamp, a.kind, a.level, a.message, snapshot) for a in tick.alerts],
            )
            self.db.commit()

    def sessions(self) -> list[dict[str, Any]]:
        return self._query("SELECT * FROM sessions ORDER BY id DESC")

    def session(self, session_id: int) -> Optional[dict[str, Any]]:
        rows = self._query("SELECT * FROM sessions WHERE id=?", (session_id,))
        return rows[0] if rows else None

    def observations(self, session_id: int) -> list[dict[str, Any]]:
        return self._query("SELECT * FROM observations WHERE session_id=? ORDER BY ts", (session_id,))

    def alerts(self, session_id: int) -> list[dict[str, Any]]:
        return self._query("SELECT rowid AS id, * FROM alerts WHERE session_id=? ORDER BY ts", (session_id,))

    def acknowledge(self, alert_id: int) -> None:
        self._exec("UPDATE alerts SET acknowledged=1 WHERE rowid=?", (alert_id,))

    def summary(self, session_id: int) -> list[dict[str, Any]]:
        """每位學生各狀態所佔的次數與比例，以及專注度分數。"""
        sess = self.session(session_id)
        if not sess:
            return []
        order = [s["name"] for s in json.loads(sess["layout"])["seats"]]
        counts: dict[str, dict[str, int]] = {n: {} for n in order}
        for r in self._query(
            "SELECT student, status, COUNT(*) AS n FROM observations WHERE session_id=? GROUP BY student, status",
            (session_id,),
        ):
            counts.setdefault(r["student"], {})[r["status"]] = r["n"]
        out = []
        for name, c in counts.items():
            total = sum(c.values())
            judged = total - c.get(Status.UNKNOWN.value, 0)
            row = {"student": name, "total": total, "counts": c,
                   "ratios": {k: v / total for k, v in c.items()} if total else {}}
            row["focus_score"] = round(100 * c.get(Status.FOCUSED.value, 0) / judged) if judged else None
            out.append(row)
        return out
