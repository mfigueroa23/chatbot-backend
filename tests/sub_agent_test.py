import pytest
from src.agents.llm import AreaInfo, FaqHit, FinalText, ProcedureHit, ToolCall, ToolCalls, build_area_messages
from src.agents.sub_agent import AreaAnswer, run_sub_agent
from src.agents.tools import AreaToolbox
from src.models.business_area import AreaScope
from src.models.procedure_field import FieldKind
from src.services.area_notifier import Requester
from src.services.procedures import FieldSpec
from tests.fakes import FakeAgentLLM, FakeNotifier, FakeRetriever

CREDITS = AreaInfo(1, "Créditos", "Créditos automotrices", AreaScope.internal, "Eres el área de Créditos", "spaces/CRED")
INSURANCE = AreaInfo(2, "Seguros", "Seguros", AreaScope.internal, "Eres el área de Seguros", "spaces/SEG")
TERM = FaqHit("¿Plazo?", "Hasta 48 meses", 0.9, id=11, area_id=1)
OTHER_AREA_FAQ = FaqHit("¿Cobertura?", "Robo y choque", 0.9, id=21, area_id=2)
CONTRACT = ProcedureHit(7, "Copia del contrato", "Se envía al correo", [FieldSpec("rut", "RUT del titular", FieldKind.rut)], 0.9, 1)
REQUESTER = Requester("Ana", "ana@autofin.cl", "google_chat")


def toolbox(retriever: FakeRetriever | None = None, faqs: list[FaqHit] | None = None,
            procedures: list[ProcedureHit] | None = None, pending: ProcedureHit | None = None,
            notifier: FakeNotifier | None = None, attempts: dict[int, int] | None = None,
            area: AreaInfo = CREDITS) -> AreaToolbox:
    return AreaToolbox(area, retriever or FakeRetriever(), notifier or FakeNotifier(), REQUESTER, "Quiero mi contrato",
                       faqs or [], procedures or [], pending, attempts or {}, max_attempts=3)


def messages_for(box: AreaToolbox, question: str = "¿Plazo?"):
    return build_area_messages(box.area, "Reglas", box.faqs, box.procedures, box.pending, [], question, 20, [])


def start(procedure_id: int = 7, text: str = "", **data: str) -> ToolCalls:
    datos = [{"campo": name, "valor": value} for name, value in data.items()]
    return ToolCalls([ToolCall("c1", "iniciar_procedimiento", {"procedimiento_id": procedure_id, "datos": datos})], text)


@pytest.mark.anyio
async def test_toolbox_busca_solo_en_su_area():
    retriever = FakeRetriever(faqs=[TERM, OTHER_AREA_FAQ])
    box = toolbox(retriever)

    output = await box.execute(ToolCall("c1", "buscar_faq", {"consulta": "cobertura del seguro"}), "")

    assert retriever.tool_searches == [(1, "cobertura del seguro")]
    assert "Hasta 48 meses" in output and "Robo y choque" not in output
    assert box.evidence


@pytest.mark.anyio
async def test_toolbox_sin_resultados_no_da_evidencia():
    box = toolbox(FakeRetriever())

    output = await box.execute(ToolCall("c1", "buscar_procedimiento", {"consulta": "algo"}), "")

    assert "Sin resultados" in output and not box.evidence


def test_toolbox_lo_encontrado_en_el_area_es_evidencia():
    assert toolbox(faqs=[TERM]).evidence
    assert not toolbox().evidence


@pytest.mark.anyio
async def test_iniciar_procedimiento_ask_explica_los_pasos_y_queda_en_curso():
    box = toolbox(procedures=[CONTRACT])

    await box.execute(start(text="El área te enviará la copia.").calls[0], "El área te enviará la copia.")

    assert box.result is not None and box.result.kind == "ask"
    assert box.result.text == "El área te enviará la copia."


@pytest.mark.anyio
async def test_iniciar_procedimiento_sent_notifica_al_area():
    notifier = FakeNotifier()
    box = toolbox(procedures=[CONTRACT], notifier=notifier)

    await box.execute(start(rut="12.345.678-5").calls[0], "")

    assert box.result is not None and box.result.kind == "sent"
    assert notifier.sent and notifier.sent[0][0] == "spaces/CRED"


@pytest.mark.anyio
async def test_iniciar_procedimiento_failed_si_no_se_entrega():
    box = toolbox(procedures=[CONTRACT], notifier=FakeNotifier(fail=True))

    await box.execute(start(rut="12.345.678-5").calls[0], "")

    assert box.result is not None and box.result.kind == "failed"


@pytest.mark.anyio
async def test_iniciar_procedimiento_gave_up_tras_los_intentos():
    box = toolbox(procedures=[CONTRACT], attempts={7: 2})

    await box.execute(start(rut="123").calls[0], "")

    assert box.result is not None and box.result.kind == "gave_up"


@pytest.mark.anyio
async def test_iniciar_procedimiento_desconocido_no_termina():
    box = toolbox(procedures=[CONTRACT])

    output = await box.execute(start(procedure_id=99).calls[0], "")

    assert box.result is None and "no está disponible" in output


@pytest.mark.anyio
async def test_loop_responde_en_un_paso_con_lo_encontrado_en_su_area():
    llm = FakeAgentLLM(steps={"Créditos": [FinalText("Hasta 48 meses [F11]")]})
    box = toolbox(faqs=[TERM])

    answer = await run_sub_agent(llm, box, messages_for(box), max_steps=4)

    assert answer == AreaAnswer(CREDITS, "answered", "Hasta 48 meses [F11]", {})
    assert llm.step_calls == 1


@pytest.mark.anyio
async def test_loop_busca_y_responde_en_dos_pasos():
    search = ToolCalls([ToolCall("c1", "buscar_faq", {"consulta": "plazo"})])
    llm = FakeAgentLLM(steps={"Créditos": [search, FinalText("Hasta 48 meses")]})
    box = toolbox(FakeRetriever(faqs=[TERM]))

    answer = await run_sub_agent(llm, box, messages_for(box), max_steps=4)

    assert answer.kind == "answered" and llm.step_calls == 2


@pytest.mark.anyio
async def test_loop_respeta_max_steps():
    search = ToolCalls([ToolCall("c1", "buscar_faq", {"consulta": "plazo"})])
    llm = FakeAgentLLM(steps={"Créditos": [search]})
    box = toolbox(FakeRetriever(faqs=[TERM]))

    answer = await run_sub_agent(llm, box, messages_for(box), max_steps=3)

    assert answer.kind == "no_answer" and llm.step_calls == 3


@pytest.mark.anyio
async def test_loop_sin_prompt_no_llama_al_modelo():
    llm = FakeAgentLLM(steps={"Créditos": [FinalText("x")]})
    box = toolbox(faqs=[TERM], area=AreaInfo(1, "Créditos", "Créditos", AreaScope.internal, None))

    answer = await run_sub_agent(llm, box, messages_for(box), max_steps=4)

    assert answer.kind == "no_answer" and llm.step_calls == 0


@pytest.mark.anyio
async def test_loop_procedimiento_ask_devuelve_el_procedimiento_en_curso():
    llm = FakeAgentLLM(steps={"Créditos": [start(text="Te explico los pasos.")]})
    box = toolbox(procedures=[CONTRACT])

    answer = await run_sub_agent(llm, box, messages_for(box), max_steps=4)

    assert (answer.kind, answer.text, answer.procedure_id) == ("procedure_ask", "Te explico los pasos.", 7)


@pytest.mark.anyio
async def test_guardrail_descarta_un_texto_sin_evidencias():
    llm = FakeAgentLLM(steps={"Créditos": [FinalText("Inventado")]})
    box = toolbox()

    answer = await run_sub_agent(llm, box, messages_for(box), max_steps=4)

    assert answer.kind == "no_answer" and answer.text is None


@pytest.mark.anyio
async def test_guardrail_lo_elegido_cuenta_como_evidencia_aunque_este_bajo_el_umbral():
    chosen = FaqHit("¿Plazo?", "Hasta 48 meses", 0.6, id=11, area_id=1)
    llm = FakeAgentLLM(steps={"Créditos": [FinalText("Hasta 48 meses")]})
    box = toolbox(faqs=[chosen])

    answer = await run_sub_agent(llm, box, messages_for(box), max_steps=4)

    assert answer.kind == "answered"



@pytest.mark.anyio
async def test_evidencia_de_la_respuesta_son_las_faq_y_procedimientos_del_area():
    llm = FakeAgentLLM(steps={"Créditos": [FinalText("Hasta 48 meses [F11]")]})
    box = toolbox(faqs=[TERM], procedures=[CONTRACT])

    answer = await run_sub_agent(llm, box, messages_for(box), max_steps=4)

    assert (answer.faqs, answer.procedures) == ([TERM], [CONTRACT])


@pytest.mark.anyio
async def test_evidencia_incluye_lo_encontrado_por_las_tools():
    retriever = FakeRetriever([TERM])
    llm = FakeAgentLLM(steps={"Créditos": [ToolCalls([ToolCall("c1", "buscar_faq", {"consulta": "plazo"})]),
                                           FinalText("Hasta 48 meses")]})
    box = toolbox(retriever)

    answer = await run_sub_agent(llm, box, messages_for(box), max_steps=4)

    assert answer.kind == "answered" and answer.faqs == [TERM]


@pytest.mark.anyio
async def test_evidencia_vacia_sin_respuesta():
    llm = FakeAgentLLM(steps={"Créditos": [FinalText("No sé")]})
    box = toolbox()

    answer = await run_sub_agent(llm, box, messages_for(box), max_steps=4)

    assert answer.kind == "no_answer" and (answer.faqs, answer.procedures) == ([], [])
