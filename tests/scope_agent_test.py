import asyncio
import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from src.agents.llm import AreaInfo, CallBudget, FaqHit, FinalText, ProcedureHit, ScopeDecision, ToolCall, ToolCalls, ToolSpec
from src.agents.scope_agent import ScopeRequest, run_scope_agent
from src.models.business_area import AreaScope
from src.models.procedure_field import FieldKind
from src.services.area_notifier import Requester
from src.services.business_data import AreaTopics
from src.services.procedures import FieldSpec
from src.utils.exceptions.agent import LlmUnavailableError
from tests.fakes import FakeAgentLLM, FakeNotifier, FakeRetriever

PAYROLL = AreaInfo(10, "Remuneraciones", "Sueldos y liquidaciones", AreaScope.internal, "Eres Remuneraciones", "spaces/RRHH")
MANAGEMENT = AreaInfo(11, "Gestión", "Carga de documentos", AreaScope.internal, "Eres Gestión", "spaces/GESTION")
NO_PROMPT = AreaInfo(12, "Comercial", "Ventas", AreaScope.internal, None)
SALARY = FaqHit("¿Cuándo pagan el sueldo?", "El día 30", 0.9, id=41, area_id=10)
LOAD = ProcedureHit(9, "Cargar documento", "Gestión lo carga", [FieldSpec("documento", "Número", FieldKind.number)], 0.9, 11)
TOPICS = {10: AreaTopics(["¿Cuándo pagan el sueldo?", "¿Cómo pido mi liquidación?"]), 11: AreaTopics([], ["Cargar documento"])}
ANA = Requester("Ana", "ana@autofin.cl", "google_chat")


def request(question: str = "¿Cuándo pagan?", pending: ProcedureHit | None = None, history: list[BaseMessage] | None = None,
            areas: list[AreaInfo] | None = None) -> ScopeRequest:
    return ScopeRequest(scope=AreaScope.internal, areas=areas or [PAYROLL, MANAGEMENT, NO_PROMPT], topics=TOPICS,
                        prompt="Prompt del agente interno", rules="Reglas", question=question, history=history or [],
                        pending=pending, attempts={}, requester=ANA, notifier=FakeNotifier())


@pytest.mark.anyio
async def test_elige_las_areas_y_las_consulta_en_paralelo():
    llm = FakeAgentLLM(scope=[ScopeDecision([10, 11], "sueldo y carga", False)],
                       steps={"Remuneraciones": [FinalText("El día 30")], "Gestión": [FinalText("Gestión lo carga")]})

    report = await run_scope_agent(llm, FakeRetriever([SALARY], [LOAD]), request(), CallBudget(100))

    assert [(answer.area.name, answer.text) for answer in report.answers] == [
        ("Remuneraciones", "El día 30"), ("Gestión", "Gestión lo carga")]
    assert report.catalog is None and (llm.scope_calls, llm.step_calls) == (1, 2)
    # La consulta reformulada es la que recibe cada área.
    assert str(llm.step_messages[0][-1].content) == "sueldo y carga"


class SlowAreasLLM(FakeAgentLLM):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.running = 0
        self.peak = 0

    async def step(self, messages: list[BaseMessage], tools: list[ToolSpec]):
        self.running += 1
        self.peak = max(self.peak, self.running)
        await asyncio.sleep(0.01)
        self.running -= 1
        return await super().step(messages, tools)


@pytest.mark.anyio
async def test_elige_dos_areas_que_corren_a_la_vez():
    llm = SlowAreasLLM(scope=[ScopeDecision([10, 11], "x", False)],
                       steps={"Remuneraciones": [FinalText("a")], "Gestión": [FinalText("b")]})

    await run_scope_agent(llm, FakeRetriever([SALARY], [LOAD]), request(), CallBudget(100))

    assert llm.peak == 2


@pytest.mark.anyio
async def test_respaldo_por_coincidencias_si_no_elige_areas_validas():
    llm = FakeAgentLLM(scope=[ScopeDecision([99], "", False)], steps={"Remuneraciones": [FinalText("El día 30")]})

    report = await run_scope_agent(llm, FakeRetriever([SALARY]), request(), CallBudget(100))

    assert [answer.area for answer in report.answers] == [PAYROLL]
    assert str(llm.step_messages[0][-1].content) == "¿Cuándo pagan?"


@pytest.mark.anyio
async def test_respaldo_sin_coincidencias_no_consulta_areas():
    llm = FakeAgentLLM(scope=[ScopeDecision([], "", False)])

    report = await run_scope_agent(llm, FakeRetriever(), request("¿vacaciones?"), CallBudget(100))

    assert report.answers == [] and llm.step_calls == 0


@pytest.mark.anyio
async def test_elige_un_area_sin_prompt_no_la_consulta():
    llm = FakeAgentLLM(scope=[ScopeDecision([12], "x", False)])

    report = await run_scope_agent(llm, FakeRetriever(), request(), CallBudget(100))

    assert report.answers == []


@pytest.mark.anyio
async def test_en_curso_va_a_su_area_aunque_elija_otra():
    start = ToolCalls([ToolCall("c1", "iniciar_procedimiento", {"procedimiento_id": 9, "datos": [
        {"campo": "documento", "valor": "123"}]})])
    llm = FakeAgentLLM(scope=[ScopeDecision([10], "123", False)], steps={"Gestión": [start]})
    notifier = FakeNotifier()
    scope_request = request("123", pending=LOAD)

    report = await run_scope_agent(llm, FakeRetriever(stored=[LOAD]),
                                   ScopeRequest(**{**scope_request.__dict__, "notifier": notifier}), CallBudget(100))

    assert [(answer.area, answer.kind) for answer in report.answers] == [(MANAGEMENT, "procedure_sent")]
    assert notifier.sent[0][0] == "spaces/GESTION" and report.attempts == {9: 0}


@pytest.mark.anyio
async def test_en_curso_el_ambito_ve_el_historial():
    llm = FakeAgentLLM(scope=[ScopeDecision([10], "x", False)], steps={"Remuneraciones": [FinalText("ok")]})
    history: list[BaseMessage] = [HumanMessage("¿Cuándo pagan?"), AIMessage("El día 30.")]

    await run_scope_agent(llm, FakeRetriever([SALARY]), request("¿y el bono?", history=history), CallBudget(100))

    assert [str(m.content) for m in llm.scope_messages[0][1:]] == ["¿Cuándo pagan?", "El día 30.", "¿y el bono?"]


@pytest.mark.anyio
async def test_catalogo_devuelve_temas_y_tramites_sin_consultar_areas():
    llm = FakeAgentLLM(scope=[ScopeDecision([], "", True)])

    report = await run_scope_agent(llm, FakeRetriever([SALARY]), request("¿qué puedo consultarte?"), CallBudget(100))

    assert report.answers == [] and llm.step_calls == 0
    assert report.catalog is not None
    assert "Remuneraciones" in report.catalog and "¿Cómo pido mi liquidación?" in report.catalog
    assert "Cargar documento" in report.catalog and "El día 30" not in report.catalog


@pytest.mark.anyio
async def test_externo_ignora_un_area_que_no_esta_en_su_ambito():
    credits = AreaInfo(1, "Créditos", "Créditos", AreaScope.external, "Eres Créditos", "spaces/CRED")
    llm = FakeAgentLLM(scope=[ScopeDecision([10], "x", False)])
    external = ScopeRequest(**{**request(areas=[credits]).__dict__, "scope": AreaScope.external, "topics": {}})

    report = await run_scope_agent(llm, FakeRetriever(), external, CallBudget(100))

    assert report.answers == []
    system = str(llm.scope_messages[0][0].content)
    assert "Créditos" in system and "Remuneraciones" not in system


@pytest.mark.anyio
async def test_presupuesto_cuenta_el_ambito_y_las_areas():
    llm = FakeAgentLLM(scope=[ScopeDecision([10], "x", False)], steps={"Remuneraciones": [FinalText("ok")]})
    budget = CallBudget(1)

    with pytest.raises(LlmUnavailableError):
        await run_scope_agent(llm, FakeRetriever([SALARY]), request(), budget)


class SignalsFirstRetriever(FakeRetriever):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started = asyncio.Event()

    async def scope_signals(self, scope: AreaScope, query: str):
        self.started.set()
        return await super().scope_signals(scope, query)


class WaitsForSignalsLLM(FakeAgentLLM):
    def __init__(self, retriever: SignalsFirstRetriever, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.retriever = retriever

    async def decide_scope(self, messages: list[BaseMessage]) -> ScopeDecision:
        # Si las señales esperaran a la decisión, este await no terminaría nunca.
        await asyncio.wait_for(self.retriever.started.wait(), timeout=1)
        return await super().decide_scope(messages)


@pytest.mark.anyio
async def test_elige_con_la_decision_y_las_senales_a_la_vez():
    retriever = SignalsFirstRetriever([SALARY])
    llm = WaitsForSignalsLLM(retriever, scope=[ScopeDecision([10], "x", False)], steps={"Remuneraciones": [FinalText("ok")]})

    report = await run_scope_agent(llm, retriever, request(), CallBudget(100))

    assert [answer.area for answer in report.answers] == [PAYROLL]
    assert retriever.refreshed_area_ids == [10, 11, 12]


@pytest.mark.anyio
async def test_en_curso_y_seguimientos_las_senales_incluyen_el_mensaje_anterior():
    retriever = FakeRetriever([SALARY])
    llm = FakeAgentLLM(scope=[ScopeDecision([10], "x", False)], steps={"Remuneraciones": [FinalText("ok")]})
    history: list[BaseMessage] = [HumanMessage("¿Dónde veo mi liquidación?"), AIMessage("En el portal.")]

    await run_scope_agent(llm, retriever, request("¿Y la de octubre?", history=history), CallBudget(100))

    assert retriever.searches[0][1] == "¿Dónde veo mi liquidación?\n¿Y la de octubre?"
