import sqlite3
from contextlib import contextmanager
from pathlib import Path

from config import DATABASE_PATH


@contextmanager
def connect(path: str | Path | None = None):
    database = Path(path or DATABASE_PATH)
    database.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

