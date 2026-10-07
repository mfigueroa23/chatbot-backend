import logging
from dataclasses import dataclass
from typing import Literal
from src.agents.llm import AreaInfo, ProcedureHit
from src.agents.strategies import Notifier
from src.models.business_area import AreaScope
from src.services.area_notifier import Requester, format_request
from src.services.procedures import FieldSpec, missing_or_invalid, web_contact_fields
from src.utils.exceptions.notification import NotificationDeliveryError

logger = logging.getLogger(__name__)

MISSING_DATA = "Para continuar con «{procedure}» necesito: {labels}."
INVALID_DATA = "Estos datos no son válidos: {labels}. ¿Me los indicas de nuevo?"
REQUEST_SENT = "Listo, enviamos tu solicitud «{procedure}» al área de {area}, que la gestionará y te contactará."

ProcedureKind = Literal["ask", "sent", "gave_up", "failed"]

@dataclass(frozen=True)
class ProcedureResult:
    kind: ProcedureKind
    text: str | None
    attempts: dict[int, int]

def required_fields(procedure: ProcedureHit, area: AreaInfo) -> list[FieldSpec]:
    # El cliente web es anónimo: el área necesita su nombre y contacto aunque el procedimiento no los pida.
    return procedure.fields + web_contact_fields() if area.scope == AreaScope.external else procedure.fields

def labels(fields: list[FieldSpec]) -> str:
    return ", ".join(field.label for field in fields)

async def handle_procedure(
    procedure: ProcedureHit,
    area: AreaInfo,
    data: dict[str, str],
    requester: Requester | None,
    message: str,
    attempts: dict[int, int],
    max_attempts: int,
    notifier: Notifier,
    model_text: str,
    is_new: bool,
) -> ProcedureResult:
    attempts = dict(attempts)
    check = missing_or_invalid(required_fields(procedure, area), data)
    if check.invalid:
        attempts[procedure.id] = attempts.get(procedure.id, 0) + 1
        if attempts[procedure.id] >= max_attempts:
            return ProcedureResult("gave_up", None, attempts)
        return ProcedureResult("ask", INVALID_DATA.format(labels=labels(check.invalid)), attempts)
    if check.missing:
        # Al identificar el procedimiento, la explicación de los pasos la redacta el modelo en la misma llamada.
        if is_new and model_text.strip():
            return ProcedureResult("ask", model_text, attempts)
        return ProcedureResult("ask", MISSING_DATA.format(procedure=procedure.name, labels=labels(check.missing)), attempts)
    requester = requester or Requester(check.valid["nombre"], check.valid["contacto"], "web")
    rows = [(field.label, check.valid[field.name]) for field in procedure.fields]
    try:
        if not area.chat_space:
            raise NotificationDeliveryError(f"El área {area.name} no tiene space configurado")
        await notifier.notify(area.chat_space, format_request(procedure.name, rows, requester, message))
    except NotificationDeliveryError as exc:
        # Sin los datos del usuario en el log: solo el procedimiento y el motivo.
        logger.error("No se pudo notificar la solicitud %s al área: %s", procedure.name, exc)
        return ProcedureResult("failed", None, attempts)
    attempts[procedure.id] = 0
    return ProcedureResult("sent", REQUEST_SENT.format(procedure=procedure.name, area=area.name), attempts)
