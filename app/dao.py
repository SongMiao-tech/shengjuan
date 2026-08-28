# -*- coding: utf-8 -*-
"""数据访问层（DAO）：sqlite3 封装，各表基础 CRUD
用法:
    from app import dao
    dao.init_db()
    dao.voice_dao.insert(Voice(None, "S_xxx", "我的声音", "clone"))
    voices = dao.voice_dao.list_all()
"""
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from .models import User, Voice, Task, Work

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "shengjuan.db"
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """建表（幂等）+ 空表时插入测试数据"""
    db_dir = DB_PATH.parent
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        conn.executescript((db_dir / "schema.sql").read_text(encoding="utf-8"))
        if conn.execute("SELECT COUNT(*) FROM voices").fetchone()[0] == 0:
            conn.executescript((db_dir / "seed.sql").read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def _rows(cls, rows):
    return [cls(**dict(r)) for r in rows]


# ---------- Voice ----------
class VoiceDAO:
    def insert(self, v: Voice) -> int:
        with _lock, _connect() as c:
            cur = c.execute(
                "INSERT INTO voices (speaker_id, name, type, provider, gender, note) VALUES (?,?,?,?,?,?)",
                (v.speaker_id, v.name, v.type, v.provider, v.gender, v.note))
            return cur.lastrowid

    def get_by_speaker(self, speaker_id: str) -> Optional[Voice]:
        with _connect() as c:
            r = c.execute("SELECT * FROM voices WHERE speaker_id=?", (speaker_id,)).fetchone()
            return Voice(**dict(r)) if r else None

    def list_all(self, type_filter: str = None) -> list[Voice]:
        with _connect() as c:
            if type_filter:
                rows = c.execute("SELECT * FROM voices WHERE type=? ORDER BY created_at DESC", (type_filter,)).fetchall()
            else:
                rows = c.execute("SELECT * FROM voices ORDER BY created_at DESC").fetchall()
            return _rows(Voice, rows)

    def update_name(self, speaker_id: str, name: str):
        with _lock, _connect() as c:
            c.execute("UPDATE voices SET name=? WHERE speaker_id=?", (name, speaker_id))

    def delete(self, speaker_id: str):
        with _lock, _connect() as c:
            c.execute("DELETE FROM voices WHERE speaker_id=?", (speaker_id,))


# ---------- Task ----------
class TaskDAO:
    def upsert(self, t: Task) -> int:
        with _lock, _connect() as c:
            r = c.execute("SELECT id FROM tasks WHERE task_id=?", (t.task_id,)).fetchone()
            if r:
                c.execute("""UPDATE tasks SET status=?, segments_json=?, duration_s=?, error=? WHERE task_id=?""",
                          (t.status, t.segments_json, t.duration_s, t.error, t.task_id))
                return r["id"]
            cur = c.execute(
                "INSERT INTO tasks (task_id, text_len, narrator, use_bgm, status, segments_json, duration_s, error) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (t.task_id, t.text_len, t.narrator, int(t.use_bgm), t.status,
                 t.segments_json, t.duration_s, t.error))
            return cur.lastrowid

    def get(self, task_id: str) -> Optional[Task]:
        with _connect() as c:
            r = c.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            return Task(**dict(r)) if r else None

    def list_recent(self, limit: int = 20) -> list[Task]:
        with _connect() as c:
            rows = c.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return _rows(Task, rows)


# ---------- Work ----------
class WorkDAO:
    def insert(self, w: Work) -> int:
        with _lock, _connect() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO works (task_id, title, audio_path, duration_s, bgm_name) VALUES (?,?,?,?,?)",
                (w.task_id, w.title, w.audio_path, w.duration_s, w.bgm_name))
            return cur.lastrowid

    def get(self, task_id: str) -> Optional[Work]:
        with _connect() as c:
            r = c.execute("SELECT * FROM works WHERE task_id=?", (task_id,)).fetchone()
            return Work(**dict(r)) if r else None

    def list_recent(self, limit: int = 50) -> list[Work]:
        with _connect() as c:
            rows = c.execute("SELECT * FROM works ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return _rows(Work, rows)


# ---------- User ----------
class UserDAO:
    def get_by_username(self, username: str) -> Optional[User]:
        with _connect() as c:
            r = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            return User(**dict(r)) if r else None


voice_dao = VoiceDAO()
task_dao = TaskDAO()
work_dao = WorkDAO()
user_dao = UserDAO()


if __name__ == "__main__":
    init_db()
    print("预置音色:", [v.name for v in voice_dao.list_all()])
    print("最近作品:", [(w.title, w.duration_s) for w in work_dao.list_recent(5)])
