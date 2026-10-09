import pytest
from src.agents.coordinator import route, sanitize, synthesize
from src.agents.llm import AreaInfo, AreaResult, Catalog, RoutingDecision, Subtask
from src.models.business_area import AreaScope
from tests.fakes import FakeCoordinatorModel

SAC = AreaInfo(1, "Servicio al Cliente", "Pagos", "Eres SAC.", ("Pagos",))
SALES = AreaInfo(2, "Ventas", "Créditos", "Eres Ventas.", ("Créditos",))
# Catálogo del canal externo: solo áreas externas activas. El 9 (interna) y el 5 (inactiva) no están.
CATALOG = Catalog(AreaScope.external, "Coordinador externo.", "Reglas.", (SAC, SALES))


def areas(decision: RoutingDecision) -> list[int]:
    return [subtask.area_id for subtask in decision.subtasks]


def test_route_descarta_areas_de_otro_canal_inactivas_e_inventadas():
    decision = RoutingDecision("areas", (Subtask(9, "bono"), Subtask(5, "x"), Subtask(404, "y"), Subtask(1, "cuota")))

    assert areas(sanitize(decision, CATALOG, 3)) == [1]


def test_route_quita_duplicados_y_subtareas_vacias():
    decision = RoutingDecision("areas", (Subtask(1, "cuota"), Subtask(1, "prepago"), Subtask(2, "  ")))

    result = sanitize(decision, CATALOG, 3)

    assert [(s.area_id, s.query) for s in result.subtasks] == [(1, "cuota")]


def test_route_aplica_el_maximo_de_areas_por_mensaje():
    decision = RoutingDecision("areas", (Subtask(1, "cuota"), Subtask(2, "crédito")))

    assert areas(sanitize(decision, CATALOG, 1)) == [1]


def test_route_respuesta_directa_no_crea_subtareas():
    decision = RoutingDecision("direct", (Subtask(1, "ignorada"),), reply=" ¡Hola! ")

    assert sanitize(decision, CATALOG, 3) == RoutingDecision("direct", reply="¡Hola!")


def test_route_directa_sin_texto_pasa_a_consulta_sin_areas():
    assert sanitize(RoutingDecision("direct", reply=" "), CATALOG, 3) == RoutingDecision("areas", ())


@pytest.mark.anyio
async def test_route_envia_al_modelo_el_catalogo_y_sanea_su_decision():
    model = FakeCoordinatorModel(RoutingDecision("areas", (Subtask(2, "crédito"), Subtask(9, "bono"))))

    decision = await route(model, CATALOG, [], "¿Qué crédito me conviene?", 3)

    assert areas(decision) == [2]
    assert "[2] Ventas" in str(model.route_calls[0][0].content)
    assert str(model.route_calls[0][-1].content).startswith("¿Qué crédito me conviene?")


@pytest.mark.anyio
@pytest.mark.parametrize("found", [(True, True), (True, False), (False, False)])
async def test_synthesize_recibe_que_areas_encontraron_informacion(found):
    model = FakeCoordinatorModel(reply="Respuesta combinada")
    results = [AreaResult(1, "Servicio al Cliente", "cuota", found[0], "Pague en la web." if found[0] else ""),
               AreaResult(2, "Ventas", "crédito", found[1], "Crédito automotriz." if found[1] else "")]

    reply = await synthesize(model, CATALOG, [], "¿Cuota y crédito?", results)

    system = str(model.synthesize_calls[0][0].content)
    info = system[system.index("<informacion"):system.index("</informacion>")]
    assert reply == "Respuesta combinada"
    assert info.count("Encontrado: sí") == sum(found) and info.count("Encontrado: no") == 2 - sum(found)
