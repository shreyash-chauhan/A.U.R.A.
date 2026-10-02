import json
import logging
from typing import Any
from aura.actions.registry import ActionRegistry, validate_arguments

log = logging.getLogger(__name__)


class IntentRouter:
    def __init__(self, registry: ActionRegistry, ollama: Any, min_confidence: float = .70):
        self.registry, self.ollama, self.min_confidence = registry, ollama, min_confidence

    def route(self, user_text: str) -> dict[str, Any]:
        raw = self.ollama.generate(user_text, self.registry.describe())
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            log.debug("Router rejected non-JSON model output")
            return {"kind": "fallback", "message": "I couldn't understand that. Please try again."}
        if not isinstance(obj, dict) or set(obj) != {"intent", "confidence", "arguments"}:
            log.debug("Router rejected model output with an unexpected shape")
            return {"kind": "fallback", "message": "I couldn't understand that. Please try again."}
        intent, confidence, args = obj["intent"], obj["confidence"], obj["arguments"]
        if not isinstance(intent, str) or isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            log.debug("Router rejected invalid intent or confidence fields")
            return {"kind": "fallback", "message": "I couldn't understand that. Please try again."}
        if intent == "clarify":
            question = args.get("question") if isinstance(args, dict) else None
            if isinstance(args, dict) and set(args) == {"question"} and isinstance(question, str) and question.strip() and len(question) <= 240:
                return {"kind": "clarify", "message": question.strip()}
            log.debug("Router rejected malformed clarification response")
            return {"kind": "fallback", "message": "I couldn't understand that. Please try again."}
        if intent == "fallback":
            return {"kind": "fallback", "message": "I don't have that capability yet."}
        spec = self.registry.get(intent)
        if not spec:
            log.debug("Router rejected unregistered action ID: %s", intent)
            return {"kind": "fallback", "message": "I don't have that capability yet."}
        valid, error = validate_arguments(spec.argument_schema, args)
        if not valid:
            log.debug("Router rejected arguments for %s: %s", intent, error)
            return {"kind": "fallback", "message": "I couldn't understand that. Please try again."}
        if confidence < self.min_confidence:
            log.debug("Router confidence %.2f below threshold %.2f", confidence, self.min_confidence)
            return {"kind": "clarify", "message": "I'm not sure what you mean. Could you say that another way?"}
        return {"kind": "action", "intent": intent, "arguments": args,
                "requires_confirmation": spec.requires_confirmation}
