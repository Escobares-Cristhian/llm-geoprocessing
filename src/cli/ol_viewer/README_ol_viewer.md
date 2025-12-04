# OpenLayers Viewer (minimal)

- Serves `index.html` via an internal localhost HTTP server.
- Watches `GEO_OUT_DIR` (or `./gee_out`) for newly created `.tif` files during the session.
- Every found raster is symlinked/copied into `src/cli/ol_viewer/rasters/` and listed in `layers.json`.
- The web UI polls `layers.json` every 2 seconds and shows a checkbox to toggle each layer.