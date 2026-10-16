from typing import cast
from sqlalchemy import DefaultClause, String, Table, UniqueConstraint
from src.models.cors_origins import CorsOrigin

TABLE = cast(Table, CorsOrigin.__table__)


def test_cors_origin_tiene_origen_unico_y_no_nulo():
    unique = [c for c in TABLE.constraints if isinstance(c, UniqueConstraint) and c.name == "uq_cors_origins_origin"]
    origin = TABLE.c.origin

    assert TABLE.name == "cors_origins"
    assert origin.nullable is False
    assert isinstance(origin.type, String) and origin.type.length == 255
    assert len(unique) == 1
    assert [column.name for column in unique[0].columns] == ["origin"]


def test_cors_origin_esta_habilitado_por_defecto_en_la_base_de_datos():
    enabled = TABLE.c.enabled

    assert enabled.nullable is False
    assert isinstance(enabled.server_default, DefaultClause)
    assert str(enabled.server_default.arg) == "true"
