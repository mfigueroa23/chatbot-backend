import pytest
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from src.agents.coordinator import CoordinatorToolbox, run_coordinator
from src.agents.llm import AreaInfo, CallBudget, FaqHit, FinalText, ProcedureHit, ToolCall, ToolCalls
from src.agents.scope_agent import ScopeReport
from src.agents.sub_agent import AreaAnswer
from src.models.business_area import AreaScope
from src.models.procedure_field import FieldKind
from src.services.area_notifier import Requester
from src.services.procedures import FieldSpec
from src.utils.exceptions.agent import LlmUnavailableError
from tests.fakes import FakeAgentLLM, FakeNotifier

PAYROLL = AreaInfo(10, "Remuneraciones", "Sueldos", AreaScope.internal, "Eres Remuneraciones", "spaces/RRHH")
NO_SPACE = AreaInfo(11, "Gestión", "Documentos", AreaScope.internal, "Eres Gestión", None)
SALARY = FaqHit("¿Cuándo pagan?", "El día 30. Dudas a remuneraciones@autofin.cl", 0.9, id=41, area_id=10)
PAYSLIP = ProcedureHit(8, "Copia de liquidación", "Remuneraciones la envía", [FieldSpec("rut", "RUT", FieldKind.rut)], 0.9, 10)
ANA = Requester("Ana Pérez", "ana@autofin.cl", "google_chat")


def answered(area: AreaInfo = PAYROLL, text: str = "El día 30 [F41]") -> AreaAnswer:
    return AreaAnswer(area, "answered", text, {}, faqs=[SALARY])


class Consult:
    """Doble del agente de ámbito: registra las consultas y devuelve un informe guionizado."""

    def __init__(self, *reports: ScopeReport):
        self.reports = list(reports) or [ScopeReport([])]
        self.queries: list[str] = []

    async def __call__(self, query: str) -> ScopeReport:
        self.queries.append(query)
        return self.reports.pop(0) if len(self.reports) > 1 else self.reports[0]


async def fallback_space() -> str | None:
    return "spaces/GENERAL"


def internal(consult: Consult | None = None, notifier: FakeNotifier | None = None,
             space=fallback_space) -> CoordinatorToolbox:
    return CoordinatorToolbox(AreaScope.internal, consult or Consult(), notifier or FakeNotifier(), ANA, "¿Cuándo pagan?",
                              fallback_space=space)


def web(open_now: bool = True, offer_pending: bool = False) -> CoordinatorToolbox:
    async def is_open() -> bool:
        return open_now
    return CoordinatorToolbox(AreaScope.external, Consult(), FakeNotifier(), None, "¿Plazo?", is_open=is_open,
                              offer_pending=offer_pending)


def call(name: str, **args) -> ToolCall:
    return ToolCall(f"c-{name}", name, args)


# --- consultar_areas ---------------------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_consultar_areas_devuelve_el_contenido_y_guarda_la_evidencia():
    consult = Consult(ScopeReport([answered()]))
    box = internal(consult)

    result = await box.execute(call("consultar_areas", consulta="¿Cuándo pagan el sueldo?"))

    assert consult.queries == ["¿Cuándo pagan el sueldo?"]
    assert result == "[Remuneraciones]\nEl día 30" and box.consulted
    assert box.answers == [answered()] and box.evidence == ["¿Cuándo pagan?\nEl día 30. Dudas a remuneraciones@autofin.cl"]


@pytest.mark.anyio
async def test_consultar_areas_sin_informacion_y_catalogo():
    box = internal(Consult(ScopeReport([AreaAnswer(PAYROLL, "no_answer", None, {})]), ScopeReport([]),
                           ScopeReport([], "Remuneraciones: Sueldos\n  Temas: ¿Cuándo pagan?")))

    no_info = await box.execute(call("consultar_areas", consulta="¿bono?"))
    nothing = await box.execute(call("consultar_areas", consulta="¿vacaciones?"))
    catalog = await box.execute(call("consultar_areas", consulta="¿qué puedo consultar?"))

    assert no_info == "[Remuneraciones]\nSin información sobre esta consulta."
    assert nothing == "Ninguna área tiene información sobre esta consulta."
    assert catalog.startswith("[Temas y trámites que puedes ofrecer]") and "¿Cuándo pagan?" in catalog


@pytest.mark.anyio
async def test_consultar_areas_el_ambito_lo_fija_el_codigo():
    assert [spec.name for spec in internal().specs()] == ["consultar_areas", "avisar_area"]
    assert set(internal().specs()[0].parameters["properties"]) == {"consulta"}


@pytest.mark.anyio
async def test_consultar_areas_procedimiento_enviado_cuenta_como_entregado():
    sent = AreaAnswer(PAYROLL, "procedure_sent", "Solicitud «Copia de liquidación» entregada.", {8: 0}, 8, procedures=[PAYSLIP])
    box = internal(Consult(ScopeReport([sent], attempts={8: 0})))

    result = await box.execute(call("consultar_areas", consulta="12.345.678-5"))

    assert "entregada" in result and box.delivered and box.attempts == {8: 0}
    assert box.evidence == ["Copia de liquidación\nRemuneraciones la envía"]


@pytest.mark.anyio
async def test_consultar_areas_notificacion_fallida():
    failed = AreaAnswer(PAYROLL, "notification_failed", None, {8: 0}, 8)
    box = internal(Consult(ScopeReport([failed])))

    result = await box.execute(call("consultar_areas", consulta="12.345.678-5"))

    assert box.notification_failed and not box.delivered and "contacte directamente" in result


# --- avisar_area -------------------------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_avisar_area_entrega_al_area_consultada():
    notifier = FakeNotifier()
    box = internal(Consult(ScopeReport([answered()])), notifier)
    await box.execute(call("consultar_areas", consulta="¿bono?"))

    result = await box.execute(call("avisar_area", resumen="Pregunta por el bono de diciembre"))

    assert box.delivered and "Remuneraciones" in result
    space, text = notifier.sent[0]
    assert space == "spaces/RRHH" and "Pregunta por el bono de diciembre" in text and "Ana Pérez <ana@autofin.cl>" in text


@pytest.mark.anyio
async def test_avisar_area_sin_area_va_al_space_general():
    notifier = FakeNotifier()
    box = internal(notifier=notifier)

    await box.execute(call("avisar_area", resumen="Duda general"))

    assert notifier.sent[0][0] == "spaces/GENERAL" and box.delivered


@pytest.mark.anyio
async def test_avisar_area_fallida_pide_contactar_directamente():
    box = internal(Consult(ScopeReport([answered(NO_SPACE)])))
    await box.execute(call("consultar_areas", consulta="x"))

    result = await box.execute(call("avisar_area", resumen="x"))

    assert not box.delivered and "contacte directamente" in result


@pytest.mark.anyio
async def test_avisar_area_falla_la_entrega():
    box = internal(notifier=FakeNotifier(fail=True))

    result = await box.execute(call("avisar_area", resumen="x"))

    assert not box.delivered and "contacte directamente" in result


@pytest.mark.anyio
async def test_avisar_area_solo_una_vez_por_mensaje():
    notifier = FakeNotifier()
    box = internal(notifier=notifier)

    await box.execute(call("avisar_area", resumen="x"))
    second = await box.execute(call("avisar_area", resumen="x"))

    assert len(notifier.sent) == 1 and "ya" in second


def test_avisar_area_no_existe_en_el_web():
    assert "avisar_area" not in [spec.name for spec in web().specs()]


# --- ofrecer_ejecutivo / responder_oferta --------------------------------------------------------------------------

@pytest.mark.anyio
@pytest.mark.parametrize(("open_now", "offer"), [(True, "human"), (False, "channels")])
async def test_ofrecer_ejecutivo_segun_el_horario(open_now, offer):
    box = web(open_now)

    result = await box.execute(call("ofrecer_ejecutivo"))

    assert box.offer == offer and result


def test_ofrecer_ejecutivo_no_existe_en_el_interno():
    assert "ofrecer_ejecutivo" not in [spec.name for spec in internal().specs()]


@pytest.mark.anyio
@pytest.mark.parametrize("accepts", [True, False])
async def test_responder_oferta_con_oferta_pendiente(accepts):
    box = web(offer_pending=True)

    await box.execute(call("responder_oferta", acepta=accepts))

    assert box.offer_answer is accepts and "responder_oferta" in [spec.name for spec in box.specs()]


@pytest.mark.anyio
async def test_responder_oferta_sin_oferta_pendiente_no_hace_nada():
    box = web()

    result = await box.execute(call("responder_oferta", acepta=True))

    assert box.offer_answer is None and "No hay" in result
    assert "responder_oferta" not in [spec.name for spec in box.specs()]


# --- bucle ---------------------------------------------------------------------------------------------------------

def coordinator_messages(question: str = "¿Cuándo pagan?") -> list[BaseMessage]:
    return [SystemMessage("Coordinador"), HumanMessage(question)]


@pytest.mark.anyio
async def test_bucle_consulta_y_responde_con_el_texto_final():
    llm = FakeAgentLLM()
    box = internal(Consult(ScopeReport([answered()])))

    turn = await run_coordinator(llm, box, coordinator_messages(), CallBudget(100))

    assert turn.text == "El día 30" and llm.coordinator_step_calls == 2
    tool_message = llm.coordinator_step_messages[1][-1]
    assert isinstance(tool_message, ToolMessage) and tool_message.content == "[Remuneraciones]\nEl día 30"


@pytest.mark.anyio
async def test_bucle_responde_sin_herramientas():
    llm = FakeAgentLLM(coordinator_steps=[FinalText("¡Hola! ¿En qué te ayudo?")])

    turn = await run_coordinator(llm, internal(), coordinator_messages("hola"), CallBudget(100))

    assert turn.text == "¡Hola! ¿En qué te ayudo?" and not turn.toolbox.consulted


@pytest.mark.anyio
async def test_bucle_ejecuta_varias_herramientas_del_mismo_paso():
    notifier = FakeNotifier()
    llm = FakeAgentLLM(coordinator_steps=[
        ToolCalls([call("consultar_areas", consulta="bono"), call("avisar_area", resumen="bono")]), FinalText("Listo")])

    turn = await run_coordinator(llm, internal(Consult(ScopeReport([answered()])), notifier), coordinator_messages(),
                                 CallBudget(100))

    assert turn.text == "Listo" and len(notifier.sent) == 1


@pytest.mark.anyio
async def test_bucle_herramienta_desconocida():
    llm = FakeAgentLLM(coordinator_steps=[ToolCalls([call("borrar_todo")]), FinalText("ok")])

    turn = await run_coordinator(llm, internal(), coordinator_messages(), CallBudget(100))

    assert turn.text == "ok" and llm.coordinator_step_messages[1][-1].content == "La herramienta borrar_todo no existe."


@pytest.mark.anyio
async def test_presupuesto_agotado_es_servicio_no_disponible():
    llm = FakeAgentLLM(coordinator_steps=[ToolCalls([call("consultar_areas", consulta="x")])])

    with pytest.raises(LlmUnavailableError):
        await run_coordinator(llm, internal(), coordinator_messages(), CallBudget(5))
    assert llm.coordinator_step_calls == 5
