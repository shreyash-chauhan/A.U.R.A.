class ConsoleSpeaker:
    def speak(self, text: str) -> None:
        print(f"AURA: {text}")


class OptionalTTS:
    def speak(self, text: str) -> None:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
        except Exception:
            print(f"AURA: {text}")


class OptionalMicrophone:
    def listen(self) -> str:
        """Offline Vosk recognizer; model files are supplied separately by the user."""
        import json
        import os
        import pyaudio
        from vosk import KaldiRecognizer, Model
        model_path = os.getenv("AURA_VOSK_MODEL_PATH")
        if not model_path:
            raise RuntimeError("Set AURA_VOSK_MODEL_PATH to an installed offline Vosk model")
        model = Model(model_path)
        recognizer = KaldiRecognizer(model, 16000)
        stream = pyaudio.PyAudio().open(format=pyaudio.paInt16, channels=1, rate=16000,
                                        input=True, frames_per_buffer=8000)
        stream.start_stream()
        try:
            while True:
                data = stream.read(4000, exception_on_overflow=False)
                if recognizer.AcceptWaveform(data):
                    phrase = json.loads(recognizer.Result()).get("text", "").strip()
                    if phrase: return phrase
        finally:
            stream.stop_stream()
            stream.close()
