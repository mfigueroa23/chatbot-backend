#!/bin/sh
# Aplica las migraciones pendientes antes de arrancar la API. `alembic upgrade head` compara la
# revisión de la base de datos con la última migración y no hace nada si ya está al día.
set -e

echo "Verificando migraciones de la base de datos..."
alembic upgrade head

exec "$@"
