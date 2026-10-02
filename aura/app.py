import argparse
import logging
import re
import sys
import time
from datetime import datetime
from aura.actions.builtin import register_builtins
from aura.actions.registry import ActionRegistry
from aura.actions.router import IntentRouter
from aura.actions.handlers import Handlers
from aura.actions.workflow_action import register_workflows
from aura.adapters.notifications import notify
from aura.adapters.ollama import OllamaClient
from aura.adapters.speech import ConsoleSpeaker, OptionalMicrophone, OptionalTTS
from aura.apps.launcher import AppLauncher
from aura.apps.catalog import ALIASES
from aura.config import Settings
from aura.db import Database
from aura.reminders import ReminderService
from aura.schedules import AppScheduleService
from aura.timers import TimerService
from aura.pomodoro import PomodoroService
from aura.workflows.runner import WorkflowRunner

log = logging.getLogger("aura")


def build(settings: Settings, initialize_db: bool = True):
    speaker = OptionalTTS() if "--voice" in sys.argv else ConsoleSpeaker()
    def alert(text):
        notify(text)
        speaker.speak(text)
    if initialize_db:
        db = Database(settings.db_path)
        reminders, timers = ReminderService(db, alert), TimerService(alert)
        launcher = AppLauncher()
        schedules = AppScheduleService(db, launcher, alert)
    else:
        reminders, timers, schedules = None, None, None
        launcher = AppLauncher()
    pomodoros = PomodoroService(alert)
    registry = ActionRegistry()
    handlers = Handlers(launcher, reminders, timers, pomodoros, schedules)
    register_builtins(registry, handlers)
    register_workflows(registry, WorkflowRunner(registry))
    handlers.registry = registry
    router = IntentRouter(registry, OllamaClient(
        settings.ollama_url, settings.ollama_model,
        keep_alive=settings.ollama_keep_alive, num_ctx=settings.ollama_num_ctx,
        num_predict=settings.ollama_num_predict), settings.min_confidence)
    return registry, router, speaker, reminders, schedules


def local_shortcut(text: str) -> str | None:
    phrase = re.sub(r"[^a-z0-9 ]", "", text.casefold()).strip()
    greetings = {"hi", "hello", "hey", "hi aura", "hello aura", "hey aura",
                 "good morning", "good afternoon", "good evening",
                 "good morning aura", "good afternoon aura", "good evening aura"}
    function_requests = {"list functions", "list available functions", "show functions",
                         "show available functions", "show me available functions",
                         "list commands", "list available commands", "what functions are available",
                         "what commands can you do", "what can you do", "help"}
    if phrase in greetings: return "greet"
    if phrase in function_requests: return "list_functions"
    return None


def local_app_request(text: str) -> tuple[str, dict] | None:
    """Handle unambiguous app commands without spending time on model routing."""
    phrase = text.casefold().strip()
    if "spotify" in phrase:
        if re.search(r"\b(toggle|pause|resume|play|unpause)\b", phrase):
            return "toggle_spotify", {}
        if re.search(r"\b(listen to|open|launch|start)\b", phrase):
            return "open_app", {"app_id": "spotify"}

    asks_to_open = re.search(r"\b(open|launch|start|schedule)\b", phrase)
    if not asks_to_open:
        return None
    matched_app = None
    for alias in sorted(ALIASES, key=len, reverse=True):
        if re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", phrase):
            matched_app = ALIASES[alias]
            break
    if not matched_app:
        return None

    delay = re.search(r"\b(?:in|after)\s+(\d+)\s+(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?)\b", phrase)
    if delay:
        amount = int(delay.group(1))
        unit = delay.group(2)
        multiplier = 1 if unit.startswith(("second", "sec")) else 60 if unit.startswith(("minute", "min")) else 3600 if unit.startswith(("hour", "hr")) else 86400
        return "schedule_open_app", {"app_id": matched_app, "delay_seconds": amount * multiplier}
    # Clock-time and recurring phrases need date interpretation from the router.
    if re.search(r"\b(at|every|tomorrow|tonight|weekday|weekly|daily)\b", phrase):
        return None
    return "open_app", {"app_id": matched_app}


def deliver(result, speaker):
    function_ids = result.data.get("display_functions")
    if function_ids:
        print("\nRegistered AURA functions:\n" + "\n".join(f"  - {name}" for name in function_ids))
    speaker.speak(result.message)


def main():
    parser = argparse.ArgumentParser(description="AURA local desktop assistant")
    parser.add_argument("--list-actions", action="store_true")
    parser.add_argument("--voice", action="store_true", help="Use optional speech recognition and TTS")
    args = parser.parse_args()
    settings = Settings()
    logging.basicConfig(level=logging.DEBUG if settings.debug else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    registry, router, speaker, reminders, schedules = build(settings, initialize_db=not args.list_actions)
    if args.list_actions:
        for item in registry.describe(): print(item["intent"], "—", item["description"])
        return
    reminders.start()
    schedules.start()
    mic = OptionalMicrophone() if args.voice else None
    speaker.speak("AURA is ready. Type a request, or type quit to exit.")
    pending_confirmation = None
    try:
        while True:
            try:
                text = mic.listen() if mic else input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            except Exception:
                speaker.speak("I couldn't hear that. Please try again.")
                continue
            if not text: continue
            if text.casefold() in {"quit", "exit", "stop aura"}:
                break
            log.debug("Input received (%d characters)", len(text))
            # Timestamp every request before either direct handling or inference.
            # Reusing the previous model request's timestamp made short schedules overdue.
            registry.request_started_at = datetime.now().astimezone()
            if pending_confirmation:
                action, arguments = pending_confirmation
                pending_confirmation = None
                if text.casefold().strip(" .!?") in {"yes", "confirm", "do it", "proceed"}:
                    result = registry.execute(action, arguments)
                    log.info("Confirmed action %s result=%s", action, result.success)
                    deliver(result, speaker)
                else:
                    speaker.speak("Okay, cancelled.")
                continue
            shortcut = local_shortcut(text)
            if shortcut:
                deliver(registry.execute(shortcut, {}), speaker)
                continue
            direct_app = local_app_request(text)
            if direct_app:
                intent, arguments = direct_app
                deliver(registry.execute(intent, arguments), speaker)
                continue
            try:
                route_started = time.perf_counter()
                decision = router.route(text)
                log.debug("Intent route completed in %.2fs", time.perf_counter()-route_started)
            except Exception:
                if settings.debug: log.exception("Intent routing failed")
                else: log.warning("Intent routing failed")
                speaker.speak("I couldn't reach the local language model. Check that Ollama is running.")
                continue
            log.debug("Validated routing kind=%s intent=%s", decision.get("kind"), decision.get("intent"))
            if decision["kind"] != "action":
                speaker.speak(decision["message"])
                continue
            if decision["requires_confirmation"]:
                pending_confirmation = (decision["intent"], decision["arguments"])
                speaker.speak("Are you sure? Say yes to confirm or no to cancel.")
                continue
            result = registry.execute(decision["intent"], decision["arguments"])
            log.info("Action %s completed success=%s", decision["intent"], result.success)
            deliver(result, speaker)
    finally:
        reminders.stop()
        schedules.stop()


if __name__ == "__main__": main()
