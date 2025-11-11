#!/bin/bash

# ================================================
# Script para crear un Shapefile (Rectángulo) desde un BBOX
# Uso: ./crear_bbox.sh min_lon min_lat max_lon max_lat EPSG_CODE nombre_archivo
# ================================================

# --- Validación de Entradas ---

# 1. Revisar si GDAL (ogr2ogr) está instalado
if ! command -v ogr2ogr &> /dev/null
then
    echo "Error: 'ogr2ogr' no se encuentra."
    echo "Por favor, instala GDAL (ej: sudo apt install gdal-bin)"
    exit 1
fi

# 2. Revisar el número de argumentos (ahora 6)
if [ "$#" -ne 6 ]; then
    echo "Uso incorrecto."
    echo "Ejemplo: $0 -60.76 -33.02 -60.61 -32.85 4326 mi_rectangulo"
    exit 1
fi

# --- Asignación de Variables ---
MIN_LON=$1
MIN_LAT=$2
MAX_LON=$3
MAX_LAT=$4
EPSG_CODE=$5 # Nuevo parámetro
OUTPUT_NAME=$6 # Este ahora es el sexto argumento
OUTPUT_SHP="${OUTPUT_NAME}.shp"

# --- Lógica Principal (Generar GeoJSON y convertir) ---

echo "Creando Shapefile: $OUTPUT_SHP (EPSG:$EPSG_CODE)..."

# Pasamos el GeoJSON a ogr2ogr
cat << EOF | ogr2ogr -f "ESRI Shapefile" "$OUTPUT_SHP" /vsistdin/ -a_srs "EPSG:$EPSG_CODE"
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [$MIN_LON, $MIN_LAT],
            [$MAX_LON, $MIN_LAT],
            [$MAX_LON, $MAX_LAT],
            [$MIN_LON, $MAX_LAT],
            [$MIN_LON, $MIN_LAT]
          ]
        ]
      },
      "properties": {
        "id": 1,
        "name": "$OUTPUT_NAME"
      }
    }
  ]
}
EOF

# --- Confirmación ---
if [ $? -eq 0 ]; then
    echo "¡Éxito! Se crearon los archivos para '$OUTPUT_SHP'."
else
    echo "Error: Ocurrió un problema durante la conversión de ogr2ogr."
fi
