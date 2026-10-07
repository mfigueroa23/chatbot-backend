import logging
from typing import Any, Literal
from src.agents.llm import AreaInfo, ToolCall, ToolSpec
from src.agents.retriever import ProcedureHit, Retriever
from src.agents.strategies import Notifier
from src.models.business_area import AreaScope
from src.services.area_notifier import Requester, format_request
from src.services.procedures import FieldSpec, missing_or_invalid, web_contact_fields
from src.utils.exceptions.notification import NotificationDeliveryError

logger = logging.getLogger(__name__)

ToolOutcome = Literal["wants_human", "gave_up", "notification_failed", "no_answer"]

QUERY_PARAMETERS = {
    "type": "object",
    "properties": {"consulta": {"type": "string", "description": "Consulta de búsqueda, redactada con el contexto de la conversación"}},
    "required": ["consulta"],
}
# Gemini no admite objetos con claves libres en las funciones: los datos van como lista de pares campo/valor.
NOTIFY_PARAMETERS = {
    "type": "object",
    "properties": {
        "procedimiento_id": {"type": "integer", "description": "id del procedimiento devuelto por buscar_procedimiento"},
        "datos": {
            "type": "array",
            "description": "Datos entregados por el usuario, uno por campo exigido",
            "items": {
                "type": "object",
                "properties": {"campo": {"type": "string"}, "valor": {"type": "string"}},
                "required": ["campo", "valor"],
            },
        },
    },
    "required": ["procedimiento_id", "datos"],
}
NO_PARAMETERS: dict[str, Any] = {"type": "object", "properties": {}}

SEARCH_FAQ = ToolSpec("buscar_faq", "Busca en las preguntas frecuentes de esta área.", QUERY_PARAMETERS)
SEARCH_PROCEDURE = ToolSpec(
    "buscar_procedimiento", "Busca los procedimientos de esta área para solicitudes que el área debe ejecutar.", QUERY_PARAMETERS)
NOTIFY_AREA = ToolSpec(
    "notificar_area", "Envía al área una solicitud de procedimiento con todos los datos que exige.", NOTIFY_PARAMETERS)
NO_ANSWER = ToolSpec(
    "sin_respuesta", "Úsala cuando lo recuperado no responde la consulta del usuario.", NO_PARAMETERS)
HAND_OFF = ToolSpec(
    "derivar_a_ejecutivo", "Deriva al cliente a un ejecutivo humano cuando lo pide o la consulta lo requiere.", NO_PARAMETERS)

class AreaToolbox:
    """Tools de un sub-agente. El área la fija el código: el modelo nunca elige en qué área buscar o notificar."""

    def __init__(
        self,
        area: AreaInfo,
        retriever: Retriever,
        notifier: Notifier,
        requester: Requester | None,
        message: str,
        attempts: dict[int, int],
        max_attempts: int,
    ):
        self.area = area
        self._retriever = retriever
        self._notifier = notifier
        self._requester = requester
        self._message = message
        self._max_attempts = max_attempts
        self.attempts = dict(attempts)
        # Hay evidencia si alguna tool devolvió FAQ o procedimientos sobre el umbral, o si se entregó una notificación.
        self.evidence = False
        self.outcome: ToolOutcome | None = None

    @property
    def is_web(self) -> bool:
        return self.area.scope == AreaScope.external

    def specs(self) -> list[ToolSpec]:
        specs = [SEARCH_FAQ, SEARCH_PROCEDURE, NOTIFY_AREA, NO_ANSWER]
        return [*specs, HAND_OFF] if self.is_web else specs

    async def execute(self, call: ToolCall) -> str:
        match call.name:
            case "buscar_faq":
                return await self._search_faq(str(call.args.get("consulta", "")))
            case "buscar_procedimiento":
                return await self._search_procedures(str(call.args.get("consulta", "")))
            case "notificar_area":
                return await self._notify(call.args)
            case "sin_respuesta":
                self.outcome = "no_answer"
                return "Consulta marcada como sin respuesta."
            case "derivar_a_ejecutivo" if self.is_web:
                self.outcome = "wants_human"
                return "Se derivará al cliente a un ejecutivo."
        return f"La herramienta {call.name} no existe."

    async def _search_faq(self, query: str) -> str:
        hits = await self._retriever.search_faq(self.area.id, query)
        if not hits:
            return "Sin resultados en esta área."
        self.evidence = True
        return "\n\n".join(f"Pregunta: {hit.question}\nRespuesta: {hit.answer}" for hit in hits)

    async def _search_procedures(self, query: str) -> str:
        hits = await self._retriever.search_procedures(self.area.id, query)
        if not hits:
            return "Sin resultados en esta área."
        self.evidence = True
        return "\n\n".join(describe_procedure(hit, self._required_fields(hit)) for hit in hits)

    def _required_fields(self, procedure: ProcedureHit) -> list[FieldSpec]:
        # El cliente web es anónimo: el área necesita su nombre y contacto aunque el procedimiento no los pida.
        return procedure.fields + web_contact_fields() if self.is_web else procedure.fields

    async def _notify(self, args: dict[str, Any]) -> str:
        try:
            # Gemini puede devolver los enteros como 9.0.
            procedure_id = int(float(str(args.get("procedimiento_id"))))
        except ValueError:
            return "Falta un procedimiento_id válido."
        procedure = await self._retriever.get_procedure(self.area.id, procedure_id)
        if procedure is None:
            return "El procedimiento indicado no existe en esta área."
        data = {str(item.get("campo")): str(item.get("valor")) for item in args.get("datos") or [] if isinstance(item, dict)}
        check = missing_or_invalid(self._required_fields(procedure), data)
        if check.invalid:
            self.attempts[procedure.id] = self.attempts.get(procedure.id, 0) + 1
            if self.attempts[procedure.id] >= self._max_attempts:
                self.outcome = "gave_up"
                return "Se agotaron los intentos para entregar datos válidos."
            labels = ", ".join(field.label for field in check.invalid)
            return f"Datos inválidos: {labels}. Pídeselos de nuevo al usuario."
        if check.missing:
            return f"Faltan datos: {', '.join(field.label for field in check.missing)}. Pídeselos al usuario."
        requester = self._requester or Requester(check.valid["nombre"], check.valid["contacto"], "web")
        rows = [(field.label, check.valid[field.name]) for field in procedure.fields]
        try:
            if not self.area.chat_space:
                raise NotificationDeliveryError(f"El área {self.area.name} no tiene space configurado")
            await self._notifier.notify(self.area.chat_space, format_request(procedure.name, rows, requester, self._message))
        except NotificationDeliveryError as exc:
            # Sin los datos del usuario en el log: solo el procedimiento y el motivo.
            logger.error("No se pudo notificar la solicitud %s al área: %s", procedure.name, exc)
            self.outcome = "notification_failed"
            return "No se pudo notificar al área."
        self.attempts.pop(procedure.id, None)
        self.evidence = True
        return "Solicitud notificada al área. Confirma al usuario que el área gestionará su solicitud."

def describe_procedure(procedure: ProcedureHit, fields: list[FieldSpec]) -> str:
    required = "\n".join(f"- {field.label} (campo: {field.name})" for field in fields) or "- Ninguno"
    return f"id: {procedure.id}\nProcedimiento: {procedure.name}\nPasos: {procedure.steps}\nDatos exigidos:\n{required}"
