"""SQLite: TTL'li cache, ayar deposu (kv) ve sinyal geçmişi."""
import json
import sqlite3
import threading
import time

from core import ROOT

DB_PATH = ROOT / "data" / "cache.db"
_conn: sqlite3.Connection | None = None
_lock = threading.Lock()


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, ts REAL, value TEXT);
            CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS signals (
                ts REAL, symbol TEXT, signal TEXT, score REAL,
                price REAL, entry REAL, sl REAL, tp1 REAL, tp2 REAL, rr REAL
            );
            """
        )
    return _conn


def cache_get(key: str, ttl: float):
    with _lock:
        row = _db().execute("SELECT ts, value FROM cache WHERE key=?", (key,)).fetchone()
    if row and time.time() - row[0] < ttl:
        return json.loads(row[1])
    return None


def cache_set(key: str, value) -> None:
    with _lock:
        _db().execute(
            "INSERT OR REPLACE INTO cache VALUES (?,?,?)", (key, time.time(), json.dumps(value))
        )
        _db().commit()


def kv_get(key: str, default=None):
    with _lock:
        row = _db().execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def kv_set(key: str, value) -> None:
    with _lock:
        _db().execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, json.dumps(value)))
        _db().commit()


def save_signals(results: list[dict]) -> None:
    now = time.time()
    rows = [
        (now, r["symbol"], r["signal"], r["score"], r["price"],
         r["entry"], r["sl"], r["tp1"], r["tp2"], r["rr"])
        for r in results
    ]
    with _lock:
        _db().executemany("INSERT INTO signals VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        _db().commit()
