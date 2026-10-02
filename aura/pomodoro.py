"""Single active, in-memory Pomodoro cycle manager."""
from datetime import datetime, timedelta
import threading
import uuid


class PomodoroService:
    def __init__(self, notify):
        self.notify = notify
        self._lock = threading.RLock()
        self._timer: threading.Timer | None = None
        self._state: dict | None = None

    def start(self, work_minutes=25, break_minutes=5, cycles=4) -> str:
        if not 1 <= work_minutes <= 180 or not 1 <= break_minutes <= 60 or not 1 <= cycles <= 12:
            raise ValueError("Pomodoro values out of range")
        with self._lock:
            if self._state is not None: raise RuntimeError("A Pomodoro is already running")
            session_id = str(uuid.uuid4())[:8]
            self._state = {"id":session_id, "work":work_minutes, "break":break_minutes,
                           "cycles":cycles, "cycle":1, "phase":"work",
                           "due":datetime.now().astimezone()+timedelta(minutes=work_minutes)}
            self._arm(work_minutes * 60, session_id)
        return session_id

    def _arm(self, seconds, session_id):
        self._timer = threading.Timer(seconds, self._advance, args=(session_id,))
        self._timer.daemon = True
        self._timer.start()

    def _advance(self, session_id):
        message = None
        with self._lock:
            state = self._state
            if not state or state["id"] != session_id: return
            if state["phase"] == "work":
                if state["cycle"] >= state["cycles"]:
                    message = "Pomodoro complete. Great work."
                    self._state = None
                    self._timer = None
                else:
                    state["phase"] = "break"
                    state["due"] = datetime.now().astimezone()+timedelta(minutes=state["break"])
                    message = f"Focus session complete. Take a {state['break']} minute break."
                    self._arm(state["break"]*60, session_id)
            else:
                state["cycle"] += 1
                state["phase"] = "work"
                state["due"] = datetime.now().astimezone()+timedelta(minutes=state["work"])
                message = f"Break complete. Start focus session {state['cycle']} of {state['cycles']}."
                self._arm(state["work"]*60, session_id)
        if message: self.notify(message)

    def cancel(self) -> bool:
        with self._lock:
            if self._state is None: return False
            self._state = None
            timer, self._timer = self._timer, None
        if timer: timer.cancel()
        return True

    def status(self):
        with self._lock: return dict(self._state) if self._state else None
