def notify(text: str) -> None:
    try:
        from winotify import Notification
        Notification(app_id="AURA", title="AURA reminder", msg=text, duration="long").show()
    except Exception:
        pass
