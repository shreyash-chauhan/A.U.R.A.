import json
from aura.actions.registry import ActionRegistry
from aura.actions.router import IntentRouter
from aura.models import ActionResult, ActionSpec


class Model:
    def __init__(self, value): self.value = value
    def generate(self, text, capabilities): return self.value


def registry(calls=None):
    calls = calls if calls is not None else []
    r = ActionRegistry()
    r.register(ActionSpec("echo", "Echo", {"type":"object","properties":{"value":{"type":"string"}},"required":["value"],"additionalProperties":False},
                          lambda value: calls.append(value) or ActionResult(True, value)))
    return r


def test_valid_intent_passes_allowlisted_schema():
    router = IntentRouter(registry(), Model(json.dumps({"intent":"echo","confidence":.9,"arguments":{"value":"ok"}})))
    assert router.route("say ok")["kind"] == "action"


def test_malformed_json_falls_back():
    assert IntentRouter(registry(), Model("not json")).route("x")["kind"] == "fallback"


def test_unknown_action_does_not_execute():
    d = IntentRouter(registry(), Model('{"intent":"shell","confidence":1,"arguments":{"cmd":"bad"}}')).route("x")
    assert d["kind"] == "fallback"


def test_low_confidence_requests_clarification():
    raw = '{"intent":"echo","confidence":0.2,"arguments":{"value":"ok"}}'
    assert IntentRouter(registry(), Model(raw)).route("x")["kind"] == "clarify"


def test_model_clarification_never_reaches_execution():
    raw = '{"intent":"clarify","confidence":0.9,"arguments":{"question":"Which browser do you mean?"}}'
    decision = IntentRouter(registry(), Model(raw)).route("open my browser")
    assert decision == {"kind":"clarify", "message":"Which browser do you mean?"}


def test_extra_args_rejected():
    r = registry([])
    assert not r.execute("echo", {"value":"ok", "command":"whoami"}).success
