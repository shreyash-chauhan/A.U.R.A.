import sqlite3
from pathlib import Path
from contextlib import contextmanager


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL,
                created_at TEXT NOT NULL, scheduled_at TEXT NOT NULL,
                recurrence TEXT, status TEXT NOT NULL DEFAULT 'pending',
                last_triggered_at TEXT)""")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
