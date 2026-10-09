"""Interfaces tipadas de los agentes (constitución, punto 3): el grafo solo conoce estos contratos."""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol
from langchain_core.messages import AIMessage, BaseMessage
from pydantic import BaseModel, Field
from src.agents.tools.registry import AreaTool
from src.models.business_area import AreaScope

@dataclass(frozen=True)
class AreaInfo:
    id: int
    name: str
    description: str
    system_prompt: str
    categories: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    # Correos habilitados para sus herramientas (en minúsculas); None = el área no tiene lista (spec 002, RF-4, RF-5).
    members: frozenset[str] | None = None
    mcp_servers: tuple[str, ...] = ()

@dataclass(frozen=True)
class McpServerConfig:
    """Servidor MCP activo (spec 002, RF-9): la credencial se busca en property por credential_key (RF-12)."""
    name: str
    url: str
    credential_key: str | None = None
    allowed_tools: tuple[str, ...] = ()

@dataclass(frozen=True)
class Catalog:
    """Lo que un coordinador puede usar en este mensaje: solo las áreas activas de su canal (RF-3)."""
    scope: AreaScope
    coordinator_prompt: str
    sub_agent_rules: str
    areas: tuple[AreaInfo, ...]
    # Servidores MCP activos asignados a alguna área del catálogo, por nombre (spec 002, RF-9, RF-10).
    mcp_servers: Mapping[str, McpServerConfig] = field(default_factory=dict)

    def area(self, area_id: int) -> AreaInfo | None:
        return next((area for area in self.areas if area.id == area_id), None)

@dataclass(frozen=True)
class Subtask:
    area_id: int
    query: str

@dataclass(frozen=True)
class RoutingDecision:
    """direct: el coordinador responde solo (saludo, tema ajeno, catálogo); areas: subtareas para los sub-agentes."""
    kind: Literal["areas", "direct"]
    subtasks: tuple[Subtask, ...] = ()
    reply: str = ""

@dataclass(frozen=True)
class FaqHit:
    id: int
    category: str
    question: str
    answer: str

@dataclass(frozen=True)
class AreaResult:
    area_id: int
    area_name: str
    query: str
    found: bool
    content: str = ""
    # Interpretaciones distintas de la consulta que responden sus FAQ: el coordinador pregunta a cuál se refiere
    # (spec 002, RF-28, RF-29).
    options: tuple[str, ...] = ()

ANSWER_TOOL = "responder"

class Answer(BaseModel):
    """Entrega al coordinador el resultado de la subtarea."""
    encontrado: bool = Field(description="true si las preguntas frecuentes o las herramientas responden la consulta")
    contenido: str = Field(description="El contenido que responde la consulta; vacío si no se encontró información")
    interpretaciones: list[str] = Field(default_factory=list, description=(
        "Si las preguntas frecuentes responden interpretaciones distintas de la consulta, una frase corta por "
        "interpretación, sin elegir una; vacía si la consulta no es ambigua"))

class CoordinatorModel(Protocol):
    async def route(self, messages: list[BaseMessage]) -> RoutingDecision: ...
    async def synthesize(self, messages: list[BaseMessage]) -> str: ...

class SubAgentModel(Protocol):
    async def step(self, messages: list[BaseMessage], tools: Sequence[AreaTool], answer_only: bool) -> AIMessage:
        """Una llamada: el AIMessage trae llamadas a herramientas, entre ellas la de `responder` (D7)."""
        ...

class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

class KnowledgeSource(Protocol):
    async def search(self, subtasks: Sequence[Subtask], k: int) -> dict[int, list[FaqHit]]:
        """FAQ activas más parecidas a cada subtarea, solo de su área, por area_id (RF-8, RF-24)."""
        ...

    async def search_area(self, area_id: int, query: str, k: int) -> list[FaqHit]:
        """Otra búsqueda en las FAQ de un área, desde un sub-agente en paralelo (spec 002, RF-25, RF-26)."""
        ...
