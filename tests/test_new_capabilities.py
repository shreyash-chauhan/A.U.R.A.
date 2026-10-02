from datetime import datetime, timedelta
from unittest.mock import patch
import json

from aura.actions.registry import ActionRegistry
from aura.actions.builtin import register_builtins
from aura.actions.handlers import Handlers
from aura.actions.workflow_action import register_workflows
from aura.apps.launcher import AppLauncher
from aura.db import Database
from aura.models import ActionResult
from aura.pomodoro import PomodoroService
from aura.reminders import ReminderService
from aura.schedules import AppScheduleService
from aura.timers import TimerService
from aura.workflows.runner import WorkflowRunner
from aura.adapters.ollama import OllamaClient


class FakeLauncher:
    def __init__(self): self.opened = []
    def open(self, app): self.opened.append(app.app_id); return True, f"Opening {app.display_name}."


def test_reminder_command_and_null_recurrence_are_valid(tmp_path):
    db = Database(tmp_path / "aura.sqlite3")
    reminders = ReminderService(db, lambda _: None)
    handler = Handlers(None, reminders, None)
    from aura.actions.registry import validate_arguments
    schema = {"type":"object", "properties":{"text":{"type":"string"},
              "datetime":{"type":"string"}, "recurrence":{"type":"string","nullable":True}},
              "required":["text","datetime"], "additionalProperties":False}
    assert validate_arguments(schema, {"text":"submit work", "datetime":
        (datetime.now().astimezone()+timedelta(hours=1)).isoformat(), "recurrence":None})[0]
    rid = reminders.create("submit work", (datetime.now().astimezone()+timedelta(hours=1)).isoformat())
    assert reminders.list()[0]["id"] == rid


def test_function_list_and_greeting_are_registered(tmp_path):
    db = Database(tmp_path / "aura.sqlite3")
    launcher = FakeLauncher()
    reminders = ReminderService(db, lambda _: None)
    timers = TimerService(lambda _: None)
    pomodoros = PomodoroService(lambda _: None)
    schedules = AppScheduleService(db, launcher, lambda _: None)
    handlers = Handlers(launcher, reminders, timers, pomodoros, schedules)
    registry = ActionRegistry()
    register_builtins(registry, handlers)
    register_workflows(registry, WorkflowRunner(registry))
    handlers.registry = registry
    listed = registry.execute("list_functions", {})
    assert "schedule_open_app" in listed.data["display_functions"]
    assert registry.execute("greet", {}).message.startswith("Good ")


def test_pomodoro_can_be_started_and_cancelled():
    pomodoros = PomodoroService(lambda _: None)
    session_id = pomodoros.start(work_minutes=1, break_minutes=1, cycles=1)
    assert pomodoros.status()["id"] == session_id
    assert pomodoros.cancel()
    assert pomodoros.status() is None


def test_app_schedule_persists_and_launches_due_app(tmp_path):
    db = Database(tmp_path / "aura.sqlite3")
    launcher = FakeLauncher()
    events = []
    schedules = AppScheduleService(db, launcher, events.append)
    schedule_id = schedules.create("chrome", (datetime.now().astimezone()+timedelta(minutes=2)).isoformat(), "daily")
    assert schedules.list()[0]["id"] == schedule_id
    with db.connect() as conn:
        conn.execute("UPDATE app_schedules SET scheduled_at=? WHERE id=?",
                     ((datetime.now().astimezone()-timedelta(seconds=1)).isoformat(), schedule_id))
    schedules._process_due()
    assert launcher.opened == ["chrome"]
    assert schedules.list()[0]["recurrence"] == "daily"


def test_ollama_client_disables_thinking_and_keeps_model_warm():
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps({"message":{"content":"{}"}, "load_duration":0,
            "prompt_eval_duration":0,"eval_duration":0}).encode()
    client = OllamaClient("http://localhost:11434", "qwen3:8b", keep_alive="15m", num_ctx=4096, num_predict=96)
    with patch("urllib.request.urlopen", return_value=Response()) as mocked:
        assert client.generate("hello", []) == "{}"
    body = json.loads(mocked.call_args.args[0].data)
    assert body["think"] is False
    assert body["keep_alive"] == "15m"
    assert body["options"]["num_predict"] == 96
