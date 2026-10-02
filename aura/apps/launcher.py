import os
import shutil
import subprocess
import sys
from pathlib import Path
import re
from aura.apps.catalog import APPS, AppSpec


class AppLauncher:
    def __init__(self):
        self._cache: dict[str, str | None] = {}

    @staticmethod
    def _start_menu_candidates() -> list[Path]:
        roots = [Path(os.getenv("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs",
                 Path(os.getenv("PROGRAMDATA", "C:/ProgramData")) / r"Microsoft\Windows\Start Menu\Programs"]
        return [p for root in roots if root.exists() for p in root.rglob("*.lnk")]

    def resolve(self, spec: AppSpec) -> str | None:
        if spec.app_id in self._cache:
            return self._cache[spec.app_id]
        found = None
        for candidate in spec.candidates:
            if candidate.endswith(":"):
                found = candidate
                break
            found = shutil.which(candidate)
            if found:
                break
        if not found and sys.platform == "win32":
            # Windows App Paths registration is a common source for installed desktop apps.
            try:
                import winreg
                for candidate in spec.candidates:
                    if candidate.endswith(":"): continue
                    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                            try:
                                key = winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{candidate}", 0,
                                                     winreg.KEY_READ | view)
                                found = winreg.QueryValue(key, None)
                                winreg.CloseKey(key)
                                if found: break
                            except OSError: pass
                        if found: break
                    if found: break
            except ImportError: pass
        if not found and sys.platform == "win32":
            # Match installed Start Menu shortcuts by app name and registered aliases.
            def normalized(value: str) -> str:
                return re.sub(r"[^a-z0-9]", "", value.casefold())
            shortcuts = self._start_menu_candidates()
            names = [spec.display_name, *spec.aliases, spec.app_id.replace("_", " ")]
            exact_names = {normalized(name) for name in names if normalized(name)}
            exact = [shortcut for shortcut in shortcuts if normalized(shortcut.stem) in exact_names]
            if exact:
                found = str(exact[0])
            else:
                partial_names = [normalized(name) for name in names if len(normalized(name)) >= 5]
                partial = [shortcut for shortcut in shortcuts if any(
                    name in normalized(shortcut.stem) for name in partial_names)]
                if len(partial) == 1:
                    found = str(partial[0])
        self._cache[spec.app_id] = found
        return found

    def open(self, spec: AppSpec) -> tuple[bool, str]:
        target = self.resolve(spec)
        if not target:
            return False, f"I couldn't find {spec.display_name} on this computer."
        try:
            if target.endswith(":") or target.lower().endswith(".lnk"):
                os.startfile(target)  # type: ignore[attr-defined]
            else:
                subprocess.Popen([target], shell=False, close_fds=True)
            return True, f"Opening {spec.display_name}."
        except (OSError, subprocess.SubprocessError):
            self._cache.pop(spec.app_id, None)
            return False, f"I couldn't open {spec.display_name}."

    @staticmethod
    def running(spec: AppSpec) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import psutil
            names = {p.casefold() for p in spec.process_names}
            return any(p.info.get("name", "").casefold() in names for p in psutil.process_iter(["name"]))
        except Exception:
            return False

    @staticmethod
    def close(spec: AppSpec) -> bool:
        if sys.platform != "win32" or not spec.process_names:
            return False
        try:
            import psutil
            names = {p.casefold() for p in spec.process_names}
            found = False
            for proc in psutil.process_iter(["name"]):
                if proc.info.get("name", "").casefold() in names:
                    proc.terminate()
                    found = True
            return found
        except Exception:
            return False

    @staticmethod
    def focus(spec: AppSpec) -> bool:
        if sys.platform != "win32" or not spec.process_names: return False
        try:
            import ctypes
            from ctypes import wintypes
            names = {name.casefold() for name in spec.process_names}
            user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
            EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            focused = {"ok": False}
            def visit(hwnd, _):
                if not user32.IsWindowVisible(hwnd): return True
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                process = kernel32.OpenProcess(0x1000, False, pid.value)
                if not process: return True
                try:
                    buf = ctypes.create_unicode_buffer(260)
                    size = wintypes.DWORD(len(buf))
                    if kernel32.QueryFullProcessImageNameW(process, 0, buf, ctypes.byref(size)):
                        if Path(buf.value).name.casefold() in names:
                            user32.ShowWindow(hwnd, 9)
                            focused["ok"] = bool(user32.SetForegroundWindow(hwnd))
                            if focused["ok"]: return False
                finally:
                    kernel32.CloseHandle(process)
                return True
            user32.EnumWindows(EnumWindowsProc(visit), 0)
            return focused["ok"]
        except Exception:
            return False
