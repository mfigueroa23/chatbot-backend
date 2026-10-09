import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.property import Properties

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class ToolContext:
    """Lo que una herramienta sabe del mensaje: quién escribe (spec 002, RF-1 y RF-2), la configuración del mensaje y
    cómo abrir una sesión propia (los sub-agentes corren en paralelo y AsyncSession no admite consultas concurrentes)."""
    requester: str | None = None
    properties: Properties = field(default_factory=lambda: Properties({}))
    session_factory: Callable[[], AsyncSession] | None = None
    # La conversación, su hilo de Google Chat (None en el web) y el mensaje del usuario, con los archivos leídos: para las
    # herramientas que trabajan después del mensaje, como el EDR (spec 003, plan D4).
    conversation_id: uuid.UUID | None = None
    chat_key: str | None = None
    message: str = ""

ToolRun = Callable[[dict[str, Any], ToolContext], Awaitable[str]]

@dataclass(frozen=True)
class AreaTool:
    """Herramienta que recibe un sub-agente: del registro en código o de un servidor MCP (plan 002, D5)."""
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema de los argumentos
    run: ToolRun

def code_tool[A: BaseModel](name: str, description: str, schema: type[A],
                            fn: Callable[[A, ToolContext], Awaitable[str]]) -> AreaTool:
    """Herramienta en código: el esquema sale del modelo Pydantic y los argumentos se validan antes de llamar."""
    async def run(args: dict[str, Any], context: ToolContext) -> str:
        return await fn(schema.model_validate(args), context)
    return AreaTool(name, description, schema.model_json_schema(), run)

def tools_for(area_name: str, names: Sequence[str], registry: Mapping[str, AreaTool]) -> list[AreaTool]:
    """Las herramientas del registro que nombra el área (business_area.tools); el registro está en available.py."""
    unknown = [name for name in names if name not in registry]
    if unknown:
        logger.warning("El área %s tiene herramientas que no existen en el registro: %s", area_name, ", ".join(unknown))
    return [registry[name] for name in names if name in registry]
