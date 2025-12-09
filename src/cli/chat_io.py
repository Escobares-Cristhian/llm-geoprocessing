# src/cli/chat_io.py

import threading
import time
from typing import List, Optional

# Active GUI ChatIO instance (if any).
_CURRENT_CHAT_IO: Optional["ChatIO"] = None
_QT_APP = None


def _ensure_qt_app():
    """Create or reuse a single QApplication instance for the Qt chat UI."""
    global _QT_APP
    if _QT_APP is not None:
        return _QT_APP

    try:
        from PyQt5.QtWidgets import QApplication  # type: ignore
    except Exception as e:
        raise RuntimeError("PyQt5 is required for GUI mode") from e

    app = QApplication.instance() or QApplication([])
    _QT_APP = app
    return app


class ChatIO:
    def __init__(
        self,
        user_name: str = "User",
        model_name: str = "Assistant",
        use_gui: bool = False,
        geo_out_dir: Optional[str] = None,
    ) -> None:
        self.user_name = user_name
        self.model_name = model_name
        self.use_gui = use_gui

        # GUI widgets/objects
        self._qt_app = None
        self._window = None
        self._text = None
        self._entry = None
        self._send_button = None
        self._pending_input: Optional[str] = None

        # Keep console log for potential debugging
        self._buffer: List[str] = []

        if self.use_gui:
            self._qt_app = _ensure_qt_app()
            self._start_gui()

        global _CURRENT_CHAT_IO
        _CURRENT_CHAT_IO = self

    # ----- public API -----

    def ask_user_input(self) -> str:
        """Get a line of input from the user (GUI if enabled, else stdin)."""
        if not self.use_gui or self._qt_app is None or self._entry is None:
            try:
                msg = input(f"\n{self.user_name}:\n")
            except EOFError:
                msg = ""
            msg = msg or ""
            self.print_user_msg(msg)
            return msg

        # GUI mode: wait until the user hits Enter or clicks Send
        self._pending_input = None

        app = self._qt_app
        assert app is not None
        app.processEvents()

        while self._pending_input is None:
            app.processEvents()
            time.sleep(0.01)

        return self._pending_input

    def print_user_msg(self, msg: str) -> None:
        self._append(f"\n{self.user_name}:\n{msg}")

    def print_assistant_msg(self, msg: str) -> None:
        self._append(f"\n{self.model_name}:\n{msg}")

    def print_command_msg(self, command_name: str, msg: str) -> None:
        self._append(f"\n[{command_name}]:\n{msg}")

    def print_mode_selected(self, mode_name: str) -> None:
        self._append(f"\n[Selected Mode: {mode_name}]")

    # ----- internals -----

    def _append(self, text: str) -> None:
        self._buffer.append(text)
        if self.use_gui and self._text is not None:
            self._text.append(text)
        else:
            print(text, flush=True)

    def _start_gui(self) -> None:
        try:
            from PyQt5.QtWidgets import (
                QWidget,
                QVBoxLayout,
                QHBoxLayout,
                QTextEdit,
                QLineEdit,
                QPushButton,
            )
        except Exception as e:
            raise RuntimeError("PyQt5 is required for GUI mode") from e

        app = self._qt_app

        main = QWidget()
        main.setWindowTitle("Geoprocessing Chat")

        layout = QVBoxLayout(main)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        layout.addWidget(self._text)

        entry_layout = QHBoxLayout()
        self._entry = QLineEdit()
        self._entry.returnPressed.connect(self._on_send)
        entry_layout.addWidget(self._entry)

        self._send_button = QPushButton("Send")
        self._send_button.clicked.connect(self._on_send)
        entry_layout.addWidget(self._send_button)

        layout.addLayout(entry_layout)

        main.resize(800, 600)
        main.show()

        self._window = main
        if app is not None:
            app.processEvents()

    def _on_send(self) -> None:
        if self._entry is None:
            return
        msg = self._entry.text()
        if not msg:
            return
        self._entry.clear()
        self.print_user_msg(msg)
        self._pending_input = msg


# Patch Chatbot.send_message to keep GUI responsive
try:
    from llm_geoprocessing.app.chatbot.chatbot import Chatbot  # type: ignore[attr-defined]
except Exception:
    Chatbot = None  # type: ignore[assignment]


def _run_blocking_with_gui_events(fn, *args, **kwargs):
    if (
        _CURRENT_CHAT_IO is None
        or not _CURRENT_CHAT_IO.use_gui
        or _CURRENT_CHAT_IO._qt_app is None
    ):
        return fn(*args, **kwargs)

    result = None
    done = False

    def _call():
        nonlocal result, done
        result = fn(*args, **kwargs)
        done = True

    t = threading.Thread(target=_call, daemon=True)
    t.start()
    app = _CURRENT_CHAT_IO._qt_app

    while not done:
        app.processEvents()
        time.sleep(0.01)

    return result


if Chatbot is not None:
    _orig_send_message = Chatbot.send_message

    def _patched_send_message(self, msg: str) -> str:  # type: ignore[override]
        return _run_blocking_with_gui_events(_orig_send_message, self, msg)

    Chatbot.send_message = _patched_send_message
