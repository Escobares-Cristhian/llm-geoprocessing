# src/cli/chat_io.py

import json
import os
import re
import shutil
import subprocess
from pathlib import Path


def _get_bounds(path: Path) -> tuple[float, float, float, float] | None:
    """
    Read WGS84 bounds (west, south, east, north) using gdalinfo -json.
    Returns None if needed keys are not present.
    """
    gdalinfo = shutil.which("gdalinfo")
    if gdalinfo is None:
        return None

    proc = subprocess.run(
        [gdalinfo, "-json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    info = json.loads(proc.stdout)

    # Prefer wgs84Extent if present
    if "wgs84Extent" in info:
        extent = info["wgs84Extent"]
        if isinstance(extent, dict) and "coordinates" in extent:
            coords = extent["coordinates"]
            if isinstance(coords, list) and len(coords) > 0:
                ring = coords[0]
                lons: list[float] = []
                lats: list[float] = []
                for c in ring:
                    if isinstance(c, list) and len(c) == 2:
                        lons.append(float(c[0]))
                        lats.append(float(c[1]))
                if lons and lats:
                    return min(lons), min(lats), max(lons), max(lats)

    # Fallback: cornerCoordinates
    if "cornerCoordinates" in info:
        corners = info["cornerCoordinates"]
        if isinstance(corners, dict):
            lons = []
            lats = []
            for v in corners.values():
                if isinstance(v, list) and len(v) == 2:
                    lons.append(float(v[0]))
                    lats.append(float(v[1]))
            if lons and lats:
                return min(lons), min(lats), max(lons), max(lats)

    return None


def _ensure_view_image(path: Path) -> Path:
    """
    For TIFF images, generate a PNG for browser display (same folder).
    For other formats, return the original path.
    """
    suffix = path.suffix.lower()
    if suffix not in {".tif", ".tiff"}:
        return path

    gdal_translate = shutil.which("gdal_translate")
    if gdal_translate is None:
        return path

    png_path = path.with_suffix(".viewer.png")

    subprocess.run(
        [gdal_translate, "-of", "PNG", str(path), str(png_path)],
        check=True,
        capture_output=True,
        text=True,
    )

    return png_path


def _build_leaflet_html(
    img_rel: str,
    south: float,
    west: float,
    north: float,
    east: float,
    title: str = "GeoLLM Map",
) -> str:
    """
    Full Leaflet HTML with basemap + image overlay.
    """
    return f"""<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="initial-scale=1,maximum-scale=1,user-scalable=no" />
    <title>{title}</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
      html, body, #map {{
        height: 100%;
        width: 100%;
        margin: 0;
        padding: 0;
      }}
    </style>
  </head>
  <body>
    <div id="map"></div>
    <script>
      var map = L.map('map');

      L.tileLayer('https://wms.ign.gob.ar/geoserver/gwc/service/tms/1.0.0/capabaseargenmap@EPSG%3A3857@png/{{z}}/{{x}}/{{-y}}.png', {{
        attribution: '<a href="https://www.ign.gob.ar">IGN Argentina</a> | <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
        minZoom: 3,
        maxZoom: 18,
        tileSize: 256,
        continuousWorld: false,
        noWrap: false
      }}).addTo(map);

      var imageBounds = [[{south}, {west}], [{north}, {east}]];
      var overlay = L.imageOverlay('{img_rel}', imageBounds).addTo(map);
      map.fitBounds(imageBounds);
    </script>
  </body>
</html>
"""


def _open_leaflet_html(image_path: str, title: str = "GeoLLM Map") -> Path:
    """
    Create a Leaflet HTML viewer next to the image and return the HTML path.
    """
    path = Path(image_path).resolve()
    if not path.exists():
        raise FileNotFoundError(path)

    bounds = _get_bounds(path)
    if bounds is None:
        west, south, east, north = -180.0, -90.0, 180.0, 90.0
    else:
        west, south, east, north = bounds

    view_path = _ensure_view_image(path)
    img_rel = view_path.name  # HTML lives in same folder as the image/PNG

    html_path = path.with_suffix(path.suffix + ".html")
    html = _build_leaflet_html(
        img_rel=img_rel,
        south=south,
        west=west,
        north=north,
        east=east,
        title=title,
    )
    html_path.write_text(html, encoding="utf-8")
    return html_path


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

        self._app = None
        self._window = None
        self._text = None
        self._entry = None
        self._send_button = None
        self._view = None  # web view for Leaflet

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
            from PyQt5.QtCore import Qt
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

            # Right: Leaflet web view
            self._view = QWebEngineView()

            splitter.addWidget(left_widget)
            splitter.addWidget(self._view)
            splitter.setStretchFactor(0, 3)
            splitter.setStretchFactor(1, 5)

            main_layout = QVBoxLayout()
            main_layout.addWidget(splitter)

            self._window.setLayout(main_layout)
            self._window.resize(1200, 700)
            self._window.show()

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
        Look for absolute image paths in assistant messages, generate a Leaflet
        HTML for the last one and show it in the embedded browser (GUI only).
        """
        if not self.use_gui or self._view is None:
            return

        from PyQt5.QtCore import QUrl

        # Match absolute Unix-style paths ending in common raster/image extensions,
        # but NOT things like "file.tif.html" (negative lookahead for '.').
        pattern = r"(/[\w\-/\.]+?\.(?:tif|tiff|png|jpg|jpeg))(?!\.)"
        matches = re.findall(pattern, text)

        if not matches:
            return

        last_path = os.path.abspath(matches[-1])
        if not os.path.exists(last_path):
            print(f"[manual print][Warning] Image path not found: {last_path}")
            return

        html_path = _open_leaflet_html(last_path)
        url = QUrl.fromLocalFile(str(html_path))
        self._view.load(url)
        self._app.processEvents()
