"""Quién puede usar las herramientas de un área (spec 002, RF-3 a RF-7). Se decide en el código antes de llamar al
modelo: lo que el sub-agente no recibe, no lo puede ejecutar (plan 002, D6)."""
from collections.abc import Sequence
from src.agents.llm import AreaInfo
from src.agents.tools.registry import AreaTool

def normalize_email(email: str | None) -> str | None:
    return email.strip().lower() if email and email.strip() else None

def can_use_tools(area: AreaInfo, requester: str | None) -> bool:
    if area.members is None:
        return True
    # El web es anónimo: nunca usa las herramientas de un área con lista (RF-3).
    email = normalize_email(requester)
    return email is not None and email in area.members

def restricted_note(tools: Sequence[AreaTool]) -> str:
    """Nota para el prompt del sub-agente cuando se le retiran herramientas: describe las funciones, sin sus nombres
    internos (spec 001, RF-38)."""
    functions = "; ".join(tool.description.rstrip(".") for tool in tools)
    return ("La persona que escribe no está habilitada para estas funciones del área: " + functions + ". Si pide algo "
            "que las requiere, dile que esa función no está habilitada para ella, sin más detalles. Las preguntas "
            "frecuentes del área sí las puedes usar.")
