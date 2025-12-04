# src/cli/chat_io.py

import json
import os
import socket
import threading
import time
import http.server
import socketserver
import subprocess
import re
from pathlib import Path
from typing import Dict, List, Optional

# Active GUI ChatIO instance (if any).
_CURRENT_CHAT_IO: Optional["ChatIO"] = None
_QT_APP = None


def _ensure_qt_app():
    """Create or reuse a single QApplication instance (with QtWebEngine ready)."""
    global _QT_APP
    if _QT_APP is not None:
        return _QT_APP

    try:
        from PyQt5 import QtCore  # type: ignore
        from PyQt5 import QtWebEngineWidgets  # noqa: F401  # type: ignore
        from PyQt5.QtWidgets import QApplication  # type: ignore
    except Exception as e:
        raise RuntimeError("PyQt5 with QtWebEngine is required for GUI mode") from e

    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts, True)
    app = QApplication.instance() or QApplication([])
    _QT_APP = app
    return app


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _ThreadedHTTPServer:
    """Tiny static server for the OpenLayers webview."""

    def __init__(self, root_dir: Path, port: Optional[int] = None) -> None:
        self.root_dir = Path(root_dir)
        self.port = port or _pick_free_port()
        handler_cls = self._make_handler(self.root_dir)
        self.httpd = socketserver.TCPServer(
            ("127.0.0.1", self.port),
            handler_cls,
            bind_and_activate=True,
        )
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @staticmethod
    def _make_handler(root_dir: Path):
        class Handler(http.server.SimpleHTTPRequestHandler):
            def translate_path(self, path):
                from urllib.parse import unquote, urlsplit

                path = unquote(urlsplit(path).path)
                new = root_dir / path.lstrip("/")
                return str(new)

            def log_message(self, format, *args):  # type: ignore[override]
                pass

        return Handler

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        try:
            self.httpd.shutdown()
        except Exception:
            pass


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

        self.geo_out_dir = Path(
            geo_out_dir or os.environ.get("GEO_OUT_DIR", "./gee_out")
        ).resolve()
        self.geo_out_dir.mkdir(parents=True, exist_ok=True)

        self._module_dir = Path(__file__).parent
        self._webroot = self._module_dir / "ol_viewer"
        self._rasters_dir = self._webroot / "rasters"
        self._layers_json = self._webroot / "layers.json"
        self._webroot.mkdir(exist_ok=True, parents=True)
        self._rasters_dir.mkdir(exist_ok=True)

        self._session_start = time.time()
        self._known: Dict[str, float] = {}  # tif name -> mtime
        self._meta: Dict[str, Dict[str, object]] = {}  # tif name -> {png, epsg, extent}

        self._server: Optional[_ThreadedHTTPServer] = None
        self._qt_app = None
        self._window = None
        self._view = None
        self._text = None
        self._entry = None
        self._send_button = None
        self._pending_input: Optional[str] = None

        self._buffer: List[str] = []

        if self.use_gui:
            self._qt_app = _ensure_qt_app()
            self._start_server()
            self._start_viewer()
            self._start_scanner()

        global _CURRENT_CHAT_IO
        _CURRENT_CHAT_IO = self

    # ----- public API -----

    def ask_user_input(self) -> str:
        if not self.use_gui or self._qt_app is None or self._entry is None:
            try:
                msg = input(f"\n{self.user_name}:\n")
            except EOFError:
                msg = ""
            msg = msg or ""
            self.print_user_msg(msg)
            return msg

        self._pending_input = None
        app = self._qt_app

        while self._pending_input is None:
            app.processEvents()
            time.sleep(0.01)

        msg = self._pending_input or ""
        self._pending_input = None
        app.processEvents()
        return msg

    def print_user_msg(self, msg: str) -> None:
        self._append(f"\n{self.user_name}:\n{msg}")

    def print_assistant_msg(self, msg: str) -> None:
        self._append(f"\n{self.model_name}:\n{msg}")

    def print_command_msg(self, command_name: str, msg: str) -> None:
        self._append(f"\n[{command_name}]:\n{msg}")

    def print_mode_selected(self, mode_name: str) -> None:
        self._append(f"\n[Selected Mode: {mode_name}]")

    def register_raster(self, path: str) -> None:
        try:
            p = Path(path).resolve()
            if p.suffix.lower() in (".tif", ".tiff") and p.exists():
                self._known[p.name] = p.stat().st_mtime
                self._link_and_update(p)
        except Exception:
            pass

    # ----- internals -----

    def _append(self, text: str) -> None:
        self._buffer.append(text)
        if self.use_gui and self._text is not None:
            self._text.append(text)
        else:
            print(text, flush=True)

    def _start_server(self) -> None:
        self._server = _ThreadedHTTPServer(self._webroot)
        self._server.start()

    def _start_viewer(self) -> None:
        try:
            from PyQt5.QtWidgets import (
                QWidget,
                QVBoxLayout,
                QHBoxLayout,
                QTextEdit,
                QLineEdit,
                QPushButton,
                QSplitter,
            )
            from PyQt5.QtWebEngineWidgets import QWebEngineView
            from PyQt5.QtCore import QUrl
        except Exception as e:
            raise RuntimeError("PyQt5 with QtWebEngine is required for GUI mode") from e

        app = self._qt_app

        main = QWidget()
        main.setWindowTitle("Geoprocessing Chat + Map (OpenLayers)")

        layout = QVBoxLayout(main)
        splitter = QSplitter()
        layout.addWidget(splitter)

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

        self._view = QWebEngineView()
        url = QUrl(f"http://127.0.0.1:{self._server.port}/index.html")
        self._view.load(url)

        splitter.addWidget(left_widget)
        splitter.addWidget(self._view)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 5)

        main.resize(1400, 900)
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

    def _start_scanner(self) -> None:
        def _scan_loop() -> None:
            while True:
                try:
                    self._scan_for_rasters()
                except Exception:
                    pass
                time.sleep(1.5)

        threading.Thread(target=_scan_loop, daemon=True).start()

    def _scan_for_rasters(self) -> None:
        for pattern in ("*.tif", "*.tiff"):
            for p in self.geo_out_dir.rglob(pattern):
                try:
                    mtime = p.stat().st_mtime
                except FileNotFoundError:
                    continue
                if mtime >= self._session_start and self._known.get(p.name, 0.0) < mtime:
                    self._known[p.name] = mtime
                    self._link_and_update(p)

    def _get_raster_info(self, src: Path) -> Optional[tuple]:
        try:
            proc = subprocess.run(
                ["gdalinfo", "-json", str(src)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                text=True,
            )
        except Exception:
            return None

        try:
            info = json.loads(proc.stdout)
        except Exception:
            return None

        epsg = "EPSG:4326"
        cs = info.get("coordinateSystem") or {}
        wkt = cs.get("wkt")
        if isinstance(wkt, str):
            m = re.search(r'AUTHORITY\["EPSG","(\d+)"\]', wkt)
            if m:
                epsg = f"EPSG:{m.group(1)}"

        corners = info.get("cornerCoordinates") or {}
        ul = corners.get("upperLeft")
        lr = corners.get("lowerRight")
        if not ul or not lr:
            return None

        minx = float(ul["x"])
        maxy = float(ul["y"])
        maxx = float(lr["x"])
        miny = float(lr["y"])
        return epsg, [minx, miny, maxx, maxy]

    def _link_and_update(self, src: Path) -> None:
        info = self._get_raster_info(src)
        if info is None:
            return
        epsg, extent = info

        png_name = src.stem + ".png"
        dst = self._rasters_dir / png_name

        need_convert = True
        try:
            if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
                need_convert = False
        except FileNotFoundError:
            need_convert = True

        if need_convert:
            try:
                subprocess.run(
                    ["gdal_translate", "-of", "PNG", str(src), str(dst)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                return

        self._meta[src.name] = {
            "png": png_name,
            "epsg": epsg,
            "extent": extent,
        }
        self._write_layers_json()

    def _write_layers_json(self) -> None:
        layers = []
        for tif_name in sorted(self._meta.keys()):
            meta = self._meta[tif_name]
            layers.append(
                {
                    "name": tif_name,
                    "title": tif_name,
                    "url": f"/rasters/{meta['png']}",
                    "visible": True,
                    "extent": meta["extent"],
                    "projection": meta["epsg"],
                }
            )
        tmp = self._layers_json.with_suffix(".tmp")
        tmp.write_text(json.dumps(layers), encoding="utf-8")
        tmp.replace(self._layers_json)


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
