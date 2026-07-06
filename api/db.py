"""SQLite layer — single writer (API process), WAL, module-global connection."""
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

DDL = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  google_id TEXT,
  plan TEXT NOT NULL DEFAULT 'free',
  chapters_converted INTEGER NOT NULL DEFAULT 0,
  stripe_customer_id TEXT,
  payment_failed INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions(
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS magic_links(
  token_hash TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS books(
  id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  author TEXT,
  source_key TEXT,
  status TEXT NOT NULL DEFAULT 'ready',
  error TEXT,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS chapters(
  id INTEGER PRIMARY KEY,
  book_id TEXT NOT NULL,
  idx INTEGER NOT NULL,
  title TEXT NOT NULL,
  text TEXT NOT NULL,
  chars INTEGER NOT NULL,
  audio_key TEXT,
  duration REAL,
  status TEXT NOT NULL DEFAULT 'none',
  progress REAL NOT NULL DEFAULT 0,
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_chapters_book ON chapters(book_id);
CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY,
  chapter_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  state TEXT NOT NULL DEFAULT 'queued',
  engine TEXT NOT NULL DEFAULT 'kokoro',
  attempts INTEGER NOT NULL DEFAULT 0,
  claimed_by TEXT,
  claimed_at INTEGER,
  error TEXT,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
"""


def connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        path = Path(os.environ.get("DATA_DIR", ".")) / "genaudi.db"
        _conn = sqlite3.connect(path, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(DDL)
    return _conn


def reset_for_tests():
    global _conn
    if _conn is not None:
        _conn.close()
    _conn = None


def q(sql, args=()):
    return connect().execute(sql, args).fetchall()


def q1(sql, args=()):
    return connect().execute(sql, args).fetchone()


def ex(sql, args=()):
    with _lock:
        cur = connect().execute(sql, args)
        connect().commit()
        return cur


@contextmanager
def tx():
    """Multi-statement atomic transaction. Yields the connection."""
    with _lock:
        c = connect()
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
