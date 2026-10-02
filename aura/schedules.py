"""Persistent, allowlisted schedules for launching registered applications."""
from datetime import datetime, timedelta
import logging
import threading

from aura.apps.catalog import resolve_app
from aura.db import Database

log = logging.getLogger(__name__)


class AppScheduleService:
    def __init__(self, database: Database, launcher, notify):
        self.db, self.launcher, self.notify = database, launcher, notify
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        with self.db.connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS app_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_id TEXT NOT NULL,
                scheduled_at TEXT NOT NULL,
                recurrence TEXT NOT NULL DEFAULT 'once',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                last_triggered_at TEXT)""")

    def create(self, app_id: str, datetime_value: str, recurrence: str = "once", allow_due: bool = False) -> int:
        app = resolve_app(app_id)
        if not app: raise ValueError("Unknown application")
        if recurrence not in {"once", "daily", "weekdays", "weekly"}: raise ValueError("Invalid recurrence")
        scheduled = datetime.fromisoformat(datetime_value).astimezone()
        if recurrence == "weekdays":
            while scheduled.weekday() >= 5: scheduled += timedelta(days=1)
        if scheduled <= datetime.now().astimezone() and not allow_due:
            raise ValueError("Schedule must be in the future")
        with self.db.connect() as conn:
            cur = conn.execute("INSERT INTO app_schedules(app_id,scheduled_at,recurrence,created_at) VALUES(?,?,?,?)",
                (app.app_id, scheduled.isoformat(), recurrence, datetime.now().astimezone().isoformat()))
            return int(cur.lastrowid)

    def list(self):
        with self.db.connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM app_schedules WHERE status IN ('pending','failed') ORDER BY scheduled_at")]

    def cancel(self, schedule_id: int) -> bool:
        with self.db.connect() as conn:
            return conn.execute("UPDATE app_schedules SET status='cancelled' WHERE id=? AND status='pending'",
                                (schedule_id,)).rowcount > 0

    def start(self):
        if self._thread and self._thread.is_alive(): return
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="aura-app-schedules")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread: self._thread.join(timeout=2)

    def _worker(self):
        while not self._stop.is_set():
            try: self._process_due()
            except Exception: log.exception("App schedule iteration failed")
            self._stop.wait(1)

    def _process_due(self):
        now = datetime.now().astimezone()
        with self.db.connect() as conn:
            # Compare actual instants. Lexical ISO comparisons can be wrong if an
            # existing schedule and the current time carry different UTC offsets.
            rows = [row for row in conn.execute(
                "SELECT * FROM app_schedules WHERE status='pending'")
                if datetime.fromisoformat(row["scheduled_at"]).astimezone() <= now]
            for row in rows:
                app = resolve_app(row["app_id"])
                success, message = self.launcher.open(app) if app else (False, "App is no longer registered")
                if not success:
                    log.warning("Scheduled launch %s failed for %s: %s", row["id"], row["app_id"], message)
                try: self.notify(f"Scheduled launch: {message}")
                except Exception: log.exception("App schedule notification failed")
                if row["recurrence"] == "once":
                    conn.execute("UPDATE app_schedules SET status=? ,last_triggered_at=? WHERE id=?",
                                 ("completed" if success else "failed", now.isoformat(), row["id"]))
                else:
                    previous = datetime.fromisoformat(row["scheduled_at"])
                    if row["recurrence"] == "weekdays":
                        next_at = previous + timedelta(days=1)
                        while next_at <= now or next_at.weekday() >= 5:
                            next_at += timedelta(days=1)
                    else:
                        step = timedelta(days=1 if row["recurrence"] == "daily" else 7)
                        next_at = previous + step
                        while next_at <= now: next_at += step
                    conn.execute("UPDATE app_schedules SET scheduled_at=?,last_triggered_at=? WHERE id=?",
                                 (next_at.isoformat(), now.isoformat(), row["id"]))
