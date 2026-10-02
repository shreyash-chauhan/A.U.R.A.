from datetime import datetime, timedelta
import threading
import uuid


class TimerService:
    def __init__(self, notify):
        self.notify, self._timers, self._lock = notify, {}, threading.Lock()

    def create(self, seconds: int) -> str:
        if not 1 <= seconds <= 604800: raise ValueError("Timer duration out of range")
        timer_id = str(uuid.uuid4())[:8]
        timer = threading.Timer(seconds, self._fire, args=(timer_id,))
        with self._lock: self._timers[timer_id] = (datetime.now().astimezone()+timedelta(seconds=seconds), timer)
        timer.daemon = True; timer.start()
        return timer_id

    def _fire(self, timer_id):
        with self._lock: self._timers.pop(timer_id, None)
        self.notify("Your timer is up.")

    def cancel(self, timer_id: str | None = None) -> bool:
        with self._lock:
            if timer_id is None:
                if not self._timers: return False
                timer_id = min(self._timers, key=lambda k: self._timers[k][0])
            item = self._timers.pop(timer_id, None)
        if item: item[1].cancel(); return True
        return False

    def list(self):
        with self._lock: return [{"id": k, "due": v[0].isoformat()} for k,v in self._timers.items()]

    def stop(self):
        """Cancel pending timers during an explicit assistant shutdown."""
        with self._lock:
            timers = [timer for _, timer in self._timers.values()]
            self._timers.clear()
        for timer in timers:
            timer.cancel()
