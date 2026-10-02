from datetime import datetime, timedelta
import datetime as datetime_module
import os
from pathlib import Path
import subprocess
import sys
import urllib.parse
import webbrowser
from aura.apps.catalog import resolve_app
from aura.models import ActionResult


class Handlers:
    def __init__(self, launcher, reminders, timers, pomodoros=None, schedules=None):
        self.launcher, self.reminders, self.timers = launcher, reminders, timers
        self.pomodoros, self.schedules, self.registry = pomodoros, schedules, None

    def greet(self):
        hour = datetime.now().astimezone().hour
        period = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
        return ActionResult(True, f"Good {period}. How can I help?")

    def list_functions(self):
        if self.registry is None: return ActionResult(False, "The action list isn't available.")
        items = self.registry.describe()
        return ActionResult(True, "Here are AURA's available functions.",
                            {"display_functions": [f"{item['intent']}: {item['description'].split('; app IDs and aliases:', 1)[0]}" for item in items]})

    def explain_function(self, function_id):
        if self.registry is None: return ActionResult(False, "The function directory isn't available.")
        item = self.registry.explain(function_id)
        if item is None:
            return ActionResult(False, f"I couldn't find a function named {function_id}. Ask me to list available functions.")
        details = [f"{item['id']}: {item['description']}"]
        if item["arguments"]: details.append("Arguments: " + ", ".join(item["arguments"]) + ".")
        if item["examples"]: details.append("Example: " + item["examples"][0])
        return ActionResult(True, " ".join(details), {"function": item})

    def open_app(self, app_id):
        spec = resolve_app(app_id)
        if not spec: return ActionResult(False, "I couldn't find that application in my app list.")
        ok, msg = self.launcher.open(spec)
        return ActionResult(ok, msg, {"app_id": spec.app_id})

    def close_app(self, app_id):
        spec = resolve_app(app_id)
        if not spec: return ActionResult(False, "I couldn't find that application in my app list.")
        ok = self.launcher.close(spec)
        return ActionResult(ok, f"Closed {spec.display_name}." if ok else f"{spec.display_name} is not open or couldn't be closed.")

    def restart_app(self, app_id):
        closed = self.close_app(app_id)
        if not closed.success: return closed
        return self.open_app(app_id)

    def focus_app(self, app_id):
        spec = resolve_app(app_id)
        if not spec: return ActionResult(False, "I couldn't find that application in my app list.")
        if self.launcher.focus(spec): return ActionResult(True, f"Bringing {spec.display_name} forward.")
        return ActionResult(False, f"I couldn't find an open window for {spec.display_name}.")

    def open_shortcut(self, shortcut):
        urls = {"google":"https://www.google.com", "youtube":"https://www.youtube.com",
                "github":"https://github.com", "chatgpt":"https://chatgpt.com",
                "google_drive":"https://drive.google.com"}
        return self.open_url(urls[shortcut])

    def media_key(self, key):
        if sys.platform != "win32": return ActionResult(False, "Media keys are available on Windows.")
        try:
            import ctypes
            from ctypes import wintypes
            KEYEVENTF_KEYUP, INPUT_KEYBOARD, VK = 0x0002, 1, {"play":0xB3,"next":0xB0,"previous":0xB1}
            class MOUSEINPUT(ctypes.Structure):
                _fields_ = [("dx",wintypes.LONG),("dy",wintypes.LONG),("mouseData",wintypes.DWORD),
                            ("dwFlags",wintypes.DWORD),("time",wintypes.DWORD),("dwExtraInfo",ctypes.c_size_t)]
            class KEYBDINPUT(ctypes.Structure):
                _fields_ = [("wVk",wintypes.WORD),("wScan",wintypes.WORD),("dwFlags",wintypes.DWORD),
                            ("time",wintypes.DWORD),("dwExtraInfo",ctypes.c_size_t)]
            class HARDWAREINPUT(ctypes.Structure):
                _fields_ = [("uMsg",wintypes.DWORD),("wParamL",wintypes.WORD),("wParamH",wintypes.WORD)]
            class INPUT_UNION(ctypes.Union):
                _fields_ = [("mi",MOUSEINPUT),("ki",KEYBDINPUT),("hi",HARDWAREINPUT)]
            class INPUT(ctypes.Structure):
                _fields_ = [("type",wintypes.DWORD),("union",INPUT_UNION)]
            user32 = ctypes.windll.user32
            user32.SendInput.argtypes = (wintypes.UINT,ctypes.POINTER(INPUT),ctypes.c_int)
            user32.SendInput.restype = wintypes.UINT
            events = (INPUT * 2)()
            for item, flags in zip(events, (0,KEYEVENTF_KEYUP)):
                item.type = INPUT_KEYBOARD
                item.ki = KEYBDINPUT(VK[key],0,flags,0,0)
            sent = user32.SendInput(2,events,ctypes.sizeof(INPUT))
            if sent != 2:
                return ActionResult(False, "Windows rejected the media key. Spotify may be running with higher permissions.")
            return ActionResult(True, {"play":"Toggling playback.","next":"Skipping to the next track.","previous":"Going to the previous track."}[key])
        except Exception: return ActionResult(False, "I couldn't send the media control.")

    def toggle_spotify(self):
        result = self.media_key("play")
        if result.success:
            return ActionResult(True, "Sent the Windows play/pause media key. It controls the active media session, which should be Spotify when Spotify is the active player.")
        return result

    def open_url(self, url):
        parsed = urllib.parse.urlparse(url if "://" in url else "https://" + url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ActionResult(False, "That web address doesn't look valid.")
        webbrowser.open(parsed.geturl(), new=2)
        return ActionResult(True, "Opening that page.")

    def search_web(self, query):
        return self.open_url("https://www.google.com/search?q=" + urllib.parse.quote_plus(query))

    def search_youtube(self, query):
        return self.open_url("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query))

    def create_reminder(self, text, datetime, recurrence=None):
        try: rid = self.reminders.create(text, datetime, recurrence)
        except (ValueError, TypeError): return ActionResult(False, "I couldn't set that reminder. Check that you gave me a future time.")
        return ActionResult(True, "Reminder set.", {"reminder_id": rid})

    def list_reminders(self):
        rows = self.reminders.list()
        if not rows: return ActionResult(True, "You have no upcoming reminders.")
        brief = "; ".join(f"{r['id']}: {r['text']} at {r['scheduled_at']}" for r in rows[:8])
        return ActionResult(True, brief, {"reminders": rows})

    def delete_reminder(self, reminder_id):
        ok = self.reminders.delete(reminder_id)
        return ActionResult(ok, "Reminder deleted." if ok else "I couldn't find that reminder.")

    def edit_reminder(self, reminder_id, text=None, datetime=None):
        try: ok = self.reminders.edit(reminder_id, text, datetime)
        except (ValueError, TypeError): return ActionResult(False, "I couldn't update that reminder. Check that the new time is in the future.")
        return ActionResult(ok, "Reminder updated." if ok else "I couldn't find that reminder.")

    def snooze_reminder(self, reminder_id, minutes):
        ok = self.reminders.snooze(reminder_id, minutes)
        return ActionResult(ok, "Reminder snoozed." if ok else "I couldn't snooze that reminder.")

    def set_timer(self, seconds):
        try: timer_id = self.timers.create(seconds)
        except ValueError: return ActionResult(False, "That timer duration is out of range.")
        amount = f"{seconds // 60} minutes" if seconds >= 60 and seconds % 60 == 0 else f"{seconds} seconds"
        return ActionResult(True, f"Your timer is set for {amount}.", {"timer_id": timer_id})

    def start_pomodoro(self, work_minutes=25, break_minutes=5, cycles=4):
        work_minutes = 25 if work_minutes is None else work_minutes
        break_minutes = 5 if break_minutes is None else break_minutes
        cycles = 4 if cycles is None else cycles
        try: session_id = self.pomodoros.start(work_minutes, break_minutes, cycles)
        except (ValueError, RuntimeError): return ActionResult(False, "A Pomodoro is already running, or those settings are out of range.")
        return ActionResult(True, f"Pomodoro started: {work_minutes} minutes focus, {break_minutes} minutes break, {cycles} cycles.",
                            {"pomodoro_id": session_id})

    def cancel_pomodoro(self):
        ok = self.pomodoros.cancel()
        return ActionResult(ok, "Pomodoro cancelled." if ok else "There isn't an active Pomodoro.")

    def schedule_open_app(self, app_id, datetime=None, recurrence="once", delay_seconds=None):
        recurrence = recurrence or "once"
        if (datetime is None) == (delay_seconds is None):
            return ActionResult(False, "Give me either a clock time or a delay, such as in 10 seconds.")
        if delay_seconds is not None:
            if isinstance(delay_seconds, bool) or not isinstance(delay_seconds, int) or not 1 <= delay_seconds <= 604800:
                return ActionResult(False, "The delay must be between 1 second and 7 days.")
            request_started = getattr(self.registry, "request_started_at", None)
            base = request_started or datetime_module.datetime.now().astimezone()
            datetime = (base + timedelta(seconds=delay_seconds)).isoformat(timespec="seconds")
        try: schedule_id = self.schedules.create(app_id, datetime, recurrence, allow_due=delay_seconds is not None)
        except (ValueError, TypeError): return ActionResult(False, "I couldn't schedule that app launch. Check the app and time.")
        spec = resolve_app(app_id)
        if delay_seconds is not None:
            unit = "second" if delay_seconds == 1 else "seconds"
            message = f"I'll open {spec.display_name} in {delay_seconds} {unit}."
        else:
            message = f"I'll open {spec.display_name} at the scheduled time ({recurrence})."
        return ActionResult(True, message,
                            {"schedule_id":schedule_id})

    def list_app_schedules(self):
        rows = self.schedules.list()
        if not rows: return ActionResult(True, "There are no scheduled app launches.")
        summary = "; ".join(f"{r['id']}: {r['app_id']} at {r['scheduled_at']} ({r['recurrence']}, {r['status']})" for r in rows[:10])
        return ActionResult(True, summary, {"schedules":rows})

    def cancel_app_schedule(self, schedule_id):
        ok = self.schedules.cancel(schedule_id)
        return ActionResult(ok, "Scheduled app launch cancelled." if ok else "I couldn't find that scheduled launch.")

    def cancel_timer(self, timer_id=None):
        ok = self.timers.cancel(timer_id)
        return ActionResult(ok, "Timer cancelled." if ok else "You don't have a matching timer.")

    def list_timers(self):
        rows = self.timers.list()
        return ActionResult(True, f"You have {len(rows)} active timer(s).", {"timers": rows})

    def time_now(self): return ActionResult(True, datetime.now().astimezone().strftime("It's %I:%M %p."))
    def date_now(self): return ActionResult(True, datetime.now().astimezone().strftime("Today is %A, %B %d."))

    def volume(self, direction):
        if sys.platform != "win32": return ActionResult(False, "Volume controls are available on Windows.")
        try:
            from ctypes import POINTER, cast
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            device = AudioUtilities.GetSpeakers()
            interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            endpoint = cast(interface, POINTER(IAudioEndpointVolume))
            if direction == "mute": endpoint.SetMute(1, None)
            elif direction == "unmute": endpoint.SetMute(0, None)
            else:
                current = endpoint.GetMasterVolumeLevelScalar()
                endpoint.SetMasterVolumeLevelScalar(max(0, min(1, current + (.1 if direction == "up" else -.1))), None)
            return ActionResult(True, {"up":"Volume up.","down":"Volume down.","mute":"Muted.","unmute":"Unmuted."}[direction])
        except Exception:
            return ActionResult(False, "I couldn't adjust the system volume. Install the optional Windows audio dependency.")

    def system_power(self, kind):
        if sys.platform != "win32": return ActionResult(False, "That system action is available on Windows.")
        args = ["shutdown", "/s" if kind == "shutdown" else "/r", "/t", "0"]
        try:
            subprocess.Popen(args, shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return ActionResult(True, f"Starting {kind}.")
        except OSError:
            return ActionResult(False, f"I couldn't {kind} the computer.")

    def lock_pc(self):
        if sys.platform != "win32": return ActionResult(False, "Lock is available on Windows.")
        try: subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"], shell=False); return ActionResult(True, "Locking the computer.")
        except OSError: return ActionResult(False, "I couldn't lock the computer.")

    def open_known_folder(self, name):
        home = Path.home()
        known = {"desktop": home / "Desktop", "downloads": home / "Downloads", "documents": home / "Documents"}
        target = known[name]
        if not target.exists(): return ActionResult(False, f"I couldn't find your {name} folder.")
        try:
            if sys.platform == "win32": os.startfile(str(target))
            else: webbrowser.open(target.as_uri())
            return ActionResult(True, f"Opening {name}.")
        except OSError: return ActionResult(False, f"I couldn't open {name}.")

    def create_folder(self, name):
        if not name.strip() or name in {".", ".."} or any(c in name for c in '<>:"/\\|?*'):
            return ActionResult(False, "That folder name isn't valid.")
        target = (Path.home() / "Documents" / name).resolve()
        root = (Path.home() / "Documents").resolve()
        if root not in target.parents: return ActionResult(False, "That folder location isn't allowed.")
        try: target.mkdir(exist_ok=False); return ActionResult(True, f"Created folder {name} in Documents.")
        except FileExistsError: return ActionResult(False, "A folder with that name already exists.")
        except OSError: return ActionResult(False, "I couldn't create that folder.")

    @staticmethod
    def _safe_user_path(value):
        candidate = Path(value).expanduser()
        if not candidate.is_absolute(): candidate = Path.home() / candidate
        candidate = candidate.resolve(strict=True)
        allowed = [(Path.home() / name).resolve() for name in ("Documents", "Downloads", "Desktop")]
        if not any(root == candidate or root in candidate.parents for root in allowed):
            raise ValueError("outside allowed user folders")
        return candidate

    def open_user_path(self, path, expect_directory):
        try: target = self._safe_user_path(path)
        except (OSError, ValueError, RuntimeError): return ActionResult(False, "That path isn't available in your user folders.")
        if expect_directory and not target.is_dir(): return ActionResult(False, "That isn't a folder.")
        if not expect_directory and not target.is_file(): return ActionResult(False, "That isn't a file.")
        try:
            if sys.platform == "win32": os.startfile(str(target))
            else: webbrowser.open(target.as_uri())
            return ActionResult(True, f"Opening {target.name}.")
        except OSError: return ActionResult(False, "I couldn't open that location.")

    def search_files(self, query):
        terms = query.strip().casefold()
        if not terms: return ActionResult(False, "Tell me what file to look for.")
        roots = [(Path.home() / name) for name in ("Documents", "Downloads", "Desktop")]
        matches, inspected = [], 0
        for root in roots:
            if not root.exists(): continue
            try:
                for path in root.rglob("*"):
                    inspected += 1
                    if inspected > 10000: break
                    if path.is_file() and terms in path.name.casefold():
                        matches.append(str(path))
                        if len(matches) >= 10: break
            except OSError: continue
            if len(matches) >= 10 or inspected > 10000: break
        if not matches: return ActionResult(True, "I couldn't find a matching file.", {"matches": []})
        return ActionResult(True, f"I found {len(matches)} matching file(s).", {"matches": matches})

    def fallback(self, original_text=""):
        return ActionResult(False, "I don't have that capability yet.")
