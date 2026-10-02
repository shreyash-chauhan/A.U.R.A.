"""Windows desktop window and system-tray shell for A.U.R.A."""

from datetime import datetime
import json
import logging
import urllib.error
import urllib.request

from aura.apps.catalog import ALIASES
from aura.app import build
from aura.core import AssistantCore
from aura.adapters.camera import WebcamPresence
from aura.adapters.speech import OfflineMicrophone, WindowsSpeechOutput

log = logging.getLogger(__name__)


def _qt():
    try:
        from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal
        from PySide6.QtGui import QAction, QIcon
        from PySide6.QtWidgets import (
            QApplication, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
            QListWidget, QMainWindow, QMenu, QMessageBox, QPushButton, QStyle,
            QSystemTrayIcon, QVBoxLayout, QWidget,
        )
    except ImportError as exc:
        raise RuntimeError(
            "The A.U.R.A. desktop interface needs its desktop dependencies. "
            'From the project folder, run: py -m pip install -e ".[desktop]". '
            "Then start A.U.R.A. again."
        ) from exc
    return locals()


def run_desktop(settings):
    qt = _qt()
    QApplication = qt["QApplication"]
    QDialog = qt["QDialog"]
    QFormLayout = qt["QFormLayout"]
    QHBoxLayout = qt["QHBoxLayout"]
    QLabel = qt["QLabel"]
    QLineEdit = qt["QLineEdit"]
    QListWidget = qt["QListWidget"]
    QMainWindow = qt["QMainWindow"]
    QMenu = qt["QMenu"]
    QMessageBox = qt["QMessageBox"]
    QPushButton = qt["QPushButton"]
    QStyle = qt["QStyle"]
    QSystemTrayIcon = qt["QSystemTrayIcon"]
    QVBoxLayout = qt["QVBoxLayout"]
    QWidget = qt["QWidget"]
    QAction = qt["QAction"]
    QIcon = qt["QIcon"]
    QThreadPool = qt["QThreadPool"]
    QTimer = qt["QTimer"]
    Qt = qt["Qt"]
    QObject = qt["QObject"]
    QRunnable = qt["QRunnable"]
    Signal = qt["Signal"]

    class TaskSignals(QObject):
        result = Signal(object, object)
        failed = Signal(object, str)

    class Task(QRunnable):
        def __init__(self, function, signals, on_result, on_failed):
            super().__init__()
            self.function = function
            self.signals = signals
            self.on_result, self.on_failed = on_result, on_failed

        def run(self):
            try:
                self.signals.result.emit(self.on_result, self.function())
            except Exception as exc:
                log.exception("Desktop background task failed")
                self.signals.failed.emit(self.on_failed, str(exc))

    class WindowSignals(QObject):
        reminder = Signal(str)
        voice_text = Signal(str)
        microphone_status = Signal(str)
        camera_status = Signal(str)

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("A.U.R.A. — Adaptive User Responsive Assistant")
            self.resize(760, 650)
            self.pool = QThreadPool.globalInstance()
            self.pool.setMaxThreadCount(3)
            self.task_signals = task_signals
            self.task_signals.result.connect(lambda callback, value: callback(value))
            self.task_signals.failed.connect(lambda callback, message: callback(message))
            self.signals = WindowSignals()
            self.signals.reminder.connect(self._add_event)
            self.signals.voice_text.connect(lambda text: self._submit_text(text, voice=True))
            self.signals.microphone_status.connect(self._microphone_status)
            self.signals.camera_status.connect(self._camera_status)
            self._request_active = False
            self._pending_voice = []
            self._camera_enabled = False
            self._ollama_check_active = False
            self._shutting_down = False
            self._build_ui()
            self._build_tray()
            self._init_runtime()
            self._refresh_ollama()
            self.status_timer = QTimer(self)
            self.status_timer.timeout.connect(self._refresh_ollama)
            self.status_timer.start(30000)

        def _build_ui(self):
            root = QWidget(self)
            layout = QVBoxLayout(root)
            title = QLabel("A.U.R.A.")
            title.setStyleSheet("font-size: 28px; font-weight: 700;")
            subtitle = QLabel("Adaptive User Responsive Assistant  ·  Local-first MDP prototype")
            subtitle.setStyleSheet("color: #64748b; font-size: 13px;")
            layout.addWidget(title)
            layout.addWidget(subtitle)

            status_title = QLabel("System status")
            status_title.setStyleSheet("font-size: 16px; font-weight: 600; margin-top: 12px;")
            layout.addWidget(status_title)
            self.status_labels = {}
            status_layout = QFormLayout()
            for name, initial in (
                ("Assistant", "Starting"),
                ("Microphone", "Off — enable when ready"),
                ("Speech output", "Windows speech, ready when needed"),
                ("Ollama service", "Checking local service…"),
                ("Qwen model", "Waiting for Ollama status"),
                ("Webcam", "Off — enable when ready"),
                ("Visual context", "Unknown — webcam is off"),
                ("ESP32 chair sensors", "Not connected"),
            ):
                value = QLabel(initial)
                value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                self.status_labels[name] = value
                status_layout.addRow(name, value)
            layout.addLayout(status_layout)

            privacy_row = QHBoxLayout()
            self.mic_button = QPushButton("Enable microphone")
            self.mic_button.setCheckable(True)
            self.mic_button.toggled.connect(self._toggle_microphone)
            self.camera_button = QPushButton("Enable webcam")
            self.camera_button.setCheckable(True)
            self.camera_button.toggled.connect(self._toggle_camera)
            privacy_row.addWidget(self.mic_button)
            privacy_row.addWidget(self.camera_button)
            privacy_row.addStretch(1)
            layout.addLayout(privacy_row)

            event_title = QLabel("Recent activity")
            event_title.setStyleSheet("font-size: 16px; font-weight: 600; margin-top: 12px;")
            layout.addWidget(event_title)
            self.events = QListWidget()
            self.events.setAlternatingRowColors(True)
            layout.addWidget(self.events, 1)

            command_row = QHBoxLayout()
            self.command = QLineEdit()
            self.command.setPlaceholderText("Type a request, for example: Open Chrome")
            self.command.returnPressed.connect(self._submit)
            self.send_button = QPushButton("Send")
            self.send_button.clicked.connect(self._submit)
            command_row.addWidget(self.command, 1)
            command_row.addWidget(self.send_button)
            layout.addLayout(command_row)

            footer = QHBoxLayout()
            self.settings_button = QPushButton("Settings")
            self.settings_button.clicked.connect(self._show_settings)
            self.status_button = QPushButton("Status")
            self.status_button.clicked.connect(self._refresh_ollama)
            exit_button = QPushButton("Exit A.U.R.A.")
            exit_button.clicked.connect(self._exit)
            footer.addWidget(self.settings_button)
            footer.addWidget(self.status_button)
            footer.addStretch(1)
            footer.addWidget(QLabel("Close this window to keep A.U.R.A. in the tray."))
            footer.addWidget(exit_button)
            layout.addLayout(footer)
            self.setCentralWidget(root)

        def _build_tray(self):
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
            self.tray = QSystemTrayIcon(QIcon(icon), self)
            self.tray.setToolTip("A.U.R.A. is running")
            menu = QMenu()
            open_action = QAction("Open A.U.R.A.", self)
            open_action.triggered.connect(self._show_window)
            menu.addAction(open_action)
            self.listening_action = QAction("Enable microphone", self)
            self.listening_action.setCheckable(True)
            self.listening_action.toggled.connect(self._set_microphone_enabled)
            menu.addAction(self.listening_action)
            self.presence_action = QAction("Enable webcam context", self)
            self.presence_action.setCheckable(True)
            self.presence_action.toggled.connect(self._set_camera_enabled)
            menu.addAction(self.presence_action)
            status_action = QAction("Status", self)
            status_action.triggered.connect(self._show_status)
            menu.addAction(status_action)
            settings_action = QAction("Settings", self)
            settings_action.triggered.connect(self._show_settings)
            menu.addAction(settings_action)
            menu.addSeparator()
            exit_action = QAction("Exit A.U.R.A.", self)
            exit_action.triggered.connect(self._exit)
            menu.addAction(exit_action)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(self._tray_activated)
            self.tray.show()

        def _init_runtime(self):
            self.speaker = WindowsSpeechOutput()
            self.microphone = OfflineMicrophone(settings.vosk_model_path)
            self.webcam = WebcamPresence()
            (self.registry, self.router, _speaker, self.reminders, self.schedules,
             self.timers, self.pomodoros) = build(
                settings, speaker=self.speaker, notify_user=self.signals.reminder.emit
            )
            self.core = AssistantCore(self.registry, self.router, ALIASES, self._context_snapshot)
            self.reminders.start()
            self.schedules.start()
            self.status_labels["Assistant"].setText("Running in tray")
            self._add_event("A.U.R.A. is ready. Type a request below.")

        def _add_event(self, text):
            stamp = datetime.now().astimezone().strftime("%I:%M:%S %p")
            self.events.insertItem(0, f"{stamp}  {text}")
            while self.events.count() > 100:
                self.events.takeItem(self.events.count() - 1)

        def _submit(self):
            text = self.command.text().strip()
            if not text:
                return
            self.command.clear()
            self._submit_text(text)

        def _submit_text(self, text, voice=False):
            if self._request_active:
                if voice:
                    self._pending_voice.append(text)
                return
            self._add_event(f"You: {text}")
            self._request_active = True
            self.send_button.setEnabled(False)
            self.command.setEnabled(False)
            self.status_labels["Assistant"].setText("Processing request…")
            task = Task(lambda: self.core.handle(text), self.task_signals,
                        self._handle_reply, self._handle_task_error)
            self.pool.start(task)

        def _handle_reply(self, reply):
            if reply.functions:
                self._add_event("Available functions:")
                for function in reply.functions:
                    self._add_event(f"  • {function}")
            self._add_event(f"A.U.R.A.: {reply.message}")
            self.speaker.speak(reply.message)
            self._finish_request()

        def _handle_task_error(self, message):
            log.error("Request failed: %s", message)
            self._add_event("A.U.R.A.: Something went wrong while handling that request.")
            self._finish_request()

        def _finish_request(self):
            self._request_active = False
            self.send_button.setEnabled(True)
            self.command.setEnabled(True)
            self.command.setFocus()
            self.status_labels["Assistant"].setText("Running in tray")
            if self._pending_voice:
                text = self._pending_voice.pop(0)
                self._submit_text(text, voice=True)

        def _toggle_microphone(self, enabled):
            self.listening_action.blockSignals(True)
            self.listening_action.setChecked(enabled)
            self.listening_action.blockSignals(False)
            self._set_microphone_enabled(enabled)

        def _set_microphone_enabled(self, enabled):
            self.mic_button.blockSignals(True)
            self.mic_button.setChecked(enabled)
            self.mic_button.setText("Disable microphone" if enabled else "Enable microphone")
            self.mic_button.blockSignals(False)
            if enabled:
                self.status_labels["Microphone"].setText("Starting offline speech recognition…")
                self.microphone.start(self.signals.voice_text.emit, self.signals.microphone_status.emit)
            else:
                self.microphone.stop()
                self.status_labels["Microphone"].setText("Off — microphone is not active")

        def _microphone_status(self, status):
            self.status_labels["Microphone"].setText(status)
            if status.startswith("Unavailable"):
                self.mic_button.setChecked(False)
                self.listening_action.setChecked(False)
                self._add_event(f"Microphone: {status}")

        def _toggle_camera(self, enabled):
            self.presence_action.blockSignals(True)
            self.presence_action.setChecked(enabled)
            self.presence_action.blockSignals(False)
            self._set_camera_enabled(enabled)

        def _set_camera_enabled(self, enabled):
            self._camera_enabled = bool(enabled)
            self.camera_button.blockSignals(True)
            self.camera_button.setChecked(enabled)
            self.camera_button.setText("Disable webcam" if enabled else "Enable webcam")
            self.camera_button.blockSignals(False)
            if enabled:
                self.status_labels["Webcam"].setText("Starting local webcam processing…")
                self.status_labels["Visual context"].setText("Checking for a face in frame")
                self.webcam.start(self.signals.camera_status.emit)
            else:
                self.webcam.stop()
                self.status_labels["Webcam"].setText("Off — webcam is not active")
                self.status_labels["Visual context"].setText("Unknown — webcam is off")

        def _context_snapshot(self):
            if not self._camera_enabled:
                return None
            state = self.webcam.status
            if state == "Face in frame":
                return {"webcam_face_in_frame": True}
            if state == "No face detected":
                return {"webcam_face_in_frame": False}
            return None

        def _camera_status(self, status):
            self.status_labels["Webcam"].setText("On" if status in {"Face in frame", "No face detected"} else status)
            if status in {"Face in frame", "No face detected"}:
                self.status_labels["Visual context"].setText(status)
            elif status.startswith("Unavailable"):
                self.camera_button.setChecked(False)
                self.presence_action.setChecked(False)
                self.status_labels["Visual context"].setText("Unknown — webcam unavailable")
            elif status == "Off":
                self.status_labels["Visual context"].setText("Unknown — webcam is off")

        def _refresh_ollama(self):
            if self._ollama_check_active or self._shutting_down:
                return
            self.status_labels["Speech output"].setText(self.speaker.status)
            self._ollama_check_active = True
            self.status_labels["Ollama service"].setText("Checking local service…")
            self.status_labels["Qwen model"].setText("Waiting for Ollama status")
            task = Task(lambda: _check_ollama(settings), self.task_signals,
                        self._ollama_result, self._ollama_error)
            self.pool.start(task)

        def _ollama_result(self, result):
            self._ollama_check_active = False
            service, model, tray_status = result
            self.status_labels["Ollama service"].setText(service)
            self.status_labels["Qwen model"].setText(model)
            self.tray.setToolTip(f"A.U.R.A. is running — {tray_status}")

        def _ollama_error(self, message):
            self._ollama_check_active = False
            self.status_labels["Ollama service"].setText("Status check failed")
            self.status_labels["Qwen model"].setText("Status check failed")
            log.debug("Ollama status check failed: %s", message)

        def _show_settings(self):
            dialog = QDialog(self)
            dialog.setWindowTitle("A.U.R.A. Settings")
            dialog.setMinimumWidth(520)
            layout = QVBoxLayout(dialog)
            fields = QFormLayout()
            fields.addRow("Model", QLabel(settings.ollama_model))
            fields.addRow("Ollama address", QLabel(settings.ollama_url))
            fields.addRow("Local data", QLabel(str(settings.db_path)))
            fields.addRow("Voice input", QLabel("Offline Vosk recognition; microphone starts only when enabled"))
            fields.addRow("Speech output", QLabel("Windows built-in SAPI voices; processed locally"))
            fields.addRow("Webcam context", QLabel("On-device face-in-frame check; no frames are saved"))
            fields.addRow("ESP32 chair sensors", QLabel("Not connected"))
            layout.addLayout(fields)
            note = QLabel("Configuration editing and first-run setup will be added in a later milestone.")
            note.setWordWrap(True)
            layout.addWidget(note)
            close_button = QPushButton("Close")
            close_button.clicked.connect(dialog.accept)
            layout.addWidget(close_button)
            dialog.exec()

        def _show_status(self):
            self._show_window()
            self._refresh_ollama()

        def _show_window(self):
            self.showNormal()
            self.raise_()
            self.activateWindow()

        def _tray_activated(self, reason):
            if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                          QSystemTrayIcon.ActivationReason.DoubleClick):
                self._show_window()

        def _exit(self):
            self._shutting_down = True
            self.status_timer.stop()
            self.tray.hide()
            if self.reminders:
                self.reminders.stop()
            if self.schedules:
                self.schedules.stop()
            if self.timers:
                self.timers.stop()
            if self.pomodoros:
                self.pomodoros.cancel()
            self.microphone.stop()
            self.webcam.stop()
            self.speaker.stop()
            QApplication.quit()

        def closeEvent(self, event):
            if self._shutting_down:
                event.accept()
            elif QSystemTrayIcon.isSystemTrayAvailable():
                event.ignore()
                self.hide()
            else:
                event.ignore()
                QMessageBox.warning(
                    self, "System tray unavailable",
                    "A.U.R.A. is keeping this window open because Windows did not report an available system tray. Use Exit A.U.R.A. from the tray menu when it becomes available.",
                )

    app = QApplication.instance() or QApplication([])
    app.setApplicationName("A.U.R.A.")
    app.setQuitOnLastWindowClosed(False)
    task_signals = TaskSignals(app)
    window = MainWindow()
    if not QSystemTrayIcon.isSystemTrayAvailable():
        window._add_event("System tray was not detected; closing the window will not exit A.U.R.A.")
        QMessageBox.information(
            window, "System tray unavailable",
            "A.U.R.A. can run, but Windows did not report an available system tray. The Exit A.U.R.A. menu will be available once a tray is detected.",
        )
    window.show()
    return app.exec()


def _check_ollama(settings):
    base = settings.ollama_url.rstrip("/")
    request = urllib.request.Request(base + "/api/tags", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return ("Not reachable — start Ollama to enable language understanding",
                "Waiting for Ollama", "Ollama unavailable")
    models = [item.get("name", "") for item in payload.get("models", [])]
    requested = settings.ollama_model
    candidates = {requested}
    if ":" not in requested:
        candidates.add(requested + ":latest")
    installed = any(name in candidates for name in models)
    if installed:
        return ("Connected locally", f"{settings.ollama_model} available locally",
                f"{settings.ollama_model} ready")
    return ("Connected locally", f"{settings.ollama_model} is not installed",
            "Configured model missing")


def main():
    from aura.config import Settings
    settings = Settings()
    logging.basicConfig(level=logging.DEBUG if settings.debug else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        return run_desktop(settings)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
