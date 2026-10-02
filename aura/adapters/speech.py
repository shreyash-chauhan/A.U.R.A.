"""Offline microphone recognition and Windows speech output."""

from __future__ import annotations

from pathlib import Path
import json
import logging
import os
import queue
import shutil
import threading
import urllib.request
import zipfile

log = logging.getLogger(__name__)
MODEL_NAME = "vosk-model-small-en-in-0.4"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"


class ConsoleSpeaker:
    """Text output for the command-line interface."""
    def speak(self, text: str):
        print(f"AURA: {text}")


def default_model_dir() -> Path:
    base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData/Local"))
    return base / "AURA" / "models" / MODEL_NAME


class WindowsSpeechOutput:
    """Serialize TTS on one worker; uses Windows SAPI through pyttsx3."""
    def __init__(self):
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._enabled = True
        self._status = "Ready when enabled"

    @property
    def status(self):
        return self._status

    @property
    def enabled(self):
        return self._enabled

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)

    def speak(self, text: str):
        if not self._enabled or not text:
            return
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="AURA-TTS", daemon=True)
                self._thread.start()
        self._queue.put(str(text))

    def _run(self):
        engine = None
        while True:
            text = self._queue.get()
            if text is None:
                break
            if not self._enabled:
                continue
            try:
                if engine is None:
                    import pyttsx3
                    engine = pyttsx3.init("sapi5")
                    self._status = "Windows speech ready"
                engine.say(text)
                engine.runAndWait()
            except Exception:
                self._status = "Speech output unavailable — check Windows audio"
                log.exception("Windows TTS failed")
                engine = None

    def stop(self):
        self._queue.put(None)
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)


class OfflineMicrophone:
    """Opt-in Vosk microphone listener. Audio is processed locally and discarded."""
    def __init__(self, model_path: str | Path | None = None):
        self.model_path = Path(model_path).expanduser() if model_path else default_model_dir()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._on_text = None
        self._on_status = None
        self._status = "Off"
        self._recognized: queue.Queue[str] = queue.Queue()
        self._restart_requested = False
        self._lifecycle_lock = threading.Lock()

    @property
    def status(self):
        return self._status

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    def start(self, on_text, on_status=lambda _s: None):
        with self._lifecycle_lock:
            if self.running:
                if self._stop.is_set():
                    self._on_text, self._on_status = on_text, on_status
                    self._restart_requested = True
                return
            self._on_text, self._on_status = on_text, on_status
            self._stop.clear()
            self._restart_requested = False
            self._thread = threading.Thread(target=self._run, name="AURA-microphone", daemon=True)
            self._thread.start()

    def _run(self):
        self._listen()
        with self._lifecycle_lock:
            if self._restart_requested and not self._stop.is_set():
                on_text, on_status = self._on_text, self._on_status
                self._restart_requested = False
                self._stop.clear()
                self._thread = threading.Thread(target=self._run, name="AURA-microphone", daemon=True)
                self._thread.start()

    def listen(self) -> str:
        """Blocking single-result mode for the legacy console interface."""
        if not self.running:
            self.start(self._recognized.put)
        return self._recognized.get()

    def _set_status(self, value):
        self._status = value
        try:
            self._on_status(value)
        except Exception:
            log.debug("Could not report microphone state", exc_info=True)

    def _ensure_model(self):
        if (self.model_path / "am").is_dir() and (self.model_path / "conf").is_dir():
            return self.model_path
        self._set_status("Downloading offline English model (about 36 MB)…")
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        archive = self.model_path.parent / f"{MODEL_NAME}.zip.download"
        staging = self.model_path.parent / f".{MODEL_NAME}.extracting"
        try:
            request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "AURA/0.1"})
            with urllib.request.urlopen(request, timeout=60) as response, archive.open("wb") as out:
                shutil.copyfileobj(response, out)
            if self._stop.is_set():
                raise InterruptedError("Microphone was disabled during model setup")
            staging.mkdir(parents=True, exist_ok=True)
            root = staging.resolve()
            with zipfile.ZipFile(archive) as zf:
                for info in zf.infolist():
                    target = (staging / info.filename).resolve()
                    if target != root and root not in target.parents:
                        raise ValueError("Unsafe path in speech model archive")
                zf.extractall(staging)
            extracted = staging / MODEL_NAME
            if not (extracted / "am").is_dir():
                raise ValueError("Speech model archive did not contain the expected model")
            if self.model_path.exists():
                raise FileExistsError(
                    f"The configured speech model folder is incomplete: {self.model_path}"
                )
            extracted.replace(self.model_path)
            return self.model_path
        finally:
            archive.unlink(missing_ok=True)
            shutil.rmtree(staging, ignore_errors=True)

    def _listen(self):
        try:
            import sounddevice as sd
            import vosk
            vosk.SetLogLevel(-1)
            model = vosk.Model(str(self._ensure_model()))
            if self._stop.is_set():
                self._set_status("Off")
                return
            recognizer = vosk.KaldiRecognizer(model, 16000)
            self._set_status("Listening — local processing")
            with sd.RawInputStream(samplerate=16000, blocksize=8000, dtype="int16",
                                   channels=1) as stream:
                while not self._stop.is_set():
                    data, overflowed = stream.read(4000)
                    if overflowed:
                        log.debug("Microphone audio buffer overflow")
                    if recognizer.AcceptWaveform(bytes(data)):
                        text = json.loads(recognizer.Result()).get("text", "").strip()
                        if text and not self._stop.is_set():
                            self._on_text(text)
        except Exception as exc:
            if not self._stop.is_set():
                log.exception("Microphone recognition failed")
                self._set_status(f"Unavailable — {exc}")
                return
        self._set_status("Off")

    def stop(self):
        with self._lifecycle_lock:
            self._restart_requested = False
            self._stop.set()
            thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=0.25)
        if not self.running:
            self._set_status("Off")
