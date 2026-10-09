"""Herramientas de los servidores MCP de un área (spec 002, RF-9 a RF-15). Solo entran las de allowed_tools (plan 002,
D9); un servidor caído se omite y el área sigue con sus FAQ y sus herramientas en código (RF-13)."""
import logging
from collections.abc import Callable, Sequence
from contextlib import AsyncExitStack
from typing import Any
from src.agents.llm import McpServerConfig
from src.agents.prompts import information
from src.agents.tools.registry import AreaTool, ToolContext
from src.services.mcp.client import McpClient, McpToolInfo, http_target
from src.services.property import Properties
from src.utils.exceptions.mcp import McpUnavailableError

logger = logging.getLogger(__name__)

MCP_FAILED = "La herramienta no está disponible en este momento."

McpConnector = Callable[[McpServerConfig, str | None, float], McpClient]

def connect_http(server: McpServerConfig, credential: str | None, timeout: float) -> McpClient:
    return McpClient(server.name, http_target(server.url, credential, timeout), timeout)

def allowed(server: McpServerConfig, tools: Sequence[McpToolInfo]) -> list[McpToolInfo]:
    """Solo las herramientas de la lista permitida; una lista vacía no deja pasar ninguna (RF-11)."""
    return [tool for tool in tools if tool.name in server.allowed_tools]

def as_area_tool(client: McpClient, tool: McpToolInfo) -> AreaTool:
    async def run(args: dict[str, Any], context: ToolContext) -> str:
        try:
            text = await client.call_tool(tool.name, args)
        except McpUnavailableError as exc:
            logger.warning("Falló la herramienta MCP %s: %s", tool.name, exc)
            return MCP_FAILED
        # Lo que devuelve un servidor de terceros es información, nunca instrucciones (RF-15).
        return information(f"herramienta {tool.name} de {client.name}", text or "(sin resultado)")
    schema = tool.input_schema or {"type": "object", "properties": {}}
    return AreaTool(tool.name, tool.description, schema, run)

class McpToolset:
    """Abre una sesión por servidor al entrar y las cierra al salir, aunque el sub-agente falle (plan 002, D8)."""

    def __init__(self, servers: Sequence[McpServerConfig], properties: Properties, taken: set[str],
                 connect: McpConnector = connect_http):
        self._servers = servers
        self._properties = properties
        self._taken = set(taken)
        self._connect = connect
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> list[AreaTool]:
        timeout = float(self._properties.get_int("mcp_timeout_seconds", 5))
        tools: list[AreaTool] = []
        for server in self._servers:
            credential = self._properties.values.get(server.credential_key) if server.credential_key else None
            if server.credential_key and not credential:
                logger.warning("El servidor MCP %s no tiene su credencial en property (%s)", server.name, server.credential_key)
                continue
            try:
                client = await self._stack.enter_async_context(self._connect(server, credential, timeout))
                listed = await client.list_tools()
            except McpUnavailableError as exc:
                logger.warning("El servidor MCP %s no está disponible: %s", server.name, exc)
                continue
            for tool in allowed(server, listed):
                if tool.name in self._taken:
                    logger.warning("Se omite la herramienta MCP %s de %s: el nombre ya está en uso", tool.name, server.name)
                    continue
                self._taken.add(tool.name)
                tools.append(as_area_tool(client, tool))
        return tools

    async def __aexit__(self, *exc_info: object) -> None:
        await self._stack.aclose()
