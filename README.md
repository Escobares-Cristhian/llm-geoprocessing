# LLM Geoprocessing

This project is an LLM-driven geoprocessing app that turns chat requests into spatial workflows.
It uses a FastAPI Google Earth Engine (GEE) microservice to run geoprocesses and export GeoTIFF tiles.
Outputs are written to a shared host folder and can be uploaded to PostGIS when enabled.
A Qt/X11 GUI mode is available for interactive use in supported environments.
The Docker Compose stack includes three services: geollm (chat app), gee (GEE service), and postgis (optional).

## Key features

- Interactive chat modes for geoprocessing and interpreter workflows
- FastAPI GEE plugin service for Earth Engine operations
- GeoTIFF tile export to ./gee_out
- Optional PostGIS upload target
- Supports multiple LLM providers

## Requirements

- Docker + Docker Compose
- Optional: Linux with X11 if using the GUI

## Quickstart (happy path)

1) Copy `.env.example` to `.env`.
2) Set at least one provider key in `.env`: `GEMINI_API_KEY` and/or `OPENAI_API_KEY`.
3) Ensure `./secrets/gee-sa.json` exists (see `docs/DEVELOPMENT.md`).
4) Start the app:

```bash
docker compose -f docker/compose.dev.yaml run --rm --build geollm python -m llm_geoprocessing.app.main
```

If the services are started, the GEE FastAPI docs are at http://localhost:8000/docs.

## Common commands (copy/paste)

Start supporting services (gee + postgis) in background:

```bash
docker compose -f docker/compose.dev.yaml up -d gee postgis
```

Tail gee logs:

```bash
docker compose -f docker/compose.dev.yaml logs --no-log-prefix -f gee
```

Stop stack:

```bash
docker compose -f docker/compose.dev.yaml down
```

## Configuration (essentials)

- `GEMINI_API_KEY`: Gemini API key for LLM access.
- `OPENAI_API_KEY`: OpenAI API key for LLM access.
- `GEE_PLUGIN_URL`: Override URL for the GEE FastAPI service if needed.
- `GEO_OUT_DIR`: Container output directory (default `/gee_out`).
- `POSTGIS_ENABLED`: Enable PostGIS upload when set to true.
- `POSTGIS_HOST`: PostGIS hostname.
- `POSTGIS_PORT`: PostGIS port.
- `POSTGIS_DB`: PostGIS database name.
- `POSTGIS_USER`: PostGIS user.
- `POSTGIS_PASSWORD`: PostGIS password.
- `POSTGIS_SCHEMA`: Target schema for uploads.
- `POSTGIS_TABLE_PREFIX`: Prefix for created tables.
- `POSTGIS_SRID`: SRID to use for uploads.

For details beyond this overview, see `docs/DEVELOPMENT.md`.

## Outputs

Results are written to `./gee_out` on the host (mounted as `/gee_out` in containers).
The GEE service produces tiled GeoTIFF outputs.

## Troubleshooting

- Missing Earth Engine credentials: see `docs/DEVELOPMENT.md`.
- GUI/X11 DISPLAY issues: see `docs/DEVELOPMENT.md`.
- PostGIS connection failures: see `docs/DEVELOPMENT.md`.

## Known CRS issues and QGIS workaround

- MODIS sinusoidal tiles may require a custom CRS in QGIS. Use:

```text
+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +R=6371007.181 +units=m +no_defs
```

- The geoprocess agent also attempts an automatic GDAL SRS fix for MODIS sinusoidal rasters.

## Development documentation

The GEE plugin is the default implementation and can be replaced as needed, see `docs/DEVELOPMENT.md`.
Architecture, JSON contract, plugin API details, testing, and extending geoprocesses are documented in `docs/DEVELOPMENT.md`.

## License

See `LICENSE.txt`.
