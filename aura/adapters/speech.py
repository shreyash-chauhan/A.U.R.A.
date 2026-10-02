"""Local neural speech output (Piper) and recognition (faster-whisper)."""

from __future__ import annotations

from collections import deque
from pathlib import Path
import logging
import os
import queue
import threading
import urllib.request

log = logging.getLogger(__name__)
DEFAULT_PIPER_VOICE = "en_US-lessac-medium"
PIPER_MODEL_BASE = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/"
    "en/en_US/lessac/medium"
)
WHISPER_PROMPT = (
    "AURA, open Chrome, Spotify, VS Code, reminders, timers, and Pomodoro. "
    "The user speaks English with an Indian accent."
)


class ConsoleSpeaker:
    """Text output for the command-line interface."""
    def speak(self, text: str):
        print(f"AURA: {text}")


def _app_data_dir() -> Path:
    base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData/Local"))
    return base / "AURA"


class PiperSpeechOutput:
    """Queue neural TTS on one worker and play audio through the default output."""
    def __init__(self, voice: str | None = None, on_status=lambda _s: None):
        self.voice_id = voice or os.getenv("AURA_PIPER_VOICE", DEFAULT_PIPER_VOICE)
        self.voice_dir = _app_data_dir() / "voices"
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._status = "Piper voice will load on first use"
        self._on_status = on_status

    @property
    def status(self):
        return self._status

    def _set_status(self, status: str):
        self._status = status
        try:
            self._on_status(status)
        except Exception:
            log.debug("Could not report TTS state", exc_info=True)

    def _voice_paths(self):
        return (self.voice_dir / f"{self.voice_id}.onnx",
                self.voice_dir / f"{self.voice_id}.onnx.json")

    def _ensure_voice(self):
        model_path, config_path = self._voice_paths()
        if model_path.is_file() and config_path.is_file():
            return model_path
        if self.voice_id != DEFAULT_PIPER_VOICE:
            raise FileNotFoundError(
                f"The configured Piper voice '{self.voice_id}' is not installed."
            )
        self.voice_dir.mkdir(parents=True, exist_ok=True)
        self._set_status("Downloading Piper voice (about 64 MB; one time)…")
        for filename in (model_path.name, config_path.name):
            target = self.voice_dir / filename
            if target.is_file():
                continue
            temporary = target.with_suffix(target.suffix + ".download")
            url = f"{PIPER_MODEL_BASE}/{filename}?download=true"
            request = urllib.request.Request(url, headers={"User-Agent": "AURA/0.2"})
            try:
                with urllib.request.urlopen(request, timeout=90) as response, temporary.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        return model_path

    def speak(self, text: str):
        if not text:
            return
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="AURA-Piper-TTS", daemon=True)
                self._thread.start()
        self._queue.put(str(text))

    def _play(self, voice, text: str):
        import sounddevice as sd
        chunks = iter(voice.synthesize(text))
        first = next(chunks, None)
        if first is None:
            return
        with sd.RawOutputStream(samplerate=first.sample_rate,
                                channels=first.sample_channels,
                                dtype="int16") as output:
            output.write(first.audio_int16_bytes)
            for chunk in chunks:
                output.write(chunk.audio_int16_bytes)

    def _run(self):
        voice = None
        try:
            while True:
                text = self._queue.get()
                if text is None:
                    break
                try:
                    if voice is None:
                        self._set_status("Loading Piper neural voice…")
                        from piper import PiperVoice
                        voice = PiperVoice.load(str(self._ensure_voice()))
                    self._set_status("Speaking with Piper")
                    self._play(voice, text)
                    self._set_status("Piper voice ready")
                except Exception as exc:
                    log.exception("Piper speech output failed")
                    self._set_status(f"Speech unavailable — {exc}")
                    voice = None
        except Exception:
            log.exception("Piper speech worker failed")
            self._set_status("Speech worker stopped unexpectedly")

    def stop(self):
        self._queue.put(None)
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)


class WhisperMicrophone:
    """Opt-in local Whisper listener with pause-based utterance capture."""
    sample_rate = 16000
    frame_samples = 320  # 20 ms, mono, int16
    frame_bytes = frame_samples * 2

    def __init__(self, model_name: str = "small.en"):
        self.model_name = model_name
        self.model_dir = _app_data_dir() / "models"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._on_text = None
        self._on_status = None
        self._status = "Off"
        self._recognized: queue.Queue[str] = queue.Queue()
        self._restart_requested = False
        self._lifecycle_lock = threading.Lock()
        self._model = None

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
            self._thread = threading.Thread(target=self._run, name="AURA-Whisper-STT", daemon=True)
            self._thread.start()

    def _run(self):
        self._listen()
        with self._lifecycle_lock:
            if self._restart_requested and not self._stop.is_set():
                self._restart_requested = False
                self._stop.clear()
                self._thread = threading.Thread(target=self._run, name="AURA-Whisper-STT", daemon=True)
                self._thread.start()

    def listen(self) -> str:
        """Blocking single-result mode for the legacy console interface."""
        if not self.running:
            self.start(self._recognized.put)
        return self._recognized.get()

    def _set_status(self, status: str):
        self._status = status
        try:
            self._on_status(status)
        except Exception:
            log.debug("Could not report microphone state", exc_info=True)

    def _load_model(self):
        if self._model is not None:
            return self._model
        from faster_whisper import WhisperModel
        self._set_status(f"Loading Whisper {self.model_name} on CPU; first setup downloads the model…")
        self.model_dir.mkdir(parents=True, exist_ok=True)
        cpu_threads = max(2, min(8, (os.cpu_count() or 4) - 2))
        self._model = WhisperModel(
            self.model_name, device="cpu", compute_type="int8",
            cpu_threads=cpu_threads, download_root=str(self.model_dir),
        )
        return self._model

    def _capture_utterance(self, stream):
        import numpy as np
        history: deque[tuple[bytes, bool]] = deque(maxlen=15)
        frames: list[bytes] = []
        recording = False
        silence_frames = 0
        noise_floor = 55.0
        max_frames = 1200  # Allow a natural sentence while staying below Whisper's 30-second window.

        while not self._stop.is_set():
            audio, overflowed = stream.read(self.frame_samples)
            if overflowed:
                log.debug("Microphone audio buffer overflow")
            frame = bytes(audio)
            if len(frame) != self.frame_bytes:
                continue
            samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
            level = float(np.sqrt(np.mean(samples * samples)))
            threshold = max(110.0, noise_floor * 2.4)
            active = level >= threshold

            if not recording:
                history.append((frame, active))
                if level < threshold:
                    noise_floor = noise_floor * 0.98 + level * 0.02
                if sum(1 for _audio, voiced in history if voiced) >= 3:
                    recording = True
                    frames = [audio_frame for audio_frame, _voiced in history]
                    self._set_status("Listening — local Whisper recognition")
            else:
                frames.append(frame)
                if active:
                    silence_frames = 0
                else:
                    silence_frames += 1
                if silence_frames >= 55 or len(frames) >= max_frames:
                    return b"".join(frames)
        return None

    def _transcribe(self, model, audio_bytes):
        import numpy as np
        samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = model.transcribe(
            samples, language="en", beam_size=5, temperature=0,
            vad_filter=True, vad_parameters={"min_silence_duration_ms": 250},
            initial_prompt=WHISPER_PROMPT, condition_on_previous_text=False,
            no_speech_threshold=0.55,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    def _listen(self):
        try:
            import sounddevice as sd
            model = self._load_model()
            if self._stop.is_set():
                self._set_status("Off")
                return
            self._set_status("Whisper ready — microphone is listening")
            while not self._stop.is_set():
                with sd.RawInputStream(
                    samplerate=self.sample_rate, blocksize=self.frame_samples,
                    dtype="int16", channels=1,
                ) as stream:
                    audio = self._capture_utterance(stream)
                if audio is None or self._stop.is_set():
                    break
                self._set_status("Transcribing locally…")
                text = self._transcribe(model, audio)
                if text and not self._stop.is_set():
                    log.debug("Whisper recognized %d characters", len(text))
                    self._on_text(text)
                self._set_status("Whisper ready — microphone is listening")
        except Exception as exc:
            if not self._stop.is_set():
                log.exception("Whisper microphone recognition failed")
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
