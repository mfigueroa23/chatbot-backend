"""Coordinador: la única voz del asistente. Conversa en texto libre y actúa con herramientas.

No conoce las áreas: consulta al agente de ámbito de su canal, que el código fija. Cada herramienta deja en el toolbox
los hechos que el código necesita después (evidencia, entregas, oferta) para no depender de lo que el modelo diga.
"""
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from src.agents.audit import strip_citations
from src.agents.llm import AgentLLM, CallBudget, FinalText, ToolCall, ToolSpec
from src.agents.scope_agent import ScopeReport
from src.agents.strategies import Notifier
from src.agents.sub_agent import AreaAnswer
from src.models.business_area import AreaScope
from src.services.area_notifier import Requester, format_unanswered
from src.utils.exceptions.notification import NotificationDeliveryError

logger = logging.getLogger(__name__)

CONSULT = ToolSpec(
    "consultar_areas",
    "Consulta al especialista de las áreas de este canal. Devuelve la información de las áreas que correspondan o, si "
    "el usuario pregunta qué puede consultar, los temas y trámites disponibles. Úsala para cualquier consulta sobre la "
    "empresa y para continuar un trámite con los datos que entregue el usuario.",
    {"type": "object", "properties": {"consulta": {
        "type": "string", "description": "La consulta completa, con el contexto de la conversación"}}, "required": ["consulta"]})
NOTIFY = ToolSpec(
    "avisar_area",
    "Avisa al área para que una persona revise la consulta. Úsala solo si el colaborador lo pide explícitamente.",
    {"type": "object", "properties": {"resumen": {
        "type": "string", "description": "Resumen de la consulta para el área"}}, "required": ["resumen"]})
OFFER = ToolSpec(
    "ofrecer_ejecutivo",
    "Ofrece al cliente hablar con un ejecutivo cuando no puedes resolver su consulta o pide hablar con una persona; "
    "fuera de horario se le muestran los canales oficiales.",
    {"type": "object", "properties": {}})
ANSWER_OFFER = ToolSpec(
    "responder_oferta",
    "Registra si el cliente acepta o rechaza la oferta de hablar con un ejecutivo que está pendiente.",
    {"type": "object", "properties": {"acepta": {"type": "boolean"}}, "required": ["acepta"]})

NO_AREA = "Ninguna área tiene información sobre esta consulta."
NO_INFO = "Sin información sobre esta consulta."
CATALOG_HEADER = "[Temas y trámites que puedes ofrecer]"
NOTIFY_FAILED = "No se pudo avisar al área; pide al colaborador que contacte directamente con el área."

Consult = Callable[[str], Awaitable[ScopeReport]]
Offer = Literal["human", "channels"]

class CoordinatorToolbox:
    def __init__(
        self,
        scope: AreaScope,
        consult: Consult,
        notifier: Notifier,
        requester: Requester | None,
        question: str,
        fallback_space: Callable[[], Awaitable[str | None]] | None = None,
        is_open: Callable[[], Awaitable[bool]] | None = None,
        offer_pending: bool = False,
    ):
        self.scope = scope
        self._consult = consult
        self._notifier = notifier
        self._requester = requester
        self._question = question
        self._fallback_space = fallback_space
        self._is_open = is_open
        self.offer_pending = offer_pending
        # Hechos del turno que el código usa después.
        self.consulted = False
        self.answers: list[AreaAnswer] = []
        self.evidence: list[str] = []
        self.attempts: dict[int, int] = {}
        self.procedure: AreaAnswer | None = None  # último resultado de un procedimiento en este turno
        self.delivered = False  # alguna notificación al área se entregó
        self.notification_failed = False
        self.notified = False
        self.offer: Offer | None = None
        self.offer_answer: bool | None = None

    def specs(self) -> list[ToolSpec]:
        if self.scope == AreaScope.internal:
            return [CONSULT, NOTIFY]
        return [CONSULT, OFFER, *([ANSWER_OFFER] if self.offer_pending else [])]

    async def execute(self, call: ToolCall) -> str:
        names = {spec.name for spec in self.specs()}
        if call.name == ANSWER_OFFER.name and self.scope == AreaScope.external and not self.offer_pending:
            return "No hay una oferta de ejecutivo pendiente."
        if call.name not in names:
            return f"La herramienta {call.name} no existe."
        match call.name:
            case "consultar_areas":
                return await self._consult_areas(str(call.args.get("consulta", "")) or self._question)
            case "avisar_area":
                return await self._notify(str(call.args.get("resumen", "")) or self._question)
            case "ofrecer_ejecutivo":
                return await self._offer()
        return self._answer_offer(bool(call.args.get("acepta")))

    async def _consult_areas(self, query: str) -> str:
        report = await self._consult(query)
        self.consulted = True
        self.attempts.update(report.attempts)
        if report.catalog is not None:
            return f"{CATALOG_HEADER}\n{report.catalog}"
        if not report.answers:
            return NO_AREA
        self.answers += report.answers
        for answer in report.answers:
            self.evidence += [f"{faq.question}\n{faq.answer}" for faq in answer.faqs]
            self.evidence += [f"{procedure.name}\n{procedure.steps}" for procedure in answer.procedures]
        return "\n\n".join(f"[{answer.area.name}]\n{self._describe(answer)}" for answer in report.answers)

    def _describe(self, answer: AreaAnswer) -> str:
        if answer.kind in ("procedure_ask", "procedure_sent", "notification_failed", "gave_up"):
            self.procedure = answer
        name = next((p.name for p in answer.procedures if p.id == answer.procedure_id), "el trámite")
        match answer.kind:
            case "answered":
                return strip_citations(answer.text or "") or NO_INFO
            case "procedure_ask" | "procedure_sent":
                if answer.kind == "procedure_sent":
                    self.delivered = True
                return answer.text or NO_INFO
            case "notification_failed":
                self.notification_failed = True
                if self.scope == AreaScope.internal:
                    return (f"No se pudo entregar la solicitud «{name}» al área; indica al colaborador que no se envió y "
                            "que contacte directamente con el área.")
                return f"No se pudo entregar la solicitud «{name}» al área; se mostrarán al cliente los canales oficiales."
            case "gave_up":
                return f"El usuario no entregó datos válidos para «{name}» tras los intentos permitidos; no se avisó al área."
        return NO_INFO

    async def _notify(self, summary: str) -> str:
        if self.notified:
            return "El aviso ya se intentó en este mensaje."
        self.notified = True
        requester = self._requester or Requester(None, None, "google_chat")
        areas = list({answer.area.id: answer.area for answer in self.answers}.values())
        try:
            if areas:
                targets = [(area.chat_space, area.name) for area in areas]
            else:
                targets = [(await self._fallback_space() if self._fallback_space else None, None)]
            for space, area_name in targets:
                # Un área sin space configurado cuenta como aviso fallido: el colaborador debe saber a quién acudir.
                if not space:
                    raise NotificationDeliveryError(f"El área {area_name or 'general'} no tiene space configurado")
                await self._notifier.notify(space, format_unanswered(summary, area_name, requester))
        except NotificationDeliveryError as exc:
            logger.error("No se pudo avisar al área de la consulta: %s", exc)
            return NOTIFY_FAILED
        self.delivered = True
        names = ", ".join(area.name for area in areas) or "general"
        return f"Aviso entregado al área {names}; una persona revisará la consulta."

    async def _offer(self) -> str:
        if self._is_open is not None and await self._is_open():
            self.offer = "human"
            return "Se mostrará al cliente la opción de hablar con un ejecutivo; invítalo a aceptarla o rechazarla."
        self.offer = "channels"
        return "Fuera del horario de atención: se mostrarán los canales oficiales; invita al cliente a usarlos o a reformular."

    def _answer_offer(self, accepts: bool) -> str:
        self.offer_answer = accepts
        if accepts:
            return "El cliente aceptó: se le pedirán su nombre y un dato de contacto."
        return "El cliente rechazó la oferta: se le mostrarán los canales oficiales."

@dataclass(frozen=True)
class CoordinatorTurn:
    text: str
    toolbox: CoordinatorToolbox

async def run_coordinator(llm: AgentLLM, toolbox: CoordinatorToolbox, messages: list[BaseMessage],
                          budget: CallBudget) -> CoordinatorTurn:
    messages = list(messages)
    # Sin tope propio de pasos: lo acota el presupuesto de llamadas del mensaje.
    while True:
        budget.spend()
        step = await llm.step(messages, toolbox.specs())
        if isinstance(step, FinalText):
            return CoordinatorTurn(step.text.strip(), toolbox)
        messages.append(AIMessage(content=step.text, tool_calls=[
            {"id": call.id, "name": call.name, "args": call.args, "type": "tool_call"} for call in step.calls]))
        # En orden: avisar al área depende de las áreas consultadas en el mismo paso.
        for call in step.calls:
            messages.append(ToolMessage(content=await toolbox.execute(call), tool_call_id=call.id, name=call.name))
