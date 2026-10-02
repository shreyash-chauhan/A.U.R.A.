"""Opt-in, on-device webcam face-in-frame signal. Frames are never saved."""

from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)


class WebcamPresence:
    def __init__(self, camera_index: int = 0, sample_interval: float = 1.0):
        self.camera_index = camera_index
        self.sample_interval = sample_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = "Off"
        self._on_status = lambda _status: None
        self._restart_requested = False
        self._lifecycle_lock = threading.Lock()

    @property
    def status(self):
        return self._status

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    def start(self, on_status=lambda _status: None):
        with self._lifecycle_lock:
            if self.running:
                if self._stop.is_set():
                    self._on_status = on_status
                    self._restart_requested = True
                return
            self._on_status = on_status
            self._stop.clear()
            self._restart_requested = False
            self._thread = threading.Thread(target=self._run, name="AURA-webcam", daemon=True)
            self._thread.start()

    def _run(self):
        self._observe()
        with self._lifecycle_lock:
            if self._restart_requested and not self._stop.is_set():
                self._restart_requested = False
                self._stop.clear()
                self._thread = threading.Thread(target=self._run, name="AURA-webcam", daemon=True)
                self._thread.start()

    def _set_status(self, status):
        self._status = status
        try:
            self._on_status(status)
        except Exception:
            log.debug("Could not report webcam state", exc_info=True)

    def _observe(self):
        camera = None
        try:
            import cv2
            camera = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            if not camera.isOpened():
                self._set_status("Unavailable — webcam could not be opened")
                return
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            detector = cv2.CascadeClassifier(cascade_path)
            if detector.empty():
                self._set_status("Unavailable — face detector could not be loaded")
                return
            # Require two consecutive observations before changing the state.
            last = None
            streak = 0
            self._set_status("Camera on — checking locally; no frames are saved")
            while not self._stop.is_set():
                ok, frame = camera.read()
                if not ok:
                    self._set_status("Unavailable — webcam frame could not be read")
                    break
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = detector.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5,
                                                  minSize=(45, 45))
                observed = "Face in frame" if len(faces) else "No face detected"
                if observed == last:
                    streak += 1
                else:
                    last, streak = observed, 1
                if streak >= 2 and self._status != observed:
                    self._set_status(observed)
                del frame, gray, faces
                self._stop.wait(self.sample_interval)
        except Exception as exc:
            if not self._stop.is_set():
                log.exception("Webcam presence detection failed")
                self._set_status(f"Unavailable — {exc}")
        finally:
            if camera is not None:
                camera.release()
            if self._stop.is_set():
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
