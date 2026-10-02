"""Windows desktop window and system-tray shell for A.U.R.A."""

from datetime import datetime
import json
import logging
import urllib.error
import urllib.request

from aura.apps.catalog import ALIASES
from aura.app import build
from aura.core import AssistantCore

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
            self._request_active = False
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
                ("Microphone / speech input", "Not integrated in desktop interface"),
                ("Speech output", "Not integrated in desktop interface"),
                ("Ollama service", "Checking local service…"),
                ("Qwen model", "Waiting for Ollama status"),
                ("Camera", "Not integrated"),
                ("User presence", "Not available — sensor integration is planned"),
                ("ESP32 chair sensors", "Not connected"),
            ):
                value = QLabel(initial)
                value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                self.status_labels[name] = value
                status_layout.addRow(name, value)
            layout.addLayout(status_layout)

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
            self.listening_action = QAction("Enable listening (voice setup required)", self)
            self.listening_action.setEnabled(False)
            menu.addAction(self.listening_action)
            self.presence_action = QAction("Enable presence detection (sensor setup required)", self)
            self.presence_action.setEnabled(False)
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
            (self.registry, self.router, _speaker, self.reminders, self.schedules,
             self.timers, self.pomodoros) = build(
                settings, speaker=_SilentSpeaker(), notify_user=self.signals.reminder.emit
            )
            self.core = AssistantCore(self.registry, self.router, ALIASES)
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
            if self._request_active:
                return
            text = self.command.text().strip()
            if not text:
                return
            self.command.clear()
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

        def _refresh_ollama(self):
            if self._ollama_check_active or self._shutting_down:
                return
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
            fields.addRow("Voice input", QLabel("Not integrated in the desktop interface"))
            fields.addRow("Presence sensing", QLabel("Not integrated"))
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

    class _SilentSpeaker:
        def speak(self, _text):
            return None

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
