"""Request handling shared by the console and desktop interfaces."""

from dataclasses import dataclass
from datetime import datetime
import logging
import re
import time

from aura.actions.registry import ActionRegistry
from aura.actions.router import IntentRouter

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AssistantReply:
    message: str
    functions: tuple[str, ...] = ()


def local_shortcut(text: str) -> str | None:
    phrase = re.sub(r"[^a-z0-9 ]", "", text.casefold()).strip()
    greetings = {"hi", "hello", "hey", "hi aura", "hello aura", "hey aura",
                 "good morning", "good afternoon", "good evening",
                 "good morning aura", "good afternoon aura", "good evening aura"}
    function_requests = {"list functions", "list available functions", "show functions",
                         "show available functions", "show me available functions",
                         "list commands", "list available commands", "what functions are available",
                         "what commands can you do", "what can you do", "help"}
    if phrase in greetings:
        return "greet"
    if phrase in function_requests:
        return "list_functions"
    return None


def local_app_request(text: str, aliases: dict[str, str]) -> tuple[str, dict] | None:
    """Handle unambiguous app commands without spending time on model routing."""
    phrase = text.casefold().strip()
    if "spotify" in phrase:
        if re.search(r"\b(toggle|pause|resume|play|unpause)\b", phrase):
            return "toggle_spotify", {}
        if re.search(r"\b(listen to|open|launch|start)\b", phrase):
            return "open_app", {"app_id": "spotify"}

    if not re.search(r"\b(open|launch|start|schedule)\b", phrase):
        return None
    matched_app = None
    for alias in sorted(aliases, key=len, reverse=True):
        if re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", phrase):
            matched_app = aliases[alias]
            break
    if not matched_app:
        return None

    delay = re.search(r"\b(?:in|after)\s+(\d+)\s+(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?)\b", phrase)
    if delay:
        amount = int(delay.group(1))
        unit = delay.group(2)
        multiplier = 1 if unit.startswith(("second", "sec")) else 60 if unit.startswith(("minute", "min")) else 3600 if unit.startswith(("hour", "hr")) else 86400
        return "schedule_open_app", {"app_id": matched_app, "delay_seconds": amount * multiplier}
    if re.search(r"\b(at|every|tomorrow|tonight|weekday|weekly|daily)\b", phrase):
        return None
    return "open_app", {"app_id": matched_app}


class AssistantCore:
    """Coordinates intent routing, confirmation, and registered action execution."""

    def __init__(self, registry: ActionRegistry, router: IntentRouter, aliases: dict[str, str],
                 context_provider=None):
        self.registry, self.router, self.aliases = registry, router, aliases
        self.context_provider = context_provider
        self._pending_confirmation: tuple[str, dict] | None = None

    def handle(self, text: str) -> AssistantReply:
        text = text.strip()
        if not text:
            return AssistantReply("Please enter a request.")

        self.registry.request_started_at = datetime.now().astimezone()
        if self._pending_confirmation:
            action, arguments = self._pending_confirmation
            self._pending_confirmation = None
            if text.casefold().strip(" .!?") in {"yes", "confirm", "do it", "proceed"}:
                result = self.registry.execute(action, arguments)
                log.info("Confirmed action %s result=%s", action, result.success)
                return self._from_result(result)
            return AssistantReply("Okay, cancelled.")

        shortcut = local_shortcut(text)
        if shortcut:
            return self._from_result(self.registry.execute(shortcut, {}))

        direct_app = local_app_request(text, self.aliases)
        if direct_app:
            intent, arguments = direct_app
            return self._from_result(self.registry.execute(intent, arguments))

        try:
            route_started = time.perf_counter()
            context = self.context_provider() if self.context_provider else None
            decision = self.router.route(text, context=context) if context else self.router.route(text)
            log.debug("Intent route completed in %.2fs", time.perf_counter() - route_started)
        except Exception:
            if log.isEnabledFor(logging.DEBUG):
                log.exception("Intent routing failed")
            else:
                log.warning("Intent routing failed")
            return AssistantReply("I couldn't reach the local language model. Check that Ollama is running.")

        log.debug("Validated routing kind=%s intent=%s", decision.get("kind"), decision.get("intent"))
        if decision["kind"] != "action":
            return AssistantReply(decision["message"])
        if decision["requires_confirmation"]:
            self._pending_confirmation = (decision["intent"], decision["arguments"])
            return AssistantReply("Are you sure? Say yes to confirm or no to cancel.")

        result = self.registry.execute(decision["intent"], decision["arguments"])
        log.info("Action %s completed success=%s", decision["intent"], result.success)
        return self._from_result(result)

    @staticmethod
    def _from_result(result) -> AssistantReply:
        functions = tuple(result.data.get("display_functions", ()))
        return AssistantReply(result.message, functions)
