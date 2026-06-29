import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "store" / "reminders.db"
TICK_SECONDS = 3
SUMMARY_EVERY_SECONDS = 30

_started = False
_lock = threading.Lock()


def _conn():
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def init_db():
    with _conn() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS reminders ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, run_at TEXT NOT NULL, "
            "created_at TEXT NOT NULL, fired INTEGER NOT NULL DEFAULT 0, fired_at TEXT)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, info TEXT, at TEXT NOT NULL)"
        )


def _parse_run_at(run_at):
    value = run_at.strip()
    if value.startswith("+"):
        return datetime.now() + timedelta(seconds=int(value[1:].rstrip("sс")))
    return datetime.fromisoformat(value)


def remind_add(text, run_at):
    when = _parse_run_at(run_at).isoformat(timespec="seconds")
    with _conn() as conn:
        cursor = conn.execute(
            "INSERT INTO reminders (text, run_at, created_at) VALUES (?, ?, ?)",
            (text, when, _now_iso()),
        )
        conn.execute(
            "INSERT INTO events (kind, info, at) VALUES ('added', ?, ?)", (text, _now_iso())
        )
        reminder_id = cursor.lastrowid
    return {"id": reminder_id, "text": text, "run_at": when, "fired": 0}


def reminders_list():
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, text, run_at, fired, fired_at FROM reminders ORDER BY id ASC"
        ).fetchall()
    return [dict(row) for row in rows]


def _fire_due():
    now = _now_iso()
    with _conn() as conn:
        due = conn.execute(
            "SELECT id, text FROM reminders WHERE fired = 0 AND run_at <= ?", (now,)
        ).fetchall()
        for row in due:
            conn.execute(
                "UPDATE reminders SET fired = 1, fired_at = ? WHERE id = ?", (now, row["id"])
            )
            conn.execute(
                "INSERT INTO events (kind, info, at) VALUES ('fired', ?, ?)", (row["text"], now)
            )


def summary_run():
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM reminders").fetchone()["c"]
        fired = conn.execute("SELECT COUNT(*) AS c FROM reminders WHERE fired = 1").fetchone()["c"]
        ticks = conn.execute("SELECT COUNT(*) AS c FROM events WHERE kind = 'tick'").fetchone()["c"]
        recent = conn.execute(
            "SELECT text, fired_at FROM reminders WHERE fired = 1 ORDER BY fired_at DESC LIMIT 5"
        ).fetchall()
    return {
        "reminders_total": total,
        "reminders_fired": fired,
        "reminders_pending": total - fired,
        "scheduler_ticks": ticks,
        "recent_fired": [dict(row) for row in recent],
        "generated_at": _now_iso(),
    }


def _loop():
    last_tick = datetime.now()
    while True:
        _fire_due()
        if (datetime.now() - last_tick).total_seconds() >= SUMMARY_EVERY_SECONDS:
            with _conn() as conn:
                conn.execute(
                    "INSERT INTO events (kind, info, at) VALUES ('tick', NULL, ?)", (_now_iso(),)
                )
            last_tick = datetime.now()
        time.sleep(TICK_SECONDS)


def start_scheduler():
    global _started
    with _lock:
        if _started:
            return
        init_db()
        threading.Thread(target=_loop, daemon=True).start()
        _started = True
