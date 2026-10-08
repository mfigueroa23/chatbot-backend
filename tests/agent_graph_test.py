import asyncio
import logging
from collections.abc import Awaitable, Callable
import pytest
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from src.agents.behavior import Candidate, Clarification, ClarifyOption
from src.agents.graph import AgentContext, AgentResult, Catalog, build_graph, checkpoint_serializer, run_agent
from src.agents.llm import AgentStep, AreaInfo, CoordinatorReply, FaqHit, FinalText, ToolCall, ToolCalls, ToolSpec
from src.agents.retriever import ProcedureHit, ScopeSignals
from src.models.business_area import AreaScope
from src.models.procedure_field import FieldKind
from src.services.area_notifier import Requester
from src.services.procedures import FieldSpec
from tests.fakes import FakeAgentLLM, FakeNotifier, FakeRetriever

CREDITS = AreaInfo(1, "Créditos", "Créditos automotrices", AreaScope.external, "Eres el área de Créditos", "spaces/CREDITOS")
INSURANCE = AreaInfo(2, "Seguros", "Seguros del vehículo", AreaScope.external, "Eres el área de Seguros", "spaces/SEGUROS")
NO_PROMPT = AreaInfo(3, "Postventa", "Mantenciones", AreaScope.external, None)
AGENT_PROMPT = "Prompt del agente externo cargado en la base de datos para las pruebas"
TERM = FaqHit("¿Plazo máximo?", "Hasta 48 meses", 0.9, id=11, area_id=1)
THEFT = FaqHit("¿Cubre robo?", "Sí, cubre robo", 0.85, id=21, area_id=2)
CONTRACT = ProcedureHit(7, "Copia del contrato", "El área envía la copia al correo del titular",
                        [FieldSpec("rut", "RUT del titular", FieldKind.rut)], 0.9, area_id=1)
CONTACT = {"rut": "12.345.678-5", "nombre": "Ana Pérez", "contacto": "ana@correo.cl"}


FIXED: dict[str, str | None] = {"greeting": "¡Hola!", "closing": "¡Con gusto!", "off_topic": "No puedo ayudarte con eso."}


def catalog_with(fixed: dict[str, str | None]) -> Callable[[AreaScope], Awaitable[Catalog]]:
    async def load(scope: AreaScope) -> Catalog:
        areas = [CREDITS, INSURANCE, NO_PROMPT]
        return Catalog(areas, AGENT_PROMPT, "Reglas comunes de las áreas", dict(fixed), [area.name for area in areas])
    return load


load_catalog = catalog_with(FIXED)


async def run(
    llm: FakeAgentLLM,
    retriever: FakeRetriever | None = None,
    question: str = "¿Cuál es el plazo del crédito?",
    graph=None,
    thread_id: str | None = None,
    notifier: FakeNotifier | None = None,
    requester: Requester | None = None,
    catalog: Callable[[AreaScope], Awaitable[Catalog]] = load_catalog,
    offer_pending: bool = False,
) -> AgentResult:
    graph = graph or build_graph(AreaScope.external)
    context = AgentContext(llm, retriever or FakeRetriever([TERM]), catalog, notifier or FakeNotifier(), requester,
                           offer_pending=offer_pending)
    return await run_agent(graph, question, context, thread_id)


def delegate(*area_ids: int) -> CoordinatorReply:
    return CoordinatorReply("delegate", list(area_ids))


def start(text: str = "", **data: str) -> ToolCalls:
    datos = [{"campo": name, "valor": value} for name, value in data.items()]
    return ToolCalls([ToolCall("c1", "iniciar_procedimiento", {"procedimiento_id": 7, "datos": datos})], text)


# --- Estado -------------------------------------------------------------------------------------------------------

def test_checkpoint_serializa_una_clarification():
    serde = checkpoint_serializer()
    value = {"clarifications": {"web": Clarification("options", [ClarifyOption(1, "faq", 11, 1, "¿Plazo?")])}}

    assert serde.loads_typed(serde.dumps_typed(value)) == value


# --- coordinate ---------------------------------------------------------------------------------------------------

class SignalsFirstRetriever(FakeRetriever):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started = asyncio.Event()

    async def scope_signals(self, scope: AreaScope, query: str) -> ScopeSignals:
        self.started.set()
        return await super().scope_signals(scope, query)


class WaitsForSignalsLLM(FakeAgentLLM):
    def __init__(self, retriever: SignalsFirstRetriever, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.retriever = retriever

    async def coordinate(self, messages: list[BaseMessage]) -> CoordinatorReply:
        # Si las señales esperaran a la llamada del agente del canal, este await no terminaría nunca.
        await asyncio.wait_for(self.retriever.started.wait(), timeout=1)
        return await super().coordinate(messages)


@pytest.mark.anyio
async def test_coordinate_lanza_la_llamada_y_las_senales_a_la_vez():
    retriever = SignalsFirstRetriever([TERM])
    llm = WaitsForSignalsLLM(retriever, coordinator=[delegate(1)], steps={"Créditos": [FinalText("Hasta 48 meses")]})

    result = await run(llm, retriever)

    assert result.outcome == "answered"
    assert retriever.refreshed_area_ids == [1, 2, 3]


@pytest.mark.anyio
async def test_coordinate_manipulacion_responde_la_negativa_sin_agentes_de_area():
    llm = FakeAgentLLM(coordinator=[CoordinatorReply("manipulation")])

    result = await run(llm)

    assert (result.outcome, result.reply) == ("rejected", None)
    assert llm.coordinator_calls == 1 and llm.step_calls == 0


@pytest.mark.anyio
async def test_coordinate_persona_sin_agentes_de_area():
    llm = FakeAgentLLM(coordinator=[CoordinatorReply("wants_human")])

    result = await run(llm)

    assert result.outcome == "wants_human" and llm.step_calls == 0


@pytest.mark.anyio
async def test_coordinate_mixta_tras_la_llamada_del_agente_del_canal():
    llm = FakeAgentLLM(coordinator=[delegate(1)])

    result = await run(llm, FakeRetriever([TERM], other_scope_match=True))

    assert result.outcome == "mixed_scope"
    assert llm.coordinator_calls == 1 and llm.step_calls == 0


@pytest.mark.anyio
async def test_coordinate_manipulacion_gana_a_la_mixta():
    llm = FakeAgentLLM(coordinator=[CoordinatorReply("manipulation")])

    result = await run(llm, FakeRetriever([TERM], other_scope_match=True))

    assert result.outcome == "rejected"


@pytest.mark.anyio
async def test_coordinate_el_agente_del_canal_ve_las_areas_sin_su_contenido():
    llm = FakeAgentLLM(coordinator=[delegate(1)], steps={"Créditos": [FinalText("Hasta 48 meses")]})

    await run(llm)

    system = str(llm.coordinator_messages[0][0].content)
    assert AGENT_PROMPT in system and "[A1] Créditos" in system and "[A2] Seguros" in system
    assert "Hasta 48 meses" not in system and "Eres el área de" not in system


# --- route y area_agent -------------------------------------------------------------------------------------------

class ConcurrentAreasLLM(FakeAgentLLM):
    """El agente de Créditos espera a que empiece el de Seguros: solo termina si ambos corren a la vez."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.insurance_started = asyncio.Event()

    async def step(self, messages: list[BaseMessage], tools: list[ToolSpec]) -> AgentStep:
        system = str(messages[0].content)
        if "### Área: Seguros" in system:
            self.insurance_started.set()
        else:
            await asyncio.wait_for(self.insurance_started.wait(), timeout=1)
        return await super().step(messages, tools)


@pytest.mark.anyio
async def test_route_delega_en_dos_areas_en_el_mismo_superpaso():
    llm = ConcurrentAreasLLM(coordinator=[delegate(1, 2)],
                             steps={"Créditos": [FinalText("Hasta 48 meses")], "Seguros": [FinalText("Sí, cubre robo")]})
    retriever = FakeRetriever([TERM, THEFT])

    result = await run(llm, retriever, "¿Plazo del crédito y cubre robo?")

    assert result.outcome == "answered"
    assert result.reply is not None and "Hasta 48 meses" in result.reply and "Sí, cubre robo" in result.reply
    assert sorted(retriever.area_searches) == [1, 2]
    assert {area.id for area in result.areas} == {1, 2}


@pytest.mark.anyio
async def test_route_cada_agente_de_area_solo_ve_su_area():
    llm = FakeAgentLLM(coordinator=[delegate(1, 2)],
                       steps={"Créditos": [FinalText("Hasta 48 meses")], "Seguros": [FinalText("Sí, cubre robo")]})

    await run(llm, FakeRetriever([TERM, THEFT]))

    systems = [str(messages[0].content) for messages in llm.step_messages]
    credits_system = next(system for system in systems if "### Área: Créditos" in system)
    assert "Hasta 48 meses" in credits_system and "Sí, cubre robo" not in credits_system
    assert "Eres el área de Seguros" not in credits_system


@pytest.mark.anyio
async def test_route_respaldo_con_las_areas_que_tienen_coincidencias():
    llm = FakeAgentLLM(coordinator=[delegate()], steps={"Créditos": [FinalText("Hasta 48 meses")]})

    result = await run(llm)

    assert result.outcome == "answered" and llm.step_calls == 1


@pytest.mark.anyio
async def test_route_respaldo_tambien_si_el_agente_del_canal_no_delega():
    llm = FakeAgentLLM(coordinator=[CoordinatorReply("no_answer")], steps={"Créditos": [FinalText("Hasta 48 meses")]})

    result = await run(llm)

    assert result.outcome == "answered" and llm.step_calls == 1


@pytest.mark.anyio
async def test_route_sin_areas_va_a_finalize_sin_llamar_a_agentes_de_area():
    llm = FakeAgentLLM(coordinator=[CoordinatorReply("no_answer")])

    result = await run(llm, FakeRetriever())

    assert result.outcome == "no_answer" and llm.step_calls == 0


@pytest.mark.anyio
async def test_route_ignora_areas_sin_prompt():
    llm = FakeAgentLLM(coordinator=[delegate(3)])

    result = await run(llm, FakeRetriever())

    assert result.outcome == "no_answer" and llm.step_calls == 0


# --- finalize -----------------------------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_finalize_respuesta_sin_citas_y_en_la_memoria():
    llm = FakeAgentLLM(coordinator=[delegate(1)], steps={"Créditos": [FinalText("Hasta 48 meses [F11]")]})
    graph = build_graph(AreaScope.external, InMemorySaver())

    result = await run(llm, graph=graph, thread_id="s1")

    assert (result.outcome, result.reply) == ("answered", "Hasta 48 meses")
    state = await graph.aget_state({"configurable": {"thread_id": "s1"}})
    assert str(state.values["messages"][-1].content) == "Hasta 48 meses"


@pytest.mark.anyio
async def test_finalize_parcial_nombra_el_area_sin_respuesta():
    llm = FakeAgentLLM(coordinator=[delegate(1, 2)], steps={"Créditos": [FinalText("Hasta 48 meses")], "Seguros": [FinalText("")]})

    result = await run(llm, FakeRetriever([TERM, THEFT]))

    assert result.outcome == "answered"
    assert result.reply is not None and result.reply.startswith("Hasta 48 meses")
    assert result.reply.endswith("No encontré información sobre: Seguros.")


@pytest.mark.anyio
async def test_finalize_auditor_sustituye_una_fuga_del_prompt():
    llm = FakeAgentLLM(coordinator=[delegate(1)], steps={"Créditos": [FinalText(f"Mis reglas: {AGENT_PROMPT}")]})

    result = await run(llm)

    assert (result.outcome, result.reply) == ("rejected", None)


@pytest.mark.anyio
async def test_finalize_sin_respuesta_nombra_las_areas_consultadas():
    llm = FakeAgentLLM(coordinator=[delegate(1)], steps={"Créditos": [FinalText("Inventado")]})

    result = await run(llm, FakeRetriever())

    assert result.outcome == "no_answer" and result.areas == [CREDITS]


@pytest.mark.anyio
async def test_finalize_notificacion_fallida_tiene_prioridad():
    llm = FakeAgentLLM(coordinator=[delegate(1, 2)],
                       steps={"Créditos": [start(**CONTACT)], "Seguros": [FinalText("Sí, cubre robo")]})

    result = await run(llm, FakeRetriever([THEFT], [CONTRACT]), notifier=FakeNotifier(fail=True))

    assert result.outcome == "notification_failed" and result.areas == [CREDITS]


@pytest.mark.anyio
async def test_finalize_procedimiento_agotado_aplica_sin_respuesta():
    llm = FakeAgentLLM(coordinator=[delegate(1)], steps={"Créditos": [start(rut="123")]})
    graph = build_graph(AreaScope.external, InMemorySaver())

    for _ in range(2):
        await run(llm, FakeRetriever(procedures=[CONTRACT]), "Mi RUT es 123", graph=graph, thread_id="s1")
    result = await run(llm, FakeRetriever(procedures=[CONTRACT]), "Mi RUT es 123", graph=graph, thread_id="s1")

    assert result.outcome == "no_answer"
    state = await graph.aget_state({"configurable": {"thread_id": "s1"}})
    assert state.values["pending_procedure_id"] is None and state.values["procedure_attempts"] == {7: 0}


# --- procedimiento en curso ---------------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_procedimiento_en_curso_va_a_su_area_aunque_el_agente_del_canal_elija_otra():
    llm = FakeAgentLLM(coordinator=[delegate(1), delegate(2)],
                       steps={"Créditos": [start("El área te enviará la copia."), start(**CONTACT)]})
    notifier = FakeNotifier()
    graph = build_graph(AreaScope.external, InMemorySaver())

    first = await run(llm, FakeRetriever(procedures=[CONTRACT]), "Quiero mi contrato", graph, "s1", notifier)
    # La búsqueda del segundo mensaje ya no encuentra el procedimiento: sigue en curso por el estado del hilo.
    second = await run(llm, FakeRetriever(stored=[CONTRACT]), "12.345.678-5, Ana Pérez, ana@correo.cl", graph, "s1", notifier)

    assert (first.outcome, first.reply) == ("answered", "El área te enviará la copia.")
    assert second.outcome == "answered" and second.reply is not None and "Copia del contrato" in second.reply
    assert notifier.sent and notifier.sent[0][0] == "spaces/CREDITOS"


# --- Casos de la spec 001 -----------------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_thread_recuerda_la_conversacion_y_aisla_hilos():
    graph = build_graph(AreaScope.external, InMemorySaver())
    llm = FakeAgentLLM(coordinator=[delegate(1)], steps={"Créditos": [FinalText("Hasta 48 meses")]})

    await run(llm, graph=graph, thread_id="a", question="¿Plazo del crédito?")
    await run(llm, graph=graph, thread_id="a", question="¿Y la tasa?")
    await run(llm, graph=graph, thread_id="b", question="Hola")

    second_turn = [str(m.content) for m in llm.coordinator_messages[1][1:-1]]
    assert second_turn == ["¿Plazo del crédito?", "Hasta 48 meses"]
    assert len(llm.coordinator_messages[2]) == 2  # solo el system prompt y la pregunta
    assert [str(m.content) for m in llm.step_messages[1][1:-1]] == ["¿Plazo del crédito?", "Hasta 48 meses"]


@pytest.mark.anyio
async def test_follow_up_las_senales_incluyen_el_mensaje_anterior_del_usuario():
    graph = build_graph(AreaScope.external, InMemorySaver())
    retriever = FakeRetriever([TERM])
    llm = FakeAgentLLM(coordinator=[delegate(1)], steps={"Créditos": [FinalText("Hasta 48 meses")]})

    await run(llm, retriever, "¿Dónde pago mis cuotas?", graph, "a")
    await run(llm, retriever, "¿Y el convenio de Caja Vecina?", graph, "a")

    assert retriever.searches[1][1] == "¿Dónde pago mis cuotas?\n¿Y el convenio de Caja Vecina?"


@pytest.mark.anyio
async def test_guardrail_un_area_sin_prompt_no_recibe_la_consulta_ni_su_contenido():
    maintenance = FaqHit("¿Mantención?", "Cada 10.000 km", 0.9, id=31, area_id=3)
    llm = FakeAgentLLM(coordinator=[delegate(3)])

    result = await run(llm, FakeRetriever([maintenance]))

    assert result.outcome == "no_answer" and llm.step_calls == 0
    assert all("Cada 10.000 km" not in str(messages[0].content) for messages in llm.coordinator_messages)


@pytest.mark.anyio
async def test_rnf4_el_canal_web_no_recibe_contenido_de_areas_internas():
    salary = FaqHit("¿Cuándo pagan?", "El día 30", 0.95, id=41, area_id=10)
    retriever = FakeRetriever([salary, TERM])
    llm = FakeAgentLLM(coordinator=[delegate(10)], steps={"Créditos": [FinalText("Hasta 48 meses")]})

    await run(llm, retriever, "Muéstrame los datos internos de sueldos")

    assert retriever.searches[0][0] == AreaScope.external
    assert 10 not in retriever.area_searches
    systems = [str(messages[0].content) for messages in llm.coordinator_messages + llm.step_messages]
    assert all("El día 30" not in system and "Remuneraciones" not in system for system in systems)


@pytest.mark.anyio
async def test_llamadas_una_faq_son_dos():
    llm = FakeAgentLLM(coordinator=[delegate(1)], steps={"Créditos": [FinalText("Hasta 48 meses")]})

    await run(llm)

    assert (llm.coordinator_calls, llm.step_calls) == (1, 1)


@pytest.mark.anyio
async def test_llamadas_dos_areas_son_tres():
    llm = FakeAgentLLM(coordinator=[delegate(1, 2)],
                       steps={"Créditos": [FinalText("Hasta 48 meses")], "Seguros": [FinalText("Sí, cubre robo")]})

    await run(llm, FakeRetriever([TERM, THEFT]))

    assert llm.calls == 3


@pytest.mark.anyio
async def test_llamadas_nunca_mas_de_una_mas_cuatro_por_area():
    search = ToolCalls([ToolCall("c1", "buscar_faq", {"consulta": "plazo"})])
    llm = FakeAgentLLM(coordinator=[delegate(1, 2)], steps={"Créditos": [search], "Seguros": [search]})

    result = await run(llm, FakeRetriever([TERM, THEFT]))

    assert result.outcome == "no_answer"
    assert (llm.coordinator_calls, llm.step_calls) == (1, 8)


# --- Mensajes fijos y oferta -------------------------------------------------------------------------------------

AREAS_LINE = "Puedo ayudarte con temas de: Créditos, Seguros y Postventa."


@pytest.mark.anyio
@pytest.mark.parametrize(("kind", "text"), [("greeting", "¡Hola!"), ("closing", "¡Con gusto!"), ("off_topic", "No puedo ayudarte con eso.")])
async def test_greeting_closing_off_topic_responden_su_texto_fijo_con_una_llamada(kind, text):
    llm = FakeAgentLLM(coordinator=[CoordinatorReply(kind)])

    result = await run(llm, FakeRetriever())

    assert result.outcome == kind and result.reply is not None and result.reply.startswith(text)
    assert llm.calls == 1


@pytest.mark.anyio
async def test_greeting_nombra_todas_las_areas_activas_del_canal_web_sin_las_internas():
    result = await run(FakeAgentLLM(coordinator=[CoordinatorReply("greeting")]), FakeRetriever())

    assert result.reply is not None and result.reply.endswith(AREAS_LINE)
    assert "Remuneraciones" not in result.reply


@pytest.mark.anyio
async def test_greeting_queda_en_la_memoria_del_hilo():
    graph = build_graph(AreaScope.external, InMemorySaver())

    await run(FakeAgentLLM(coordinator=[CoordinatorReply("greeting")]), FakeRetriever(), "hola", graph, "s1")

    state = await graph.aget_state({"configurable": {"thread_id": "s1"}})
    assert str(state.values["messages"][-1].content).startswith("¡Hola!")


@pytest.mark.anyio
async def test_greeting_con_consulta_delega_en_el_area():
    llm = FakeAgentLLM(coordinator=[delegate(1)], steps={"Créditos": [FinalText("Hasta 48 meses")]})

    result = await run(llm, question="Hola, ¿cuál es el plazo del crédito?")

    assert (result.outcome, result.reply) == ("answered", "Hasta 48 meses")


@pytest.mark.anyio
async def test_off_topic_con_una_faq_propia_sobre_el_umbral_delega_en_su_area():
    llm = FakeAgentLLM(coordinator=[CoordinatorReply("off_topic")], steps={"Créditos": [FinalText("Hasta 48 meses")]})

    result = await run(llm, question="Derechos ARCO")

    assert result.outcome == "answered" and llm.step_calls == 1


@pytest.mark.anyio
async def test_texto_fijo_ausente_registra_el_error_y_sigue_con_el_flujo(caplog):
    caplog.set_level(logging.ERROR, logger="src")
    llm = FakeAgentLLM(coordinator=[CoordinatorReply("greeting")], steps={"Créditos": [FinalText("Hasta 48 meses")]})

    result = await run(llm, catalog=catalog_with({**FIXED, "greeting": None}))

    assert "external_greeting" in caplog.text
    assert (result.outcome, result.reply) == ("answered", "Hasta 48 meses")


@pytest.mark.anyio
async def test_texto_fijo_cambia_entre_mensajes_sin_reiniciar():
    texts = iter(["¡Hola!", "¡Buenas!"])

    async def changing(scope: AreaScope) -> Catalog:
        return await catalog_with({**FIXED, "greeting": next(texts)})(scope)

    llm = FakeAgentLLM(coordinator=[CoordinatorReply("greeting")])
    first = await run(llm, FakeRetriever(), catalog=changing)
    second = await run(llm, FakeRetriever(), catalog=changing)

    assert first.reply is not None and first.reply.startswith("¡Hola!")
    assert second.reply is not None and second.reply.startswith("¡Buenas!")


@pytest.mark.anyio
async def test_otro_ambito_sin_coincidencias_propias_es_fuera_de_tema_aunque_haya_candidatos():
    candidate = Candidate("faq", 11, 1, "¿Plazo máximo?", 0.6)
    llm = FakeAgentLLM(coordinator=[delegate()])

    result = await run(llm, FakeRetriever(other_scope_match=True, candidates=[candidate]))

    assert result.outcome == "off_topic" and result.reply is not None and result.reply.startswith("No puedo ayudarte")
    assert llm.step_calls == 0


@pytest.mark.anyio
@pytest.mark.parametrize(("kind", "outcome"), [("accept_offer", "offer_accepted"), ("decline_offer", "offer_declined")])
async def test_oferta_pendiente_se_responde_por_texto(kind, outcome):
    result = await run(FakeAgentLLM(coordinator=[CoordinatorReply(kind)]), FakeRetriever(), "ok", offer_pending=True)

    assert (result.outcome, result.reply) == (outcome, None)


@pytest.mark.anyio
async def test_oferta_sin_oferta_pendiente_sigue_el_flujo_normal():
    llm = FakeAgentLLM(coordinator=[CoordinatorReply("accept_offer")], steps={"Créditos": [FinalText("Hasta 48 meses")]})

    result = await run(llm, offer_pending=False)

    assert result.outcome == "answered"


@pytest.mark.anyio
async def test_fijo_en_procedimiento_no_toca_el_procedimiento_ni_los_intentos():
    llm = FakeAgentLLM(coordinator=[delegate(1), CoordinatorReply("greeting"), delegate(1)],
                       steps={"Créditos": [start(rut="123"), start(**CONTACT)]})
    notifier = FakeNotifier()
    graph = build_graph(AreaScope.external, InMemorySaver())
    config: RunnableConfig = {"configurable": {"thread_id": "s1"}}

    await run(llm, FakeRetriever(procedures=[CONTRACT]), "Mi RUT es 123", graph, "s1", notifier)
    before = (await graph.aget_state(config)).values
    greeting = await run(llm, FakeRetriever(stored=[CONTRACT]), "hola", graph, "s1", notifier)
    after = (await graph.aget_state(config)).values
    done = await run(llm, FakeRetriever(stored=[CONTRACT]), "12.345.678-5, Ana Pérez, ana@correo.cl", graph, "s1", notifier)

    assert greeting.outcome == "greeting"
    assert (after["pending_procedure_id"], after["procedure_attempts"]) == (7, before["procedure_attempts"]) == (7, {7: 1})
    assert done.outcome == "answered" and notifier.sent
