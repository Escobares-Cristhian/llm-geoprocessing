# src/cli/chat_io.py

import os
import re
import threading
import time

# Active GUI ChatIO instance (if any).
_CURRENT_CHAT_IO = None


class ChatIO:
    def __init__(
        self,
        user_name: str = "User",
        model_name: str = "Assistant",
        use_gui: bool = True,
        window_title: str = "GeoLLM Chat",
    ) -> None:
        self.user_name = user_name
        self.model_name = model_name
        self.use_gui = use_gui

        self._pending_input: str | None = None
        self._opened_images: set[str] = set()
        self._session_products: list[str] = []

        self._app = None
        self._window = None
        self._text = None
        self._entry = None
        self._send_button = None
        self._view = None  # right-side web view (leafmap / Jupyter app)

        if self.use_gui:
            # No fallback: if this fails, let it raise
            from PyQt5.QtWidgets import (
                QApplication,
                QWidget,
                QSplitter,
                QTextEdit,
                QLineEdit,
                QPushButton,
                QVBoxLayout,
                QHBoxLayout,
            )
            from PyQt5.QtCore import Qt, QUrl
            from PyQt5.QtWebEngineWidgets import QWebEngineView

            self._app = QApplication.instance()
            if self._app is None:
                self._app = QApplication([])

            self._window = QWidget()
            self._window.setWindowTitle(window_title)

            splitter = QSplitter(Qt.Horizontal)

            # Left: chat
            left_widget = QWidget()
            left_layout = QVBoxLayout(left_widget)

            self._text = QTextEdit()
            self._text.setReadOnly(True)
            left_layout.addWidget(self._text)

            entry_layout = QHBoxLayout()
            self._entry = QLineEdit()
            self._entry.returnPressed.connect(self._on_send)
            entry_layout.addWidget(self._entry)

            self._send_button = QPushButton("Send")
            self._send_button.clicked.connect(self._on_send)
            entry_layout.addWidget(self._send_button)

            left_layout.addLayout(entry_layout)

            # Right: web view with external leafmap/Jupyter app
            self._view = QWebEngineView()

            # URL of the map UI (e.g. Voila / Jupyter app running leafmap)
            map_url = os.environ.get("GEOMAP_URL", "http://127.0.0.1:8866")
            self._view.load(QUrl(map_url))

            splitter.addWidget(left_widget)
            splitter.addWidget(self._view)
            splitter.setStretchFactor(0, 3)
            splitter.setStretchFactor(1, 5)

            main_layout = QVBoxLayout()
            main_layout.addWidget(splitter)

            self._window.setLayout(main_layout)
            self._window.resize(1200, 700)
            self._window.show()

            # Register this instance as the active GUI ChatIO
            global _CURRENT_CHAT_IO
            _CURRENT_CHAT_IO = self

    def ask_user_input(self) -> str | None:
        if not self.use_gui:
            return input(f"\n{self.user_name}: ")

        self._pending_input = None
        while self._pending_input is None:
            self._app.processEvents()

        msg = self._pending_input
        self._pending_input = None
        self._app.processEvents()
        return msg

    def print_user_msg(self, msg: str) -> None:
        self._append(f"\n{self.user_name}:\n{msg}")

    def print_assistant_msg(self, msg: str) -> None:
        self._append(f"\n{self.model_name}:\n{msg}")
        self._maybe_open_viewer(msg)

    def print_command_msg(self, command_name: str, msg: str) -> None:
        self._append(f"\n[{command_name}]:\n{msg}")

    def print_mode_selected(self, mode_name: str) -> None:
        self._append(f"\n[Selected Mode: {mode_name}]")

    # ----- internal helpers -----

    def _append(self, text: str) -> None:
        if not self.use_gui or self._text is None:
            print(text, flush=True, sep="")
            return

        self._text.append(text)
        if self._app is not None:
            self._app.processEvents()

    def _on_send(self) -> None:
        if self._entry is None:
            return
        msg = self._entry.text()
        if not msg:
            return
        self._entry.clear()

        # show user message immediately
        self.print_user_msg(msg)

        # deliver to ask_user_input()
        self._pending_input = msg

    def _maybe_open_viewer(self, text: str) -> None:
        """
        Hook kept for compatibility.
        In the leafmap/Jupyter-based architecture, the right-hand map UI
        is an external web app, so this method does not open files itself.
        You can still parse product paths here and, for example, write
        a small config file in a shared folder if you want the leafmap app
        to react to the "last product" from the chat.
        """
        # Example: collect product paths but do nothing else.
        pattern = r"([\w\-/\.]+?\.(?:tif|tiff|png|jpg|jpeg|gpkg|shp|geojson|json))(?!\.)"
        matches = re.findall(pattern, text)
        for m in matches:
            abs_path = os.path.abspath(m)
            if abs_path not in self._session_products:
                self._session_products.append(abs_path)


def _run_blocking_with_gui_events(func, *args, **kwargs):
    """Run a blocking function while keeping the Qt GUI responsive.

    Used to wrap LLM/API calls so that chat.send_message(prompt) does not
    freeze the window, without changing call sites.
    """
    ci = _CURRENT_CHAT_IO
    if ci is None or not ci.use_gui or ci._app is None:
        return func(*args, **kwargs)

    result = {"value": None, "error": None}

    def _worker():
        try:
            result["value"] = func(*args, **kwargs)
        except Exception as e:
            result["error"] = e

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()

    # Pump events at a modest rate while we wait for the worker.
    POLL_INTERVAL = 0.2  # ~5 UI updates per second

    while thread.is_alive():
        ci._app.processEvents()
        thread.join(POLL_INTERVAL)

    if result["error"] is not None:
        raise result["error"]
    return result["value"]


# Patch Chatbot.send_message so chat.send_message(prompt) stays unchanged
try:
    from llm_geoprocessing.app.chatbot.chatbot import Chatbot  # type: ignore[attr-defined]
except Exception:
    Chatbot = None  # type: ignore[assignment]

if Chatbot is not None:
    _orig_send_message = Chatbot.send_message

    def _patched_send_message(self, msg: str) -> str:
        return _run_blocking_with_gui_events(_orig_send_message, self, msg)

    Chatbot.send_message = _patched_send_message
