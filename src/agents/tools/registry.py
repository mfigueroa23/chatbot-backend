import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pydantic import BaseModel

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class AreaTool:
    """Herramienta programada en código; un área la usa si su nombre está en business_area.tools (RF-27, RF-28)."""
    name: str
    description: str
    args_schema: type[BaseModel]
    run: Callable[[BaseModel], Awaitable[str]]

# Registro de la 2.0.0: vacío a propósito, queda el punto de extensión (spec, fuera de alcance).
TOOLS: dict[str, AreaTool] = {}

def tools_for(area_name: str, names: Sequence[str], registry: Mapping[str, AreaTool] = TOOLS) -> list[AreaTool]:
    unknown = [name for name in names if name not in registry]
    if unknown:
        logger.warning("El área %s tiene herramientas que no existen en el registro: %s", area_name, ", ".join(unknown))
    return [registry[name] for name in names if name in registry]
