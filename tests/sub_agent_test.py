import pytest
from src.agents.llm import AreaInfo, FaqHit, FinalText, ProcedureHit, ToolCall, ToolCalls, build_area_messages
from src.agents.sub_agent import AreaAnswer, run_sub_agent
from src.agents.tools import AreaToolbox
from src.models.business_area import AreaScope
from src.models.procedure_field import FieldKind
from src.services.area_notifier import Requester
from src.services.procedures import FieldSpec
import json
from src.services.edr import EdrDocument
from src.services.jira_client import JiraIssue, JiraIssueRef
from tests.fakes import FakeAgentLLM, FakeNotifier, FakeProjects, FakeRetriever

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



# --- Jira en el área habilitada (spec 005) --------------------------------------------------------------------------

PROJECTS_AREA = AreaInfo(3, "Proyectos", "Jefes de Proyecto de TI", AreaScope.internal, "Eres Proyectos", None, ("jira", "edr"))
EPIC = JiraIssue("DAIA-52", "Curse automatizado", "En curso", "Epic", "Automatizar el curse", "Luis Ramos", "Ana Pérez", None,
                 [JiraIssueRef("DAIA-53", "RF-01 fechas del pagaré", "Hecho")])


def project_toolbox(projects: FakeProjects, area: AreaInfo = PROJECTS_AREA) -> AreaToolbox:
    return AreaToolbox(area, FakeRetriever(), FakeNotifier(), REQUESTER, "¿En qué está DAIA-52?", [], [], None, {}, 3,
                       projects=projects, conversation_id="spaces/AAA")


def test_jira_sin_herramienta_en_el_area_no_se_ofrece():
    names = [spec.name for spec in project_toolbox(FakeProjects(), CREDITS).specs()]

    assert "buscar_tickets" not in names and "leer_ticket" not in names


@pytest.mark.anyio
async def test_jira_colaborador_no_habilitado_no_llama_a_jira():
    projects = FakeProjects(enabled=False, issues={"DAIA-52": EPIC})
    box = project_toolbox(projects)

    result = await box.execute(ToolCall("c1", "leer_ticket", {"clave": "DAIA-52"}), "")

    assert "no está habilitada" in result and projects.jira_calls == 0 and not box.evidence


@pytest.mark.anyio
async def test_jira_tablero_no_permitido_no_se_encuentra():
    projects = FakeProjects(issues={"OTRO-1": EPIC})
    box = project_toolbox(projects)

    result = await box.execute(ToolCall("c1", "leer_ticket", {"clave": "OTRO-1"}), "")

    assert result == "No encuentro el ticket OTRO-1." and projects.jira_calls == 0


@pytest.mark.anyio
async def test_jira_epica_con_subtareas_e_hijos_cuenta_como_evidencia():
    projects = FakeProjects(issues={"DAIA-52": EPIC}, children={"DAIA-52": [JiraIssueRef("DAIA-60", "Notificaciones", "Por hacer")]})
    box = project_toolbox(projects)

    result = await box.execute(ToolCall("c1", "leer_ticket", {"clave": "daia-52"}), "")

    assert "DAIA-52 · Curse automatizado · En curso" in result and "DAIA-53 RF-01 fechas del pagaré (Hecho)" in result
    assert "DAIA-60 Notificaciones (Por hacer)" in result and box.evidence and box.documents == [result]


@pytest.mark.anyio
async def test_jira_buscar_tickets_acota_el_jql_a_los_tableros():
    projects = FakeProjects(found=[JiraIssueRef("DAIA-53", "RF-01", "Hecho")])
    box = project_toolbox(projects)

    result = await box.execute(ToolCall("c1", "buscar_tickets", {"jql": 'text ~ "pagaré"'}), "")

    assert projects.searches == ['project in ("DAIA") AND (text ~ "pagaré")'] and "DAIA-53 RF-01 (Hecho)" in result


@pytest.mark.anyio
async def test_jira_caido_responde_sin_detalles():
    box = project_toolbox(FakeProjects(down=True))

    result = await box.execute(ToolCall("c1", "leer_ticket", {"clave": "DAIA-52"}), "")

    assert result == "No se pudo consultar Jira en este momento."



# --- EDR en el área habilitada (spec 005) ---------------------------------------------------------------------------

EDR_JSON = json.dumps({"titulo": "EDR DAIA-52 Curse automatizado", "objetivo_general": "Automatizar el curse",
                       "product_owner": {"nombre": "Luis Ramos", "cargo": "Gerente de Operaciones"}})
JIRA_ONLY = AreaInfo(3, "Proyectos", "Jefes de Proyecto de TI", AreaScope.internal, "Eres Proyectos", None, ("jira",))


def save_call(edr_json: str = EDR_JSON, new: bool = False) -> ToolCall:
    return ToolCall("c1", "guardar_edr", {"edr_json": edr_json, "nuevo": new})


def test_edr_sin_herramienta_en_el_area_no_se_ofrece():
    names = [spec.name for spec in project_toolbox(FakeProjects(), JIRA_ONLY).specs()]

    assert "guardar_edr" not in names and "leer_edr" not in names


@pytest.mark.anyio
async def test_edr_colaborador_no_habilitado_no_guarda():
    projects = FakeProjects(enabled=False)

    result = await project_toolbox(projects).execute(save_call(), "")

    assert "no está habilitada" in result and projects.saved == []


@pytest.mark.anyio
async def test_edr_guardar_devuelve_el_enlace_y_cuenta_como_evidencia():
    projects = FakeProjects()
    box = project_toolbox(projects)

    result = await box.execute(save_call(), "")

    assert "https://docs.google.com/document/d/DOC1/edit" in result
    assert box.links == ["https://docs.google.com/document/d/DOC1/edit"] and box.evidence
    assert any("Luis Ramos" in document for document in box.documents)
    conversation, saved, new = projects.saved[0]
    assert conversation == "spaces/AAA" and isinstance(saved, EdrDocument) and new is False


@pytest.mark.anyio
@pytest.mark.parametrize("edr_json", ["no es json", json.dumps({"objetivo_general": "sin título"})])
async def test_edr_invalido_pide_corregirlo(edr_json):
    projects = FakeProjects()

    result = await project_toolbox(projects).execute(save_call(edr_json), "")

    assert result.startswith("El EDR no es válido") and projects.saved == []


@pytest.mark.anyio
async def test_edr_drive_caido_no_queda_guardado():
    box = project_toolbox(FakeProjects(drive_down=True))

    result = await box.execute(save_call(), "")

    assert "No se pudo guardar el EDR" in result and box.links == []


@pytest.mark.anyio
async def test_edr_leer_el_actual_o_ninguno():
    existing = EdrDocument(titulo="EDR DAIA-52", objetivo_general="Automatizar el curse")
    with_edr = project_toolbox(FakeProjects(edrs={"spaces/AAA": existing}))
    without = project_toolbox(FakeProjects())

    found = await with_edr.execute(ToolCall("c1", "leer_edr", {}), "")
    missing = await without.execute(ToolCall("c1", "leer_edr", {}), "")

    assert "Automatizar el curse" in found and missing == "Todavía no hay un EDR en esta conversación."


@pytest.mark.anyio
async def test_edr_el_enlace_llega_en_la_respuesta_del_area():
    llm = FakeAgentLLM(steps={"Proyectos": [ToolCalls([save_call()]), FinalText("Dejé el borrador del EDR.")]})
    box = project_toolbox(FakeProjects())

    answer = await run_sub_agent(llm, box, messages_for(box), max_steps=4)

    assert answer.kind == "answered" and answer.links == ["https://docs.google.com/document/d/DOC1/edit"]


@pytest.mark.anyio
async def test_edr_guardado_sin_pasos_para_resumir_igual_entrega_el_enlace():
    llm = FakeAgentLLM(steps={"Proyectos": [ToolCalls([save_call()])]})
    box = project_toolbox(FakeProjects())

    answer = await run_sub_agent(llm, box, messages_for(box), max_steps=1)

    assert answer.kind == "answered" and answer.text
    assert answer.links == ["https://docs.google.com/document/d/DOC1/edit"]
