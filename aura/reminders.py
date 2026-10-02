from datetime import datetime, timedelta
import json
import threading
import logging
from aura.db import Database

log = logging.getLogger(__name__)


class ReminderService:
    def __init__(self, database: Database, notify):
        self.db, self.notify = database, notify
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def create(self, text: str, datetime_value: str, recurrence: str | None = None) -> int:
        scheduled = datetime.fromisoformat(datetime_value).astimezone()
        if not text.strip() or len(text) > 500:
            raise ValueError("Invalid reminder text")
        if scheduled <= datetime.now().astimezone():
            raise ValueError("Reminder time must be in the future")
        rule = self._parse_recurrence(recurrence)
        with self.db.connect() as conn:
            cur = conn.execute("INSERT INTO reminders(text,created_at,scheduled_at,recurrence) VALUES(?,?,?,?)",
                (text.strip(), datetime.now().astimezone().isoformat(), scheduled.isoformat(),
                 json.dumps(rule) if rule else None))
            return int(cur.lastrowid)

    @staticmethod
    def _parse_recurrence(value):
        if value is None:
            return None
        try:
            rule = json.loads(value)
        except (ValueError, TypeError):
            rule = {"kind": value}
        if not isinstance(rule, dict) or rule.get("kind") not in {"daily", "weekly", "interval"}:
            raise ValueError("Unsupported recurrence")
        if rule["kind"] == "interval" and not 1 <= int(rule.get("minutes", 0)) <= 525600:
            raise ValueError("Invalid recurrence interval")
        if rule["kind"] == "weekly":
            days = rule.get("days", [])
            if not isinstance(days, list) or any(not isinstance(d, int) or d not in range(7) for d in days):
                raise ValueError("Invalid weekly recurrence")
        return rule

    def list(self):
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM reminders WHERE status='pending' ORDER BY scheduled_at")]

    def delete(self, reminder_id: int) -> bool:
        with self.db.connect() as conn:
            cur = conn.execute("DELETE FROM reminders WHERE id=? AND status='pending'", (reminder_id,))
            return cur.rowcount > 0

    def edit(self, reminder_id: int, text: str | None = None, datetime_value: str | None = None) -> bool:
        if text is not None and (not text.strip() or len(text) > 500):
            raise ValueError("Invalid reminder text")
        sets, vals = [], []
        if text is not None: sets.append("text=?"); vals.append(text.strip())
        if datetime_value is not None:
            scheduled = datetime.fromisoformat(datetime_value).astimezone()
            if scheduled <= datetime.now().astimezone(): raise ValueError("Reminder time must be in the future")
            sets.append("scheduled_at=?"); vals.append(scheduled.isoformat())
        if not sets: return False
        vals.append(reminder_id)
        with self.db.connect() as conn:
            return conn.execute(f"UPDATE reminders SET {','.join(sets)} WHERE id=? AND status='pending'", vals).rowcount > 0

    def snooze(self, reminder_id: int, minutes: int) -> bool:
        if not 1 <= minutes <= 10080: return False
        with self.db.connect() as conn:
            return conn.execute("UPDATE reminders SET scheduled_at=? WHERE id=? AND status='pending'",
                ((datetime.now().astimezone()+timedelta(minutes=minutes)).isoformat(), reminder_id)).rowcount > 0

    def start(self):
        if self._thread and self._thread.is_alive(): return
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="aura-reminders")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread: self._thread.join(timeout=2)

    def _worker(self):
        while not self._stop.is_set():
            try:
                self._process_due()
            except Exception:
                log.exception("Reminder scheduler iteration failed")
            self._stop.wait(1)

    def _process_due(self):
        now = datetime.now().astimezone()
        with self.db.connect() as conn:
            rows = list(conn.execute("SELECT * FROM reminders WHERE status='pending' AND scheduled_at<=?", (now.isoformat(),)))
            for row in rows:
                try: self.notify(row["text"])
                except Exception: log.exception("Reminder notification delivery failed")
                rule = json.loads(row["recurrence"]) if row["recurrence"] else None
                if rule:
                    next_at = self._next(datetime.fromisoformat(row["scheduled_at"]), rule, now)
                    conn.execute("UPDATE reminders SET scheduled_at=?,last_triggered_at=? WHERE id=?",
                                 (next_at.isoformat(), now.isoformat(), row["id"]))
                else:
                    conn.execute("UPDATE reminders SET status='completed',last_triggered_at=? WHERE id=?",
                                 (now.isoformat(), row["id"]))

    @staticmethod
    def _next(previous, rule, now):
        if rule["kind"] == "daily": step = timedelta(days=1)
        elif rule["kind"] == "interval": step = timedelta(minutes=rule["minutes"])
        else:
            days = sorted(set(rule.get("days", []))) or [previous.weekday()]
            candidate = previous
            while candidate <= now or candidate.weekday() not in days:
                candidate += timedelta(days=1)
            return candidate
        candidate = previous + step
        while candidate <= now: candidate += step
        return candidate
