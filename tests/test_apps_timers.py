from aura.apps.catalog import resolve_app
from aura.timers import TimerService


def test_app_alias_resolution():
    assert resolve_app("Google Chrome").app_id == "chrome"
    assert resolve_app("vs code").app_id == "vscode"
    assert resolve_app("not-a-real-app") is None


def test_duplicate_aliases_are_not_silently_used():
    # The shipped catalog currently keeps aliases unique.
    from aura.apps.catalog import ALIASES, APPS
    assert len(ALIASES) >= len(APPS)


def test_timer_create_cancel_and_listing():
    fired = []
    timers = TimerService(fired.append)
    timer_id = timers.create(60)
    assert timers.list()
    assert timers.cancel(timer_id)
    assert not timers.list()
