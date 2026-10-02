from dataclasses import dataclass


@dataclass(frozen=True)
class AppSpec:
    app_id: str
    display_name: str
    aliases: tuple[str, ...]
    candidates: tuple[str, ...] = ()
    process_names: tuple[str, ...] = ()


_rows = [
 ("chrome","Google Chrome",("chrome","google chrome"),("chrome.exe",),("chrome.exe",)),
 ("edge","Microsoft Edge",("edge","microsoft edge"),("msedge.exe",),("msedge.exe",)),
 ("firefox","Firefox",("firefox","mozilla firefox"),("firefox.exe",),("firefox.exe",)),
 ("brave","Brave",("brave","brave browser"),("brave.exe",),("brave.exe",)),
 ("opera","Opera",("opera","opera browser"),("opera.exe",),("opera.exe",)),
 ("vscode","Visual Studio Code",("vscode","vs code","visual studio code","code"),("Code.exe","code"),("Code.exe",)),
 ("visual_studio","Visual Studio",("visual studio",),("devenv.exe",),("devenv.exe",)),
 ("intellij","IntelliJ IDEA",("intellij","idea"),("idea64.exe",),("idea64.exe",)),
 ("pycharm","PyCharm",("pycharm",),("pycharm64.exe",),("pycharm64.exe",)),
 ("android_studio","Android Studio",("android studio",),("studio64.exe",),("studio64.exe",)),
 ("eclipse","Eclipse",("eclipse",),("eclipse.exe",),("eclipse.exe",)),
 ("arduino","Arduino IDE",("arduino","arduino ide"),("Arduino IDE.exe","arduino.exe"),("arduino.exe",)),
 ("matlab","MATLAB",("matlab",),("matlab.exe",),("matlab.exe",)),
 ("postman","Postman",("postman",),("Postman.exe",),("Postman.exe",)),
 ("github_desktop","GitHub Desktop",("github desktop",),("GitHubDesktop.exe",),("GitHubDesktop.exe",)),
 ("docker","Docker Desktop",("docker","docker desktop"),("Docker Desktop.exe",),("Docker Desktop.exe",)),
 ("jupyter","Jupyter",("jupyter",),("jupyter-lab.exe",),("jupyter-lab.exe",)),
 ("cursor","Cursor",("cursor",),("Cursor.exe",),("Cursor.exe",)),
 ("claude","Claude",("claude",),("Claude.exe",),("Claude.exe",)),
 ("discord","Discord",("discord",),("Update.exe",),("Discord.exe",)),
 ("whatsapp","WhatsApp",("whatsapp",),("WhatsApp.exe",),("WhatsApp.exe",)),
 ("telegram","Telegram",("telegram",),("Telegram.exe",),("Telegram.exe",)),
 ("teams","Microsoft Teams",("teams","microsoft teams"),("ms-teams.exe",),("ms-teams.exe",)),
 ("zoom","Zoom",("zoom",),("Zoom.exe",),("Zoom.exe",)),
 ("spotify","Spotify",("spotify",),("Spotify.exe",),("Spotify.exe",)),
 ("vlc","VLC",("vlc",),("vlc.exe",),("vlc.exe",)),
 ("obs","OBS Studio",("obs","obs studio"),("obs64.exe",),("obs64.exe",)),
 ("media_player","Windows Media Player",("media player","windows media player"),("wmplayer.exe",),("wmplayer.exe",)),
 ("steam","Steam",("steam",),("steam.exe",),("steam.exe",)),
 ("epic","Epic Games Launcher",("epic","epic games"),("EpicGamesLauncher.exe",),("EpicGamesLauncher.exe",)),
 ("xbox","Xbox",("xbox",),("XboxPcApp.exe",),("XboxPcApp.exe",)),
 ("ea","EA App",("ea app",),("EADesktop.exe",),("EADesktop.exe",)),
 ("ubisoft","Ubisoft Connect",("ubisoft","ubisoft connect"),("UbisoftConnect.exe",),("UbisoftConnect.exe",)),
 ("battlenet","Battle.net",("battle.net","battlenet"),("Battle.net.exe",),("Battle.net.exe",)),
 ("explorer","File Explorer",("file explorer","explorer"),("explorer.exe",),("explorer.exe",)),
 ("settings","Settings",("settings","windows settings"),("ms-settings:",),()),
 ("calculator","Calculator",("calculator","calc"),("calc.exe",),("CalculatorApp.exe",)),
 ("notepad","Notepad",("notepad",),("notepad.exe",),("Notepad.exe",)),
 ("paint","Paint",("paint","mspaint"),("mspaint.exe",),("mspaint.exe",)),
 ("snipping_tool","Snipping Tool",("snipping tool","snip"),("SnippingTool.exe",),("SnippingTool.exe",)),
 ("task_manager","Task Manager",("task manager",),("taskmgr.exe",),("Taskmgr.exe",)),
 ("terminal","Windows Terminal",("terminal","windows terminal"),("wt.exe",),("WindowsTerminal.exe",)),
 ("cmd","Command Prompt",("command prompt","cmd"),("cmd.exe",),("cmd.exe",)),
 ("powershell","PowerShell",("powershell",),("powershell.exe",),("powershell.exe",)),
 ("store","Microsoft Store",("microsoft store","store"),("ms-windows-store:",),()),
 ("nvidia","NVIDIA App",("nvidia","nvidia app"),("NVIDIA app.exe",),("NVIDIA app.exe",)),
 ("lenovo_vantage","Lenovo Vantage",("lenovo vantage",),("LenovoVantage.exe",),("LenovoVantage.exe",)),
 ("word","Microsoft Word",("word","microsoft word"),("WINWORD.EXE",),("WINWORD.EXE",)),
 ("excel","Microsoft Excel",("excel","microsoft excel"),("EXCEL.EXE",),("EXCEL.EXE",)),
 ("powerpoint","Microsoft PowerPoint",("powerpoint","microsoft powerpoint"),("POWERPNT.EXE",),("POWERPNT.EXE",)),
 ("onenote","Microsoft OneNote",("onenote","one note"),("ONENOTE.EXE",),("ONENOTE.EXE",)),
 ("outlook","Microsoft Outlook",("outlook",),("OUTLOOK.EXE",),("OUTLOOK.EXE",)),
]
APPS = {r[0]: AppSpec(r[0],r[1],r[2],r[3],r[4]) for r in _rows}
ALIASES = {alias.casefold(): app_id for app_id, spec in APPS.items() for alias in (app_id, *spec.aliases)}
_alias_owners = {}
for _app_id, _spec in APPS.items():
    for _alias in (_app_id, *_spec.aliases):
        _key = _alias.casefold()
        if _key in _alias_owners and _alias_owners[_key] != _app_id:
            raise ValueError(f"Duplicate application alias: {_alias}")
        _alias_owners[_key] = _app_id


def resolve_app(value: str) -> AppSpec | None:
    return APPS.get(ALIASES.get(value.strip().casefold(), ""))
