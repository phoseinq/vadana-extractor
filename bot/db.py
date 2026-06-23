from __future__ import annotations

import os
import sqlite3
import threading
import time

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

def init(path: str) -> None:
    global _conn
    fresh = not os.path.exists(path)
    _conn = sqlite3.connect(path, check_same_thread=False)
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA busy_timeout=4000")
    _conn.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            uid       INTEGER PRIMARY KEY,
            username  TEXT,
            name      TEXT,
            first_ts  INTEGER,
            last_ts   INTEGER,
            banned    INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS links(
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            uid     INTEGER,
            rec_id  TEXT,
            host    TEXT,
            token   TEXT,
            mode    TEXT,
            ok      INTEGER,
            ts      INTEGER);
        CREATE INDEX IF NOT EXISTS links_uid_ts ON links(uid, ts);
    """)
    _conn.commit()
    if fresh:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

def touch_user(uid: int, username: str | None, name: str | None) -> None:
    """Record/refresh a user on every interaction (keeps username/name current)."""
    now = int(time.time())
    with _lock:
        _conn.execute(
            "INSERT INTO users(uid,username,name,first_ts,last_ts) VALUES(?,?,?,?,?) "
            "ON CONFLICT(uid) DO UPDATE SET username=excluded.username, "
            "name=excluded.name, last_ts=excluded.last_ts",
            (uid, username or "", name or "", now, now))
        _conn.commit()

def add_link(uid: int, rec_id: str, host: str, token: str | None, mode: str, ok: bool) -> None:
    with _lock:
        _conn.execute(
            "INSERT INTO links(uid,rec_id,host,token,mode,ok,ts) VALUES(?,?,?,?,?,?,?)",
            (uid, rec_id, host or "", token or "", mode, 1 if ok else 0, int(time.time())))
        _conn.commit()

def set_ban(uid: int, banned: bool) -> None:
    now = int(time.time())
    with _lock:
        _conn.execute(
            "INSERT INTO users(uid,first_ts,last_ts,banned) VALUES(?,?,?,?) "
            "ON CONFLICT(uid) DO UPDATE SET banned=excluded.banned",
            (uid, now, now, 1 if banned else 0))
        _conn.commit()

def is_banned(uid: int) -> bool:
    with _lock:
        r = _conn.execute("SELECT banned FROM users WHERE uid=?", (uid,)).fetchone()
    return bool(r and r[0])

def get_user(uid: int) -> dict | None:
    with _lock:
        r = _conn.execute(
            "SELECT uid,username,name,first_ts,last_ts,banned FROM users WHERE uid=?",
            (uid,)).fetchone()
        cnt = _conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(ok),0) FROM links WHERE uid=?", (uid,)).fetchone()
    if not r:
        return None
    return {"uid": r[0], "username": r[1], "name": r[2], "first_ts": r[3],
            "last_ts": r[4], "banned": bool(r[5]), "links": cnt[0], "ok": cnt[1]}

def recent_links(uid: int, n: int = 5) -> list[dict]:
    with _lock:
        rows = _conn.execute(
            "SELECT rec_id,host,token,mode,ok,ts FROM links WHERE uid=? ORDER BY ts DESC LIMIT ?",
            (uid, n)).fetchall()
    return [{"rec_id": x[0], "host": x[1], "token": x[2], "mode": x[3],
             "ok": bool(x[4]), "ts": x[5]} for x in rows]

def search_users(q: str, n: int = 12) -> list[dict]:
    """Match by numeric id prefix, or @username / name substring (case-insensitive)."""
    q = (q or "").strip().lstrip("@")
    with _lock:
        if q.isdigit():
            rows = _conn.execute(
                "SELECT uid,username,name,banned FROM users WHERE CAST(uid AS TEXT) LIKE ? "
                "ORDER BY last_ts DESC LIMIT ?", (q + "%", n)).fetchall()
        elif q:
            like = "%" + q + "%"
            rows = _conn.execute(
                "SELECT uid,username,name,banned FROM users WHERE username LIKE ? OR name LIKE ? "
                "ORDER BY last_ts DESC LIMIT ?", (like, like, n)).fetchall()
        else:
            rows = _conn.execute(
                "SELECT uid,username,name,banned FROM users ORDER BY last_ts DESC LIMIT ?",
                (n,)).fetchall()
    return [{"uid": x[0], "username": x[1], "name": x[2], "banned": bool(x[3])} for x in rows]

def stats() -> dict:
    with _lock:
        u = _conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        ln = _conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
        b = _conn.execute("SELECT COUNT(*) FROM users WHERE banned=1").fetchone()[0]
    return {"users": u, "links": ln, "banned": b}

def _demo() -> None:
    import tempfile
    p = os.path.join(tempfile.mkdtemp(), "t.db")
    init(p)
    touch_user(7, "swan", "🦢")
    add_link(7, "lk9l06g01mos", "https://vadavc30.ec.iau.ir", "abc123", "video", False)
    add_link(7, "l92cnur34luk", "https://vadavc30.ec.iau.ir", "xy", "video", True)
    u = get_user(7)
    assert u["uid"] == 7 and u["username"] == "swan" and u["links"] == 2 and u["ok"] == 1, u
    assert recent_links(7)[0]["rec_id"] == "l92cnur34luk"
    assert search_users("swan")[0]["uid"] == 7
    assert search_users("7")[0]["uid"] == 7
    set_ban(7, True)
    assert is_banned(7) is True
    set_ban(7, False)
    assert is_banned(7) is False
    print("db ok:", stats())

if __name__ == "__main__":
    _demo()
