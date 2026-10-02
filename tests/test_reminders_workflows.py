from datetime import datetime, timedelta
from aura.db import Database
from aura.reminders import ReminderService
from aura.actions.registry import ActionRegistry
from aura.actions.workflow_action import register_workflows
from aura.workflows.runner import WorkflowRunner
from aura.models import ActionResult, ActionSpec


def test_reminder_persistence_and_recurrence_validation(tmp_path):
    path = tmp_path / "test.sqlite3"
    service = ReminderService(Database(path), lambda text: None)
    service.create("submit homework", (datetime.now().astimezone()+timedelta(hours=1)).isoformat(), '{"kind":"daily"}')
    assert len(ReminderService(Database(path), lambda text: None).list()) == 1


def test_due_one_time_reminder_completes(tmp_path):
    db = Database(tmp_path / "db.sqlite3")
    events=[]; service=ReminderService(db, events.append)
    service.create("hello", (datetime.now().astimezone()-timedelta(seconds=1)).isoformat())
    service._process_due()
    assert events == ["hello"]
    with db.connect() as conn:
        assert conn.execute("select status from reminders").fetchone()[0] == "completed"


def test_workflow_calls_only_registered_actions():
    r = ActionRegistry()
    calls=[]
    r.register(ActionSpec("safe", "safe", {"type":"object","properties":{},"required":[],"additionalProperties":False}, lambda: calls.append(1) or ActionResult(True,"ok")))
    # An unknown workflow step never reaches execution.
    assert not WorkflowRunner(r).run("study_mode").success
    assert calls == []


def test_workflow_metadata_registered():
    r=ActionRegistry(); register_workflows(r, WorkflowRunner(r))
    assert r.get("run_workflow") is not None
