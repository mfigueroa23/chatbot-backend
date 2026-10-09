import asyncio
import logging
from datetime import UTC, datetime
import pytest
from fastapi.testclient import TestClient
from main import app
from src.services.retention import retention_cutoff, run_retention
from src.utils.exceptions.database import DatabaseUnavailableError


def test_la_fecha_de_corte_resta_los_dias_de_retencion():
    assert retention_cutoff(datetime(2026, 10, 31, tzinfo=UTC), 30) == datetime(2026, 10, 1, tzinfo=UTC)


@pytest.mark.anyio
async def test_un_error_de_bd_se_registra_y_la_tarea_sigue(caplog):
    calls: list[int] = []

    async def purge() -> int:
        calls.append(1)
        if len(calls) == 1:
            raise DatabaseUnavailableError("conexión rechazada")
        return 0

    with caplog.at_level(logging.ERROR, logger="src"):
        task = asyncio.create_task(run_retention(purge, interval=0.01))
        while len(calls) < 2:
            await asyncio.sleep(0.01)
        task.cancel()

    assert len(calls) >= 2 and "base de datos no disponible" in caplog.text


def test_la_app_arranca_y_se_cierra_sin_tocar_la_bd():
    # La primera pasada espera una hora: arrancar y cerrar no ejecuta ningún DELETE.
    with TestClient(app) as client:
        assert client.get("/").json() is True
