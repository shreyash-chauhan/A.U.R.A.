import logging
from typing import Any
from aura.models import ActionResult, ActionSpec

log = logging.getLogger(__name__)


class ActionRegistry:
    def __init__(self) -> None:
        self._actions: dict[str, ActionSpec] = {}
        self.request_started_at = None

    def register(self, spec: ActionSpec) -> None:
        if spec.action_id in self._actions:
            raise ValueError(f"Duplicate action ID: {spec.action_id}")
        self._actions[spec.action_id] = spec

    def get(self, action_id: str) -> ActionSpec | None:
        return self._actions.get(action_id)

    def describe(self) -> list[dict[str, Any]]:
        return [{"intent": s.action_id, "description": s.description,
                 "arguments": s.argument_schema, "examples": list(s.examples)}
                for s in self._actions.values()]

    def ids(self) -> tuple[str, ...]:
        return tuple(self._actions)

    def explain(self, action_id: str) -> dict[str, Any] | None:
        """Return a user-facing explanation from the same metadata used for routing."""
        key = "".join(ch for ch in action_id.casefold() if ch.isalnum())
        for spec in self._actions.values():
            canonical = "".join(ch for ch in spec.action_id.casefold() if ch.isalnum())
            if key == canonical:
                props = spec.argument_schema.get("properties", {})
                required = set(spec.argument_schema.get("required", []))
                arguments = []
                for name, rule in props.items():
                    detail = f"{rule.get('type', 'value')}{', required' if name in required else ', optional'}"
                    if "enum" in rule: detail += f"; {len(rule['enum'])} allowed values"
                    arguments.append(f"{name} ({detail})")
                description = spec.description.split("; app IDs and aliases:", 1)[0]
                return {"id": spec.action_id, "description": description,
                        "arguments": arguments, "examples": list(spec.examples)}
        return None

    def execute(self, action_id: str, arguments: dict[str, Any]) -> ActionResult:
        spec = self.get(action_id)
        if not spec:
            return ActionResult(False, "I don't have that capability yet.", {"error": "unknown_action"})
        valid, error = validate_arguments(spec.argument_schema, arguments)
        if not valid:
            return ActionResult(False, "I couldn't understand that request.", {"error": error})
        try:
            result = spec.handler(**arguments)
            if not isinstance(result, ActionResult):
                log.error("Action %s returned an invalid result type", action_id)
                return ActionResult(False, "That action couldn't be completed.", {"error": "invalid_action_result"})
            return result
        except Exception:
            if log.isEnabledFor(logging.DEBUG):
                log.exception("Action %s failed", action_id)
            else:
                log.warning("An action failed (%s)", action_id)
            return ActionResult(False, "That action couldn't be completed.", {"error": "execution_failed"})


def validate_arguments(schema: dict[str, Any], arguments: Any) -> tuple[bool, str | None]:
    if not isinstance(arguments, dict):
        return False, "arguments_must_be_object"
    props = schema.get("properties", {})
    required = schema.get("required", [])
    if set(arguments) - set(props):
        return False, "unexpected_arguments"
    if set(required) - set(arguments):
        return False, "missing_arguments"
    for key, value in arguments.items():
        rule = props[key]
        if value is None and rule.get("nullable", False) and key not in required:
            continue
        typ = rule.get("type")
        if typ == "string" and (not isinstance(value, str) or not value.strip()):
            return False, f"invalid_{key}"
        if typ == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
            return False, f"invalid_{key}"
        if typ == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
            return False, f"invalid_{key}"
        if "enum" in rule and value not in rule["enum"]:
            return False, f"invalid_{key}"
        if typ == "string" and len(value) > rule.get("maxLength", 1000):
            return False, f"invalid_{key}"
        if typ in {"integer", "number"} and not (rule.get("minimum", float("-inf")) <= value <= rule.get("maximum", float("inf"))):
            return False, f"invalid_{key}"
    return True, None
