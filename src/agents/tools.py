import logging
from typing import Protocol
from src.agents.llm import AreaInfo, FaqHit, ProcedureHit, ToolCall, ToolSpec, describe_procedure
from src.agents.procedure_flow import ProcedureResult, handle_procedure
from src.agents.strategies import Notifier
from src.models.business_area import AreaScope
from src.services.area_notifier import Requester
import json
from pydantic import ValidationError
from src.services.edr import EdrDocument, EdrSaved
from src.services.jira_client import JiraIssue, JiraIssueRef
from src.services.procedures import web_contact_fields
from src.services.project_access import board_of, scoped_jql
from src.utils.exceptions.jira import JiraUnavailableError

logger = logging.getLogger(__name__)

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

SEARCH_TICKETS = ToolSpec(
    "buscar_tickets",
    "Busca tickets de Jira con JQL, sin indicar el proyecto: la búsqueda se acota sola a los tableros permitidos.",
    {"type": "object", "properties": {"jql": {"type": "string", "description": "Condición JQL, p. ej. text ~ \"pagaré\""}},
     "required": ["jql"]})
READ_TICKET = ToolSpec(
    "leer_ticket",
    "Lee un ticket o una épica de Jira: estado, tipo, responsable, descripción, subtareas y tickets hijos.",
    {"type": "object", "properties": {"clave": {"type": "string", "description": "Clave del ticket, p. ej. DAIA-52"}},
     "required": ["clave"]})
READ_EDR = ToolSpec(
    "leer_edr", "Lee el EDR actual de esta conversación (el último guardado), para editarlo.",
    {"type": "object", "properties": {}})
SAVE_EDR = ToolSpec(
    "guardar_edr",
    "Guarda el EDR como Google Doc: crea el de la conversación o actualiza el mismo. El EDR va como JSON con titulo "
    "(obligatorio) y, si se conocen: metadata {version, codigo_documento, tarea_trinidad, fecha, nombre_sistema}, "
    "historial [{fecha, responsable, cargo, descripcion_cambio, version}], objetivo_general, vision_general, "
    "product_owner {nombre, cargo}, equipo_desarrollo [{tipo, nombre}], aplicaciones_afectadas [{nombre, "
    "nivel_impacto}], usuarios_afectados [texto], requerimientos [{codigo_rf, nombre, tipo}], especificaciones_rf "
    "[{codigo_rf, descripcion, bloques [{titulo, parrafo, items [{texto, sub_items [texto]}]}], reglas_negocio, "
    "flujos_positivos, flujos_negativos, notas}], roles_permisos [{gerencia, perfil, permiso, accion}], impacto [{area, "
    "proceso_afectado, responsable, rf_afectado}], infraestructura, seguridad [{referencia, nombre, descripcion, "
    "nivel_riesgo}], criterios_aceptacion [{codigo, descripcion, resultado_esperado, referencia_rf, es_critico}], "
    "validaciones_cartera, glosario [{termino, definicion}]. Lo que nadie entregó se omite: queda «[PENDIENTE DEFINIR]».",
    {"type": "object", "properties": {
        "edr_json": {"type": "string", "description": "El EDR completo como JSON"},
        "nuevo": {"type": "boolean", "description": "true para crear otro EDR en vez de actualizar el de la conversación"}},
     "required": ["edr_json"]})
EDR_DRIVE_DOWN = "No se pudo guardar el EDR en Drive en este momento; no digas que quedó guardado."

NOT_ENABLED = ("La función de Jira y EDR no está habilitada para este colaborador. Indícale que esa función no está "
               "habilitada para él, sin más detalles.")
JIRA_DOWN = "No se pudo consultar Jira en este momento."
INVALID_SEARCH = "La búsqueda no es válida: escribe una condición JQL sin indicar el proyecto."

class ProjectServices(Protocol):
    async def is_enabled(self, email: str | None) -> bool: ...
    async def allowed_boards(self) -> list[str]: ...
    async def search(self, jql: str) -> list[JiraIssueRef]: ...
    async def get_issue(self, key: str) -> JiraIssue | None: ...
    async def children(self, key: str) -> list[JiraIssueRef]: ...
    async def get_edr(self, conversation_id: str) -> EdrDocument | None: ...
    async def save_edr(self, conversation_id: str, edr: EdrDocument, new: bool) -> EdrSaved: ...

def describe_refs(refs: list[JiraIssueRef]) -> str:
    return "\n".join(f"- {ref.key} {ref.summary} ({ref.status})" for ref in refs)

def describe_issue(issue: JiraIssue, children: list[JiraIssueRef]) -> str:
    lines = [f"{issue.key} · {issue.summary} · {issue.status}",
             f"Tipo: {issue.issue_type} · Responsable: {issue.assignee or 'sin asignar'} · Informante: {issue.reporter or '—'}"]
    if issue.parent:
        lines.append(f"Pertenece a: {issue.parent}")
    lines.append(f"Descripción:\n{issue.description or '(sin descripción)'}")
    if issue.subtasks:
        lines.append(f"Subtareas:\n{describe_refs(issue.subtasks)}")
    if children:
        lines.append(f"Tickets hijos:\n{describe_refs(children)}")
    return "\n".join(lines)

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
        projects: ProjectServices | None = None,
        conversation_id: str = "",
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
        self._projects = projects
        self._conversation_id = conversation_id
        self.links: list[str] = []  # enlaces de los EDR guardados en este turno
        # Lo leído en Jira o guardado en un EDR: es evidencia para el guardarraíl y el control posterior.
        self.documents: list[str] = []

    @property
    def evidence(self) -> bool:
        # Un texto solo vale si se apoya en contenido del área o en el procedimiento en curso.
        return bool(self.faqs or self.procedures or self.pending or self.documents)

    def specs(self) -> list[ToolSpec]:
        enabled = self._projects is not None
        jira = [SEARCH_TICKETS, READ_TICKET] if "jira" in self.area.tools and enabled else []
        edr = [READ_EDR, SAVE_EDR] if "edr" in self.area.tools and enabled and self._conversation_id else []
        return [SEARCH_FAQ, SEARCH_PROCEDURE, START_PROCEDURE, *jira, *edr]

    async def execute(self, call: ToolCall, model_text: str) -> str:
        match call.name:
            case "buscar_faq":
                return await self._search_faq(str(call.args.get("consulta", "")))
            case "buscar_procedimiento":
                return await self._search_procedures(str(call.args.get("consulta", "")))
            case "iniciar_procedimiento":
                return await self._start(call, model_text)
            case "buscar_tickets" | "leer_ticket" if any(spec.name == call.name for spec in self.specs()):
                return await self._jira(call)
            case "leer_edr" | "guardar_edr" if any(spec.name == call.name for spec in self.specs()):
                return await self._edr(call)
        return f"La herramienta {call.name} no existe."

    async def _edr(self, call: ToolCall) -> str:
        assert self._projects is not None
        if not await self._projects.is_enabled(self._requester.contact if self._requester else None):
            return NOT_ENABLED
        if call.name == "leer_edr":
            current = await self._projects.get_edr(self._conversation_id)
            if current is None:
                return "Todavía no hay un EDR en esta conversación."
            return f"EDR actual de la conversación:\n{current.model_dump_json(exclude_defaults=True)}"
        try:
            edr = EdrDocument.model_validate(json.loads(str(call.args.get("edr_json", ""))))
        except (json.JSONDecodeError, ValidationError) as exc:
            # El modelo recibe qué falló para corregirlo en el paso siguiente.
            return f"El EDR no es válido; corrígelo y vuelve a guardarlo: {str(exc)[:500]}"
        try:
            saved = await self._projects.save_edr(self._conversation_id, edr, bool(call.args.get("nuevo")))
        except Exception as exc:
            logger.error("No se pudo guardar el EDR en Drive: %s", type(exc).__name__)
            return EDR_DRIVE_DOWN
        self.links.append(saved.web_link)
        # Lo guardado es evidencia: el EDR puede nombrar al PO o al equipo que entregó el colaborador.
        self.documents.append(edr.model_dump_json(exclude_defaults=True))
        return f"EDR guardado en Google Docs: {saved.web_link}"

    async def _jira(self, call: ToolCall) -> str:
        assert self._projects is not None
        # El acceso se comprueba antes de tocar Jira, con el correo que da Google Chat (nunca lo que escribe el usuario).
        if not await self._projects.is_enabled(self._requester.contact if self._requester else None):
            return NOT_ENABLED
        boards = await self._projects.allowed_boards()
        try:
            if call.name == "leer_ticket":
                key = str(call.args.get("clave", "")).strip().upper()
                # Fuera de los tableros permitidos se responde igual que si no existiera.
                issue = await self._projects.get_issue(key) if board_of(key) in boards else None
                if issue is None:
                    return f"No encuentro el ticket {key}."
                text = describe_issue(issue, await self._projects.children(key))
            else:
                jql = scoped_jql(str(call.args.get("jql", "")), boards)
                if jql is None:
                    return INVALID_SEARCH
                text = describe_refs(await self._projects.search(jql)) or "Sin tickets para esa búsqueda."
        except JiraUnavailableError:
            return JIRA_DOWN
        self.documents.append(text)
        return text

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
