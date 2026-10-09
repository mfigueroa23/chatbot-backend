"""Conexión a un servidor MCP remoto por streamable HTTP con el SDK oficial (plan 002, D7). Cualquier fallo se
convierte en McpUnavailableError; la credencial nunca va al log (spec 002, RF-12, RF-13)."""
import asyncio
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from src.utils.exceptions.mcp import McpUnavailableError

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class McpToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any]

def auth_headers(credential: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {credential}"} if credential else {}

def http_target(url: str, credential: str | None, timeout: float) -> Any:
    """Transporte streamable HTTP con la credencial como header."""
    return streamable_http_client(url, http_client=httpx2.AsyncClient(headers=auth_headers(credential), timeout=timeout))

class McpClient:
    """Una sesión con un servidor: se abre con `async with` y se cierra al salir. `target` es la URL ya armada como
    transporte o, en los tests, un servidor MCPServer en proceso."""

    def __init__(self, name: str, target: Any, timeout: float):
        self.name = name
        self._target = target
        self._timeout = timeout
        self._stack = AsyncExitStack()
        self._client: Client | None = None

    async def __aenter__(self) -> "McpClient":
        try:
            async with asyncio.timeout(self._timeout):
                self._client = await self._stack.enter_async_context(
                    Client(self._target, read_timeout_seconds=self._timeout))
        except Exception as exc:
            await self._stack.aclose()
            raise McpUnavailableError(f"{self.name}: {type(exc).__name__}") from exc
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        try:
            await self._stack.aclose()
        except Exception as exc:
            logger.warning("No se pudo cerrar la sesión con el servidor MCP %s: %s", self.name, type(exc).__name__)

    async def list_tools(self) -> list[McpToolInfo]:
        client = self._require()
        try:
            async with asyncio.timeout(self._timeout):
                listing = await client.list_tools()
        except Exception as exc:
            raise McpUnavailableError(f"{self.name}: {type(exc).__name__}") from exc
        return [McpToolInfo(tool.name, tool.description or "", dict(tool.input_schema)) for tool in listing.tools]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        client = self._require()
        try:
            async with asyncio.timeout(self._timeout):
                result = await client.call_tool(name, arguments)
        except Exception as exc:
            raise McpUnavailableError(f"{self.name}: {type(exc).__name__}") from exc
        if result.is_error:
            raise McpUnavailableError(f"{self.name}: la herramienta {name} respondió con error")
        return "\n".join(text for block in result.content if (text := getattr(block, "text", None)))

    def _require(self) -> Client:
        if self._client is None:
            raise McpUnavailableError(f"{self.name}: sesión no abierta")
        return self._client
