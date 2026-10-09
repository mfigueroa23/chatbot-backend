"""Sub-agente de un área: resuelve una subtarea con las FAQ de su área y sus herramientas, y devuelve el resultado
al coordinador. No habla con el usuario ni delega en otros sub-agentes (RF-11)."""
import asyncio
import logging
from collections.abc import Sequence
from langchain_core.messages import BaseMessage, ToolCall, ToolMessage
from pydantic import ValidationError
from src.agents.llm import ANSWER_TOOL, Answer, AreaInfo, AreaResult, Catalog, FaqHit, SubAgentModel, Subtask
from src.agents.prompts import sub_agent_messages
from src.agents.tools import AreaTool

logger = logging.getLogger(__name__)

TOOL_FAILED = "La herramienta no está disponible en este momento."

async def run_tool(tools: Sequence[AreaTool], call: ToolCall) -> str:
    tool = next((tool for tool in tools if tool.name == call["name"]), None)
    if tool is None:
        return f"La herramienta {call['name']} no existe."
    try:
        return await tool.run(tool.args_schema.model_validate(call["args"]))
    except Exception as exc:
        # Sin detalles al modelo ni al usuario (RF-30); el tipo basta para diagnosticar.
        logger.warning("La herramienta %s falló: %s", tool.name, type(exc).__name__)
        return TOOL_FAILED

async def solve(model: SubAgentModel, messages: list[BaseMessage], area: AreaInfo, subtask: Subtask,
                tools: Sequence[AreaTool], max_steps: int) -> AreaResult:
    not_found = AreaResult(area.id, area.name, subtask.query, False)
    for step in range(max(max_steps, 1)):
        # Sin herramientas, o en el último paso, solo puede responder: el número de llamadas queda acotado (RNF-6).
        answer_only = not tools or step == max_steps - 1
        reply = await model.step(messages, [] if answer_only else tools, answer_only)
        final = next((call for call in reply.tool_calls if call["name"] == ANSWER_TOOL), None)
        if final is not None:
            try:
                answer = Answer.model_validate(final["args"])
            except ValidationError:
                logger.warning("El sub-agente del área %s respondió con un formato inválido", area.name)
                return not_found
            found = answer.encontrado and bool(answer.contenido.strip())
            return AreaResult(area.id, area.name, subtask.query, found, answer.contenido.strip() if found else "")
        if not reply.tool_calls:
            logger.warning("El sub-agente del área %s terminó sin responder", area.name)
            return not_found
        outputs = [ToolMessage(await run_tool(tools, call), tool_call_id=call["id"] or "") for call in reply.tool_calls]
        messages = [*messages, reply, *outputs]
    return not_found

async def run_sub_agent(model: SubAgentModel, catalog: Catalog, area: AreaInfo, faqs: Sequence[FaqHit],
                        subtask: Subtask, tools: Sequence[AreaTool], max_steps: int, timeout: float) -> AreaResult:
    messages = sub_agent_messages(catalog, area, faqs, subtask)
    try:
        async with asyncio.timeout(timeout):
            return await solve(model, messages, area, subtask, tools, max_steps)
    except TimeoutError:
        logger.warning("El sub-agente del área %s superó los %s s", area.name, timeout)
    except Exception as exc:
        # Un sub-agente caído no impide responder con las demás áreas (RF-15).
        logger.warning("El sub-agente del área %s falló: %s", area.name, type(exc).__name__)
    return AreaResult(area.id, area.name, subtask.query, False)
