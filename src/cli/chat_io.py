# src/cli/chat_io.py

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import folium

# Local paths for Leaflet assets inside the container.
# You should put leaflet.js / leaflet.css there in the Docker image.
_LEAFLET_JS_SRC = os.environ.get("LEAFLET_JS_SRC", "/app/static/leaflet/leaflet.js")
_LEAFLET_CSS_SRC = os.environ.get("LEAFLET_CSS_SRC", "/app/static/leaflet/leaflet.css")


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

    if png_path.exists() and png_path.stat().st_mtime >= path.stat().st_mtime:
        return png_path

    subprocess.run(
        [
            gdal_translate,
            "-of",
            "PNG",
            str(path),
            str(png_path),
        ],
        check=True,
    )

    return png_path


def _ensure_view_geojson(path: Path) -> Path:
    """
    For vector files, ensure a GeoJSON file exists in the same folder for browser display.
    If input is already GeoJSON/JSON, return as-is.
    """
    suffix = path.suffix.lower()
    if suffix in {".geojson", ".json"}:
        return path

    ogr2ogr = shutil.which("ogr2ogr")
    if ogr2ogr is None:
        return path

    geojson_path = path.with_suffix(".viewer.geojson")

    if geojson_path.exists() and geojson_path.stat().st_mtime >= path.stat().st_mtime:
        return geojson_path

    subprocess.run(
        [
            ogr2ogr,
            "-f",
            "GeoJSON",
            str(geojson_path),
            str(path),
        ],
        check=True,
    )

    return geojson_path


def _get_geojson_bounds(path: Path) -> tuple[float, float, float, float] | None:
    """
    Compute WGS84 bounds from a GeoJSON file.
    """
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    lons: list[float] = []
    lats: list[float] = []

    def collect_coords(geom: dict) -> None:
        if not isinstance(geom, dict):
            return

        if "coordinates" in geom:
            def walk(coords):
                if isinstance(coords, (list, tuple)):
                    if (
                        len(coords) == 2
                        and isinstance(coords[0], (int, float))
                        and isinstance(coords[1], (int, float))
                    ):
                        lons.append(float(coords[0]))
                        lats.append(float(coords[1]))
                    else:
                        for c in coords:
                            walk(c)
            walk(geom["coordinates"])

        if "geometries" in geom and isinstance(geom["geometries"], list):
            for g in geom["geometries"]:
                collect_coords(g)

    if isinstance(obj, dict) and obj.get("type") == "FeatureCollection":
        for feat in obj.get("features", []):
            geom = feat.get("geometry")
            if geom:
                collect_coords(geom)
    elif isinstance(obj, dict) and obj.get("type") == "Feature":
        geom = obj.get("geometry")
        if geom:
            collect_coords(geom)
    else:
        if isinstance(obj, dict):
            collect_coords(obj)

    if not lons or not lats:
        return None

    return min(lons), min(lats), max(lons), max(lats)


def _ensure_leaflet_assets(html_dir: Path) -> bool:
    """
    Ensure Leaflet JS/CSS are available next to the generated HTML.
    Returns True if both files are present, False otherwise.
    """
    ok = True

    if _LEAFLET_JS_SRC and Path(_LEAFLET_JS_SRC).exists():
        dst_js = html_dir / "leaflet.js"
        if not dst_js.exists():
            shutil.copy(_LEAFLET_JS_SRC, dst_js)
    else:
        ok = False

    if _LEAFLET_CSS_SRC and Path(_LEAFLET_CSS_SRC).exists():
        dst_css = html_dir / "leaflet.css"
        if not dst_css.exists():
            shutil.copy(_LEAFLET_CSS_SRC, dst_css)
    else:
        ok = False

    return ok


def _build_initial_basemap(html_path: Path) -> None:
    """
    Build an initial Folium map with only a basemap,
    centered over Argentina and covering the whole country.
    """
    # Rough bounding box for Argentina
    south, west, north, east = -55.1, -73.6, -21.8, -53.6
    center = [(south + north) / 2.0, (west + east) / 2.0]

    m = folium.Map(
        location=center,
        zoom_start=4,
        control_scale=True,
        tiles="OpenStreetMap",
    )
    m.fit_bounds([[south, west], [north, east]])
    m.save(html_path)

    # Rewrite Leaflet URLs to local files if available
    if _ensure_leaflet_assets(html_path.parent):
        txt = html_path.read_text(encoding="utf-8")
        txt = re.sub(r"https://[^\"]*leaflet\.js", "leaflet.js", txt)
        txt = re.sub(r"https://[^\"]*leaflet\.css", "leaflet.css", txt)
        html_path.write_text(txt, encoding="utf-8")



def _build_folium_map(
    layers: list[dict],
    title: str,
    html_path: Path,
) -> None:
    """
    Build a Folium map with all layers and save it to html_path.
    """
    if not layers:
        m = folium.Map(location=[0, 0], zoom_start=2, control_scale=True)
        m.save(html_path)
        return

    south = min(layer["south"] for layer in layers)
    west = min(layer["west"] for layer in layers)
    north = max(layer["north"] for layer in layers)
    east = max(layer["east"] for layer in layers)
    center = [(south + north) / 2.0, (west + east) / 2.0]

    m = folium.Map(location=center, zoom_start=8, control_scale=True, tiles="OpenStreetMap")

    for layer in layers:
        if layer["type"] == "raster":
            bounds = [
                [layer["south"], layer["west"]],
                [layer["north"], layer["east"]],
            ]
            folium.raster_layers.ImageOverlay(
                image=layer["url"],
                bounds=bounds,
                opacity=0.8,
                name=layer["name"],
                interactive=True,
                cross_origin=False,
            ).add_to(m)
        elif layer["type"] == "vector":
            folium.GeoJson(
                data=layer["geojson"],
                name=layer["name"],
            ).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    m.fit_bounds([[south, west], [north, east]])
    m.save(html_path)


def _open_leaflet_html(
    image_path: str,
    extra_paths: list[str] | None = None,
    title: str = "GeoLLM Map",
) -> Path:
    """
    Create a Folium-based HTML viewer that shows all given products (raster + vector)
    and return the HTML path.
    """
    path = Path(image_path).resolve()
    if not path.exists():
        raise FileNotFoundError(path)

    html_path = path.with_suffix(path.suffix + ".html")
    html_dir = html_path.parent

    raw_paths = [path]
    if extra_paths:
        for p in extra_paths:
            raw_paths.append(Path(p).resolve())

    layers: list[dict] = []
    seen: set[str] = set()

    raster_exts = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}
    vector_exts = {".gpkg", ".shp", ".geojson", ".json"}

    for p in raw_paths:
        if not p.exists():
            continue
        key = str(p)
        if key in seen:
            continue
        seen.add(key)

        suffix = p.suffix.lower()

        if suffix in raster_exts:
            bounds = _get_bounds(p)
            if bounds is None:
                west, south, east, north = -180.0, -90.0, 180.0, 90.0
            else:
                west, south, east, north = bounds

            view_path = _ensure_view_image(p)
            url = str(view_path)

            layers.append(
                {
                    "type": "raster",
                    "url": url,
                    "south": south,
                    "west": west,
                    "north": north,
                    "east": east,
                    "name": p.name,
                }
            )

        elif suffix in vector_exts:
            view_path = _ensure_view_geojson(p)
            bounds = _get_geojson_bounds(view_path)
            if bounds is None:
                west, south, east, north = -180.0, -90.0, 180.0, 90.0
            else:
                west, south, east, north = bounds

            try:
                geojson_obj = json.loads(view_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            layers.append(
                {
                    "type": "vector",
                    "geojson": geojson_obj,
                    "south": south,
                    "west": west,
                    "north": north,
                    "east": east,
                    "name": p.name,
                }
            )

    # Fallback: behave like the old single-image version
    if not layers:
        bounds = _get_bounds(path)
        if bounds is None:
            west, south, east, north = -180.0, -90.0, 180.0, 90.0
        else:
            west, south, east, north = bounds
        view_path = _ensure_view_image(path)
        url = str(view_path)
        layers.append(
            {
                "type": "raster",
                "url": url,
                "south": south,
                "west": west,
                "north": north,
                "east": east,
                "name": path.name,
            }
        )

    _build_folium_map(layers=layers, title=title, html_path=html_path)

    # If local Leaflet assets exist, rewrite Leaflet JS/CSS references
    if _ensure_leaflet_assets(html_dir):
        txt = html_path.read_text(encoding="utf-8")
        txt = re.sub(r"https://[^\"]*leaflet\.js", "leaflet.js", txt)
        txt = re.sub(r"https://[^\"]*leaflet\.css", "leaflet.css", txt)
        html_path.write_text(txt, encoding="utf-8")

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
        self._session_products: list[str] = []

        self._app = None
        self._window = None
        self._text = None
        self._entry = None
        self._send_button = None
        self._view = None  # web view for Folium map

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
            from PyQt5.QtCore import QUrl

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

            # Right: Folium map in QWebEngineView
            self._view = QWebEngineView()
            
            # Build an initial Folium basemap centered over Argentina
            initial_html = Path("/tmp/geollm_initial_map.html")
            _build_initial_basemap(initial_html)

            url = QUrl.fromLocalFile(str(initial_html))
            self._view.load(url)

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
        Look for raster/vector paths in assistant messages, keep a list
        of all products for the current session, and refresh the Folium
        viewer with all of them (GUI only).
        """
        if not self.use_gui or self._view is None:
            return

        from PyQt5.QtCore import QUrl

        # Match absolute or relative paths ending in raster/vector extensions,
        # but NOT things like "file.tif.html" (negative lookahead for '.').
        pattern = r"([\w\-/\.]+?\.(?:tif|tiff|png|jpg|jpeg|gpkg|shp|geojson|json))(?!\.)"
        matches = re.findall(pattern, text)

        if not matches:
            return

        updated = False
        for m in matches:
            abs_path = os.path.abspath(m)
            if os.path.exists(abs_path) and abs_path not in self._session_products:
                self._session_products.append(abs_path)
                updated = True

        if not updated:
            return

        # Use the last product as anchor for the HTML file location
        last_path = self._session_products[-1]

        html_path = _open_leaflet_html(
            last_path,
            extra_paths=self._session_products[:-1],
        )
        url = QUrl.fromLocalFile(str(html_path))
        self._view.load(url)
        self._app.processEvents()
