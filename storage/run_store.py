"""Saved run history (local database file). Passwords and secret keys are never saved here."""
from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  started_at REAL, ended_at REAL,
  state TEXT, target_url TEXT,
  questions_done INTEGER DEFAULT 0,
  model_calls INTEGER DEFAULT 0,
  model_latency_total REAL DEFAULT 0,
  errors TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS steps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT, ts REAL, state TEXT,
  question_id TEXT, question_text TEXT,
  answer TEXT, action TEXT,
  verification TEXT, retries INTEGER DEFAULT 0,
  error TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS finished_sections (
  course TEXT, section TEXT, finished_at REAL,
  PRIMARY KEY (course, section)
);
"""


def course_key_for_url(url: str) -> str:
    """Stable course identifier for an outline address.

    Course outline addresses carry a class-course number after the P14_ID
    marker (it survives session/checksum rotations, unlike the full address).
    Plain addresses without one fall back to the full address itself, so
    local practice pages still get a steady bucket.
    """
    m = re.search(r"P14_ID[^:]*:(\d+)", url or "")
    if m:
        return m.group(1)
    base = (url or "").split("#")[0]
    return base if base else ""


class RunStore:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def create_run(self, target_url: str) -> str:
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        self._conn.execute(
            "INSERT INTO runs (run_id, started_at, state, target_url) VALUES (?,?,?,?)",
            (run_id, time.time(), "INITIALIZE", target_url))
        self._conn.commit()
        return run_id

    def log_step(self, run_id: str, state: str, question_id: str = "",
                 question_text: str = "", answer: str = "", action: str = "",
                 verification: str = "", retries: int = 0, error: str = "") -> None:
        self._conn.execute(
            "INSERT INTO steps (run_id, ts, state, question_id, question_text, answer, action, verification, retries, error)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (run_id, time.time(), state, question_id or "", (question_text or "")[:2000],
             (answer or "")[:1000], (action or "")[:500], (verification or "")[:500], retries, (error or "")[:1000]))
        self._conn.commit()

    def finish_run(self, run_id: str, state: str, questions_done: int = 0,
                   model_calls: int = 0, latency: float = 0.0, errors: str = "") -> None:
        self._conn.execute(
            "UPDATE runs SET ended_at=?, state=?, questions_done=?, model_calls=?, model_latency_total=?, errors=? WHERE run_id=?",
            (time.time(), state, questions_done, model_calls, latency, (errors or "")[:2000], run_id))
        self._conn.commit()

    def summary(self, run_id: str) -> dict:
        cur = self._conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,))
        row = cur.fetchone()
        cols = [d[0] for d in cur.description] if cur.description else []
        run = dict(zip(cols, row)) if row else {}
        cur2 = self._conn.execute("SELECT state, question_id, answer, action, verification, error FROM steps WHERE run_id=? ORDER BY id", (run_id,))
        run["steps"] = [dict(zip(["state", "question_id", "answer", "action", "verification", "error"], r)) for r in cur2.fetchall()]
        return run

    def record_finished_section(self, course: str, section: str) -> None:
        """Remember a finished course section (by outline entry name)."""
        if not course or not section:
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO finished_sections (course, section, finished_at) VALUES (?,?,?)",
            (course, section, time.time()))
        self._conn.commit()

    def finished_sections(self, course: str) -> dict[str, float]:
        """Finished sections for one course: {name: finished_at}."""
        if not course:
            return {}
        cur = self._conn.execute(
            "SELECT section, finished_at FROM finished_sections WHERE course=?", (course,))
        return {row[0]: row[1] for row in cur.fetchall()}

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
