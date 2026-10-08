from typing import Protocol
from src.agents.llm import AreaInfo, FaqHit, ProcedureHit, ToolCall, ToolSpec, describe_procedure
from src.agents.procedure_flow import ProcedureResult, handle_procedure
from src.agents.strategies import Notifier
from src.models.business_area import AreaScope
from src.services.area_notifier import Requester
from src.services.procedures import web_contact_fields

QUERY_PARAMETERS = {
    "type": "object",
    "properties": {"consulta": {"type": "string", "description": "Consulta de búsqueda, redactada con el contexto de la conversación"}},
    "required": ["consulta"],
}
# Gemini no admite objetos con claves libres en las funciones: los datos van como lista de pares campo/valor.
START_PARAMETERS = {
    "type": "object",
    "properties": {
        "procedimiento_id": {"type": "integer", "description": "Id [P…] del procedimiento"},
        "datos": {
            "type": "array",
            "description": "Datos que el usuario entregó en la conversación, uno por campo exigido",
            "items": {
                "type": "object",
                "properties": {"campo": {"type": "string"}, "valor": {"type": "string"}},
                "required": ["campo", "valor"],
            },
        },
    },
    "required": ["procedimiento_id", "datos"],
}

SEARCH_FAQ = ToolSpec(
    "buscar_faq", "Busca de nuevo en las preguntas frecuentes de esta área con una consulta reformulada.", QUERY_PARAMETERS)
SEARCH_PROCEDURE = ToolSpec(
    "buscar_procedimiento", "Busca de nuevo en los procedimientos de esta área con una consulta reformulada.", QUERY_PARAMETERS)
START_PROCEDURE = ToolSpec(
    "iniciar_procedimiento",
    "Inicia o continúa un procedimiento del área con los datos entregados; explica los pasos en el texto de tu respuesta.",
    START_PARAMETERS)

class AreaSearch(Protocol):
    async def search_area_faqs(self, area_id: int, query: str) -> list[FaqHit]: ...
    async def search_area_procedures(self, area_id: int, query: str) -> list[ProcedureHit]: ...

class AreaToolbox:
    """Tools de un agente de área. El área la fija el código: el modelo nunca elige en qué área buscar o notificar."""

    def __init__(
        self,
        area: AreaInfo,
        retriever: AreaSearch,
        notifier: Notifier,
        requester: Requester | None,
        message: str,
        faqs: list[FaqHit],
        procedures: list[ProcedureHit],
        pending: ProcedureHit | None,
        attempts: dict[int, int],
        max_attempts: int,
    ):
        self.area = area
        self._retriever = retriever
        self._notifier = notifier
        self._requester = requester
        self._message = message
        self._max_attempts = max_attempts
        # Lo conocido del área en este turno: lo encontrado, lo elegido por el usuario y lo devuelto por las búsquedas.
        self.faqs = list(faqs)
        self.procedures = list(procedures)
        self.pending = pending
        self.attempts = dict(attempts)
        self.result: ProcedureResult | None = None
        self.procedure: ProcedureHit | None = None

    @property
    def evidence(self) -> bool:
        # Un texto solo vale si se apoya en contenido del área o en el procedimiento en curso.
        return bool(self.faqs or self.procedures or self.pending)

    def specs(self) -> list[ToolSpec]:
        return [SEARCH_FAQ, SEARCH_PROCEDURE, START_PROCEDURE]

    async def execute(self, call: ToolCall, model_text: str) -> str:
        match call.name:
            case "buscar_faq":
                return await self._search_faq(str(call.args.get("consulta", "")))
            case "buscar_procedimiento":
                return await self._search_procedures(str(call.args.get("consulta", "")))
            case "iniciar_procedimiento":
                return await self._start(call, model_text)
        return f"La herramienta {call.name} no existe."

    async def _search_faq(self, query: str) -> str:
        hits = await self._retriever.search_area_faqs(self.area.id, query)
        if not hits:
            return "Sin resultados en esta área."
        known = {faq.id for faq in self.faqs}
        self.faqs += [hit for hit in hits if hit.id not in known]
        return "\n\n".join(f"[F{hit.id}] Pregunta: {hit.question}\nRespuesta: {hit.answer}" for hit in hits)

    async def _search_procedures(self, query: str) -> str:
        hits = await self._retriever.search_area_procedures(self.area.id, query)
        if not hits:
            return "Sin resultados en esta área."
        known = {procedure.id for procedure in self.procedures}
        self.procedures += [hit for hit in hits if hit.id not in known]
        extra = web_contact_fields() if self.area.scope == AreaScope.external else []
        return "\n\n".join(describe_procedure(hit, extra) for hit in hits)

    async def _start(self, call: ToolCall, model_text: str) -> str:
        try:
            # Gemini puede devolver los enteros como 9.0.
            procedure_id = int(float(str(call.args.get("procedimiento_id"))))
        except ValueError:
            return "Falta un procedimiento_id válido."
        # Solo un procedimiento encontrado, elegido o en curso: nunca uno que el modelo invente.
        known = {procedure.id: procedure for procedure in self.procedures}
        if self.pending is not None:
            known.setdefault(self.pending.id, self.pending)
        procedure = known.get(procedure_id)
        if procedure is None:
            return "El procedimiento indicado no está disponible en esta área."
        data = {str(item.get("campo")): str(item.get("valor"))
                for item in call.args.get("datos") or [] if isinstance(item, dict)}
        is_new = self.pending is None or self.pending.id != procedure.id
        self.result = await handle_procedure(
            procedure, self.area, data, self._requester, self._message, self.attempts, self._max_attempts,
            self._notifier, model_text, is_new)
        self.attempts = self.result.attempts
        self.procedure = procedure
        return "Procedimiento procesado."
