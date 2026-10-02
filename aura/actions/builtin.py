from aura.models import ActionSpec

S = lambda typ, **kw: {"type": typ, **kw}
OBJ = lambda properties, required=(): {"type":"object", "properties":properties, "required":list(required), "additionalProperties":False}


def register_builtins(registry, handlers):
    from aura.apps.catalog import APPS
    app_ids = sorted(APPS)
    app_schema = OBJ({"app_id":S("string",maxLength=80)}, ["app_id"])
    for action, desc, fn in [("open_app","Open a registered application",handlers.open_app),
                             ("close_app","Close a registered application",handlers.close_app),
                             ("restart_app","Restart a registered application",handlers.restart_app),
                             ("focus_app","Bring a registered application forward",handlers.focus_app)]:
        details = ("; registered app IDs: " + ", ".join(
            f"{app_id}={APPS[app_id].display_name}" for app_id in app_ids)) if action == "open_app" else ""
        registry.register(ActionSpec(action,desc + details,app_schema,fn,examples=("Open Chrome.",)))
    registry.register(ActionSpec("open_url","Open a safe HTTP or HTTPS web address",OBJ({"url":S("string",maxLength=2048)},["url"]),handlers.open_url))
    registry.register(ActionSpec("search_web","Search the web",OBJ({"query":S("string",maxLength=500)},["query"]),handlers.search_web))
    registry.register(ActionSpec("search_youtube","Search YouTube",OBJ({"query":S("string",maxLength=500)},["query"]),handlers.search_youtube))
    for shortcut in ("google","youtube","github","chatgpt","google_drive"):
        registry.register(ActionSpec("open_"+shortcut,"Open " + shortcut.replace("_"," "),OBJ({}),lambda s=shortcut: handlers.open_shortcut(s)))
    registry.register(ActionSpec("create_reminder","Set a persistent reminder. Convert relative times to a future ISO-8601 local datetime. Recurrence is optional JSON text such as daily or weekly.",OBJ({"text":S("string",maxLength=500),"datetime":S("string",maxLength=64),"recurrence":S("string",maxLength=200,nullable=True)},["text","datetime"]),handlers.create_reminder,
        examples=("Set a reminder for breakfast at 8 AM.","Remind me to have breakfast at 8 AM.","Remind me tomorrow at 9 AM to attend class.","Remind me every Monday at 8 AM to check my timetable.")))
    registry.register(ActionSpec("list_reminders","List pending reminders",OBJ({}),handlers.list_reminders,examples=("List my reminders.",)))
    registry.register(ActionSpec("delete_reminder","Delete a pending reminder",OBJ({"reminder_id":S("integer",minimum=1)},["reminder_id"]),handlers.delete_reminder))
    registry.register(ActionSpec("edit_reminder","Edit a pending reminder",OBJ({"reminder_id":S("integer",minimum=1),"text":S("string",maxLength=500,nullable=True),"datetime":S("string",maxLength=64,nullable=True)},["reminder_id"]),handlers.edit_reminder))
    registry.register(ActionSpec("snooze_reminder","Snooze a pending reminder",OBJ({"reminder_id":S("integer",minimum=1),"minutes":S("integer",minimum=1,maximum=10080)},["reminder_id","minutes"]),handlers.snooze_reminder))
    registry.register(ActionSpec("set_timer","Set a timer from an explicit duration, converted to seconds; clarify if the user omitted its unit",OBJ({"seconds":S("integer",minimum=1,maximum=604800)},["seconds"]),handlers.set_timer,
        examples=("Set a timer for 5 minutes.","Set a timer for 30 seconds.")))
    registry.register(ActionSpec("start_pomodoro","Start a focus Pomodoro with optional work minutes, break minutes, and cycle count",OBJ({
        "work_minutes":S("integer",minimum=1,maximum=180,nullable=True),"break_minutes":S("integer",minimum=1,maximum=60,nullable=True),"cycles":S("integer",minimum=1,maximum=12,nullable=True)}),handlers.start_pomodoro,
        examples=("Start a Pomodoro.","Start a 50 minute focus session with a 10 minute break.")))
    registry.register(ActionSpec("cancel_pomodoro","Cancel the active Pomodoro",OBJ({}),handlers.cancel_pomodoro))
    registry.register(ActionSpec("schedule_open_app","Schedule a registered application at a local clock time or after a delay in seconds",OBJ({
        "app_id":S("string",maxLength=80),"datetime":S("string",maxLength=64,nullable=True),
        "delay_seconds":S("integer",minimum=1,maximum=604800,nullable=True),
        "recurrence":S("string",enum=["once","daily","weekdays","weekly"],nullable=True)
    },["app_id"]),handlers.schedule_open_app,
        examples=("Open Chrome in 10 seconds.","Open Chrome at 6 PM.","Open VS Code every weekday at 9 AM.","Open Teams every Monday at 10 AM.")))
    registry.register(ActionSpec("list_app_schedules","List scheduled app launches",OBJ({}),handlers.list_app_schedules))
    registry.register(ActionSpec("cancel_app_schedule","Cancel a scheduled app launch",OBJ({"schedule_id":S("integer",minimum=1)},["schedule_id"]),handlers.cancel_app_schedule))
    registry.register(ActionSpec("greet","Respond to a greeting",OBJ({}),handlers.greet,
        examples=("Hello AURA.","Good morning.")))
    registry.register(ActionSpec("list_functions","Display the IDs of all registered AURA functions",OBJ({}),handlers.list_functions,
        examples=("List available functions.","What commands can you do?")))
    registry.register(ActionSpec("explain_function","Explain a registered AURA function, its arguments, and an example",
        OBJ({"function_id":S("string",maxLength=100)},["function_id"]),handlers.explain_function,
        examples=("Explain the open_app function.","What does schedule_open_app do?")))
    registry.register(ActionSpec("cancel_timer","Cancel a timer",OBJ({"timer_id":S("string",maxLength=36,nullable=True)}),handlers.cancel_timer))
    registry.register(ActionSpec("list_timers","List active timers",OBJ({}),handlers.list_timers))
    registry.register(ActionSpec("get_current_time","Report the local time",OBJ({}),handlers.time_now))
    registry.register(ActionSpec("get_current_date","Report the local date",OBJ({}),handlers.date_now))
    for action, direction in [("volume_up","up"),("volume_down","down"),("mute","mute"),("unmute","unmute")]:
        registry.register(ActionSpec(action,"Adjust system volume",OBJ({}),lambda d=direction: handlers.volume(d)))
    for action, key in [("play_pause","play"),("next_track","next"),("previous_track","previous")]:
        registry.register(ActionSpec(action,"Control media playback",OBJ({}),lambda k=key: handlers.media_key(k)))
    registry.register(ActionSpec("toggle_spotify","Send the Windows play/pause media key for Spotify playback",
        OBJ({}),handlers.toggle_spotify,examples=("Toggle Spotify.","Pause Spotify.","Resume Spotify.")))
    for action, kind in [("shutdown_pc","shutdown"),("restart_pc","restart")]:
        registry.register(ActionSpec(action,f"{kind.title()} the computer",OBJ({}),lambda k=kind: handlers.system_power(k),True))
    registry.register(ActionSpec("lock_pc","Lock the computer",OBJ({}),handlers.lock_pc))
    registry.register(ActionSpec("open_settings","Open Windows Settings",OBJ({}),lambda: handlers.open_app("settings")))
    registry.register(ActionSpec("open_task_manager","Open Task Manager",OBJ({}),lambda: handlers.open_app("task_manager")))
    registry.register(ActionSpec("open_file_explorer","Open File Explorer",OBJ({}),lambda: handlers.open_app("explorer")))
    for folder in ("downloads","documents","desktop"):
        registry.register(ActionSpec("open_"+folder,"Open the " + folder + " folder",OBJ({}),lambda f=folder: handlers.open_known_folder(f)))
    registry.register(ActionSpec("create_folder","Create a folder under Documents",OBJ({"name":S("string",maxLength=100)},["name"]),handlers.create_folder))
    registry.register(ActionSpec("open_file","Open a file in a known user folder",OBJ({"path":S("string",maxLength=2048)},["path"]),lambda path: handlers.open_user_path(path,False)))
    registry.register(ActionSpec("open_folder","Open a folder in a known user folder",OBJ({"path":S("string",maxLength=2048)},["path"]),lambda path: handlers.open_user_path(path,True)))
    registry.register(ActionSpec("search_files","Search filenames in Documents, Downloads, and Desktop",OBJ({"query":S("string",maxLength=100)},["query"]),handlers.search_files))
    for action, app_id in [("open_calculator","calculator"),("open_notes","notepad"),("open_calendar","outlook")]:
        registry.register(ActionSpec(action,"Open " + app_id.replace("_"," "),OBJ({}),lambda a=app_id: handlers.open_app(a)))
    registry.register(ActionSpec("fallback","Handle unsupported requests",OBJ({"original_text":S("string",maxLength=1000)}),handlers.fallback))
