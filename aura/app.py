import argparse
import logging
import sys
from aura.actions.builtin import register_builtins
from aura.actions.registry import ActionRegistry
from aura.actions.router import IntentRouter
from aura.actions.handlers import Handlers
from aura.actions.workflow_action import register_workflows
from aura.adapters.notifications import notify
from aura.adapters.ollama import OllamaClient
from aura.adapters.speech import ConsoleSpeaker, OptionalMicrophone, OptionalTTS
from aura.apps.launcher import AppLauncher
from aura.config import Settings
from aura.db import Database
from aura.reminders import ReminderService
from aura.schedules import AppScheduleService
from aura.timers import TimerService
from aura.pomodoro import PomodoroService
from aura.workflows.runner import WorkflowRunner
from aura.core import AssistantCore

log = logging.getLogger("aura")


def build(settings: Settings, initialize_db: bool = True, speaker=None, notify_user=None):
    speaker = speaker or (OptionalTTS() if "--voice" in sys.argv else ConsoleSpeaker())
    def alert(text):
        notify(text)
        if notify_user:
            notify_user(text)
        else:
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
    return registry, router, speaker, reminders, schedules, timers, pomodoros


def main():
    parser = argparse.ArgumentParser(description="AURA local desktop assistant")
    parser.add_argument("--list-actions", action="store_true")
    parser.add_argument("--voice", action="store_true", help="Use optional speech recognition and TTS")
    parser.add_argument("--desktop", action="store_true", help="Open the desktop window and system tray")
    args = parser.parse_args()
    settings = Settings()
    logging.basicConfig(level=logging.DEBUG if settings.debug else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.desktop:
        from aura.desktop import run_desktop
        try:
            run_desktop(settings)
        except RuntimeError as exc:
            parser.error(str(exc))
        return
    registry, router, speaker, reminders, schedules, timers, pomodoros = build(
        settings, initialize_db=not args.list_actions
    )
    if args.list_actions:
        for item in registry.describe(): print(item["intent"], "—", item["description"])
        return
    reminders.start()
    schedules.start()
    from aura.apps.catalog import ALIASES
    core = AssistantCore(registry, router, ALIASES)
    mic = OptionalMicrophone() if args.voice else None
    speaker.speak("AURA is ready. Type a request, or type quit to exit.")
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
            reply = core.handle(text)
            if reply.functions:
                print("\nRegistered AURA functions:\n" + "\n".join(f"  - {name}" for name in reply.functions))
            speaker.speak(reply.message)
    finally:
        reminders.stop()
        schedules.stop()
        timers.stop()
        pomodoros.cancel()


if __name__ == "__main__": main()
